"""
Tests unitaires des adresses EVM et de la hierarchie d'erreurs.

Le test le plus important du fichier est test_adresse_mldsa_est_une
_adresse_evm_valide : il verifie la propriete sur laquelle repose toute
la PHASE 3, a savoir qu'une adresse derivee d'une cle publique ML-DSA
est directement utilisable par l'EVM, sans conversion.
"""

from __future__ import annotations

import pytest
import rlp
from eth_utils import keccak

from src.crypto.address import ADDRESS_LENGTH
from src.crypto.address import AddressError as CryptoAddressError
from src.crypto.address import public_key_to_address
from src.evm.addresses import (
    ZERO_ADDRESS,
    address_to_hex,
    generate_contract_address,
    is_valid_address,
    is_zero_address,
    short_hex,
    validate_address,
)
from src.evm.errors import (
    AddressError,
    EVMError,
    ExecutionError,
    StateError,
)

SENDER = bytes.fromhex("11" * 20)


# --- Compatibilite avec la couche crypto de la PHASE 1 ---------------

def test_adresse_mldsa_est_une_adresse_evm_valide():
    """Une adresse derivee d'une cle ML-DSA est utilisable telle quelle."""
    public_key = b"\xAB" * 1312  # taille d'une cle publique ML-DSA-44
    address = public_key_to_address(public_key)

    assert len(address) == ADDRESS_LENGTH
    assert is_valid_address(address)


def test_longueur_adresse_identique_entre_les_deux_couches():
    """La couche EVM ne redefinit pas sa propre largeur d'adresse."""
    from src.crypto import address as crypto_address
    from src.evm import addresses as evm_addresses

    assert evm_addresses.ADDRESS_LENGTH is crypto_address.ADDRESS_LENGTH


# --- is_valid_address / validate_address ------------------------------

def test_is_valid_address_accepte_vingt_octets():
    assert is_valid_address(b"\x00" * 20)
    assert is_valid_address(b"\xFF" * 20)


@pytest.mark.parametrize(
    "invalide",
    [b"", b"\x01" * 19, b"\x01" * 21, "0x" + "11" * 20, None, 12345],
)
def test_is_valid_address_rejette_les_valeurs_malformees(invalide):
    assert not is_valid_address(invalide)


def test_validate_address_retourne_l_adresse():
    """Le retour permet l'usage en ligne."""
    assert validate_address(SENDER) is SENDER


def test_validate_address_rejette_une_mauvaise_longueur():
    with pytest.raises(AddressError, match="exactly 20 bytes"):
        validate_address(b"\x01" * 19)


def test_validate_address_rejette_un_mauvais_type():
    with pytest.raises(AddressError, match="must be bytes"):
        validate_address("0x" + "11" * 20)


def test_validate_address_nomme_le_champ_fautif():
    """Le message doit designer le champ pour etre exploitable."""
    with pytest.raises(AddressError, match="recipient"):
        validate_address(b"\x01" * 3, "recipient")


# --- Adresse nulle / deploiement --------------------------------------

def test_zero_address_fait_vingt_octets_nuls():
    assert ZERO_ADDRESS == b"\x00" * 20
    assert is_valid_address(ZERO_ADDRESS)


def test_is_zero_address_distingue_le_deploiement():
    assert is_zero_address(ZERO_ADDRESS)
    assert not is_zero_address(SENDER)


def test_is_zero_address_ne_leve_pas_sur_valeur_malformee():
    """La detection ne doit pas exiger une adresse valide."""
    assert not is_zero_address(None)
    assert not is_zero_address(b"")


# --- Derivation d'adresse de contrat ----------------------------------

def test_adresse_contrat_suit_la_formule_ethereum():
    attendu = keccak(rlp.encode([SENDER, 0]))[-20:]
    assert generate_contract_address(SENDER, 0) == attendu


def test_adresse_contrat_conforme_a_py_evm():
    """
    Reference croisee avec py-evm sur les cas limites du codage RLP
    des entiers (frontieres 0, 127/128 et 255/256).
    """
    reference = pytest.importorskip("eth._utils.address")

    for nonce in [0, 1, 127, 128, 255, 256, 1000, 2**32, 2**64]:
        assert generate_contract_address(SENDER, nonce) == \
            reference.generate_contract_address(SENDER, nonce)


def test_adresse_contrat_fait_vingt_octets():
    for nonce in [0, 1, 999]:
        assert len(generate_contract_address(SENDER, nonce)) == ADDRESS_LENGTH


def test_adresse_contrat_est_deterministe():
    """Condition pour que les trois VMs referencent le meme contrat."""
    a = generate_contract_address(SENDER, 7)
    b = generate_contract_address(SENDER, 7)
    assert a == b


def test_adresse_contrat_change_avec_le_nonce():
    adresses = {generate_contract_address(SENDER, n) for n in range(10)}
    assert len(adresses) == 10


def test_adresse_contrat_change_avec_l_expediteur():
    autre = bytes.fromhex("22" * 20)
    assert generate_contract_address(SENDER, 0) != \
        generate_contract_address(autre, 0)


def test_adresse_contrat_rejette_un_expediteur_invalide():
    with pytest.raises(AddressError):
        generate_contract_address(b"\x01" * 19, 0)


def test_adresse_contrat_rejette_un_nonce_negatif():
    with pytest.raises(AddressError, match=">= 0"):
        generate_contract_address(SENDER, -1)


@pytest.mark.parametrize("mauvais_nonce", ["0", None, 1.5, b"\x00"])
def test_adresse_contrat_rejette_un_nonce_non_entier(mauvais_nonce):
    with pytest.raises(AddressError, match="integer"):
        generate_contract_address(SENDER, mauvais_nonce)


def test_adresse_contrat_rejette_un_booleen():
    """
    isinstance(True, int) vaut True en Python : sans garde explicite,
    un booleen serait traite comme le nonce 1 en silence.
    """
    with pytest.raises(AddressError, match="integer"):
        generate_contract_address(SENDER, True)


# --- Affichage --------------------------------------------------------

def test_address_to_hex():
    assert address_to_hex(SENDER) == "0x" + "11" * 20


def test_address_to_hex_coherent_avec_la_couche_crypto():
    from src.crypto.address import address_to_hex as crypto_hex
    assert address_to_hex(SENDER) == crypto_hex(SENDER)


def test_short_hex_est_abrege():
    court = short_hex(SENDER)
    assert court == "0x1111..1111"
    assert len(court) < len(address_to_hex(SENDER))


def test_les_fonctions_d_affichage_rejettent_une_adresse_invalide():
    for fonction in (address_to_hex, short_hex):
        with pytest.raises(CryptoAddressError):
            fonction(b"\x01" * 5)


# --- Hierarchie d'exceptions ------------------------------------------

@pytest.mark.parametrize("exc", [StateError, ExecutionError, AddressError])
def test_toutes_les_erreurs_evm_derivent_de_evm_error(exc):
    """Un appelant peut tout intercepter avec un seul except."""
    assert issubclass(exc, EVMError)


def test_address_error_est_aussi_une_erreur_crypto():
    """
    Double heritage : le code PHASE 1 qui intercepte
    src.crypto.address.AddressError attrape aussi les erreurs EVM.
    Sans cela, deux classes homonymes coexisteraient et un
    `except AddressError` en laisserait passer la moitie.
    """
    assert issubclass(AddressError, CryptoAddressError)

    with pytest.raises(CryptoAddressError):
        validate_address(b"trop court")

    with pytest.raises(EVMError):
        validate_address(b"trop court")
