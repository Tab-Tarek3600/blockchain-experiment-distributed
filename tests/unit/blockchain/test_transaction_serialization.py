"""
Tests de Transaction.to_dict() / from_dict(), séparés des tests de
signature ML-DSA pour rester ciblés sur la sérialisation.
"""

import pytest

from src.blockchain.transaction import Transaction, TransactionError
from src.crypto.address import ADDRESS_LENGTH
from src.crypto.ml_dsa import MLDSA

RECIPIENT = b"\x01" * ADDRESS_LENGTH


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def keypair(ml_dsa):
    return ml_dsa.generate_keypair()


def test_to_dict_contains_expected_keys(keypair):
    tx = Transaction.create(
        nonce=1,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"payload",
    )
    d = tx.to_dict()

    assert set(d.keys()) == {
        "nonce", "sender", "recipient", "value",
        "gas_limit", "gas_price", "data", "public_key", "signature",
    }
    assert d["signature"] is None


def test_round_trip_unsigned_transaction(keypair):
    tx = Transaction.create(
        nonce=1,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"payload",
    )

    restored = Transaction.from_dict(tx.to_dict())

    assert restored == tx


def test_round_trip_signed_transaction(ml_dsa, keypair):
    tx = Transaction.create(
        nonce=1,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"payload",
    )
    signature = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    signed_tx = tx.with_signature(signature)

    restored = Transaction.from_dict(signed_tx.to_dict())

    assert restored == signed_tx
    assert ml_dsa.verify(restored.signing_hash, restored.signature, restored.public_key) is True


def test_from_dict_rejects_missing_field(keypair):
    tx = Transaction.create(
        nonce=1,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )
    data = tx.to_dict()
    del data["nonce"]

    with pytest.raises(TransactionError):
        Transaction.from_dict(data)


def test_from_dict_rejects_invalid_hex(keypair):
    tx = Transaction.create(
        nonce=1,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )
    data = tx.to_dict()
    data["sender"] = "not-valid-hex-zz"

    with pytest.raises(TransactionError):
        Transaction.from_dict(data)


def test_from_dict_rejects_tampered_sender(keypair):
    tx = Transaction.create(
        nonce=1,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )
    data = tx.to_dict()
    data["sender"] = "ff" * ADDRESS_LENGTH  # ne correspond plus a public_key

    with pytest.raises(TransactionError):
        Transaction.from_dict(data)
