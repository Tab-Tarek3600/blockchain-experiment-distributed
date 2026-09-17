"""
Tests unitaires du rejeu de l'etat depuis le stockage.

Trois familles de tests dominent ce fichier :

  * « Rattrapage » -- verifie qu'un noeud qui n'a pas produit les
    derniers blocs retrouve neanmoins l'etat exact, condition pour
    qu'il puisse calculer la racine de SON bloc dans un round-robin
    ou il ne propose qu'un bloc sur trois.

  * « Essai a blanc » -- verifie que root_after n'engage rien. Un
    producteur doit connaitre la racine avant de signer, alors que le
    bloc peut encore etre refuse ; si l'etat avancait, il refleterait
    un bloc inexistant.

  * « Determinisme » -- deux rejoueurs independants partant du meme
    stockage obtiennent la meme racine (critere n.12 : les 3 VMs
    convergent).
"""

from __future__ import annotations

import pytest

from src.blockchain.block import Block, EMPTY_STATE_ROOT
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.crypto.address import public_key_to_address
from src.evm.errors import BlockGasLimitExceeded, StateError
from src.evm.replay import NOTHING_APPLIED, StateReplayer
from src.evm.state import BLOCK_GAS_LIMIT, EVMState

# Cles publiques ML-DSA-44 (1312 octets). Transaction impose que
# sender derive de public_key : les adresses sont donc calculees.
PK_ALICE = b"\x01" * 1312
PK_BOB = b"\x02" * 1312
PK_VALIDATEUR = b"\x04" * 1312
ALICE = public_key_to_address(PK_ALICE)
BOB = public_key_to_address(PK_BOB)

SIGNATURE = b"\x03" * 2420


# --- fabrication de blocs -------------------------------------------


def transaction(nonce, *, public_key=PK_ALICE, recipient=BOB, value=1):
    """Transaction signee (la signature n'est pas verifiee ici)."""
    tx = Transaction.create(
        nonce=nonce,
        public_key=public_key,
        recipient=recipient,
        value=value,
        gas_limit=21_000,
        gas_price=0,
    )
    return tx.with_signature(SIGNATURE)


def bloc(height, transactions=(), *, previous=b"\x00" * 32, timestamp=None):
    """
    Bloc signe pret a etre stocke.

    Le state_root est laisse a EMPTY_STATE_ROOT : ces tests portent sur
    le rejeu, pas sur la coherence du champ annonce (point 2, receveur).
    """
    block = Block.create(
        height=height,
        previous_block_hash=previous,
        timestamp=timestamp if timestamp is not None else 1_700_000_000 + height * 5,
        transactions=transactions,
        validator_public_key=PK_VALIDATEUR,
    )
    return block.with_signature(SIGNATURE)


@pytest.fixture
def storage(tmp_path):
    return ChainStorage(tmp_path / "data")


@pytest.fixture
def chaine(storage):
    """
    Chaine de 4 blocs : genese, un transfert, un bloc vide, un
    transfert. Les blocs sont chaines par leur hash.
    """
    blocks = [bloc(0)]
    for hauteur, txs in enumerate(
        [(transaction(0),), (), (transaction(1),)], start=1
    ):
        blocks.append(
            bloc(hauteur, txs, previous=blocks[-1].block_hash)
        )

    for b in blocks:
        storage.save_block(b)

    return blocks


def approvisionne(state):
    """Credite Alice pour que ses transferts reussissent."""
    state.set_balance(ALICE, 10**18)
    state.commit()


# --- etat initial ----------------------------------------------------


def test_un_rejoueur_neuf_n_a_rien_applique(storage):
    replayer = StateReplayer(storage)

    assert replayer.applied_height == NOTHING_APPLIED
    assert replayer.applied_height == -1
    assert replayer.state_root == EMPTY_STATE_ROOT


def test_le_rejoueur_cree_son_propre_etat(storage):
    replayer = StateReplayer(storage)

    assert isinstance(replayer.state, EVMState)
    assert replayer.state.is_empty


def test_l_etat_peut_etre_injecte(storage):
    state = EVMState()
    replayer = StateReplayer(storage, state=state)

    assert replayer.state is state


# --- rattrapage ------------------------------------------------------


def test_la_genese_compte_comme_appliquee(storage, chaine):
    """
    Le bloc 0 ne contient rien, mais doit faire avancer le compteur :
    sinon applied_height accuse un decalage permanent d'une unite par
    rapport a Blockchain.height.
    """
    replayer = StateReplayer(storage)
    replayer.sync_to(0)

    assert replayer.applied_height == 0
    assert replayer.state_root == EMPTY_STATE_ROOT


def test_rejeu_complet_de_la_chaine(storage, chaine):
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)

    racine = replayer.sync_to(3)

    assert replayer.applied_height == 3
    assert racine == replayer.state_root
    assert replayer.state.get_nonce(ALICE) == 2
    assert replayer.state.get_balance(BOB) == 2


def test_le_rattrapage_est_incrementiel(storage, chaine):
    """
    Le cas nominal du round-robin : le noeud est a jour jusqu'a son
    dernier tour, deux blocs des pairs sont arrives entre-temps.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)

    replayer.sync_to(1)
    assert replayer.applied_height == 1
    assert replayer.state.get_nonce(ALICE) == 1

    replayer.sync_to(3)
    assert replayer.applied_height == 3
    assert replayer.state.get_nonce(ALICE) == 2


def test_resynchroniser_a_la_meme_hauteur_ne_change_rien(storage, chaine):
    """
    Appeler sync_to alors qu'on est deja a jour doit etre gratuit et
    sans effet : c'est ce qui autorise a l'appeler avant chaque
    proposition sans precaution.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    racine = replayer.sync_to(3)

    assert replayer.sync_to(3) == racine
    assert replayer.applied_height == 3
    assert replayer.state.get_nonce(ALICE) == 2


def test_rejeu_par_etapes_equivaut_au_rejeu_direct(storage, chaine):
    pas_a_pas = StateReplayer(storage)
    approvisionne(pas_a_pas.state)
    for hauteur in range(4):
        pas_a_pas.sync_to(hauteur)

    direct = StateReplayer(storage)
    approvisionne(direct.state)
    direct.sync_to(3)

    assert pas_a_pas.state_root == direct.state_root


def test_deux_rejoueurs_independants_convergent(storage, chaine):
    """Critere n.12 : trois VMs rejouant la meme chaine convergent."""
    premier = StateReplayer(storage)
    approvisionne(premier.state)
    second = StateReplayer(storage)
    approvisionne(second.state)

    assert premier.sync_to(3) == second.sync_to(3)


# --- refus ------------------------------------------------------------


def test_reculer_est_refuse(storage, chaine):
    """
    Cette chaine PoA n'a aucun mecanisme de reorganisation : une
    demande de recul signale une anomalie et ne doit pas rendre
    silencieusement une racine qui ne correspond a rien.
    """
    replayer = StateReplayer(storage)
    replayer.sync_to(3)

    with pytest.raises(StateError, match="rewind"):
        replayer.sync_to(1)


def test_un_bloc_manquant_est_signale(storage):
    storage.save_block(bloc(0))
    replayer = StateReplayer(storage)

    with pytest.raises(StateError, match="cannot replay height 1"):
        replayer.sync_to(1)


def test_l_etat_reste_utilisable_apres_un_bloc_manquant(storage, chaine):
    """
    Un echec en cours de rattrapage ne doit pas laisser le rejoueur
    dans un etat incoherent : ce qui a ete applique reste applique.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)

    with pytest.raises(StateError):
        replayer.sync_to(10)

    assert replayer.applied_height == 3
    assert replayer.state.get_nonce(ALICE) == 2


@pytest.mark.parametrize("hauteur", [-1, -42])
def test_une_hauteur_negative_est_refusee(storage, hauteur):
    replayer = StateReplayer(storage)

    with pytest.raises(StateError, match="non-negative"):
        replayer.sync_to(hauteur)


@pytest.mark.parametrize("hauteur", [True, 1.0, "3", None])
def test_une_hauteur_non_entiere_est_refusee(storage, hauteur):
    replayer = StateReplayer(storage)

    with pytest.raises(StateError, match="integer"):
        replayer.sync_to(hauteur)


# --- essai a blanc ----------------------------------------------------


def test_root_after_n_engage_pas_l_etat(storage, chaine):
    """
    Le coeur du mecanisme : calculer la racine d'un bloc candidat ne
    doit rien changer a l'etat, car ce bloc peut encore etre refuse.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    avant = replayer.state_root
    nonce_avant = replayer.state.get_nonce(ALICE)

    replayer.root_after(
        [transaction(2)],
        block_number=4,
        timestamp=1_700_000_020,
        coinbase=BOB,
    )

    assert replayer.state_root == avant
    assert replayer.state.get_nonce(ALICE) == nonce_avant
    assert replayer.applied_height == 3


def test_root_after_annonce_la_racine_reellement_obtenue(storage, chaine):
    """
    La valeur predite doit etre exactement celle obtenue apres
    application reelle : sinon le bloc annoncerait une racine fausse.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    tx = transaction(2)
    predite = replayer.root_after(
        [tx],
        block_number=4,
        timestamp=1_700_000_020,
        coinbase=BOB,
    ).state_root

    dernier = bloc(
        4, (tx,), previous=chaine[-1].block_hash, timestamp=1_700_000_020
    )
    storage.save_block(dernier)
    reelle = replayer.sync_to(4)

    assert predite == reelle


def test_root_after_est_repetable(storage, chaine):
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    arguments = dict(block_number=4, timestamp=1_700_000_020, coinbase=BOB)
    premiere = replayer.root_after([transaction(2)], **arguments)
    seconde = replayer.root_after([transaction(2)], **arguments)

    assert premiere.state_root == seconde.state_root
    assert premiere.gas_used == seconde.gas_used


def test_root_after_sur_un_bloc_vide_rend_la_racine_courante(storage, chaine):
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    racine = replayer.root_after(
        [], block_number=4, timestamp=1_700_000_020, coinbase=BOB
    ).state_root

    assert racine == replayer.state_root


def test_root_after_reflete_le_contexte_du_bloc(storage, chaine):
    """
    Le coinbase percoit les frais : deux beneficiaires differents
    doivent donner deux racines differentes des lors que gas_price > 0.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    payante = Transaction.create(
        nonce=2,
        public_key=PK_ALICE,
        recipient=BOB,
        value=1,
        gas_limit=21_000,
        gas_price=1,
    ).with_signature(SIGNATURE)

    vers_bob = replayer.root_after(
        [payante], block_number=4, timestamp=1_700_000_020, coinbase=BOB
    ).state_root
    vers_alice = replayer.root_after(
        [payante], block_number=4, timestamp=1_700_000_020, coinbase=ALICE
    ).state_root

    assert vers_bob != vers_alice


def test_root_after_expose_le_gas_du_bloc(storage, chaine):
    """
    Le gas doit accompagner la racine : l'appelant en a besoin pour
    juger du cout d'un bloc sans avoir a le reexecuter.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    resultat = replayer.root_after(
        [transaction(2)],
        block_number=4,
        timestamp=1_700_000_020,
        coinbase=BOB,
    )

    assert resultat.gas_used == 21_000
    assert len(resultat.receipts) == 1
    assert resultat.receipts[0].is_success


def test_root_after_annonce_le_gas_reellement_consomme(storage, chaine):
    """
    Pendant du test sur la racine : le gas predit doit lui aussi
    correspondre a l'application reelle, sinon la projection serait
    trompeuse.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    tx = transaction(2)
    predit = replayer.root_after(
        [tx], block_number=4, timestamp=1_700_000_020, coinbase=BOB
    ).gas_used

    dernier = bloc(
        4, (tx,), previous=chaine[-1].block_hash, timestamp=1_700_000_020
    )
    storage.save_block(dernier)
    replayer.sync_to(4)

    assert predit == 21_000


def test_root_after_sur_bloc_vide_ne_consomme_aucun_gas(storage, chaine):
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    resultat = replayer.root_after(
        [], block_number=4, timestamp=1_700_000_020, coinbase=BOB
    )

    assert resultat.gas_used == 0
    assert resultat.receipts == ()


def test_root_after_refuse_un_bloc_hors_plafond_de_gas(storage, chaine):
    """
    Le plafond pose dans l'executeur doit rester visible a travers
    root_after : un bloc hors plafond ne doit pas se voir attribuer une
    racine, il doit etre rejete. C'est ce qui permettra au receveur
    d'ecarter un bloc hostile sans l'executer.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    enorme = [
        Transaction.create(
            nonce=2 + i,
            public_key=PK_ALICE,
            recipient=BOB,
            value=0,
            gas_limit=BLOCK_GAS_LIMIT,
            gas_price=0,
        ).with_signature(SIGNATURE)
        for i in range(2)
    ]

    with pytest.raises(BlockGasLimitExceeded):
        replayer.root_after(
            enorme, block_number=4, timestamp=1_700_000_020, coinbase=BOB
        )


def test_un_refus_pour_gas_n_engage_pas_l_etat(storage, chaine):
    """
    Le refus ne doit pas laisser l'etat a moitie avance : le rejoueur
    doit rester utilisable pour le bloc legitime suivant.
    """
    replayer = StateReplayer(storage)
    approvisionne(replayer.state)
    replayer.sync_to(3)

    avant = replayer.state_root
    hauteur_avant = replayer.applied_height

    enorme = [
        Transaction.create(
            nonce=2 + i,
            public_key=PK_ALICE,
            recipient=BOB,
            value=0,
            gas_limit=BLOCK_GAS_LIMIT,
            gas_price=0,
        ).with_signature(SIGNATURE)
        for i in range(2)
    ]

    with pytest.raises(BlockGasLimitExceeded):
        replayer.root_after(
            enorme, block_number=4, timestamp=1_700_000_020, coinbase=BOB
        )

    assert replayer.state_root == avant
    assert replayer.applied_height == hauteur_avant

    # Le rejoueur reste operationnel.
    suivant = replayer.root_after(
        [transaction(2)], block_number=4, timestamp=1_700_000_020, coinbase=BOB
    )
    assert suivant.gas_used == 21_000


# --- representation ---------------------------------------------------


def test_repr_mentionne_la_hauteur_appliquee(storage, chaine):
    replayer = StateReplayer(storage)
    replayer.sync_to(0)

    assert "applied_height=0" in repr(replayer)
