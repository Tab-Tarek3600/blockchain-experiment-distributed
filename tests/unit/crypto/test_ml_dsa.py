import pytest

from src.crypto.ml_dsa import MLDSA, MLDSAError


def test_generate_keypair_returns_expected_sizes():
    ml_dsa = MLDSA()
    keypair = ml_dsa.generate_keypair()

    assert len(keypair.public_key) == 1312
    assert len(keypair.secret_key) == 2560


def test_sign_and_verify_valid_signature():
    ml_dsa = MLDSA()
    keypair = ml_dsa.generate_keypair()
    message = b"block-header-hash-placeholder"

    signature = ml_dsa.sign(message, keypair.secret_key)

    assert ml_dsa.verify(message, signature, keypair.public_key) is True


def test_verify_rejects_tampered_message():
    ml_dsa = MLDSA()
    keypair = ml_dsa.generate_keypair()
    message = b"original-message"
    tampered = b"tampered-message"

    signature = ml_dsa.sign(message, keypair.secret_key)

    assert ml_dsa.verify(tampered, signature, keypair.public_key) is False


def test_verify_rejects_wrong_public_key():
    ml_dsa = MLDSA()
    keypair_a = ml_dsa.generate_keypair()
    keypair_b = ml_dsa.generate_keypair()
    message = b"some-message"

    signature = ml_dsa.sign(message, keypair_a.secret_key)

    assert ml_dsa.verify(message, signature, keypair_b.public_key) is False


def test_invalid_variant_raises_error():
    with pytest.raises(MLDSAError):
        MLDSA(variant="NOT-A-REAL-VARIANT")


def test_sign_rejects_non_bytes_message():
    ml_dsa = MLDSA()
    keypair = ml_dsa.generate_keypair()

    with pytest.raises(MLDSAError):
        ml_dsa.sign("not-bytes", keypair.secret_key)
