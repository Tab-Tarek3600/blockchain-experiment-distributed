"""
Tests de node.validator : vérification cryptographique réelle
(ML-DSA via liboqs) + règles contextuelles (appartenance PoA),
au-dessus de blockchain.validation.
"""

import pytest

from src.blockchain.block import Block, ZERO_HASH
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
from src.crypto.ml_dsa import MLDSA
from src.node.validator import (
    ValidatorError,
    validate_block_for_acceptance,
    validate_transaction_for_acceptance,
)

RECIPIENT = b"\x01" * ADDRESS_LENGTH


class CountingMLDSA(MLDSA):
    """
    Wrapper autour de MLDSA qui compte les appels à verify(), pour
    prouver que les vérifications cryptographiques coûteuses ne sont
    tentées qu'après que les vérifications bon marché aient réussi
    (ordre fail-fast).
    """

    def __init__(self):
        super().__init__()
        self.verify_call_count = 0

    def verify(self, message, signature, public_key):
        self.verify_call_count += 1
        return super().verify(message, signature, public_key)


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


def make_genesis(ml_dsa, validator_keypair):
    return make_signed_block(ml_dsa, validator_keypair, height=0, previous_hash=ZERO_HASH)


# ---------------------------------------------------------------------
# validate_transaction_for_acceptance
# ---------------------------------------------------------------------


def test_accepts_valid_signed_transaction(ml_dsa, sender_keypair):
    tx = make_signed_tx(ml_dsa, sender_keypair)
    validate_transaction_for_acceptance(tx, ml_dsa)  # must not raise


def test_rejects_unsigned_transaction(sender_keypair):
    tx = Transaction.create(
        nonce=0,
        public_key=sender_keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )

    with pytest.raises(ValidatorError, match="structure"):
        validate_transaction_for_acceptance(tx)


def test_rejects_transaction_with_invalid_signature(ml_dsa, sender_keypair):
    tx = make_signed_tx(ml_dsa, sender_keypair)
    forged = tx.with_signature(b"\x00" * len(tx.signature))

    with pytest.raises(ValidatorError, match="signature"):
        validate_transaction_for_acceptance(forged, ml_dsa)


def test_rejects_transaction_signed_by_wrong_key(ml_dsa, sender_keypair):
    other_keypair = ml_dsa.generate_keypair()
    tx = make_signed_tx(ml_dsa, sender_keypair)

    # Signature valide, mais produite par une autre paire de clés que
    # celle déclarée dans public_key -- doit être rejetée.
    forged_signature = ml_dsa.sign(tx.signing_hash, other_keypair.secret_key)
    forged_tx = tx.with_signature(forged_signature)

    with pytest.raises(ValidatorError, match="signature"):
        validate_transaction_for_acceptance(forged_tx, ml_dsa)


# ---------------------------------------------------------------------
# validate_block_for_acceptance -- cas valides
# ---------------------------------------------------------------------


def test_accepts_valid_block(ml_dsa, validator_keypair, sender_keypair):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)

    tx = make_signed_tx(ml_dsa, sender_keypair)
    block1 = make_signed_block(
        ml_dsa, validator_keypair, height=1, previous_hash=genesis.block_hash,
        transactions=[tx],
    )

    validate_block_for_acceptance(block1, genesis, authorized, ml_dsa)  # must not raise


def test_accepts_empty_block(ml_dsa, validator_keypair):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)

    block1 = make_signed_block(
        ml_dsa, validator_keypair, height=1, previous_hash=genesis.block_hash
    )

    validate_block_for_acceptance(block1, genesis, authorized, ml_dsa)  # must not raise


# ---------------------------------------------------------------------
# validate_block_for_acceptance -- rejets structurels et de chaînage
# ---------------------------------------------------------------------


def test_rejects_block_with_wrong_height(ml_dsa, validator_keypair):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)

    bad_block = make_signed_block(
        ml_dsa, validator_keypair, height=5, previous_hash=genesis.block_hash
    )

    with pytest.raises(ValidatorError, match="chain link"):
        validate_block_for_acceptance(bad_block, genesis, authorized, ml_dsa)


def test_rejects_block_with_wrong_previous_hash(ml_dsa, validator_keypair):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)

    bad_block = make_signed_block(
        ml_dsa, validator_keypair, height=1, previous_hash=b"\xff" * 32
    )

    with pytest.raises(ValidatorError, match="chain link"):
        validate_block_for_acceptance(bad_block, genesis, authorized, ml_dsa)


# ---------------------------------------------------------------------
# validate_block_for_acceptance -- appartenance PoA
# ---------------------------------------------------------------------


def test_rejects_block_from_unauthorized_validator(ml_dsa, validator_keypair, sender_keypair):
    genesis = make_genesis(ml_dsa, validator_keypair)
    unauthorized_keypair = sender_keypair  # not in the authorized set
    authorized = (public_key_to_address(validator_keypair.public_key),)

    block1 = make_signed_block(
        ml_dsa, unauthorized_keypair, height=1, previous_hash=genesis.block_hash
    )

    with pytest.raises(ValidatorError, match="not an authorized"):
        validate_block_for_acceptance(block1, genesis, authorized, ml_dsa)


# ---------------------------------------------------------------------
# validate_block_for_acceptance -- signature du bloc
# ---------------------------------------------------------------------


def test_rejects_unsigned_block(ml_dsa, validator_keypair):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)

    unsigned_block = Block.create(
        height=1,
        previous_block_hash=genesis.block_hash,
        timestamp=1010,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )

    with pytest.raises(ValidatorError, match="not signed"):
        validate_block_for_acceptance(unsigned_block, genesis, authorized, ml_dsa)


def test_rejects_block_with_invalid_block_signature(ml_dsa, validator_keypair):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)

    block1 = Block.create(
        height=1,
        previous_block_hash=genesis.block_hash,
        timestamp=1010,
        transactions=(),
        validator_public_key=validator_keypair.public_key,
    )
    forged = block1.with_signature(b"\x00" * 2420)  # taille plausible, contenu invalide

    with pytest.raises(ValidatorError, match="invalid validator ML-DSA signature"):
        validate_block_for_acceptance(forged, genesis, authorized, ml_dsa)


# ---------------------------------------------------------------------
# validate_block_for_acceptance -- signatures des transactions
# ---------------------------------------------------------------------


def test_rejects_block_with_transaction_having_invalid_signature(
    ml_dsa, validator_keypair, sender_keypair
):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)

    valid_tx = make_signed_tx(ml_dsa, sender_keypair)
    forged_tx = valid_tx.with_signature(b"\x00" * len(valid_tx.signature))

    block1 = make_signed_block(
        ml_dsa, validator_keypair, height=1, previous_hash=genesis.block_hash,
        transactions=[forged_tx],
    )

    with pytest.raises(ValidatorError, match="transaction at index 0"):
        validate_block_for_acceptance(block1, genesis, authorized, ml_dsa)


# ---------------------------------------------------------------------
# Ordre fail-fast : les vérifications coûteuses ne sont pas tentées
# si une vérification bon marché échoue avant.
# ---------------------------------------------------------------------


def test_cheap_checks_short_circuit_before_any_crypto_verification(
    ml_dsa, validator_keypair
):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)
    counting_ml_dsa = CountingMLDSA()

    bad_block = make_signed_block(
        ml_dsa, validator_keypair, height=99, previous_hash=b"\xff" * 32
    )

    with pytest.raises(ValidatorError, match="chain link"):
        validate_block_for_acceptance(bad_block, genesis, authorized, counting_ml_dsa)

    assert counting_ml_dsa.verify_call_count == 0


def test_authorization_check_short_circuits_before_signature_verification(
    ml_dsa, validator_keypair, sender_keypair
):
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)
    counting_ml_dsa = CountingMLDSA()

    block_from_unauthorized = make_signed_block(
        ml_dsa, sender_keypair, height=1, previous_hash=genesis.block_hash
    )

    with pytest.raises(ValidatorError, match="not an authorized"):
        validate_block_for_acceptance(
            block_from_unauthorized, genesis, authorized, counting_ml_dsa
        )

    assert counting_ml_dsa.verify_call_count == 0


def test_block_signature_verified_before_transaction_signatures(
    ml_dsa, validator_keypair, sender_keypair
):
    """
    Si la signature du bloc lui-même est invalide, les signatures des
    transactions ne doivent jamais être vérifiées.
    """
    genesis = make_genesis(ml_dsa, validator_keypair)
    authorized = (public_key_to_address(validator_keypair.public_key),)
    counting_ml_dsa = CountingMLDSA()

    tx = make_signed_tx(ml_dsa, sender_keypair)
    block1 = Block.create(
        height=1,
        previous_block_hash=genesis.block_hash,
        timestamp=1010,
        transactions=[tx],
        validator_public_key=validator_keypair.public_key,
    )
    forged_block = block1.with_signature(b"\x00" * 2420)

    with pytest.raises(ValidatorError, match="invalid validator ML-DSA signature"):
        validate_block_for_acceptance(forged_block, genesis, authorized, counting_ml_dsa)

    # Un seul appel a verify() : celui (échoué) sur la signature du bloc.
    assert counting_ml_dsa.verify_call_count == 1
