"""
Tests du module genesis.py : création déterministe et validation du
bloc Genesis. Utilise de vraies clés ML-DSA pour les cas de test qui
impliquent une signature.
"""

import pytest

from src.blockchain.block import ZERO_HASH
from src.blockchain.genesis import (
    DEFAULT_GENESIS_TIMESTAMP,
    GENESIS_HEIGHT,
    GenesisError,
    create_genesis_block,
    is_genesis_block,
    is_genesis_block_valid,
    sign_genesis_block,
    validate_genesis_block,
)
from src.crypto.address import public_key_to_address
from src.crypto.ml_dsa import MLDSA


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def validator_keypair(ml_dsa):
    return ml_dsa.generate_keypair()


# ---------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------


def test_create_genesis_block_has_expected_shape(validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)

    assert genesis.height == GENESIS_HEIGHT
    assert genesis.previous_block_hash == ZERO_HASH
    assert genesis.transaction_count == 0
    assert genesis.timestamp == DEFAULT_GENESIS_TIMESTAMP
    assert genesis.is_signed is False


def test_create_genesis_block_derives_validator_address(validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    assert genesis.validator == public_key_to_address(validator_keypair.public_key)


def test_create_genesis_block_accepts_custom_timestamp(validator_keypair):
    genesis = create_genesis_block(
        validator_public_key=validator_keypair.public_key,
        timestamp=123456,
    )
    assert genesis.timestamp == 123456


def test_create_genesis_block_is_deterministic(validator_keypair):
    genesis_a = create_genesis_block(validator_public_key=validator_keypair.public_key)
    genesis_b = create_genesis_block(validator_public_key=validator_keypair.public_key)

    assert genesis_a.block_hash == genesis_b.block_hash


def test_create_genesis_block_rejects_invalid_public_key():
    with pytest.raises(GenesisError):
        create_genesis_block(validator_public_key=b"")


# ---------------------------------------------------------------------
# is_genesis_block
# ---------------------------------------------------------------------


def test_is_genesis_block_true_for_genesis(validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    assert is_genesis_block(genesis) is True


def test_is_genesis_block_false_for_non_block():
    assert is_genesis_block("not-a-block") is False


def test_is_genesis_block_false_for_wrong_height(validator_keypair, ml_dsa):
    from src.blockchain.block import Block

    not_genesis = Block.create(
        height=1,
        previous_block_hash=ZERO_HASH,
        timestamp=DEFAULT_GENESIS_TIMESTAMP,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    assert is_genesis_block(not_genesis) is False


# ---------------------------------------------------------------------
# Signature (optionnelle)
# ---------------------------------------------------------------------


def test_sign_genesis_block_produces_valid_signature(ml_dsa, validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    signed_genesis = sign_genesis_block(genesis, validator_keypair.secret_key, ml_dsa)

    assert signed_genesis.is_signed is True
    assert ml_dsa.verify(
        signed_genesis.signing_hash,
        signed_genesis.signature,
        signed_genesis.validator_public_key,
    ) is True


def test_sign_genesis_block_preserves_genesis_shape(ml_dsa, validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    signed_genesis = sign_genesis_block(genesis, validator_keypair.secret_key, ml_dsa)

    assert is_genesis_block(signed_genesis) is True


def test_sign_genesis_block_rejects_non_genesis_block(ml_dsa, validator_keypair):
    from src.blockchain.block import Block

    not_genesis = Block.create(
        height=1,
        previous_block_hash=ZERO_HASH,
        timestamp=DEFAULT_GENESIS_TIMESTAMP,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )

    with pytest.raises(GenesisError):
        sign_genesis_block(not_genesis, validator_keypair.secret_key, ml_dsa)


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


def test_validate_genesis_block_accepts_valid_unsigned_genesis(validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    assert validate_genesis_block(genesis) is True


def test_validate_genesis_block_accepts_valid_signed_genesis(ml_dsa, validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    signed_genesis = sign_genesis_block(genesis, validator_keypair.secret_key, ml_dsa)

    assert validate_genesis_block(signed_genesis) is True


def test_validate_genesis_block_rejects_wrong_height(validator_keypair):
    from src.blockchain.block import Block

    not_genesis = Block.create(
        height=1,
        previous_block_hash=ZERO_HASH,
        timestamp=DEFAULT_GENESIS_TIMESTAMP,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )

    with pytest.raises(GenesisError, match="height"):
        validate_genesis_block(not_genesis)


def test_validate_genesis_block_rejects_wrong_previous_hash(validator_keypair):
    from src.blockchain.block import Block

    bad_genesis = Block.create(
        height=0,
        previous_block_hash=b"\xff" * 32,
        timestamp=DEFAULT_GENESIS_TIMESTAMP,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )

    with pytest.raises(GenesisError, match="previous_block_hash"):
        validate_genesis_block(bad_genesis)


def test_validate_genesis_block_checks_expected_validator(validator_keypair, ml_dsa):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    other_keypair = ml_dsa.generate_keypair()

    with pytest.raises(GenesisError, match="validator_public_key"):
        validate_genesis_block(
            genesis, expected_validator_public_key=other_keypair.public_key
        )


def test_validate_genesis_block_checks_expected_timestamp(validator_keypair):
    genesis = create_genesis_block(
        validator_public_key=validator_keypair.public_key, timestamp=1000
    )

    with pytest.raises(GenesisError, match="timestamp"):
        validate_genesis_block(genesis, expected_timestamp=9999)


def test_validate_genesis_block_accepts_matching_expected_values(validator_keypair):
    genesis = create_genesis_block(
        validator_public_key=validator_keypair.public_key, timestamp=1000
    )

    assert validate_genesis_block(
        genesis,
        expected_validator_public_key=validator_keypair.public_key,
        expected_timestamp=1000,
    ) is True


def test_is_genesis_block_valid_wrapper(validator_keypair):
    genesis = create_genesis_block(validator_public_key=validator_keypair.public_key)
    assert is_genesis_block_valid(genesis) is True
    assert is_genesis_block_valid("not-a-block") is False
