"""
Tests unitaires de l'etat du monde EVM.

Les tests de la section « Determinisme » sont les plus importants du
fichier : ils verifient les proprietes dont depend le critere n.12
(meme state_root sur les 3 VMs). Le state_root etant signe et hache
(decision D3), toute divergence de racine entre deux noeuds provoque
un FORK -- ces tests sont donc la premiere ligne de defense.
"""

from __future__ import annotations

import pytest

from src.evm.errors import EVMError, StateError
from src.evm.state import (
    CHAIN_ID,
    EMPTY_STATE_ROOT,
    MAX_UINT256,
    EVMState,
)

ALICE = b"\xAA" * 20
BOB = b"\xBB" * 20
CARL = b"\xCC" * 20


@pytest.fixture
def state() -> EVMState:
    return EVMState()


# --- Construction -----------------------------------------------------

def test_etat_neuf_est_vide(state):
    assert state.is_empty
    assert state.state_root == EMPTY_STATE_ROOT


def test_etat_neuf_accepte_la_racine_vide_explicite():
    assert EVMState(EMPTY_STATE_ROOT).is_empty


def test_racine_arbitraire_refusee_avec_un_message_clair():
    """
    Une racine n'a de sens que relativement a la base qui contient ses
    noeuds. Refuser tot evite un MissingAccountTrieNode illisible au
    premier acces, loin de l'appel fautif.
    """
    with pytest.raises(StateError, match="arbitrary state_root"):
        EVMState(b"\x42" * 32)


@pytest.mark.parametrize("mauvaise", [b"", b"\x00" * 31, b"\x00" * 33, "0x00", 42])
def test_racine_malformee_refusee(mauvaise):
    with pytest.raises(StateError):
        EVMState(mauvaise)


def test_chain_id_isole_des_reseaux_publics():
    assert CHAIN_ID == 1337


# --- Determinisme (critere n.12) --------------------------------------

def test_racine_reproductible_sur_deux_etats_independants():
    """Memes ecritures, bases distinctes -> racine identique."""
    a = EVMState()
    a.set_balance(ALICE, 1000)
    b = EVMState()
    b.set_balance(ALICE, 1000)

    assert a.commit() == b.commit()


def test_racine_independante_de_l_ordre_des_ecritures():
    """
    Propriete du trie de Merkle. Sans elle, deux noeuds appliquant les
    memes transactions dans un ordre interne different divergeraient.
    """
    a = EVMState()
    a.set_balance(BOB, 5)
    a.set_balance(ALICE, 7)

    b = EVMState()
    b.set_balance(ALICE, 7)
    b.set_balance(BOB, 5)

    assert a.commit() == b.commit()


def test_lecture_seule_ne_modifie_pas_la_racine(state):
    """Consulter un compte inexistant ne doit pas le materialiser."""
    state.get_balance(ALICE)
    state.get_nonce(ALICE)
    state.get_code(ALICE)
    state.get_storage(ALICE, 0)

    assert state.commit() == EMPTY_STATE_ROOT
    assert not state.account_exists(ALICE)


def test_ecrire_un_solde_nul_ne_cree_pas_le_compte(state):
    """
    PIEGE A FORK. En py-evm brut, set_balance(addr, 0) sur un compte
    inexistant CREE le compte et change la racine, alors que ne rien
    ecrire la laisse vierge. Deux noeuds dont l'un ecrit ce zero
    inutile et l'autre non produiraient des state_root differents.
    """
    state.set_balance(ALICE, 0)

    assert state.commit() == EMPTY_STATE_ROOT
    assert not state.account_exists(ALICE)


def test_reecrire_la_meme_valeur_ne_change_pas_la_racine(state):
    state.set_balance(ALICE, 1000)
    racine = state.commit()

    state.set_balance(ALICE, 1000)
    assert state.commit() == racine


def test_ecritures_nulles_neutres_sur_toutes_les_methodes(state):
    """Aucune ecriture sans effet ne doit materialiser un compte."""
    state.add_balance(ALICE, 0)
    state.subtract_balance(ALICE, 0)
    state.set_nonce(ALICE, 0)
    state.set_code(ALICE, b"")
    state.set_storage(ALICE, 0, 0)
    state.transfer(ALICE, BOB, 0)

    assert state.commit() == EMPTY_STATE_ROOT


# --- Soldes -----------------------------------------------------------

def test_compte_inexistant_a_un_solde_nul(state):
    assert state.get_balance(ALICE) == 0
    assert not state.account_exists(ALICE)


def test_set_et_get_balance(state):
    state.set_balance(ALICE, 12345)
    assert state.get_balance(ALICE) == 12345
    assert state.account_exists(ALICE)


def test_add_balance(state):
    state.set_balance(ALICE, 100)
    state.add_balance(ALICE, 50)
    assert state.get_balance(ALICE) == 150


def test_subtract_balance(state):
    state.set_balance(ALICE, 100)
    state.subtract_balance(ALICE, 30)
    assert state.get_balance(ALICE) == 70


def test_solde_insuffisant_leve_state_error(state):
    """
    L'appelant doit verifier le solde AVANT et traduire l'insuffisance
    en Receipt(status=0) -- jamais laisser l'exception remonter.
    """
    state.set_balance(ALICE, 10)
    with pytest.raises(StateError, match="insufficient balance"):
        state.subtract_balance(ALICE, 11)


def test_depassement_de_solde_refuse(state):
    state.set_balance(ALICE, MAX_UINT256)
    with pytest.raises(StateError, match="overflow"):
        state.add_balance(ALICE, 1)


def test_solde_maximal_accepte(state):
    state.set_balance(ALICE, MAX_UINT256)
    assert state.get_balance(ALICE) == MAX_UINT256


# --- Transferts -------------------------------------------------------

def test_transfert_conserve_le_total(state):
    state.set_balance(ALICE, 1000)
    state.transfer(ALICE, BOB, 250)

    assert state.get_balance(ALICE) == 750
    assert state.get_balance(BOB) == 250


def test_transfert_vers_soi_meme_est_neutre(state):
    """Ne doit pas etre decompose en debit puis credit."""
    state.set_balance(ALICE, 100)
    state.transfer(ALICE, ALICE, 100)
    assert state.get_balance(ALICE) == 100


def test_transfert_sans_solde_suffisant_echoue(state):
    state.set_balance(ALICE, 10)
    with pytest.raises(StateError):
        state.transfer(ALICE, BOB, 50)


# --- Nonces -----------------------------------------------------------

def test_nonce_initial_nul(state):
    assert state.get_nonce(ALICE) == 0


def test_increment_nonce(state):
    state.increment_nonce(ALICE)
    state.increment_nonce(ALICE)
    assert state.get_nonce(ALICE) == 2


def test_set_nonce(state):
    state.set_nonce(ALICE, 9)
    assert state.get_nonce(ALICE) == 9


# --- Code et contrats -------------------------------------------------

def test_compte_sans_code_n_est_pas_un_contrat(state):
    assert state.get_code(ALICE) == b""
    assert not state.is_contract(ALICE)


def test_set_code_fait_un_contrat(state):
    state.set_code(ALICE, b"\x60\x2a\x60\x00\x52")
    assert state.is_contract(ALICE)
    assert state.get_code(ALICE) == b"\x60\x2a\x60\x00\x52"


def test_set_code_refuse_autre_chose_que_des_octets(state):
    with pytest.raises(StateError, match="code must be bytes"):
        state.set_code(ALICE, "6002")


# --- Stockage ---------------------------------------------------------

def test_emplacement_vide_vaut_zero(state):
    assert state.get_storage(ALICE, 0) == 0


def test_set_et_get_storage(state):
    state.set_storage(ALICE, 0, 42)
    state.set_storage(ALICE, 1, MAX_UINT256)

    assert state.get_storage(ALICE, 0) == 42
    assert state.get_storage(ALICE, 1) == MAX_UINT256


def test_stockage_isole_entre_contrats(state):
    state.set_storage(ALICE, 0, 111)
    state.set_storage(BOB, 0, 222)

    assert state.get_storage(ALICE, 0) == 111
    assert state.get_storage(BOB, 0) == 222


# --- Racines, commit et navigation ------------------------------------

def test_commit_retourne_la_nouvelle_racine(state):
    state.set_balance(ALICE, 1)
    racine = state.commit()

    assert racine == state.state_root
    assert racine != EMPTY_STATE_ROOT


def test_at_root_relit_un_etat_engage(state):
    state.set_balance(ALICE, 1000)
    state.transfer(ALICE, BOB, 250)
    racine = state.commit()

    vue = state.at_root(racine)
    assert vue.get_balance(ALICE) == 750
    assert vue.get_balance(BOB) == 250


def test_at_root_permet_de_revenir_en_arriere(state):
    """Le trie partage sa structure : l'historique reste accessible."""
    state.set_balance(ALICE, 1000)
    racine_1 = state.commit()

    state.transfer(ALICE, BOB, 400)
    state.commit()

    ancienne = state.at_root(racine_1)
    assert ancienne.get_balance(ALICE) == 1000
    assert ancienne.get_balance(BOB) == 0


def test_at_root_refuse_une_racine_absente(state):
    with pytest.raises(StateError, match="not present"):
        state.at_root(b"\x42" * 32)


def test_at_root_refuse_une_racine_malformee(state):
    with pytest.raises(StateError, match="32 bytes"):
        state.at_root(b"\x42" * 8)


# --- Snapshot / revert ------------------------------------------------

def test_revert_annule_les_ecritures(state):
    state.set_balance(ALICE, 100)
    state.commit()

    point = state.snapshot()
    state.set_balance(ALICE, 999)
    state.set_storage(ALICE, 0, 7)
    state.revert(point)

    assert state.get_balance(ALICE) == 100
    assert state.get_storage(ALICE, 0) == 0


def test_revert_laisse_la_racine_inchangee(state):
    state.set_balance(ALICE, 100)
    racine = state.commit()

    point = state.snapshot()
    state.set_balance(CARL, 500)
    state.revert(point)

    assert state.commit() == racine


# --- Contexte de bloc -------------------------------------------------

def test_set_block_context_preserve_l_etat(state):
    state.set_balance(ALICE, 1000)
    state.commit()

    state.set_block_context(block_number=5, timestamp=1_700_000_000)
    assert state.get_balance(ALICE) == 1000


def test_set_block_context_valide_ses_arguments(state):
    with pytest.raises(StateError):
        state.set_block_context(block_number=-1, timestamp=0)

    with pytest.raises(StateError):
        state.set_block_context(block_number=True, timestamp=0)

    with pytest.raises(StateError):
        state.set_block_context(block_number=0, timestamp="tard")


def test_set_block_context_valide_le_coinbase(state):
    from src.evm.errors import AddressError

    with pytest.raises(AddressError):
        state.set_block_context(block_number=1, timestamp=0, coinbase=b"\x01" * 19)


# --- Validation des entrees -------------------------------------------

@pytest.mark.parametrize(
    "methode,args",
    [
        ("get_balance", ()),
        ("set_balance", (1,)),
        ("get_nonce", ()),
        ("increment_nonce", ()),
        ("get_code", ()),
        ("set_code", (b"",)),
    ],
)
def test_adresse_invalide_refusee(state, methode, args):
    from src.evm.errors import AddressError

    with pytest.raises(AddressError):
        getattr(state, methode)(b"\x01" * 19, *args)


@pytest.mark.parametrize("mauvaise_valeur", [-1, "5", None, 1.5, MAX_UINT256 + 1])
def test_valeur_hors_domaine_refusee(state, mauvaise_valeur):
    with pytest.raises(StateError):
        state.set_balance(ALICE, mauvaise_valeur)


def test_booleen_refuse_comme_valeur(state):
    """isinstance(True, int) vaut True : il faut une garde explicite."""
    with pytest.raises(StateError, match="integer"):
        state.set_balance(ALICE, True)


def test_toutes_les_erreurs_derivent_de_evm_error(state):
    with pytest.raises(EVMError):
        state.set_balance(ALICE, -1)


# --- Isolation de py-evm ----------------------------------------------

def test_aucun_objet_py_evm_ne_franchit_la_frontiere(state):
    """
    L'interface publique n'expose que des types Python natifs, pour
    que le reste du projet ne dependance jamais de l'API beta de
    py-evm. Aucune exception : run_message elle-meme rend un
    ExecutionOutcome, pas un Computation.
    """
    state.set_balance(ALICE, 1000)
    state.set_code(ALICE, b"\x60\x2a")
    state.set_storage(ALICE, 0, 7)

    assert isinstance(state.get_balance(ALICE), int)
    assert isinstance(state.get_nonce(ALICE), int)
    assert isinstance(state.get_code(ALICE), bytes)
    assert isinstance(state.get_storage(ALICE, 0), int)
    assert isinstance(state.state_root, bytes)
    assert isinstance(state.commit(), bytes)


def test_seul_state_importe_py_evm():
    """
    Garde-fou architectural : si un autre module de src/evm/ se met a
    importer eth.*, ce test echoue. Une rupture de l'API beta de
    py-evm doit rester reparable dans un seul fichier.
    """
    import pathlib
    import re

    # Vise le paquet `eth` de py-evm uniquement. `eth_utils`, `eth_typing`
    # et `rlp` sont des paquets DISTINCTS, a l'API stable depuis des
    # annees : la regle d'isolation ne les concerne pas. D'ou la
    # frontiere de mot apres « eth », sans quoi `from eth_utils import
    # keccak` serait signale a tort.
    motif = re.compile(r"^\s*(?:import\s+eth\b(?!_)|from\s+eth\b(?!_))", re.M)

    racine = pathlib.Path(__file__).resolve().parents[3] / "src" / "evm"
    fautifs = sorted(
        chemin.name
        for chemin in racine.glob("*.py")
        if chemin.name != "state.py" and motif.search(chemin.read_text())
    )

    assert fautifs == [], f"modules important py-evm hors state.py : {fautifs}"


def test_state_root_vide_coherent_avec_block():
    """
    EMPTY_STATE_ROOT est defini DEUX fois : dans src/evm/state.py et,
    en dur, dans src/blockchain/block.py -- ce dernier ne devant
    dependre ni de la couche EVM ni de py-evm.

    Cette duplication est le prix de l'independance du coeur PHASE 1.
    Si les deux valeurs divergeaient, un bloc vide serait rejete pour
    state_root incorrect sur les trois VMs, sans indice evident. Ce
    test transforme cette panne en echec de test immediat.
    """
    from src.blockchain.block import EMPTY_STATE_ROOT as ROOT_BLOCK

    assert ROOT_BLOCK == EMPTY_STATE_ROOT


def test_un_etat_neuf_a_la_racine_vide():
    """Ancre la constante a la valeur reellement produite par py-evm."""
    assert EVMState().state_root == EMPTY_STATE_ROOT
