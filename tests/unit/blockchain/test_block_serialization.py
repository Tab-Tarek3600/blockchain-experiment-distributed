"""
Tests de Block.to_dict() / from_dict(), séparés des tests de
signature ML-DSA pour rester ciblés sur la sérialisation.
"""

import pytest

from src.blockchain.block import Block, BlockError, ZERO_HASH
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH
from src.crypto.ml_dsa import MLDSA

RECIPIENT = b"\x01" * ADDRESS_LENGTH


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def validator_keypair(ml_dsa):
    return ml_dsa.generate_keypair()


@pytest.fixture
def sender_keypair(ml_dsa):
    return ml_dsa.generate_keypair()


def make_signed_tx(ml_dsa, sender_keypair, nonce=0):
    tx = Transaction.create(
        nonce=nonce,
        public_key=sender_keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"",
    )
    sig = ml_dsa.sign(tx.signing_hash, sender_keypair.secret_key)
    return tx.with_signature(sig)


def test_to_dict_contains_expected_keys(validator_keypair):
    block = Block.create(
        height=0,
        previous_block_hash=ZERO_HASH,
        timestamp=1000,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    data = block.to_dict()

    # `round` et `state_root` font partie de l'identité sérialisée du
    # bloc : le round est signé et la racine d'état est vérifiée par les
    # nœuds lors de l'acceptation.
    assert set(data.keys()) == {
        "height",
        "round",
        "previous_block_hash",
        "timestamp",
        "transactions",
        "validator",
        "validator_public_key",
        "state_root",
        "signature",
    }
    assert data["round"] == 0
    assert data["state_root"] == block.state_root.hex()
    assert data["transactions"] == []
    assert data["signature"] is None


def test_round_trip_unsigned_block(validator_keypair):
    block = Block.create(
        height=0,
        previous_block_hash=ZERO_HASH,
        timestamp=1000,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )

    restored = Block.from_dict(block.to_dict())

    assert restored == block


def test_round_trip_signed_block_with_transactions(
    ml_dsa, validator_keypair, sender_keypair
):
    tx = make_signed_tx(ml_dsa, sender_keypair)
    block = Block.create(
        height=0,
        previous_block_hash=ZERO_HASH,
        timestamp=1000,
        transactions=[tx],
        validator_public_key=validator_keypair.public_key,
    )
    signature = ml_dsa.sign(block.signing_hash, validator_keypair.secret_key)
    signed_block = block.with_signature(signature)

    restored = Block.from_dict(signed_block.to_dict())

    assert restored == signed_block
    assert restored.transaction_count == 1
    assert ml_dsa.verify(
        restored.signing_hash,
        restored.signature,
        restored.validator_public_key,
    ) is True


def test_from_dict_rejects_missing_field(validator_keypair):
    block = Block.create(
        height=0,
        previous_block_hash=ZERO_HASH,
        timestamp=1000,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    data = block.to_dict()
    del data["height"]

    with pytest.raises(BlockError):
        Block.from_dict(data)


def test_from_dict_rejects_invalid_transaction(validator_keypair):
    block = Block.create(
        height=0,
        previous_block_hash=ZERO_HASH,
        timestamp=1000,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    data = block.to_dict()
    data["transactions"] = [{"nonce": 0}]  # transaction incomplete

    with pytest.raises(BlockError):
        Block.from_dict(data)


def test_from_dict_rejects_tampered_validator(validator_keypair):
    block = Block.create(
        height=0,
        previous_block_hash=ZERO_HASH,
        timestamp=1000,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    data = block.to_dict()
    data["validator"] = "ff" * ADDRESS_LENGTH

    with pytest.raises(BlockError):
        Block.from_dict(data)
