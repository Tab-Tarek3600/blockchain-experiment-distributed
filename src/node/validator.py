"""
Node-level validation: cryptographic verification + contextual
acceptance rules, layered on top of blockchain.validation.

Separation of concerns:
    blockchain.validation  = structural, deterministic validation
                              (no cryptography, no notion of "who is
                              authorized")
    node.validator          = this module. Adds:
                                  - ML-DSA signature verification
                                  - PoA membership check (is the
                                    signer an authorized validator?)

This module deliberately does NOT decide whose *turn* it is to
propose a block (round-robin PoA scheduling). That is a separate
concern, owned by node.consensus.is_expected_proposer(), and is
always checked *after* validate_block_for_acceptance() succeeds. The
two checks answer different questions:
    - validator.py  : "is this a valid block, signed by *an*
                       authorized validator?"
    - consensus.py  : "was it specifically *this* validator's turn?"

Functions here receive all their dependencies as explicit parameters
(authorized_validators, ml_dsa) rather than importing node.config, so
they remain independently unit-testable without a full NodeConfig.

Fail-fast ordering in validate_block_for_acceptance (cheap checks
first, expensive ML-DSA verification last):
    1. structural validation (blockchain.validation.validate_block)
    2. chain link (previous_block_hash, height)
    3. authorized validator membership (address lookup, cheap)
    4. block signature verification (ML-DSA)
    5. transaction signatures verification (ML-DSA, one per tx)
    (6. PoA turn check -- performed separately by node.consensus)
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.blockchain.block import Block
from src.blockchain.transaction import Transaction
from src.blockchain.validation import (
    ValidationError,
    validate_block,
    validate_block_chain_link,
    validate_transaction,
)
from src.crypto.ml_dsa import MLDSA


class ValidatorError(Exception):
    """Raised when a transaction or block is rejected by the node."""


def validate_transaction_for_acceptance(
    transaction: Transaction, ml_dsa: Optional[MLDSA] = None
) -> None:
    """
    Validate a transaction for acceptance into the mempool.

    Steps:
        1. Structural validation, including the "must be signed" rule
           (blockchain.validation.validate_transaction).
        2. ML-DSA signature verification.

    Raises:
        ValidatorError: If either step fails.
    """
    try:
        validate_transaction(transaction)
    except ValidationError as exc:
        raise ValidatorError(f"transaction rejected (structure): {exc}") from exc

    verifier = ml_dsa or MLDSA()
    if not verifier.verify(
        transaction.signing_hash, transaction.signature, transaction.public_key
    ):
        raise ValidatorError("transaction rejected: invalid ML-DSA signature")


def validate_block_for_acceptance(
    block: Block,
    previous_block: Block,
    authorized_validators: Sequence[bytes],
    ml_dsa: Optional[MLDSA] = None,
) -> None:
    """
    Validate a block for acceptance into the local chain.

    See module docstring for the fail-fast ordering. Does NOT check
    whether it was this specific validator's turn to propose (that is
    node.consensus.is_expected_proposer, checked afterwards).

    Raises:
        ValidatorError: On the first failing check.
    """
    # 1. Structural validation.
    try:
        validate_block(block)
    except ValidationError as exc:
        raise ValidatorError(f"block rejected (structure): {exc}") from exc

    # 2. Chain link (height, previous_block_hash).
    try:
        validate_block_chain_link(previous_block, block)
    except ValidationError as exc:
        raise ValidatorError(f"block rejected (chain link): {exc}") from exc

    # 3. Authorized validator membership (cheap address comparison).
    if block.validator not in authorized_validators:
        raise ValidatorError(
            f"block rejected: validator {block.validator.hex()} is not "
            "an authorized PoA validator"
        )

    # 4. Block signature verification (ML-DSA).
    if not block.is_signed:
        raise ValidatorError("block rejected: block is not signed")

    verifier = ml_dsa or MLDSA()
    if not verifier.verify(
        block.signing_hash, block.signature, block.validator_public_key
    ):
        raise ValidatorError("block rejected: invalid validator ML-DSA signature")

    # 5. Transaction signatures verification (ML-DSA), one per tx.
    #    Note: Block already guarantees at construction time that every
    #    included transaction is structurally signed (BlockError
    #    otherwise); here we verify the signatures are cryptographically
    #    valid, which blockchain.validation deliberately does not do.
    for i, transaction in enumerate(block.transactions):
        if not verifier.verify(
            transaction.signing_hash, transaction.signature, transaction.public_key
        ):
            raise ValidatorError(
                f"block rejected: transaction at index {i} has an "
                "invalid ML-DSA signature"
            )
