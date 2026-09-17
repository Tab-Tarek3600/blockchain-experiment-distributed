import pytest

from src.crypto.ml_kem import MLKEM, MLKEMError


def test_generate_keypair_returns_expected_sizes():
    ml_kem = MLKEM()
    keypair = ml_kem.generate_keypair()

    assert len(keypair.public_key) == 1184
    assert len(keypair.secret_key) == 2400


def test_encapsulate_decapsulate_shared_secret_matches():
    ml_kem = MLKEM()
    keypair = ml_kem.generate_keypair()

    encapsulation = ml_kem.encapsulate(keypair.public_key)
    shared_secret = ml_kem.decapsulate(encapsulation.ciphertext, keypair.secret_key)

    assert shared_secret == encapsulation.shared_secret
    assert len(shared_secret) == 32


def test_invalid_variant_raises_error():
    with pytest.raises(MLKEMError):
        MLKEM(variant="NOT-A-REAL-VARIANT")
