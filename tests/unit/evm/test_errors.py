"""
Tests unitaires de la hierarchie d'exceptions de la couche EVM.

Ces tests portent sur un CONTRAT, pas sur du comportement calcule :
ils fixent quelles exceptions sont interceptables par quel `except`.
C'est ce qui protege le consensus. La couche EVM doit pouvoir etre
interceptee d'un seul bloc par l'appelant (Node), sans quoi une
defaillance d'infrastructure remonterait jusqu'a _accept_block() et
ferait rejeter a un noeud un bloc que ses pairs acceptent.

Le cas le plus delicat est AddressError, qui existe en DEUX exemplaires
homonymes dans le projet (src.crypto.address et src.evm.errors). Un
`except AddressError` mal resolu attraperait l'une et laisserait passer
l'autre. Le double heritage est verifie ici dans les deux sens.
"""

from __future__ import annotations

import pytest

from src.crypto.address import AddressError as CryptoAddressError
from src.evm.addresses import validate_address
from src.evm.errors import (
    AddressError,
    EVMError,
    ExecutionError,
    StateError,
)

# --- Hierarchie de base -------------------------------------------------

def test_toutes_les_erreurs_evm_derivent_de_evm_error():
    """
    Garantit qu'un appelant peut tout intercepter d'un seul bloc.
    Une classe ajoutee plus tard hors de cette hierarchie casserait
    ce test -- c'est voulu.
    """
    for classe in (StateError, ExecutionError, AddressError):
        assert issubclass(classe, EVMError)


def test_evm_error_est_une_exception():
    assert issubclass(EVMError, Exception)


def test_les_erreurs_sont_distinctes_entre_elles():
    """StateError ne doit pas attraper une ExecutionError, ni l'inverse."""
    assert not issubclass(StateError, ExecutionError)
    assert not issubclass(ExecutionError, StateError)


@pytest.mark.parametrize("classe", [EVMError, StateError, ExecutionError])
def test_le_message_est_conserve(classe):
    erreur = classe("etat corrompu")
    assert str(erreur) == "etat corrompu"


def test_une_erreur_evm_est_interceptable_globalement():
    with pytest.raises(EVMError):
        raise StateError("solde negatif")


# --- Le cas AddressError : double heritage ------------------------------

def test_address_error_derive_des_deux_hierarchies():
    assert issubclass(AddressError, EVMError)
    assert issubclass(AddressError, CryptoAddressError)


def test_address_error_evm_interceptee_comme_erreur_evm():
    """Vu depuis la couche EVM."""
    with pytest.raises(EVMError):
        raise AddressError("adresse de 19 octets")


def test_address_error_evm_interceptee_par_le_code_phase1():
    """
    Vu depuis la PHASE 1. block.py et transaction.py font deja
    `except AddressError` en important depuis src.crypto.address :
    ce code ne doit pas changer de comportement.
    """
    with pytest.raises(CryptoAddressError):
        raise AddressError("adresse de 19 octets")


def test_l_inverse_n_est_pas_vrai():
    """
    Asymetrie deliberee : une AddressError levee par la PHASE 1 n'est
    PAS une erreur EVM. La couche crypto ignore l'existence de l'EVM.
    """
    assert not issubclass(CryptoAddressError, EVMError)

    with pytest.raises(CryptoAddressError):
        raise CryptoAddressError("clef publique vide")


def test_les_deux_address_error_sont_bien_des_classes_differentes():
    """Sinon le test precedent serait vide de sens."""
    assert AddressError is not CryptoAddressError


def test_ordre_de_resolution_coherent():
    """
    Le double heritage ne doit pas produire de MRO ambigu : Python
    leverait un TypeError a la definition de la classe, mais on fige
    l'ordre attendu pour detecter une reorganisation involontaire.
    """
    mro = AddressError.__mro__
    assert mro.index(EVMError) < mro.index(CryptoAddressError)


# --- Comportement reel du code qui les leve ------------------------------

def test_validate_address_leve_une_address_error_evm():
    with pytest.raises(AddressError):
        validate_address(b"\x01" * 19)


def test_une_adresse_invalide_remonte_jusqu_au_code_phase1():
    """
    Scenario concret du piege evite : du code PHASE 1 qui appelle une
    fonction EVM et n'intercepte que l'AddressError crypto.
    """
    with pytest.raises(CryptoAddressError):
        validate_address("pas des bytes")


def test_le_message_d_erreur_nomme_le_champ_fautif():
    """Un message generique rendrait le diagnostic penible sur 3 VMs."""
    with pytest.raises(AddressError, match="coinbase"):
        validate_address(b"\x01" * 19, "coinbase")
