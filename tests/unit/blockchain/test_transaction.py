"""
Tests de Transaction : construction, structure, et intégration
avec ML-DSA pour la signature/vérification réelle.
"""

import pytest

from src.blockchain.transaction import MAX_DATA_SIZE, Transaction, TransactionError
from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
from src.crypto.ml_dsa import MLDSA

RECIPIENT = b"\x01" * ADDRESS_LENGTH


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def keypair(ml_dsa):
    return ml_dsa.generate_keypair()


def make_unsigned_tx(keypair, nonce=0, recipient=RECIPIENT, data=b"hello"):
    return Transaction.create(
        nonce=nonce,
        public_key=keypair.public_key,
        recipient=recipient,
        value=100,
        gas_limit=21000,
        gas_price=1,
        data=data,
    )


def test_create_derives_sender_from_public_key(keypair):
    tx = make_unsigned_tx(keypair)
    assert tx.sender == public_key_to_address(keypair.public_key)


def test_create_produces_unsigned_transaction(keypair):
    tx = make_unsigned_tx(keypair)
    assert tx.is_signed is False
    assert tx.signature is None


def test_sign_and_verify_valid_transaction(ml_dsa, keypair):
    tx = make_unsigned_tx(keypair)
    signature = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    signed_tx = tx.with_signature(signature)

    assert signed_tx.is_signed is True
    assert ml_dsa.verify(signed_tx.signing_hash, signed_tx.signature, signed_tx.public_key) is True


def test_verify_fails_if_signing_hash_tampered(ml_dsa, keypair):
    tx = make_unsigned_tx(keypair)
    signature = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    signed_tx = tx.with_signature(signature)

    other_tx = make_unsigned_tx(keypair, data=b"different-payload")

    assert ml_dsa.verify(other_tx.signing_hash, signed_tx.signature, signed_tx.public_key) is False


def test_with_signature_returns_new_instance(ml_dsa, keypair):
    tx = make_unsigned_tx(keypair)
    signature = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    signed_tx = tx.with_signature(signature)

    assert tx.signature is None
    assert signed_tx.signature is not None
    assert tx is not signed_tx


def test_with_signature_rejects_empty_signature(keypair):
    tx = make_unsigned_tx(keypair)
    with pytest.raises(TransactionError):
        tx.with_signature(b"")


def test_signing_hash_stable_before_and_after_signing(ml_dsa, keypair):
    tx = make_unsigned_tx(keypair)
    signing_hash_before = tx.signing_hash

    signature = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    signed_tx = tx.with_signature(signature)

    assert signed_tx.signing_hash == signing_hash_before


def test_tx_id_changes_when_signature_is_attached(ml_dsa, keypair):
    tx = make_unsigned_tx(keypair)
    unsigned_tx_id = tx.tx_id

    signature = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    signed_tx = tx.with_signature(signature)

    assert signed_tx.tx_id != unsigned_tx_id


def test_tx_id_is_deterministic(keypair):
    tx = make_unsigned_tx(keypair)
    assert tx.tx_id == tx.tx_id
    assert len(tx.tx_id) == 32


def test_create_rejects_wrong_length_recipient(keypair):
    with pytest.raises(TransactionError):
        Transaction.create(
            nonce=0,
            public_key=keypair.public_key,
            recipient=b"\x01" * 10,
            value=1,
            gas_limit=21000,
            gas_price=1,
        )


def test_create_rejects_empty_public_key():
    with pytest.raises(TransactionError):
        Transaction.create(
            nonce=0,
            public_key=b"",
            recipient=RECIPIENT,
            value=1,
            gas_limit=21000,
            gas_price=1,
        )


def test_create_rejects_negative_value(keypair):
    with pytest.raises(TransactionError):
        Transaction.create(
            nonce=0,
            public_key=keypair.public_key,
            recipient=RECIPIENT,
            value=-1,
            gas_limit=21000,
            gas_price=1,
        )


def test_create_rejects_oversized_data(keypair):
    with pytest.raises(TransactionError):
        Transaction.create(
            nonce=0,
            public_key=keypair.public_key,
            recipient=RECIPIENT,
            value=1,
            gas_limit=21000,
            gas_price=1,
            data=b"\x00" * (MAX_DATA_SIZE + 1),
        )