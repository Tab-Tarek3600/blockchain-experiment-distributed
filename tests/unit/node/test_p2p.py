"""
Tests de P2PTransport : NullP2P (no-op) et InMemoryP2P (livraison
directe entre instances connectées, sans rebroadcast automatique).
"""

import pytest

from src.blockchain.block import Block, ZERO_HASH
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH
from src.crypto.ml_dsa import MLDSA
from src.node.p2p import InMemoryP2P, NullP2P

RECIPIENT = b"\x01" * ADDRESS_LENGTH


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def keypair(ml_dsa):
    return ml_dsa.generate_keypair()


def make_signed_tx(ml_dsa, keypair, nonce=0):
    tx = Transaction.create(
        nonce=nonce,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"",
    )
    sig = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    return tx.with_signature(sig)


def make_signed_block(ml_dsa, keypair, height=0, previous_hash=None):
    block = Block.create(
        height=height,
        previous_block_hash=previous_hash or ZERO_HASH,
        timestamp=1000,
        transactions=(),
        validator_public_key=keypair.public_key,
    )
    sig = ml_dsa.sign(block.signing_hash, keypair.secret_key)
    return block.with_signature(sig)


# ---------------------------------------------------------------------
# NullP2P
# ---------------------------------------------------------------------


def test_null_p2p_broadcast_transaction_does_not_raise(ml_dsa, keypair):
    transport = NullP2P()
    tx = make_signed_tx(ml_dsa, keypair)

    transport.broadcast_transaction(tx)  # must not raise


def test_null_p2p_broadcast_block_does_not_raise(ml_dsa, keypair):
    transport = NullP2P()
    block = make_signed_block(ml_dsa, keypair)

    transport.broadcast_block(block)  # must not raise


def test_null_p2p_registered_handler_never_invoked(ml_dsa, keypair):
    transport = NullP2P()
    received = []

    transport.register_transaction_handler(lambda tx: received.append(tx))
    transport.broadcast_transaction(make_signed_tx(ml_dsa, keypair))

    assert received == []


# ---------------------------------------------------------------------
# InMemoryP2P -- connexion
# ---------------------------------------------------------------------


def test_connect_is_symmetric():
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")

    node_a.connect(node_b)

    assert "node-b" in node_a.connected_peer_ids()
    assert "node-a" in node_b.connected_peer_ids()


def test_connect_to_self_is_noop():
    node_a = InMemoryP2P("node-a")
    node_a.connect(node_a)

    assert node_a.connected_peer_ids() == []


def test_disconnect_removes_symmetric_connection():
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")
    node_a.connect(node_b)

    node_a.disconnect(node_b)

    assert "node-b" not in node_a.connected_peer_ids()
    assert "node-a" not in node_b.connected_peer_ids()


# ---------------------------------------------------------------------
# InMemoryP2P -- diffusion de transactions
# ---------------------------------------------------------------------


def test_broadcast_transaction_delivered_to_connected_peer(ml_dsa, keypair):
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")
    node_a.connect(node_b)

    received = []
    node_b.register_transaction_handler(lambda tx: received.append(tx))

    tx = make_signed_tx(ml_dsa, keypair)
    node_a.broadcast_transaction(tx)

    assert len(received) == 1
    assert received[0].tx_id == tx.tx_id


def test_broadcast_transaction_not_delivered_to_unconnected_node(ml_dsa, keypair):
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")  # not connected to node_a

    received = []
    node_b.register_transaction_handler(lambda tx: received.append(tx))

    node_a.broadcast_transaction(make_signed_tx(ml_dsa, keypair))

    assert received == []


def test_broadcast_transaction_does_not_invoke_sender_own_handler(ml_dsa, keypair):
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")
    node_a.connect(node_b)

    received_by_a = []
    node_a.register_transaction_handler(lambda tx: received_by_a.append(tx))

    node_a.broadcast_transaction(make_signed_tx(ml_dsa, keypair))

    assert received_by_a == []  # A does not receive its own broadcast


def test_broadcast_transaction_reaches_multiple_connected_peers(ml_dsa, keypair):
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")
    node_c = InMemoryP2P("node-c")
    node_a.connect(node_b)
    node_a.connect(node_c)

    received_b, received_c = [], []
    node_b.register_transaction_handler(lambda tx: received_b.append(tx))
    node_c.register_transaction_handler(lambda tx: received_c.append(tx))

    tx = make_signed_tx(ml_dsa, keypair)
    node_a.broadcast_transaction(tx)

    assert len(received_b) == 1
    assert len(received_c) == 1


def test_broadcast_does_not_auto_relay_between_unconnected_peers(ml_dsa, keypair):
    """
    Prouve l'absence de rebroadcast automatique : B et C sont tous
    deux connectés à A, mais pas entre eux. Si A diffuse à B, cela ne
    doit jamais atteindre C via un relais automatique de B.
    """
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")
    node_c = InMemoryP2P("node-c")
    node_a.connect(node_b)
    # node_c n'est connecté à personne

    received_c = []
    node_c.register_transaction_handler(lambda tx: received_c.append(tx))

    node_a.broadcast_transaction(make_signed_tx(ml_dsa, keypair))

    assert received_c == []


def test_broadcast_to_peer_without_handler_does_not_raise(ml_dsa, keypair):
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")
    node_a.connect(node_b)
    # node_b n'a enregistré aucun handler

    node_a.broadcast_transaction(make_signed_tx(ml_dsa, keypair))  # must not raise


# ---------------------------------------------------------------------
# InMemoryP2P -- diffusion de blocs
# ---------------------------------------------------------------------


def test_broadcast_block_delivered_to_connected_peer(ml_dsa, keypair):
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")
    node_a.connect(node_b)

    received = []
    node_b.register_block_handler(lambda block: received.append(block))

    block = make_signed_block(ml_dsa, keypair)
    node_a.broadcast_block(block)

    assert len(received) == 1
    assert received[0].block_hash == block.block_hash


def test_broadcast_block_not_delivered_to_unconnected_node(ml_dsa, keypair):
    node_a = InMemoryP2P("node-a")
    node_b = InMemoryP2P("node-b")

    received = []
    node_b.register_block_handler(lambda block: received.append(block))

    node_a.broadcast_block(make_signed_block(ml_dsa, keypair))

    assert received == []
