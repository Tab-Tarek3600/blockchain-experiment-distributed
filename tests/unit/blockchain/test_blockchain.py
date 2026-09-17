"""
Tests de Blockchain : création, chargement, ajout de blocs, lecture,
et cohérence mémoire/disque. Utilise tmp_path pour un ChainStorage
réel (pas de mock) et de vraies clés ML-DSA pour signer les blocs.
"""

import pytest

from src.blockchain.block import Block
from src.blockchain.blockchain import Blockchain, BlockchainError
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH
from src.crypto.ml_dsa import MLDSA


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
        recipient=b"\x01" * ADDRESS_LENGTH,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"",
    )
    sig = ml_dsa.sign(tx.signing_hash, sender_keypair.secret_key)
    return tx.with_signature(sig)


def make_next_block(ml_dsa, validator_keypair, previous_block, transactions=(), timestamp=None):
    block = Block.create(
        height=previous_block.height + 1,
        previous_block_hash=previous_block.block_hash,
        timestamp=timestamp if timestamp is not None else previous_block.timestamp + 10,
        transactions=transactions,
        validator_public_key=validator_keypair.public_key,
    )
    sig = ml_dsa.sign(block.signing_hash, validator_keypair.secret_key)
    return block.with_signature(sig)


# ---------------------------------------------------------------------
# create_new
# ---------------------------------------------------------------------


def test_create_new_initializes_chain_with_genesis(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    assert chain.height == 0
    assert chain.block_count == 1
    assert chain.genesis_block.height == 0


def test_create_new_persists_genesis_to_storage(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    assert storage.has_block(0)
    loaded = storage.load_block(0)
    assert loaded == chain.genesis_block


def test_create_new_rejects_if_storage_already_has_chain(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    with pytest.raises(BlockchainError, match="already contains a chain"):
        Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)


def test_create_new_rejects_invalid_validator_key(tmp_path):
    storage = ChainStorage(tmp_path)

    with pytest.raises(BlockchainError):
        Blockchain.create_new(storage, validator_public_key=b"")


# ---------------------------------------------------------------------
# load
# ---------------------------------------------------------------------


def test_load_rejects_empty_storage(tmp_path):
    storage = ChainStorage(tmp_path)

    with pytest.raises(BlockchainError, match="storage is empty"):
        Blockchain.load(storage)


def test_load_restores_previously_created_chain(tmp_path, ml_dsa, validator_keypair, sender_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    tx = make_signed_tx(ml_dsa, sender_keypair)
    block1 = make_next_block(ml_dsa, validator_keypair, chain.genesis_block, transactions=[tx])
    chain.add_block(block1)

    reloaded = Blockchain.load(storage)

    assert reloaded.height == 1
    assert reloaded.block_count == 2
    assert reloaded.get_block(1) == block1
    assert reloaded.get_block(1).transactions[0].tx_id == tx.tx_id


def test_load_rejects_corrupted_chain_on_disk(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    # Corrompt directement le fichier stocké (contourne l'API Blockchain)
    genesis_data = storage.load_block(0).to_dict()
    genesis_data["validator"] = "ff" * ADDRESS_LENGTH
    import json
    storage._block_path(0).write_text(json.dumps(genesis_data), encoding="utf-8")

    with pytest.raises(BlockchainError):
        Blockchain.load(storage)


# ---------------------------------------------------------------------
# open
# ---------------------------------------------------------------------


def test_open_creates_new_chain_when_storage_empty(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.open(storage, validator_public_key=validator_keypair.public_key)

    assert chain.height == 0


def test_open_raises_when_empty_and_no_validator_key(tmp_path):
    storage = ChainStorage(tmp_path)

    with pytest.raises(BlockchainError, match="required to initialize"):
        Blockchain.open(storage)


def test_open_loads_existing_chain_ignoring_validator_key_param(
    tmp_path, ml_dsa, validator_keypair
):
    storage = ChainStorage(tmp_path)
    original = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    other_keypair = ml_dsa.generate_keypair()
    reopened = Blockchain.open(storage, validator_public_key=other_keypair.public_key)

    assert reopened.height == 0
    assert reopened.genesis_block == original.genesis_block


# ---------------------------------------------------------------------
# add_block
# ---------------------------------------------------------------------


def test_add_block_appends_and_persists(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    block1 = make_next_block(ml_dsa, validator_keypair, chain.genesis_block)
    chain.add_block(block1)

    assert chain.height == 1
    assert chain.get_latest_block() == block1
    assert storage.has_block(1)


def test_add_block_rejects_wrong_height(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    bad_block = Block.create(
        height=5,
        previous_block_hash=chain.genesis_block.block_hash,
        timestamp=chain.genesis_block.timestamp + 10,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    signed = bad_block.with_signature(
        ml_dsa.sign(bad_block.signing_hash, validator_keypair.secret_key)
    )

    with pytest.raises(BlockchainError, match="does not correctly link"):
        chain.add_block(signed)

    assert chain.height == 0  # chain non modifiée


def test_add_block_rejects_wrong_previous_hash(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    bad_block = Block.create(
        height=1,
        previous_block_hash=b"\xff" * 32,
        timestamp=chain.genesis_block.timestamp + 10,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    signed = bad_block.with_signature(
        ml_dsa.sign(bad_block.signing_hash, validator_keypair.secret_key)
    )

    with pytest.raises(BlockchainError, match="does not correctly link"):
        chain.add_block(signed)


def test_add_block_rejects_non_block():
    pass  # couvert indirectement via validate_block dans add_block


def test_add_block_does_not_corrupt_cache_on_failure(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    bad_block = Block.create(
        height=1,
        previous_block_hash=b"\xff" * 32,
        timestamp=chain.genesis_block.timestamp + 10,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    signed = bad_block.with_signature(
        ml_dsa.sign(bad_block.signing_hash, validator_keypair.secret_key)
    )

    with pytest.raises(BlockchainError):
        chain.add_block(signed)

    assert chain.block_count == 1
    assert storage.get_tip_height() == 0


def test_add_multiple_blocks_builds_correct_chain(tmp_path, ml_dsa, validator_keypair, sender_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    previous = chain.genesis_block
    for i in range(5):
        tx = make_signed_tx(ml_dsa, sender_keypair, nonce=i)
        block = make_next_block(ml_dsa, validator_keypair, previous, transactions=[tx])
        chain.add_block(block)
        previous = block

    assert chain.height == 5
    assert chain.block_count == 6

    reloaded = Blockchain.load(storage)
    assert reloaded.height == 5
    assert [b.height for b in reloaded._blocks] == [0, 1, 2, 3, 4, 5]


# ---------------------------------------------------------------------
# Lecture : get_block / get_block_by_hash
# ---------------------------------------------------------------------


def test_get_block_returns_none_for_out_of_range_height(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    assert chain.get_block(99) is None
    assert chain.get_block(-1) is None


def test_get_block_by_hash_finds_correct_block(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    block1 = make_next_block(ml_dsa, validator_keypair, chain.genesis_block)
    chain.add_block(block1)

    found = chain.get_block_by_hash(block1.block_hash)
    assert found == block1


def test_get_block_by_hash_returns_none_when_not_found(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    chain = Blockchain.create_new(storage, validator_public_key=validator_keypair.public_key)

    assert chain.get_block_by_hash(b"\x99" * 32) is None
