"""
Tests de Mempool : délégation de la validation à node.validator,
gestion des doublons, conflits de nonce, limite de taille, et
ordre déterministe de get_pending().
"""

import pytest

from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH
from src.crypto.ml_dsa import MLDSA
from src.node.mempool import Mempool, MempoolError

RECIPIENT = b"\x01" * ADDRESS_LENGTH


class AlwaysRejectMLDSA(MLDSA):
    """
    ML-DSA factice dont verify() renvoie toujours False, quelle que
    soit l'entrée. Utilisé pour prouver que Mempool délègue réellement
    la vérification cryptographique à node.validator plutôt que de
    faire sa propre logique de vérification.
    """

    def verify(self, message, signature, public_key):
        return False


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def sender_keypair(ml_dsa):
    return ml_dsa.generate_keypair()


@pytest.fixture
def other_sender_keypair(ml_dsa):
    return ml_dsa.generate_keypair()


def make_signed_tx(ml_dsa, keypair, nonce=0, recipient=RECIPIENT):
    tx = Transaction.create(
        nonce=nonce,
        public_key=keypair.public_key,
        recipient=recipient,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"",
    )
    sig = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    return tx.with_signature(sig)


# ---------------------------------------------------------------------
# add_transaction -- acceptation
# ---------------------------------------------------------------------


def test_add_valid_transaction_succeeds(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx = make_signed_tx(ml_dsa, sender_keypair)

    mempool.add_transaction(tx)

    assert mempool.size() == 1
    assert mempool.contains(tx.tx_id) is True


# ---------------------------------------------------------------------
# add_transaction -- délégation réelle à node.validator
# ---------------------------------------------------------------------


def test_add_transaction_delegates_signature_check_to_validator(ml_dsa, sender_keypair):
    """
    Preuve de délégation : avec un ml_dsa dont verify() renvoie
    toujours False, même une transaction correctement signée doit
    être rejetée -- car Mempool ne fait pas sa propre vérification,
    il utilise l'instance ml_dsa qu'on lui fournit via validator.py.
    """
    rejecting_ml_dsa = AlwaysRejectMLDSA()
    mempool = Mempool(rejecting_ml_dsa)
    tx = make_signed_tx(ml_dsa, sender_keypair)  # signature réelle et valide

    with pytest.raises(MempoolError, match="rejected"):
        mempool.add_transaction(tx)


def test_add_unsigned_transaction_rejected_via_validator(ml_dsa, sender_keypair):
    tx = Transaction.create(
        nonce=0,
        public_key=sender_keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )
    mempool = Mempool(ml_dsa)

    with pytest.raises(MempoolError, match="rejected"):
        mempool.add_transaction(tx)

    assert mempool.size() == 0


def test_add_transaction_with_tampered_signature_rejected(ml_dsa, sender_keypair):
    tx = make_signed_tx(ml_dsa, sender_keypair)
    forged = tx.with_signature(b"\x00" * len(tx.signature))
    mempool = Mempool(ml_dsa)

    with pytest.raises(MempoolError, match="rejected"):
        mempool.add_transaction(forged)


# ---------------------------------------------------------------------
# add_transaction -- doublons et conflits de nonce
# ---------------------------------------------------------------------


def test_add_duplicate_transaction_rejected(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx = make_signed_tx(ml_dsa, sender_keypair)
    mempool.add_transaction(tx)

    with pytest.raises(MempoolError, match="duplicate"):
        mempool.add_transaction(tx)

    assert mempool.size() == 1


def test_add_conflicting_nonce_rejected(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = Transaction.create(
        nonce=0,  # même sender, même nonce, données différentes
        public_key=sender_keypair.public_key,
        recipient=RECIPIENT,
        value=999,
        gas_limit=21000,
        gas_price=1,
        data=b"different",
    )
    sig_b = ml_dsa.sign(tx_b.signing_hash, sender_keypair.secret_key)
    tx_b = tx_b.with_signature(sig_b)

    mempool.add_transaction(tx_a)

    with pytest.raises(MempoolError, match="nonce"):
        mempool.add_transaction(tx_b)

    assert mempool.size() == 1


def test_add_same_sender_different_nonce_both_accepted(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = make_signed_tx(ml_dsa, sender_keypair, nonce=1)

    mempool.add_transaction(tx_a)
    mempool.add_transaction(tx_b)

    assert mempool.size() == 2


def test_add_different_sender_same_nonce_both_accepted(
    ml_dsa, sender_keypair, other_sender_keypair
):
    mempool = Mempool(ml_dsa)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = make_signed_tx(ml_dsa, other_sender_keypair, nonce=0)

    mempool.add_transaction(tx_a)
    mempool.add_transaction(tx_b)

    assert mempool.size() == 2


# ---------------------------------------------------------------------
# add_transaction -- limite de taille
# ---------------------------------------------------------------------


def test_add_transaction_rejected_when_mempool_full(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa, max_size=1)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = make_signed_tx(ml_dsa, sender_keypair, nonce=1)

    mempool.add_transaction(tx_a)

    with pytest.raises(MempoolError, match="full"):
        mempool.add_transaction(tx_b)


def test_mempool_rejects_invalid_max_size():
    with pytest.raises(MempoolError):
        Mempool(max_size=0)


# ---------------------------------------------------------------------
# get_pending -- ordre déterministe
# ---------------------------------------------------------------------


def test_get_pending_returns_all_transactions(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = make_signed_tx(ml_dsa, sender_keypair, nonce=1)

    mempool.add_transaction(tx_a)
    mempool.add_transaction(tx_b)

    pending = mempool.get_pending()
    assert {tx.tx_id for tx in pending} == {tx_a.tx_id, tx_b.tx_id}


def test_get_pending_is_deterministic_regardless_of_insertion_order(
    ml_dsa, sender_keypair, other_sender_keypair
):
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = make_signed_tx(ml_dsa, other_sender_keypair, nonce=0)

    mempool_1 = Mempool(ml_dsa)
    mempool_1.add_transaction(tx_a)
    mempool_1.add_transaction(tx_b)

    mempool_2 = Mempool(ml_dsa)
    mempool_2.add_transaction(tx_b)  # ordre d'insertion inversé
    mempool_2.add_transaction(tx_a)

    order_1 = [tx.tx_id for tx in mempool_1.get_pending()]
    order_2 = [tx.tx_id for tx in mempool_2.get_pending()]

    assert order_1 == order_2


def test_get_pending_respects_limit(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    for nonce in range(5):
        mempool.add_transaction(make_signed_tx(ml_dsa, sender_keypair, nonce=nonce))

    limited = mempool.get_pending(limit=2)
    assert len(limited) == 2


def test_get_pending_returns_empty_list_when_empty(ml_dsa):
    mempool = Mempool(ml_dsa)
    assert mempool.get_pending() == []


# ---------------------------------------------------------------------
# remove_transactions
# ---------------------------------------------------------------------


def test_remove_transactions_removes_specified_only(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = make_signed_tx(ml_dsa, sender_keypair, nonce=1)
    mempool.add_transaction(tx_a)
    mempool.add_transaction(tx_b)

    mempool.remove_transactions([tx_a.tx_id])

    assert mempool.contains(tx_a.tx_id) is False
    assert mempool.contains(tx_b.tx_id) is True
    assert mempool.size() == 1


def test_remove_transactions_frees_nonce_slot(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    mempool.add_transaction(tx_a)
    mempool.remove_transactions([tx_a.tx_id])

    tx_a_replacement = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    mempool.add_transaction(tx_a_replacement)  # must not raise (slot was freed)

    assert mempool.size() == 1


def test_remove_transactions_ignores_unknown_tx_id(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    tx = make_signed_tx(ml_dsa, sender_keypair)
    mempool.add_transaction(tx)

    mempool.remove_transactions([b"\x00" * 32])  # must not raise

    assert mempool.size() == 1


# ---------------------------------------------------------------------
# contains / size
# ---------------------------------------------------------------------


def test_contains_false_for_unknown_tx_id(ml_dsa):
    mempool = Mempool(ml_dsa)
    assert mempool.contains(b"\x00" * 32) is False


def test_size_reflects_current_state(ml_dsa, sender_keypair):
    mempool = Mempool(ml_dsa)
    assert mempool.size() == 0

    mempool.add_transaction(make_signed_tx(ml_dsa, sender_keypair, nonce=0))
    assert mempool.size() == 1
