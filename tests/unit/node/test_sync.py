"""
Tests de la synchronisation de chaine (PHASE 2).

Deux niveaux, volontairement separes :

    1. IN-PROCESS  -- la logique de synchronisation cote Node
       (detection de trou, fourniture de blocs a un pair en retard),
       exercee avec un transport factice. Rapide, deterministe.

    2. TCP REEL    -- deux instances SocketP2P sur des sockets reelles,
       dont le scenario central : un noeud demarre APRES que la chaine
       a deja avance, et doit rattraper. C'est precisement le cas que
       l'ancienne implementation ne savait pas traiter.

Ce que ces tests NE prouvent PAS : le fonctionnement entre machines
distinctes (VM <-> physique). Cela releve du deploiement reel.
"""

from __future__ import annotations

import pytest

from src.blockchain.block import Block
from src.crypto.address import public_key_to_address
from src.node.p2p import NullP2P, P2PTransport
from src.node.socket_p2p import MAX_SYNC_BLOCKS, SocketP2P

from tests.unit.node.test_node import (  # fixtures partagees
    make_node,
    make_signed_tx,
    ml_dsa,
    validator_addresses,
    validator_keypairs,
)
from tests.unit.node.test_socket_p2p import free_port, wait_until


# Cle publique factice et son adresse DERIVEE : Block impose
# validator == public_key_to_address(validator_public_key).
FAKE_PUBLIC_KEY = bytes(i % 256 for i in range(1312))
FAKE_VALIDATOR = public_key_to_address(FAKE_PUBLIC_KEY)

# ---------------------------------------------------------------------
# Transport espion : enregistre les demandes de synchronisation
# ---------------------------------------------------------------------


class RecordingP2P(NullP2P):
    """
    NullP2P qui note les appels a request_blocks_from().

    Permet de verifier QUE la synchronisation est declenchee, et avec
    quelle hauteur, sans ouvrir la moindre socket.
    """

    def __init__(self) -> None:
        super().__init__()
        self.sync_requests: list[int] = []
        self.broadcast_blocks: list[Block] = []

    def request_blocks_from(self, from_height: int) -> None:
        self.sync_requests.append(from_height)

    def broadcast_block(self, block: Block) -> None:
        self.broadcast_blocks.append(block)


# ---------------------------------------------------------------------
# 1. Detection de trou (in-process)
# ---------------------------------------------------------------------


def test_block_with_gap_triggers_sync_request(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Un bloc trop en avance doit declencher une demande de synchro."""
    transport = RecordingP2P()
    node = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0, p2p=transport
    )

    # Chaine locale au genesis (hauteur 0) ; on fabrique un bloc a la
    # hauteur 5 : les hauteurs 1 a 4 manquent.
    far_block = Block(
        height=5,
        previous_block_hash=b"\x11" * 32,
        timestamp=1_700_000_100,
        transactions=(),
        validator=validator_addresses[1],
        validator_public_key=validator_keypairs[1].public_key,
        signature=b"\x00" * 2420,
    )

    node.receive_block(far_block)

    # Le bloc n'est pas ajoute (impossible a chainer)...
    assert node.height == 0
    # ...mais la synchro est demandee a partir du premier bloc manquant.
    assert transport.sync_requests == [1]


def test_gap_request_starts_at_first_missing_height(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """La demande part du premier bloc MANQUANT, pas du tip ni du bloc recu."""
    transport = RecordingP2P()
    node = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0, p2p=transport
    )

    far_block = Block(
        height=42,
        previous_block_hash=b"\x22" * 32,
        timestamp=1_700_000_200,
        transactions=(),
        validator=validator_addresses[1],
        validator_public_key=validator_keypairs[1].public_key,
        signature=b"\x00" * 2420,
    )
    node.receive_block(far_block)

    assert transport.sync_requests == [1]  # et non [42] ni [0]


def test_contiguous_block_does_not_trigger_sync(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Un bloc directement chainable ne doit PAS declencher de synchro."""
    transport = RecordingP2P()
    node = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0, p2p=transport
    )

    # Un bloc a hauteur 1 est contigu au genesis : il suit le pipeline
    # normal (et sera rejete ici faute de signature valide, ce qui est
    # sans importance : on verifie l'ABSENCE de demande de synchro).
    bad_block = Block(
        height=1,
        previous_block_hash=node.tip_hash,
        timestamp=1_700_000_050,
        transactions=(),
        validator=validator_addresses[1],
        validator_public_key=validator_keypairs[1].public_key,
        signature=b"\x00" * 2420,
    )
    with pytest.raises(Exception):
        node.receive_block(bad_block)

    assert transport.sync_requests == []


def test_old_block_does_not_trigger_sync(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Un bloc deja connu/obsolete est ignore sans demande de synchro."""
    transport = RecordingP2P()
    node = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0, p2p=transport
    )

    genesis = node._blockchain.genesis_block
    node.receive_block(genesis)  # hauteur 0 <= tip 0

    assert transport.sync_requests == []
    assert node.height == 0


# ---------------------------------------------------------------------
# 2. Fourniture de blocs a un pair en retard (in-process)
# ---------------------------------------------------------------------


def test_blocks_for_sync_returns_requested_range(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Le fournisseur renvoie les blocs demandes, dans l'ordre."""
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    blocks = node._blocks_for_sync(0, MAX_SYNC_BLOCKS)

    assert len(blocks) == 1  # seul le genesis existe
    assert blocks[0].height == 0
    assert blocks[0].block_hash == node.genesis_hash


def test_blocks_for_sync_is_capped(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Le nombre de blocs renvoyes ne depasse jamais max_count."""
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    assert node._blocks_for_sync(0, 1) == [node._blockchain.genesis_block]
    assert node._blocks_for_sync(0, 0) == []


def test_blocks_for_sync_beyond_tip_returns_empty(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Demander au-dela du tip renvoie une liste vide, sans erreur.

    Un pair plus avance que nous est une situation normale.
    """
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    assert node._blocks_for_sync(99, MAX_SYNC_BLOCKS) == []


def test_blocks_for_sync_rejects_negative_height(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Une hauteur negative renvoie une liste vide plutot que de lever."""
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    assert node._blocks_for_sync(-1, MAX_SYNC_BLOCKS) == []


def test_serving_a_peer_does_not_mutate_local_state(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Servir un pair est strictement en lecture seule."""
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    before_height, before_tip = node.height, node.tip_hash
    node._blocks_for_sync(0, MAX_SYNC_BLOCKS)

    assert (node.height, node.tip_hash) == (before_height, before_tip)


def test_local_height_provider_tracks_the_chain(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Le fournisseur de hauteur reflete le tip courant."""
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    assert node._local_height_for_sync() == node.height == 0


# ---------------------------------------------------------------------
# 3. Compatibilite des transports existants
# ---------------------------------------------------------------------


def test_null_p2p_still_satisfies_the_interface():
    """NullP2P reste utilisable : les methodes de synchro sont no-op."""
    transport = NullP2P()

    assert isinstance(transport, P2PTransport)
    transport.request_blocks_from(1)  # ne doit pas lever
    transport.register_sync_providers(lambda: 0, lambda h, n: [])


def test_in_memory_p2p_still_satisfies_the_interface():
    """InMemoryP2P n'a pas eu besoin d'etre modifie."""
    from src.node.p2p import InMemoryP2P

    transport = InMemoryP2P("n1")

    assert isinstance(transport, P2PTransport)
    transport.request_blocks_from(1)
    transport.register_sync_providers(lambda: 0, lambda h, n: [])


# ---------------------------------------------------------------------
# 4. Synchronisation sur sockets TCP reelles
# ---------------------------------------------------------------------


def test_sync_request_is_sent_on_connect():
    """
    A la connexion, un noeud demande la suite de la chaine a son pair.

    C'est le declencheur qui permet a un noeud demarre en retard de
    rattraper sans attendre le bloc suivant.
    """
    port_a, port_b = free_port(), free_port()
    a = SocketP2P("127.0.0.1", port_a, peers=[("127.0.0.1", port_b)], node_id="a")
    b = SocketP2P("127.0.0.1", port_b, peers=[("127.0.0.1", port_a)], node_id="b")

    served: list[tuple[int, int]] = []

    # `a` est a la hauteur 7 et sait servir des blocs ; `b` est au
    # genesis et doit donc reclamer a partir de la hauteur 1.
    a.register_sync_providers(lambda: 7, lambda h, n: served.append((h, n)) or [])
    b.register_sync_providers(lambda: 0, lambda h, n: [])

    a.start()
    b.start()
    try:
        assert wait_until(lambda: len(served) > 0, timeout=10.0), (
            "aucune demande de synchronisation recue apres connexion"
        )
        from_height, max_count = served[0]
        assert from_height == 1  # b est au genesis : il lui manque 1+
        assert max_count == MAX_SYNC_BLOCKS
    finally:
        a.stop()
        b.stop()


def test_requested_blocks_are_delivered_to_the_block_handler():
    """
    Les blocs servis en reponse arrivent bien au handler de bloc du
    demandeur, comme des blocs ordinaires.
    """
    port_a, port_b = free_port(), free_port()
    a = SocketP2P("127.0.0.1", port_a, peers=[("127.0.0.1", port_b)], node_id="a")
    b = SocketP2P("127.0.0.1", port_b, peers=[("127.0.0.1", port_a)], node_id="b")

    served_block = Block(
        height=1,
        previous_block_hash=b"\x33" * 32,
        timestamp=1_700_000_300,
        transactions=(),
        validator=FAKE_VALIDATOR,
        validator_public_key=FAKE_PUBLIC_KEY,
        signature=b"\x03" * 2420,
    )

    received: list[Block] = []

    a.register_sync_providers(lambda: 1, lambda h, n: [served_block])
    b.register_sync_providers(lambda: 0, lambda h, n: [])
    b.register_block_handler(received.append)

    a.start()
    b.start()
    try:
        assert wait_until(lambda: len(received) > 0, timeout=10.0), (
            "le bloc de synchronisation n'a pas atteint le handler"
        )
        assert received[0].block_hash == served_block.block_hash
        assert received[0].height == 1
    finally:
        a.stop()
        b.stop()


def test_sync_response_is_not_filtered_by_the_seen_cache():
    """
    Un bloc DEJA VU doit quand meme etre re-livre par la synchro.

    Regression importante : un bloc rejete comme orphelin a la
    premiere reception reste dans le cache anti-boucle. Si la synchro
    appliquait ce filtre, le bloc ne serait jamais rejoue et le noeud
    resterait bloque pour toujours -- exactement le defaut que la
    synchro doit corriger.
    """
    port_a, port_b = free_port(), free_port()
    a = SocketP2P("127.0.0.1", port_a, peers=[("127.0.0.1", port_b)], node_id="a")
    b = SocketP2P("127.0.0.1", port_b, peers=[("127.0.0.1", port_a)], node_id="b")

    block = Block(
        height=1,
        previous_block_hash=b"\x44" * 32,
        timestamp=1_700_000_400,
        transactions=(),
        validator=FAKE_VALIDATOR,
        validator_public_key=FAKE_PUBLIC_KEY,
        signature=b"\x03" * 2420,
    )

    # On marque le bloc comme deja vu cote destinataire.
    b._seen.add_if_new(block.block_hash)

    received: list[Block] = []
    a.register_sync_providers(lambda: 1, lambda h, n: [block])
    b.register_sync_providers(lambda: 0, lambda h, n: [])
    b.register_block_handler(received.append)

    a.start()
    b.start()
    try:
        assert wait_until(lambda: len(received) > 0, timeout=10.0), (
            "un bloc deja vu a ete filtre par le cache : la "
            "synchronisation est inoperante"
        )
    finally:
        a.stop()
        b.stop()


def test_empty_sync_response_is_not_sent():
    """
    Un pair qui n'a rien a servir reste silencieux.

    Evite un aller-retour inutile entre deux noeuds a la meme hauteur.
    """
    port_a, port_b = free_port(), free_port()
    a = SocketP2P("127.0.0.1", port_a, peers=[("127.0.0.1", port_b)], node_id="a")
    b = SocketP2P("127.0.0.1", port_b, peers=[("127.0.0.1", port_a)], node_id="b")

    received: list[Block] = []
    a.register_sync_providers(lambda: 0, lambda h, n: [])  # rien a servir
    b.register_sync_providers(lambda: 0, lambda h, n: [])
    b.register_block_handler(received.append)

    a.start()
    b.start()
    try:
        assert wait_until(lambda: len(b.connected_peer_ids()) > 0, timeout=10.0)
        import time

        time.sleep(1.0)  # laisse le temps a une eventuelle reponse
        assert received == []
    finally:
        a.stop()
        b.stop()


def test_transport_without_providers_does_not_crash():
    """
    Un SocketP2P sans fournisseur enregistre (usage hors node.py, cas
    des tests unitaires existants) doit rester parfaitement fonctionnel.
    """
    port_a, port_b = free_port(), free_port()
    a = SocketP2P("127.0.0.1", port_a, peers=[("127.0.0.1", port_b)], node_id="a")
    b = SocketP2P("127.0.0.1", port_b, peers=[("127.0.0.1", port_a)], node_id="b")

    a.start()
    b.start()
    try:
        assert wait_until(lambda: len(a.connected_peer_ids()) > 0, timeout=10.0)
        a.request_blocks_from(1)  # sans fournisseur en face : sans effet
        assert a.is_running
        assert b.is_running
    finally:
        a.stop()
        b.stop()
