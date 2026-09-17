"""
PoA consensus for the experimental blockchain.

Implements a simple round-robin Proof of Authority schedule over a
fixed, ordered set of authorized validators. The expected proposer for a block at a given height and round is:

    authorized_validators[(height + round) % len(authorized_validators)]

Round 0 is the normal schedule. If its proposer does not produce before
all active nodes' timeout, the next round selects the next validator at
the same height. The round is carried by and signed into the Block, so
all nodes apply the same deterministic rule.

Responsibilities of this module:
    - determine which validator is expected to propose a given block
    - check whether the local node is the expected proposer
    - build a signed block candidate from the current mempool

Explicitly out of scope here:
    - adding the block to the blockchain   (node.Node._accept_block)
    - validating the block for acceptance  (node.validator)
    - removing transactions from mempool   (node.Node._accept_block)
    - persistence                          (blockchain.storage)
    - network broadcast                    (node.p2p)

Dependencies are received as explicit parameters (no import of
node.config), so this module remains independently unit-testable
without a full NodeConfig.
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.blockchain.block import EMPTY_STATE_ROOT, Block
from src.blockchain.blockchain import Blockchain
from src.blockchain.transaction import Transaction
from src.crypto.ml_dsa import MLDSA
from src.node.mempool import Mempool


class ConsensusError(Exception):
    """Raised when a consensus rule is violated."""


class Consensus:
    """
    Round-robin PoA consensus over a fixed ordered validator set.

    Args:
        authorized_validators: Ordered sequence of validator addresses
            (20-byte values derived from ML-DSA public keys). The
            order is significant: it defines the round-robin schedule.
        local_address: The 20-byte address of the local node's
            validator. Used to determine whether it is this node's
            turn to propose.
    """

    def __init__(
        self,
        authorized_validators: Sequence[bytes],
        local_address: bytes,
    ) -> None:
        if not authorized_validators:
            raise ConsensusError("authorized_validators must not be empty")

        if local_address not in authorized_validators:
            raise ConsensusError(
                "local_address is not in authorized_validators; "
                "this node cannot participate as a validator"
            )

        self._validators = tuple(authorized_validators)
        self._local_address = local_address

    # ------------------------------------------------------------------
    # Turn scheduling
    # ------------------------------------------------------------------

    def get_expected_proposer(self, height: int, round: int = 0) -> bytes:
        """
        Return the address expected to propose `height` in `round`.

        The height remains the same while rounds advance. This makes a
        timeout a deterministic hand-off rather than permission for an
        arbitrary validator to produce a block.
        """
        if isinstance(height, bool) or not isinstance(height, int) or height < 0:
            raise ConsensusError("height must be a non-negative integer")
        if isinstance(round, bool) or not isinstance(round, int) or round < 0:
            raise ConsensusError("round must be a non-negative integer")

        return self._validators[(height + round) % len(self._validators)]

    def is_local_node_turn(self, height: int, round: int = 0) -> bool:
        """Return True if this node is expected at `height`/`round`."""
        return self.get_expected_proposer(height, round) == self._local_address

    def is_expected_proposer(self, block: Block) -> bool:
        """
        Return True only when the block validator matches the
        deterministic proposer for both its height and signed round.
        """
        return block.validator == self.get_expected_proposer(
            block.height, block.round
        )

    # ------------------------------------------------------------------
    # Block production
    # ------------------------------------------------------------------

    def build_candidate_block(
        self,
        blockchain: Blockchain,
        mempool: Mempool,
        local_public_key: bytes,
        local_secret_key: bytes,
        timestamp: int,
        ml_dsa: Optional[MLDSA] = None,
        max_transactions: Optional[int] = None,
        state_root: bytes = EMPTY_STATE_ROOT,
        transactions: Optional[Sequence[Transaction]] = None,
        round: int = 0,
    ) -> Block:
        """
        Build and sign a candidate block from the current mempool.

        The block is signed with the local validator's ML-DSA key but
        is NOT added to the blockchain here. The caller (node.Node)
        is responsible for passing it through
        validator.validate_block_for_acceptance() and then
        Node._accept_block(), which calls Blockchain.add_block().

        Args:
            blockchain: The local chain, used to obtain the current
                tip (previous_block_hash, next height).
            mempool: Source of pending transactions to include.
            local_public_key: ML-DSA public key of the local
                validator (used as validator_public_key in the block).
            local_secret_key: ML-DSA secret key used to sign the
                block.
            timestamp: Block timestamp (caller-provided, typically
                int(time.time())).
            ml_dsa: Optional MLDSA instance; a new one is created if
                not provided.
            max_transactions: Maximum number of transactions to
                include. Defaults to all pending transactions.
                Ignored when `transactions` is provided.
            state_root: EVM state root to record in the block. This
                module does not -- and must not -- compute it: doing so
                would make consensus depend on src.evm, hence on py-evm,
                for what is otherwise a pure scheduling concern. The
                caller (node.Node) owns the EVM state and passes the
                value in. The default keeps the block valid for callers
                that do not track EVM state at all.
            transactions: Exact transaction list to include. When
                omitted, the mempool is queried.

                Why this parameter exists: the caller must compute
                `state_root` over *exactly* the transactions that end up
                in the block. If it queried the mempool for the root and
                this method queried it again to build the block, a
                transaction arriving in between would silently make the
                announced root disagree with the block's own contents --
                a fork cause that no test would catch. Selecting once
                and passing the same list to both steps removes the
                window entirely.

        Raises:
            ConsensusError: If it is not the local node's turn to
                propose at the next height.
        """
        next_height = blockchain.height + 1

        if isinstance(round, bool) or not isinstance(round, int) or round < 0:
            raise ConsensusError("round must be a non-negative integer")

        if not self.is_local_node_turn(next_height, round):
            expected = self.get_expected_proposer(next_height, round)
            raise ConsensusError(
                f"it is not this node's turn to propose block at "
                f"height {next_height}, round {round}; expected proposer: "
                f"{expected.hex()}"
            )

        current_tip = blockchain.get_latest_block()

        selected = (
            list(transactions)
            if transactions is not None
            else mempool.get_pending(limit=max_transactions)
        )

        signer = ml_dsa or MLDSA()

        block = Block.create(
            height=next_height,
            previous_block_hash=current_tip.block_hash,
            timestamp=timestamp,
            transactions=selected,
            validator_public_key=local_public_key,
            round=round,
            state_root=state_root,
        )

        signature = signer.sign(block.signing_hash, local_secret_key)
        return block.with_signature(signature)
