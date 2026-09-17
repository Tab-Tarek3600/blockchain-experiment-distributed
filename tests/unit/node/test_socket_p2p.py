"""
Tests de SocketP2P : transport TCP reel.

Ces tests ouvrent de VRAIES sockets sur 127.0.0.1 et des ports
ephemeres. Ils ne simulent rien du reseau : seul le fait que les deux
extremites vivent dans le meme processus (ou dans deux processus
locaux pour le dernier test) les distingue d'un deploiement sur trois
machines.

Ce que ces tests ne prouvent PAS :
    - qu'un pare-feu laisse passer le trafic entre machines,
    - qu'une VM en NAT est joignable depuis l'hote,
    - qu'une machine physique et une VM se voient.
Cela releve de la validation manuelle sur le deploiement reel.
"""

import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.blockchain.block import Block
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
from src.crypto.ml_dsa import MLDSA
from src.node.p2p import P2PTransport
from src.node.socket_p2p import (
    MAX_MESSAGE_BYTES,
    SocketP2P,
    SocketP2PError,
    _encode_frame,
    _read_frame,
)

RECIPIENT = b"\x02" * ADDRESS_LENGTH


# ----------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------

def free_port() -> int:
    """Reserve puis libere un port ephemere."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(predicate, timeout=5.0, interval=0.05) -> bool:
    """Attend qu'une condition devienne vraie (evite les sleep fixes)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class Collector:
    """Handler enregistrable qui memorise ce qu'il recoit."""

    def __init__(self):
        self.items = []
        self._event = threading.Event()

    def __call__(self, item):
        self.items.append(item)
        self._event.set()

    def wait(self, count=1, timeout=5.0) -> bool:
        return wait_until(lambda: len(self.items) >= count, timeout)


@pytest.fixture(scope="module")
def ml_dsa():
    return MLDSA()


@pytest.fixture(scope="module")
def keypair(ml_dsa):
    return ml_dsa.generate_keypair()


@pytest.fixture(scope="module")
def signed_transaction(ml_dsa, keypair):
    unsigned = Transaction(
        nonce=0,
        sender=public_key_to_address(keypair.public_key),
        recipient=RECIPIENT,
        value=500,
        gas_limit=21000,
        gas_price=1,
        data=b"hello network",
        public_key=keypair.public_key,
        signature=None,
    )
    return unsigned.with_signature(ml_dsa.sign(unsigned.signing_hash, keypair.secret_key))


@pytest.fixture(scope="module")
def signed_block(ml_dsa, keypair, signed_transaction):
    unsigned = Block(
        height=1,
        previous_block_hash=b"\x11" * 32,
        timestamp=1_700_000_005,
        transactions=(signed_transaction,),
        validator=public_key_to_address(keypair.public_key),
        validator_public_key=keypair.public_key,
        signature=None,
    )
    return unsigned.with_signature(ml_dsa.sign(unsigned.signing_hash, keypair.secret_key))


@pytest.fixture
def transport_pair():
    """
    Deux SocketP2P qui se referencent mutuellement comme pairs.

    Le teardown appelle stop() sur les deux, meme si le test echoue.
    """
    port_a, port_b = free_port(), free_port()

    node_a = SocketP2P(
        host="127.0.0.1", port=port_a,
        peers=[("127.0.0.1", port_b)], node_id="A", dial_interval=0.2,
    )
    node_b = SocketP2P(
        host="127.0.0.1", port=port_b,
        peers=[("127.0.0.1", port_a)], node_id="B", dial_interval=0.2,
    )

    yield node_a, node_b

    node_a.stop()
    node_b.stop()


def connected_pair(transport_pair):
    """Demarre les deux transports et attend la connexion mutuelle."""
    node_a, node_b = transport_pair
    node_a.start()
    node_b.start()
    assert wait_until(
        lambda: node_a.connection_count() >= 1 and node_b.connection_count() >= 1
    ), "les deux transports auraient du se connecter"
    return node_a, node_b


# ----------------------------------------------------------------------
# 1. SocketP2P respecte le contrat P2PTransport
# ----------------------------------------------------------------------

def test_socket_p2p_is_a_p2p_transport():
    """SocketP2P doit etre substituable a NullP2P / InMemoryP2P."""
    transport = SocketP2P(host="127.0.0.1", port=free_port(), node_id="solo")
    assert isinstance(transport, P2PTransport)


# ----------------------------------------------------------------------
# 2. Demarrage : le noeud ecoute reellement sur son port
# ----------------------------------------------------------------------

def test_start_binds_and_listens():
    port = free_port()
    transport = SocketP2P(host="127.0.0.1", port=port, node_id="listener")
    try:
        transport.start()
        assert transport.is_running

        # Preuve independante du transport : une socket TCP externe
        # parvient a se connecter au port.
        with socket.create_connection(("127.0.0.1", port), timeout=3) as probe:
            assert probe.fileno() != -1
    finally:
        transport.stop()


def test_start_is_idempotent():
    port = free_port()
    transport = SocketP2P(host="127.0.0.1", port=port, node_id="listener")
    try:
        transport.start()
        transport.start()  # ne doit pas lever "address already in use"
        assert transport.is_running
    finally:
        transport.stop()


def test_start_on_busy_port_raises():
    """Un port deja pris doit produire une erreur explicite."""
    port = free_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)

    transport = SocketP2P(host="127.0.0.1", port=port, node_id="late")
    try:
        with pytest.raises(SocketP2PError, match="cannot listen"):
            transport.start()
    finally:
        transport.stop()
        blocker.close()


# ----------------------------------------------------------------------
# 3. Deux noeuds se connectent mutuellement
# ----------------------------------------------------------------------

def test_two_nodes_connect_to_each_other(transport_pair):
    node_a, node_b = connected_pair(transport_pair)

    assert node_a.connected_peer_ids() == ["B"]
    assert node_b.connected_peer_ids() == ["A"]


def test_mutual_dial_does_not_create_duplicate_links(transport_pair):
    """
    Les deux noeuds se composent en meme temps. Apres stabilisation,
    il ne doit rester qu'un lien par paire.
    """
    node_a, node_b = connected_pair(transport_pair)

    # Laisse plusieurs cycles de dial s'ecouler.
    time.sleep(1.0)

    assert node_a.connection_count() == 1
    assert node_b.connection_count() == 1


def test_tie_break_rule_is_symmetric():
    """
    Les deux extremites doivent designer le MEME lien physique.

    Si les deux gardaient leur propre lien sortant (ou entrant), elles
    fermeraient chacune un lien different et la paire se retrouverait
    sans aucune connexion.
    """
    node_a = SocketP2P("127.0.0.1", free_port(), node_id="A")
    node_b = SocketP2P("127.0.0.1", free_port(), node_id="B")

    # A garde son sortant <=> B garde son entrant : exactement un
    # des deux cotes privilegie son lien sortant.
    assert node_a._prefers_outbound("B") != node_b._prefers_outbound("A")


def test_mutual_dial_never_disconnects_the_pair():
    """
    Course de composition mutuelle repetee : la paire doit finir
    connectee a chaque fois, jamais a zero lien des deux cotes.
    """
    for attempt in range(5):
        port_a, port_b = free_port(), free_port()
        node_a = SocketP2P("127.0.0.1", port_a, [("127.0.0.1", port_b)], "A",
                           dial_interval=5.0)
        node_b = SocketP2P("127.0.0.1", port_b, [("127.0.0.1", port_a)], "B",
                           dial_interval=5.0)
        try:
            # Demarrage simultane pour maximiser la probabilite de course.
            barrier = threading.Barrier(2)

            def launch(node):
                barrier.wait()
                node.start()

            threads = [threading.Thread(target=launch, args=(n,))
                       for n in (node_a, node_b)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            # dial_interval est long : aucun re-dial ne viendra
            # masquer une double fermeture.
            assert wait_until(
                lambda: node_a.connection_count() == 1
                and node_b.connection_count() == 1,
                timeout=5.0,
            ), (
                f"essai {attempt}: liens A={node_a.connection_count()} "
                f"B={node_b.connection_count()}"
            )
        finally:
            node_a.stop()
            node_b.stop()


def test_node_started_later_still_connects():
    """L'ordre de demarrage des machines ne doit pas importer."""
    port_a, port_b = free_port(), free_port()
    node_a = SocketP2P("127.0.0.1", port_a, [("127.0.0.1", port_b)], "A",
                       dial_interval=0.2)
    node_b = SocketP2P("127.0.0.1", port_b, [("127.0.0.1", port_a)], "B",
                       dial_interval=0.2)
    try:
        node_a.start()          # A tourne seul, ses dials echouent
        time.sleep(0.6)
        assert node_a.connection_count() == 0

        node_b.start()          # B arrive en retard
        assert wait_until(
            lambda: node_a.connection_count() == 1
            and node_b.connection_count() == 1
        )
    finally:
        node_a.stop()
        node_b.stop()


# ----------------------------------------------------------------------
# 4-5. Propagation transaction / bloc de A vers B
# ----------------------------------------------------------------------

def test_transaction_travels_from_a_to_b(transport_pair, signed_transaction):
    node_a, node_b = connected_pair(transport_pair)

    received = Collector()
    node_b.register_transaction_handler(received)

    node_a.broadcast_transaction(signed_transaction)

    assert received.wait(), "B n'a pas recu la transaction"
    assert len(received.items) == 1
    assert received.items[0].tx_id == signed_transaction.tx_id
    assert received.items[0].value == signed_transaction.value
    assert received.items[0].data == signed_transaction.data
    assert received.items[0].signature == signed_transaction.signature


def test_block_travels_from_a_to_b(transport_pair, signed_block):
    node_a, node_b = connected_pair(transport_pair)

    received = Collector()
    node_b.register_block_handler(received)

    node_a.broadcast_block(signed_block)

    assert received.wait(), "B n'a pas recu le bloc"
    block = received.items[0]
    assert block.block_hash == signed_block.block_hash
    assert block.height == signed_block.height
    assert len(block.transactions) == 1
    assert block.transactions[0].tx_id == signed_block.transactions[0].tx_id


def test_propagation_is_bidirectional(transport_pair, signed_transaction, signed_block):
    node_a, node_b = connected_pair(transport_pair)

    at_a, at_b = Collector(), Collector()
    node_a.register_block_handler(at_a)
    node_b.register_transaction_handler(at_b)

    node_a.broadcast_transaction(signed_transaction)
    node_b.broadcast_block(signed_block)

    assert at_b.wait()
    assert at_a.wait()


# ----------------------------------------------------------------------
# 6. Les handlers enregistres sont bien appeles
# ----------------------------------------------------------------------

def test_handlers_are_invoked_with_reconstructed_objects(
    transport_pair, signed_transaction, signed_block
):
    node_a, node_b = connected_pair(transport_pair)

    tx_seen, block_seen = Collector(), Collector()
    node_b.register_transaction_handler(tx_seen)
    node_b.register_block_handler(block_seen)

    node_a.broadcast_transaction(signed_transaction)
    node_a.broadcast_block(signed_block)

    assert tx_seen.wait()
    assert block_seen.wait()
    assert isinstance(tx_seen.items[0], Transaction)
    assert isinstance(block_seen.items[0], Block)


def test_no_handler_registered_does_not_crash(transport_pair, signed_transaction):
    """Recevoir un message sans handler ne doit pas tuer la connexion."""
    node_a, node_b = connected_pair(transport_pair)

    node_a.broadcast_transaction(signed_transaction)
    time.sleep(0.4)

    assert node_b.connection_count() == 1
    assert node_a.connection_count() == 1


def test_handler_exception_does_not_kill_connection(transport_pair, signed_transaction,
                                                    signed_block):
    """Un handler applicatif qui leve ne doit pas fermer le lien."""
    node_a, node_b = connected_pair(transport_pair)

    def explode(_item):
        raise RuntimeError("handler boom")

    node_b.register_transaction_handler(explode)
    later = Collector()
    node_b.register_block_handler(later)

    node_a.broadcast_transaction(signed_transaction)
    time.sleep(0.3)

    node_a.broadcast_block(signed_block)
    assert later.wait(), "le lien devait survivre a l'exception du handler"


# ----------------------------------------------------------------------
# 7. Messages invalides rejetes sans crash
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_message",
    [
        {"type": "tx", "payload": {"nonce": "not-an-int"}},
        {"type": "tx", "payload": {}},
        {"type": "tx", "payload": "not-an-object"},
        {"type": "block", "payload": {"height": -1}},
        {"type": "block", "payload": {}},
        {"type": "block", "payload": []},
        {"type": "unknown-type", "payload": {}},
        {"payload": {}},
        {},
    ],
    ids=[
        "tx-bad-field", "tx-empty", "tx-not-object",
        "block-bad-height", "block-empty", "block-not-object",
        "unknown-type", "missing-type", "empty-message",
    ],
)
def test_invalid_messages_are_rejected(transport_pair, bad_message, signed_block):
    node_a, node_b = connected_pair(transport_pair)

    tx_seen, block_seen = Collector(), Collector()
    node_b.register_transaction_handler(tx_seen)
    node_b.register_block_handler(block_seen)

    node_a._broadcast(bad_message)
    time.sleep(0.3)

    assert tx_seen.items == []
    assert block_seen.items == []
    # La connexion doit rester utilisable apres le rejet.
    node_a.broadcast_block(signed_block)
    assert block_seen.wait(), "le lien devait survivre au message invalide"


def test_garbage_bytes_do_not_crash_the_listener():
    """Un client qui envoie n'importe quoi ne doit pas tuer le noeud."""
    port = free_port()
    transport = SocketP2P("127.0.0.1", port, node_id="victim")
    try:
        transport.start()

        with socket.create_connection(("127.0.0.1", port), timeout=3) as attacker:
            attacker.sendall(b"\x00\x00\x00\x05" + b"junk!")
            time.sleep(0.3)

        assert transport.is_running
        # Le noeud accepte encore de nouvelles connexions.
        with socket.create_connection(("127.0.0.1", port), timeout=3) as probe:
            assert probe.fileno() != -1
    finally:
        transport.stop()


def test_oversized_frame_is_refused():
    """Une longueur annoncee delirante ne doit pas allouer de memoire."""
    port = free_port()
    transport = SocketP2P("127.0.0.1", port, node_id="victim")
    try:
        transport.start()
        with socket.create_connection(("127.0.0.1", port), timeout=3) as attacker:
            attacker.sendall(struct.pack(">I", MAX_MESSAGE_BYTES + 1))
            time.sleep(0.3)
        assert transport.is_running
    finally:
        transport.stop()


# ----------------------------------------------------------------------
# Framing : un recv() ne rend pas forcement un message complet
# ----------------------------------------------------------------------

def test_frame_roundtrip_over_fragmented_stream(signed_transaction):
    """
    Deux messages envoyes octet par octet doivent etre reconstitues
    exactement : c'est le coeur du framing longueur-prefixee.
    """
    frame1 = _encode_frame({"type": "tx", "payload": signed_transaction.to_dict()})
    frame2 = _encode_frame({"type": "hello", "node_id": "X"})
    stream = frame1 + frame2

    left, right = socket.socketpair()
    try:
        def dribble():
            for i in range(len(stream)):
                left.sendall(stream[i:i + 1])
            left.shutdown(socket.SHUT_WR)

        threading.Thread(target=dribble, daemon=True).start()

        first = _read_frame(right)
        second = _read_frame(right)

        assert first["type"] == "tx"
        assert Transaction.from_dict(first["payload"]).tx_id == signed_transaction.tx_id
        assert second == {"type": "hello", "node_id": "X"}
        assert _read_frame(right) is None  # fin de flux propre
    finally:
        left.close()
        right.close()


def test_two_frames_in_a_single_recv_are_split(signed_transaction):
    """Deux messages colles dans un seul segment TCP."""
    frame1 = _encode_frame({"type": "hello", "node_id": "A"})
    frame2 = _encode_frame({"type": "hello", "node_id": "B"})

    left, right = socket.socketpair()
    try:
        left.sendall(frame1 + frame2)
        assert _read_frame(right)["node_id"] == "A"
        assert _read_frame(right)["node_id"] == "B"
    finally:
        left.close()
        right.close()


# ----------------------------------------------------------------------
# 8. Deconnexion d'un pair : pas de crash
# ----------------------------------------------------------------------

def test_peer_disconnect_is_survivable(signed_transaction):
    port_a, port_b = free_port(), free_port()
    node_a = SocketP2P("127.0.0.1", port_a, [("127.0.0.1", port_b)], "A",
                       dial_interval=10.0)
    node_b = SocketP2P("127.0.0.1", port_b, [("127.0.0.1", port_a)], "B",
                       dial_interval=10.0)
    try:
        node_a.start()
        node_b.start()
        assert wait_until(lambda: node_a.connection_count() == 1)

        node_b.stop()

        # A doit detecter la disparition de B et rester vivant.
        assert wait_until(lambda: node_a.connection_count() == 0)
        assert node_a.is_running

        # Diffuser sans aucun pair ne doit pas lever.
        node_a.broadcast_transaction(signed_transaction)
    finally:
        node_a.stop()
        node_b.stop()


def test_broadcast_with_no_peers_is_a_noop(signed_transaction, signed_block):
    transport = SocketP2P("127.0.0.1", free_port(), node_id="lonely")
    try:
        transport.start()
        transport.broadcast_transaction(signed_transaction)
        transport.broadcast_block(signed_block)
        assert transport.is_running
    finally:
        transport.stop()


# ----------------------------------------------------------------------
# 9. Anti-boucle de broadcast
# ----------------------------------------------------------------------

def test_duplicate_transaction_is_delivered_once(transport_pair, signed_transaction):
    node_a, node_b = connected_pair(transport_pair)

    received = Collector()
    node_b.register_transaction_handler(received)

    for _ in range(4):
        node_a.broadcast_transaction(signed_transaction)

    assert received.wait()
    time.sleep(0.4)
    assert len(received.items) == 1, "la deduplication a laisse passer un doublon"


def test_duplicate_block_is_delivered_once(transport_pair, signed_block):
    node_a, node_b = connected_pair(transport_pair)

    received = Collector()
    node_b.register_block_handler(received)

    for _ in range(4):
        node_a.broadcast_block(signed_block)

    assert received.wait()
    time.sleep(0.4)
    assert len(received.items) == 1


def test_echo_back_does_not_loop(transport_pair, signed_block):
    """
    Simule le pire cas : B rediffuse systematiquement ce qu'il recoit.
    A ne doit pas re-livrer l'echo a son propre handler.
    """
    node_a, node_b = connected_pair(transport_pair)

    at_a = Collector()
    node_a.register_block_handler(at_a)
    node_b.register_block_handler(lambda block: node_b.broadcast_block(block))

    node_a.broadcast_block(signed_block)
    time.sleep(0.8)

    assert at_a.items == [], "l'echo est revenu jusqu'au handler : boucle possible"


def test_sender_marks_its_own_message_as_seen(signed_block):
    transport = SocketP2P("127.0.0.1", free_port(), node_id="solo")
    transport.broadcast_block(signed_block)
    assert signed_block.block_hash in transport._seen


def test_seen_cache_is_bounded():
    from src.node.socket_p2p import _SeenCache

    cache = _SeenCache(max_size=10)
    for i in range(50):
        cache.add_if_new(i.to_bytes(4, "big"))

    assert len(cache) == 10
    assert (0).to_bytes(4, "big") not in cache      # purge FIFO
    assert (49).to_bytes(4, "big") in cache


# ----------------------------------------------------------------------
# 10. stop() ferme proprement
# ----------------------------------------------------------------------

def test_stop_releases_the_port():
    port = free_port()
    transport = SocketP2P("127.0.0.1", port, node_id="A")
    transport.start()
    transport.stop()

    assert not transport.is_running

    # Le port doit etre reutilisable immediatement.
    other = SocketP2P("127.0.0.1", port, node_id="B")
    try:
        other.start()
        assert other.is_running
    finally:
        other.stop()


def test_stop_is_idempotent_and_safe_before_start():
    transport = SocketP2P("127.0.0.1", free_port(), node_id="A")
    transport.stop()          # jamais demarre
    transport.start()
    transport.stop()
    transport.stop()          # deux fois
    assert not transport.is_running


def test_stop_closes_all_connections(transport_pair):
    node_a, node_b = connected_pair(transport_pair)

    node_a.stop()

    assert node_a.connection_count() == 0
    assert wait_until(lambda: node_b.connection_count() == 0)


def test_no_lingering_threads_after_stop():
    before = threading.active_count()

    transport = SocketP2P("127.0.0.1", free_port(), [("127.0.0.1", free_port())],
                          "A", dial_interval=0.2)
    transport.start()
    time.sleep(0.5)
    transport.stop()
    time.sleep(0.5)

    assert threading.active_count() <= before + 1, "des threads survivent a stop()"


# ----------------------------------------------------------------------
# 11. Deux PROCESSUS separes (pas seulement deux threads)
# ----------------------------------------------------------------------

RECEIVER_SCRIPT = """
import json, sys, time
from src.node.socket_p2p import SocketP2P

port = int(sys.argv[1])
peer_port = int(sys.argv[2])

received = []
transport = SocketP2P("127.0.0.1", port, [("127.0.0.1", peer_port)],
                      "receiver", dial_interval=0.2)
transport.register_transaction_handler(lambda tx: received.append(tx.tx_id.hex()))
transport.register_block_handler(lambda b: received.append(b.block_hash.hex()))
transport.start()

deadline = time.time() + 20
while time.time() < deadline and len(received) < 2:
    time.sleep(0.1)

transport.stop()
print("RESULT:" + json.dumps(received))
"""


def test_two_separate_processes_exchange_messages(tmp_path, signed_transaction,
                                                  signed_block):
    """
    Preuve que le transport fonctionne entre PROCESSUS distincts,
    et pas seulement entre threads partageant de la memoire.

    C'est l'etape intermediaire entre le test in-process et le
    deploiement sur trois machines.
    """
    script = tmp_path / "receiver.py"
    script.write_text(RECEIVER_SCRIPT)

    port_sender, port_receiver = free_port(), free_port()

    # Le processus enfant demarre depuis tmp_path : la racine du
    # depot doit lui etre donnee explicitement via PYTHONPATH, car
    # le pythonpath de pytest.ini ne s'herite pas.
    repo_root = Path(__file__).resolve().parents[3]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")

    child = subprocess.Popen(
        [sys.executable, str(script), str(port_receiver), str(port_sender)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(repo_root), env=env,
    )

    sender = SocketP2P("127.0.0.1", port_sender, [("127.0.0.1", port_receiver)],
                       "sender", dial_interval=0.2)
    try:
        sender.start()
        assert wait_until(lambda: sender.connection_count() == 1, timeout=15), (
            "le processus enfant ne s'est pas connecte"
        )

        sender.broadcast_transaction(signed_transaction)
        time.sleep(0.2)
        sender.broadcast_block(signed_block)

        stdout, stderr = child.communicate(timeout=30)
    finally:
        sender.stop()
        if child.poll() is None:
            child.kill()
            child.communicate()

    result_line = [l for l in stdout.splitlines() if l.startswith("RESULT:")]
    assert result_line, f"pas de resultat du processus enfant.\nstderr:\n{stderr}"

    received = json.loads(result_line[0][7:])
    assert signed_transaction.tx_id.hex() in received
    assert signed_block.block_hash.hex() in received
