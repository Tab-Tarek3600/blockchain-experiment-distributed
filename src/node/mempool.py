"""
Mempool: holds transactions received but not yet included in a block.

Design constraints (per fixed architecture decisions):
    - The mempool NEVER calls crypto.ml_dsa directly. All
      cryptographic and structural acceptance checks are delegated to
      node.validator.validate_transaction_for_acceptance(). This keeps
      a single point of truth for "is this transaction acceptable?",
      shared with node.py and any future entry point (API, P2P).
    - The mempool is not a second blockchain: it has no notion of
      height, chaining, or persistence. It is a pure in-memory queue.

Known v1 limitation (documented, not fixed here):
    There is no account/state model yet (no balances, no authoritative
    "next nonce per account"). The mempool therefore cannot detect
    real double-spends. It only enforces a queue-hygiene rule: at most
    one *pending* transaction per (sender, nonce) pair. This prevents
    two conflicting transactions from the same sender/nonce from both
    sitting in the queue, but it is NOT a substitute for a real state
    model (planned alongside future EVM integration).

Ordering: get_pending() returns transactions sorted deterministically
by (sender, nonce, tx_id) rather than arrival order. This makes block
candidate construction reproducible across nodes that may have
received the same transactions in a different order due to network
timing -- relevant for later multi-node experiments.
"""

from __future__ import annotations

from typing import Iterable, Optional

from src.blockchain.transaction import Transaction
from src.crypto.ml_dsa import MLDSA
from src.node.validator import ValidatorError, validate_transaction_for_acceptance

DEFAULT_MAX_SIZE = 1000


class MempoolError(Exception):
    """Raised when a transaction cannot be added to the mempool."""


class Mempool:
    """In-memory queue of pending, not-yet-included transactions."""

    def __init__(self, ml_dsa: Optional[MLDSA] = None, max_size: int = DEFAULT_MAX_SIZE) -> None:
        if max_size <= 0:
            raise MempoolError("max_size must be a positive integer")

        self._ml_dsa = ml_dsa or MLDSA()
        self._max_size = max_size

        # Insertion order is irrelevant for correctness (get_pending
        # re-sorts deterministically), but a dict keeps lookup by
        # tx_id O(1) and preserves debuggability.
        self._transactions: dict[bytes, Transaction] = {}

        # Tracks (sender, nonce) -> tx_id for pending transactions,
        # to enforce the "one pending tx per (sender, nonce)" rule.
        self._nonce_index: dict[tuple[bytes, int], bytes] = {}

    def add_transaction(self, transaction: Transaction) -> None:
        """
        Validate and add a transaction to the mempool.

        Raises:
            MempoolError: If the transaction is rejected by
                node.validator, is a duplicate, conflicts with an
                already-pending transaction from the same sender at
                the same nonce, or the mempool is full.
        """
        try:
            validate_transaction_for_acceptance(transaction, self._ml_dsa)
        except ValidatorError as exc:
            raise MempoolError(f"transaction rejected: {exc}") from exc

        tx_id = transaction.tx_id

        if tx_id in self._transactions:
            raise MempoolError(f"duplicate transaction: {tx_id.hex()}")

        nonce_key = (transaction.sender, transaction.nonce)
        if nonce_key in self._nonce_index:
            raise MempoolError(
                f"a pending transaction already exists for sender "
                f"{transaction.sender.hex()} at nonce {transaction.nonce}"
            )

        if len(self._transactions) >= self._max_size:
            raise MempoolError(f"mempool is full (max_size={self._max_size})")

        self._transactions[tx_id] = transaction
        self._nonce_index[nonce_key] = tx_id

    def get_pending(self, limit: Optional[int] = None) -> list[Transaction]:
        """
        Return pending transactions in deterministic order, sorted by
        (sender, nonce, tx_id).

        Args:
            limit: If provided, return at most this many transactions.
        """
        ordered = sorted(
            self._transactions.values(),
            key=lambda tx: (tx.sender, tx.nonce, tx.tx_id),
        )

        if limit is not None:
            return ordered[:limit]

        return ordered

    def remove_transactions(self, tx_ids: Iterable[bytes]) -> None:
        """
        Remove the given transactions from the mempool (typically
        after their inclusion in an accepted block).

        Unknown tx_ids are silently ignored, since cleanup after block
        acceptance should never fail merely because a transaction was
        already removed by a previous call.
        """
        for tx_id in tx_ids:
            transaction = self._transactions.pop(tx_id, None)
            if transaction is not None:
                nonce_key = (transaction.sender, transaction.nonce)
                self._nonce_index.pop(nonce_key, None)

    def contains(self, tx_id: bytes) -> bool:
        """Return True if a transaction with this tx_id is pending."""
        return tx_id in self._transactions

    def size(self) -> int:
        """Number of transactions currently pending."""
        return len(self._transactions)
