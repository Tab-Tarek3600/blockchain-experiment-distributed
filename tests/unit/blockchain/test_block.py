"""
Tests de Block : construction, structure, et intégration avec
ML-DSA pour la signature/vérification réelle du validateur.
"""

import pytest

from src.blockchain.block import Block, BlockError, HASH_SIZE, ZERO_HASH
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
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
    signature = ml_dsa.sign(tx.signing_hash, sender_keypair.secret_key)
    return tx.with_signature(signature)


def make_block(validator_keypair, height=0, previous_block_hash=None, transactions=None, timestamp=1000):
    return Block.create(
        height=height,
        previous_block_hash=previous_block_hash or ZERO_HASH,
        timestamp=timestamp,
        validator_public_key=validator_keypair.public_key,
        transactions=transactions or (),
    )


def test_create_derives_validator_from_public_key(validator_keypair):
    block = make_block(validator_keypair)
    assert block.validator == public_key_to_address(validator_keypair.public_key)


def test_create_rejects_unsigned_transaction(validator_keypair, sender_keypair):
    unsigned_tx = Transaction.create(
        nonce=0,
        public_key=sender_keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )

    with pytest.raises(BlockError):
        make_block(validator_keypair, transactions=[unsigned_tx])


def test_create_rejects_duplicate_transactions(ml_dsa, validator_keypair, sender_keypair):
    tx = make_signed_tx(ml_dsa, sender_keypair)

    with pytest.raises(BlockError):
        make_block(validator_keypair, transactions=[tx, tx])


def test_sign_and_verify_valid_block(ml_dsa, validator_keypair, sender_keypair):
    tx = make_signed_tx(ml_dsa, sender_keypair)
    block = make_block(validator_keypair, transactions=[tx])

    signature = ml_dsa.sign(block.signing_hash, validator_keypair.secret_key)
    signed_block = block.with_signature(signature)

    assert signed_block.is_signed is True
    assert ml_dsa.verify(
        signed_block.signing_hash, signed_block.signature, signed_block.validator_public_key
    ) is True


def test_with_signature_returns_new_instance(ml_dsa, validator_keypair):
    block = make_block(validator_keypair)
    signature = ml_dsa.sign(block.signing_hash, validator_keypair.secret_key)
    signed_block = block.with_signature(signature)

    assert block.signature is None
    assert signed_block.signature is not None
    assert block is not signed_block


def test_signing_hash_stable_before_and_after_signing(ml_dsa, validator_keypair):
    block = make_block(validator_keypair)
    signing_hash_before = block.signing_hash

    signature = ml_dsa.sign(block.signing_hash, validator_keypair.secret_key)
    signed_block = block.with_signature(signature)

    assert signed_block.signing_hash == signing_hash_before


def test_block_hash_changes_when_signature_attached(ml_dsa, validator_keypair):
    block = make_block(validator_keypair)
    unsigned_hash = block.block_hash

    signature = ml_dsa.sign(block.signing_hash, validator_keypair.secret_key)
    signed_block = block.with_signature(signature)

    assert signed_block.block_hash != unsigned_hash


def test_transactions_root_changes_with_transactions(ml_dsa, validator_keypair, sender_keypair):
    tx1 = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx2 = make_signed_tx(ml_dsa, sender_keypair, nonce=1)

    block_empty = make_block(validator_keypair, transactions=[])
    block_one_tx = make_block(validator_keypair, transactions=[tx1])
    block_two_tx = make_block(validator_keypair, transactions=[tx1, tx2])

    assert block_empty.transactions_root == ZERO_HASH
    assert block_empty.transactions_root != block_one_tx.transactions_root
    assert block_one_tx.transactions_root != block_two_tx.transactions_root


def test_block_hash_is_deterministic(validator_keypair):
    block = make_block(validator_keypair)
    assert block.block_hash == block.block_hash
    assert len(block.block_hash) == HASH_SIZE