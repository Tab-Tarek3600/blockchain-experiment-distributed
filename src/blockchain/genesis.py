"""
Genesis block creation and validation.

The genesis block is the deterministic starting point of the chain
(height 0). It is typically agreed upon out-of-band by all nodes
(shared configuration), rather than produced dynamically like normal
blocks.

Current limitation (intentional, revisited later):
    The genesis block created here never contains transactions. A
    transaction represents a transfer from an *existing* account, but
    at genesis time no account/state model exists yet (no balances,
    no nonces). Pre-allocation ("genesis mint") would require a state
    model and a dedicated transaction type that this project does not
    have yet (planned for blockchain.py / state layer). Until then,
    genesis blocks are structurally restricted to zero transactions.
"""

from __future__ import annotations

from typing import Optional

from src.blockchain.block import Block, BlockError, ZERO_HASH
from src.blockchain.validation import ValidationError, validate_block

GENESIS_HEIGHT = 0

# Default timestamp used when no explicit timestamp is provided.
# In a real multi-node deployment, all nodes MUST agree on the exact
# same timestamp (it is part of the shared genesis configuration).
DEFAULT_GENESIS_TIMESTAMP = 1_700_000_000


class GenesisError(Exception):
    """Raised when genesis block creation or validation fails."""


def create_genesis_block(
    *,
    validator_public_key: bytes,
    timestamp: int = DEFAULT_GENESIS_TIMESTAMP,
) -> Block:
    """
    Create the canonical, unsigned genesis block.

    Args:
        validator_public_key: ML-DSA public key of the initial PoA
            validator. The `validator` address field is derived from
            it automatically (see Block.create).
        timestamp: Fixed timestamp shared by all nodes of the network.

    Returns:
        An unsigned Block with height=0, previous_block_hash=ZERO_HASH
        and no transactions.

    Raises:
        GenesisError: If the block cannot be constructed (e.g. invalid
            validator_public_key).
    """
    try:
        return Block.create(
            height=GENESIS_HEIGHT,
            previous_block_hash=ZERO_HASH,
            timestamp=timestamp,
            transactions=(),
            validator_public_key=validator_public_key,
        )
    except BlockError as exc:
        raise GenesisError(f"failed to create genesis block: {exc}") from exc


def sign_genesis_block(genesis: Block, secret_key: bytes, ml_dsa=None) -> Block:
    """
    Convenience helper to sign a genesis block with ML-DSA.

    Signing the genesis block is optional: in most PoA deployments the
    genesis block is a shared configuration artifact agreed upon by
    all nodes rather than a cryptographically authorized block. This
    helper exists for setups that do want an explicit genesis
    authority signature.

    Args:
        genesis: An unsigned genesis block (as returned by
            create_genesis_block).
        secret_key: ML-DSA secret key of the genesis authority. Must
            correspond to genesis.validator_public_key.
        ml_dsa: Optional MLDSA instance (a new one is created if not
            provided).

    Returns:
        A new Block instance with the signature attached.
    """
    from src.crypto.ml_dsa import MLDSA

    if not is_genesis_block(genesis):
        raise GenesisError("provided block is not a valid genesis block shape")

    signer = ml_dsa or MLDSA()
    signature = signer.sign(genesis.signing_hash, secret_key)

    try:
        return genesis.with_signature(signature)
    except BlockError as exc:
        raise GenesisError(f"failed to attach genesis signature: {exc}") from exc


def is_genesis_block(block: Block) -> bool:
    """
    Return True if `block` has the structural shape of a genesis
    block (height 0, previous_block_hash is ZERO_HASH, no
    transactions), regardless of cryptographic validity.
    """
    if not isinstance(block, Block):
        return False

    return (
        block.height == GENESIS_HEIGHT
        and block.previous_block_hash == ZERO_HASH
        and block.transaction_count == 0
    )


def validate_genesis_block(
    block: Block,
    *,
    expected_validator_public_key: Optional[bytes] = None,
    expected_timestamp: Optional[int] = None,
) -> bool:
    """
    Validate that `block` is a structurally correct genesis block.

    Beyond generic block validation (validate_block), this enforces
    genesis-specific rules:
        - height must be 0
        - previous_block_hash must be ZERO_HASH
        - the block must not contain any transaction
        - optionally, the validator public key and timestamp must
          match expected values (useful when a node checks that a
          received genesis block matches its local configuration).

    Raises:
        GenesisError: If any genesis-specific rule is violated.
    """
    try:
        validate_block(block)
    except ValidationError as exc:
        raise GenesisError(str(exc)) from exc

    if block.height != GENESIS_HEIGHT:
        raise GenesisError(
            f"genesis block height must be {GENESIS_HEIGHT}, got {block.height}"
        )

    if block.previous_block_hash != ZERO_HASH:
        raise GenesisError("genesis block previous_block_hash must be ZERO_HASH")

    if block.transaction_count != 0:
        raise GenesisError(
            "genesis block must not contain any transaction "
            "(no account/state model exists at genesis time yet)"
        )

    if (
        expected_validator_public_key is not None
        and block.validator_public_key != expected_validator_public_key
    ):
        raise GenesisError(
            "genesis block validator_public_key does not match the expected value"
        )

    if expected_timestamp is not None and block.timestamp != expected_timestamp:
        raise GenesisError(
            "genesis block timestamp does not match the expected value"
        )

    return True


def is_genesis_block_valid(
    block: Block,
    *,
    expected_validator_public_key: Optional[bytes] = None,
    expected_timestamp: Optional[int] = None,
) -> bool:
    """Boolean wrapper around validate_genesis_block."""
    try:
        return validate_genesis_block(
            block,
            expected_validator_public_key=expected_validator_public_key,
            expected_timestamp=expected_timestamp,
        )
    except GenesisError:
        return False
