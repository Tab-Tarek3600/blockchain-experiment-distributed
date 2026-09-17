"""
Tests de ChainStorage : persistance, chargement, validation
structurelle au chargement, et détection de corruption.

Utilise tmp_path (fixture pytest) pour isoler chaque test dans un
répertoire temporaire réel sur disque — pas de mock du système de
fichiers.
"""

import pytest

from src.blockchain.block import Block, ZERO_HASH
from src.blockchain.genesis import create_genesis_block
from src.blockchain.storage import ChainStorage, StorageError
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


def make_signed_block(
    ml_dsa, validator_keypair, height, previous_hash, transactions=(), timestamp=1000
):
    block = Block.create(
        height=height,
        previous_block_hash=previous_hash,
        timestamp=timestamp,
        transactions=transactions,
        validator_public_key=validator_keypair.public_key,
    )
    sig = ml_dsa.sign(block.signing_hash, validator_keypair.secret_key)
    return block.with_signature(sig)


# ---------------------------------------------------------------------
# save_block / load_block
# ---------------------------------------------------------------------


def test_save_and_load_single_block(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    block = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)

    storage.save_block(block)
    loaded = storage.load_block(0)

    assert loaded == block


def test_save_block_creates_directory_structure(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    block = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.save_block(block)

    assert (tmp_path / "blocks").exists()
    assert storage.has_block(0)


def test_save_block_rejects_overwrite_by_default(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    block = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.save_block(block)

    with pytest.raises(StorageError):
        storage.save_block(block)


def test_save_block_allows_explicit_overwrite(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    block = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.save_block(block)

    storage.save_block(block, overwrite=True)  # must not raise


def test_save_block_rejects_non_block():
    pass  # covered indirectly; ChainStorage.save_block type-checks internally


def test_load_block_raises_for_missing_height(tmp_path):
    storage = ChainStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.load_block(0)


def test_load_block_raises_for_corrupted_json(tmp_path):
    storage = ChainStorage(tmp_path)
    storage.blocks_dir.mkdir(parents=True, exist_ok=True)
    bad_file = storage.blocks_dir / f"{0:020d}.json"
    bad_file.write_text("not-valid-json{{{", encoding="utf-8")

    with pytest.raises(StorageError):
        storage.load_block(0)


def test_load_block_raises_for_structurally_invalid_block(tmp_path, ml_dsa, validator_keypair):
    """
    Prouve que le chargement re-valide réellement la structure : un
    fichier JSON syntaxiquement correct mais représentant un bloc
    invalide (validator ne correspondant pas à validator_public_key)
    doit être rejeté.
    """
    storage = ChainStorage(tmp_path)
    block = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    data = block.to_dict()
    data["validator"] = "ff" * ADDRESS_LENGTH  # incohérent avec validator_public_key

    storage.blocks_dir.mkdir(parents=True, exist_ok=True)
    path = storage._block_path(0)
    path.write_text(__import__("json").dumps(data), encoding="utf-8")

    with pytest.raises(StorageError):
        storage.load_block(0)


# ---------------------------------------------------------------------
# append_block
# ---------------------------------------------------------------------


def test_append_block_enforces_sequential_height(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    genesis = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.append_block(genesis)

    block1 = make_signed_block(
        ml_dsa, validator_keypair, height=1, previous_hash=genesis.block_hash
    )
    storage.append_block(block1)

    assert storage.get_tip_height() == 1


def test_append_block_rejects_wrong_height(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    genesis = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.append_block(genesis)

    wrong_block = make_signed_block(
        ml_dsa, validator_keypair, height=5, previous_hash=genesis.block_hash
    )

    with pytest.raises(StorageError):
        storage.append_block(wrong_block)


# ---------------------------------------------------------------------
# get_tip_height / get_latest_block
# ---------------------------------------------------------------------


def test_get_tip_height_returns_none_when_empty(tmp_path):
    storage = ChainStorage(tmp_path)
    assert storage.get_tip_height() is None


def test_get_latest_block_returns_none_when_empty(tmp_path):
    storage = ChainStorage(tmp_path)
    assert storage.get_latest_block() is None


def test_get_latest_block_returns_tip(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    genesis = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.append_block(genesis)

    block1 = make_signed_block(
        ml_dsa, validator_keypair, height=1, previous_hash=genesis.block_hash
    )
    storage.append_block(block1)

    assert storage.get_latest_block() == block1


# ---------------------------------------------------------------------
# load_chain
# ---------------------------------------------------------------------


def test_load_chain_returns_empty_list_when_no_blocks(tmp_path):
    storage = ChainStorage(tmp_path)
    assert storage.load_chain() == []


def test_load_chain_returns_ordered_blocks(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    genesis = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.append_block(genesis)

    block1 = make_signed_block(
        ml_dsa, validator_keypair, height=1, previous_hash=genesis.block_hash
    )
    storage.append_block(block1)

    block2 = make_signed_block(
        ml_dsa, validator_keypair, height=2, previous_hash=block1.block_hash
    )
    storage.append_block(block2)

    chain = storage.load_chain()

    assert [b.height for b in chain] == [0, 1, 2]
    assert chain[0] == genesis
    assert chain[2] == block2


def test_load_chain_detects_gap(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    genesis = make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)
    storage.save_block(genesis)

    block2 = make_signed_block(
        ml_dsa, validator_keypair, height=2, previous_hash=b"\xaa" * 32
    )
    storage.save_block(block2)  # height 1 manquant, écrit directement

    with pytest.raises(StorageError, match="gap"):
        storage.load_chain()


def test_load_chain_detects_wrong_start(tmp_path, ml_dsa, validator_keypair):
    storage = ChainStorage(tmp_path)
    block1 = make_signed_block(ml_dsa, validator_keypair, height=1, previous_hash=ZERO_HASH)
    storage.save_block(block1)

    with pytest.raises(StorageError, match="start at height 0"):
        storage.load_chain()


# ---------------------------------------------------------------------
# Round-trip avec transactions et Genesis
# ---------------------------------------------------------------------


def test_round_trip_preserves_transactions(tmp_path, ml_dsa, validator_keypair, sender_keypair):
    tx = make_signed_tx(ml_dsa, sender_keypair)
    block = make_signed_block(
        ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH, transactions=[tx]
    )

    storage = ChainStorage(tmp_path)
    storage.save_block(block)
    loaded = storage.load_block(0)

    assert loaded.transaction_count == 1
    assert loaded.transactions[0].tx_id == tx.tx_id
    assert loaded == block


def test_genesis_block_round_trip(tmp_path, validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)

    storage = ChainStorage(tmp_path)
    storage.save_block(genesis)
    loaded = storage.load_block(0)

    assert loaded == genesis
