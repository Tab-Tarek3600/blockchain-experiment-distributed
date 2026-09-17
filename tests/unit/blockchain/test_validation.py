import pytest

from src.blockchain.block import HASH_SIZE, ZERO_HASH, Block, BlockError
from src.blockchain.transaction import Transaction
from src.blockchain.validation import (
    ValidationError,
    is_block_valid,
    is_transaction_valid,
    validate_block,
    validate_block_chain_link,
    validate_block_sequence,
    validate_transaction,
    validate_transaction_list,
)
from src.crypto.address import ADDRESS_LENGTH


VALIDATOR_PUBLIC_KEY = b"validator-public-key"

RECIPIENT_A = b"\x01" * ADDRESS_LENGTH
RECIPIENT_B = b"\x02" * ADDRESS_LENGTH


def make_tx(
    *,
    nonce: int = 0,
    public_key: bytes = b"transaction-public-key",
    recipient: bytes = RECIPIENT_A,
    value: int = 100,
    signature: bytes | None = b"transaction-signature",
) -> Transaction:
    tx = Transaction.create(
        nonce=nonce,
        public_key=public_key,
        recipient=recipient,
        value=value,
        gas_limit=21000,
        gas_price=1,
        data=b"",
    )

    if signature is not None:
        tx = tx.with_signature(signature)

    return tx


def make_block(
    *,
    height: int = 0,
    previous_block_hash: bytes | None = None,
    timestamp: int = 1000,
    transactions=None,
):
    return Block.create(
        height=height,
        previous_block_hash=previous_block_hash or ZERO_HASH,
        timestamp=timestamp,
        validator_public_key=VALIDATOR_PUBLIC_KEY,
        transactions=transactions or [],
    )


# ---------------------------------------------------------------------
# Transaction validation
# ---------------------------------------------------------------------


def test_validate_transaction_accepts_valid_transaction():
    tx = make_tx()
    assert validate_transaction(tx) is True


def test_validate_transaction_rejects_non_transaction():
    with pytest.raises(ValidationError):
        validate_transaction("not-a-transaction")


def test_validate_transaction_rejects_unsigned_transaction():
    tx = make_tx(signature=None)
    with pytest.raises(ValidationError):
        validate_transaction(tx)


def test_validate_transaction_returns_true_for_signed_transaction():
    tx = make_tx()
    assert validate_transaction(tx) is True


# ---------------------------------------------------------------------
# Transaction list validation
# ---------------------------------------------------------------------


def test_validate_transaction_list_accepts_empty_list():
    assert validate_transaction_list([]) is True


def test_validate_transaction_list_accepts_valid_transactions():
    tx_a = make_tx(nonce=0, public_key=b"public-key-a")
    tx_b = make_tx(nonce=1, public_key=b"public-key-b")
    assert validate_transaction_list([tx_a, tx_b]) is True


def test_validate_transaction_list_accepts_tuple():
    tx = make_tx()
    assert validate_transaction_list((tx,)) is True


def test_validate_transaction_list_rejects_non_collection():
    with pytest.raises(ValidationError):
        validate_transaction_list("not-a-list")


def test_validate_transaction_list_rejects_invalid_item():
    with pytest.raises(ValidationError):
        validate_transaction_list(["not-a-transaction"])


def test_validate_transaction_list_rejects_unsigned_transaction():
    tx = make_tx(signature=None)
    with pytest.raises(ValidationError):
        validate_transaction_list([tx])


def test_validate_transaction_list_rejects_duplicate_transaction_ids():
    tx = make_tx()
    with pytest.raises(ValidationError):
        validate_transaction_list([tx, tx])


# ---------------------------------------------------------------------
# Block validation
# ---------------------------------------------------------------------


def test_validate_block_accepts_valid_block():
    tx = make_tx()
    block = make_block(transactions=[tx])
    assert validate_block(block) is True


def test_validate_block_accepts_empty_block():
    block = make_block()
    assert validate_block(block) is True


def test_validate_block_rejects_non_block():
    with pytest.raises(ValidationError):
        validate_block("not-a-block")


def test_validate_block_rejects_block_with_unsigned_transaction():
    """
    Block garantit à la construction que toutes ses transactions sont
    signées : le rejet se produit dès Block.create() (via
    __post_init__ -> validate_structure()), avant même que
    validate_block() ne puisse être appelé.
    """
    tx = make_tx(signature=None)

    with pytest.raises(BlockError):
        make_block(transactions=[tx])


# ---------------------------------------------------------------------
# Block linking
# ---------------------------------------------------------------------


def test_validate_block_chain_link_accepts_valid_link():
    block_a = make_block(height=0, timestamp=1000)
    block_b = make_block(height=1, timestamp=2000, previous_block_hash=block_a.block_hash)

    assert validate_block_chain_link(block_a, block_b) is True


def test_validate_block_chain_link_rejects_wrong_previous_hash():
    block_a = make_block(height=0, timestamp=1000)
    block_b = make_block(height=1, timestamp=2000, previous_block_hash=b"\xbb" * HASH_SIZE)

    with pytest.raises(ValidationError):
        validate_block_chain_link(block_a, block_b)


def test_validate_block_chain_link_rejects_wrong_height():
    block_a = make_block(height=0, timestamp=1000)
    block_b = make_block(height=2, timestamp=2000, previous_block_hash=block_a.block_hash)

    with pytest.raises(ValidationError):
        validate_block_chain_link(block_a, block_b)


def test_validate_block_chain_link_rejects_non_block():
    block = make_block()
    with pytest.raises(ValidationError):
        validate_block_chain_link(block, "not-a-block")


# ---------------------------------------------------------------------
# Block sequence
# ---------------------------------------------------------------------


def test_validate_block_sequence_accepts_single_block():
    block = make_block(height=0)
    assert validate_block_sequence([block]) is True


def test_validate_block_sequence_accepts_valid_chain():
    block_a = make_block(height=0, timestamp=1000)
    block_b = make_block(height=1, timestamp=2000, previous_block_hash=block_a.block_hash)
    block_c = make_block(height=2, timestamp=3000, previous_block_hash=block_b.block_hash)

    assert validate_block_sequence([block_a, block_b, block_c]) is True


def test_validate_block_sequence_rejects_empty_sequence():
    with pytest.raises(ValidationError):
        validate_block_sequence([])


def test_validate_block_sequence_rejects_non_sequence():
    with pytest.raises(ValidationError):
        validate_block_sequence("not-a-sequence")


def test_validate_block_sequence_rejects_invalid_link():
    block_a = make_block(height=0, timestamp=1000)
    block_b = make_block(height=1, timestamp=2000, previous_block_hash=b"\xcc" * HASH_SIZE)

    with pytest.raises(ValidationError):
        validate_block_sequence([block_a, block_b])


def test_validate_block_sequence_rejects_height_gap():
    block_a = make_block(height=0, timestamp=1000)
    block_b = make_block(height=2, timestamp=2000, previous_block_hash=block_a.block_hash)

    with pytest.raises(ValidationError):
        validate_block_sequence([block_a, block_b])


# ---------------------------------------------------------------------
# Boolean wrappers
# ---------------------------------------------------------------------


def test_is_transaction_valid_wrapper():
    assert is_transaction_valid(make_tx()) is True
    assert is_transaction_valid(make_tx(signature=None)) is False


def test_is_block_valid_wrapper():
    assert is_block_valid(make_block()) is True
    assert is_block_valid("not-a-block") is False