"""
Tests unitaires des recus d'execution.

Un recu enregistre un FAIT, y compris un echec. Les invariants testes
ici garantissent qu'un recu ne peut pas decrire une situation
impossible -- par exemple un contrat cree par une transaction echouee.
"""

from __future__ import annotations

import pytest

from src.evm.receipt import STATUS_FAILURE, STATUS_SUCCESS, Receipt

TX_ID = b"\x11" * 32
CONTRAT = b"\xCC" * 20


# --- Construction -----------------------------------------------------

def test_recu_de_succes():
    recu = Receipt.success(tx_id=TX_ID, gas_used=21_000)

    assert recu.is_success
    assert not recu.is_failure
    assert recu.status == STATUS_SUCCESS
    assert recu.error is None


def test_recu_d_echec():
    recu = Receipt.failure(tx_id=TX_ID, gas_used=21_000, error="Revert")

    assert recu.is_failure
    assert not recu.is_success
    assert recu.status == STATUS_FAILURE
    assert recu.error == "Revert"


def test_recu_de_deploiement_porte_l_adresse():
    recu = Receipt.success(
        tx_id=TX_ID, gas_used=50_000, contract_address=CONTRAT
    )

    assert recu.created_contract
    assert recu.contract_address == CONTRAT


def test_recu_ordinaire_ne_cree_pas_de_contrat():
    assert not Receipt.success(tx_id=TX_ID, gas_used=21_000).created_contract


def test_un_echec_ne_cree_jamais_de_contrat():
    """Un deploiement rate ne laisse aucun contrat derriere lui."""
    recu = Receipt.failure(tx_id=TX_ID, gas_used=50_000, error="OutOfGas")
    assert recu.contract_address is None


def test_recu_immuable():
    recu = Receipt.success(tx_id=TX_ID, gas_used=1)
    with pytest.raises(Exception):
        recu.status = STATUS_FAILURE  # type: ignore[misc]


# --- Gas ---------------------------------------------------------------

def test_un_echec_consomme_du_gas():
    """
    L'echec est facture : c'est ce qui empeche de saturer la chaine
    avec des transactions vouees a echouer.
    """
    recu = Receipt.failure(tx_id=TX_ID, gas_used=60_000, error="OutOfGas")
    assert recu.gas_used == 60_000


def test_gas_nul_autorise():
    """Un rejet prealable a l'execution ne consomme rien."""
    recu = Receipt.failure(tx_id=TX_ID, gas_used=0, error="invalid nonce")
    assert recu.gas_used == 0


# --- Invariants --------------------------------------------------------

def test_contrat_incoherent_avec_un_echec_refuse():
    with pytest.raises(ValueError, match="failed transaction cannot create"):
        Receipt(
            tx_id=TX_ID,
            status=STATUS_FAILURE,
            gas_used=1,
            contract_address=CONTRAT,
        )


def test_succes_avec_erreur_refuse():
    with pytest.raises(ValueError, match="cannot carry an error"):
        Receipt(
            tx_id=TX_ID, status=STATUS_SUCCESS, gas_used=1, error="boom"
        )


@pytest.mark.parametrize("mauvais", [b"", b"\x11" * 31, b"\x11" * 33, "abc", None])
def test_tx_id_invalide_refuse(mauvais):
    with pytest.raises(ValueError, match="tx_id"):
        Receipt(tx_id=mauvais, status=STATUS_SUCCESS, gas_used=0)


@pytest.mark.parametrize("mauvais_statut", [-1, 2, "1", None, True])
def test_statut_invalide_refuse(mauvais_statut):
    with pytest.raises(ValueError):
        Receipt(tx_id=TX_ID, status=mauvais_statut, gas_used=0)


@pytest.mark.parametrize("mauvais_gas", [-1, "21000", None, 1.5, True])
def test_gas_invalide_refuse(mauvais_gas):
    with pytest.raises(ValueError, match="gas_used"):
        Receipt(tx_id=TX_ID, status=STATUS_SUCCESS, gas_used=mauvais_gas)


def test_adresse_de_contrat_invalide_refusee():
    from src.evm.errors import AddressError

    with pytest.raises(AddressError):
        Receipt(
            tx_id=TX_ID,
            status=STATUS_SUCCESS,
            gas_used=1,
            contract_address=b"\xCC" * 19,
        )


def test_output_doit_etre_des_octets():
    with pytest.raises(ValueError, match="output"):
        Receipt(tx_id=TX_ID, status=STATUS_SUCCESS, gas_used=0, output="0x2a")


# --- Serialisation -----------------------------------------------------

def test_aller_retour_dict_succes():
    origine = Receipt.success(
        tx_id=TX_ID,
        gas_used=53_000,
        contract_address=CONTRAT,
        output=b"\x2a",
    )
    assert Receipt.from_dict(origine.to_dict()) == origine


def test_aller_retour_dict_echec():
    origine = Receipt.failure(
        tx_id=TX_ID, gas_used=21_000, error="Revert", output=b"\xff"
    )
    assert Receipt.from_dict(origine.to_dict()) == origine


def test_to_dict_est_json_serialisable():
    import json

    recu = Receipt.success(tx_id=TX_ID, gas_used=1, contract_address=CONTRAT)
    rejoue = json.loads(json.dumps(recu.to_dict()))

    assert rejoue["status"] == 1
    assert rejoue["contract_address"] == CONTRAT.hex()


def test_from_dict_signale_un_champ_manquant():
    with pytest.raises(ValueError, match="missing field"):
        Receipt.from_dict({"status": 1, "gas_used": 0})


def test_repr_lisible():
    assert "success" in repr(Receipt.success(tx_id=TX_ID, gas_used=1))
    assert "failed" in repr(
        Receipt.failure(tx_id=TX_ID, gas_used=1, error="Revert")
    )
