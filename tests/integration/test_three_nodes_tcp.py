"""
Test d'integration : 3 noeuds relies par de VRAIES sockets TCP.

Topologies testées :

    triangle complet (réseau de comparaison) :

        node1 <-----> node2
           \\           /
            \\         /
             \\       /
              +-node3-+

    ligne PHASE 5 : node1 <-----> node2 <-----> node3

Chaque noeud est un Node complet (blockchain sur disque, mempool,
consensus PoA, cles ML-DSA reelles) branche sur un SocketP2P.

Difference avec le deploiement reel : les trois noeuds tournent dans
un seul processus, sur 127.0.0.1. Le transport, lui, est identique :
sockets TCP, framing, serialisation JSON. Ce test ne prouve donc PAS
la joignabilite reseau entre la machine physique et les VMs, qui doit
etre validee manuellement.

Ces tests sont plus lents (generation de cles ML-DSA + attentes
reseau). Ils sont marques `integration` et peuvent etre desactives :
    pytest -m "not integration"
"""

import socket
import threading
import time
from types import SimpleNamespace

import pytest

from src.blockchain.transaction import Transaction
from src.node.main import _production_loop
from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
from src.crypto.ml_dsa import MLDSA
from src.node.config import NodeConfig
from src.node.node import Node
from src.node.socket_p2p import SocketP2P

pytestmark = pytest.mark.integration

RECIPIENT = b"\x07" * ADDRESS_LENGTH


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(predicate, timeout=15.0, interval=0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture(scope="module")
def ml_dsa():
    return MLDSA()


@pytest.fixture(scope="module")
def keypairs(ml_dsa):
    return [ml_dsa.generate_keypair() for _ in range(3)]


@pytest.fixture
def network(tmp_path, ml_dsa, keypairs):
    """
    Monte 3 noeuds relies en triangle par TCP.

    Reproduit exactement ce que fait src/node/main.py : NodeConfig ->
    SocketP2P -> Node.from_config -> transport.start().
    """
    addresses = [public_key_to_address(kp.public_key) for kp in keypairs]
    ports = [free_port() for _ in range(3)]

    nodes, transports = [], []

    for index, keypair in enumerate(keypairs):
        key_dir = tmp_path / f"keys{index}"
        key_dir.mkdir()
        # Depose les cles ML-DSA la ou le noeud les attend.
        (key_dir / "validator_public_key.bin").write_bytes(keypair.public_key)
        (key_dir / "validator_secret_key.bin").write_bytes(keypair.secret_key)

        peers = [
            {"host": "127.0.0.1", "port": ports[other]}
            for other in range(3) if other != index
        ]

        # La configuration est la source unique de verite : le genesis
        # est decrit par le YAML, identique pour les 3 noeuds.
        config = NodeConfig.from_dict({
            "node_id": f"node{index + 1}",
            "node_name": f"Node {index + 1}",
            "data_dir": str(tmp_path / f"data{index}"),
            "host": "127.0.0.1",
            "port": ports[index],
            "peers": peers,
            "validator_key_dir": str(key_dir),
            "authorized_validators": [addr.hex() for addr in addresses],
            "genesis_validator_public_key": keypairs[0].public_key.hex(),
            "genesis_timestamp": 1_700_000_000,
            "mempool_max_size": 100,
            "block_interval_seconds": 1.0,
            "round_timeout_seconds": 0.25,
        })

        transport = SocketP2P(
            host=config.host, port=config.port, peers=config.peers,
            node_id=config.node_id, dial_interval=0.2,
        )
        node = Node.from_config(config, p2p=transport, ml_dsa=ml_dsa)

        nodes.append(node)
        transports.append(transport)

    for transport in transports:
        transport.start()

    # Attend le maillage complet : 2 connexions par noeud.
    assert wait_until(
        lambda: all(t.connection_count() == 2 for t in transports)
    ), (
        "le triangle ne s'est pas forme: "
        + str([t.connected_peer_ids() for t in transports])
    )

    yield nodes, transports, keypairs, addresses

    for transport in transports:
        transport.stop()


@pytest.fixture
def line_network(tmp_path, ml_dsa, keypairs):
    """Monte le scénario PHASE 5 node1 ↔ node2 ↔ node3 sur TCP réel."""
    addresses = [public_key_to_address(kp.public_key) for kp in keypairs]
    ports = [free_port() for _ in range(3)]
    peer_indices = ((1,), (0, 2), (1,))
    nodes, transports = [], []

    for index, keypair in enumerate(keypairs):
        key_dir = tmp_path / f"keys{index}"
        key_dir.mkdir()
        (key_dir / "validator_public_key.bin").write_bytes(keypair.public_key)
        (key_dir / "validator_secret_key.bin").write_bytes(keypair.secret_key)

        peers = [
            {"host": "127.0.0.1", "port": ports[other]}
            for other in peer_indices[index]
        ]
        config = NodeConfig.from_dict({
            "node_id": f"node{index + 1}",
            "node_name": f"Node {index + 1}",
            "data_dir": str(tmp_path / f"data{index}"),
            "host": "127.0.0.1",
            "port": ports[index],
            "peers": peers,
            "validator_key_dir": str(key_dir),
            "authorized_validators": [addr.hex() for addr in addresses],
            "genesis_validator_public_key": keypairs[0].public_key.hex(),
            "genesis_timestamp": 1_700_000_000,
            "mempool_max_size": 100,
            "block_interval_seconds": 1.0,
            "round_timeout_seconds": 0.25,
        })
        transport = SocketP2P(
            host=config.host,
            port=config.port,
            peers=config.peers,
            node_id=config.node_id,
            dial_interval=0.2,
        )
        nodes.append(Node.from_config(config, p2p=transport, ml_dsa=ml_dsa))
        transports.append(transport)

    for transport in transports:
        transport.start()

    assert wait_until(
        lambda: transports[0].connection_count() == 1
        and transports[1].connection_count() == 2
        and transports[2].connection_count() == 1
    ), [transport.connected_peer_ids() for transport in transports]

    yield nodes, transports, keypairs, addresses

    for transport in transports:
        transport.stop()


def make_signed_tx(ml_dsa, keypair, nonce, value=100):
    unsigned = Transaction(
        nonce=nonce,
        sender=public_key_to_address(keypair.public_key),
        recipient=RECIPIENT,
        value=value,
        gas_limit=21000,
        gas_price=1,
        data=b"",
        public_key=keypair.public_key,
        signature=None,
    )
    return unsigned.with_signature(ml_dsa.sign(unsigned.signing_hash, keypair.secret_key))


# ----------------------------------------------------------------------
# Prealable : reseau forme et genesis commun
# ----------------------------------------------------------------------

def test_triangle_is_fully_meshed(network):
    _nodes, transports, _kps, _addrs = network

    for transport in transports:
        assert transport.connection_count() == 2, transport.connected_peer_ids()

    assert transports[0].connected_peer_ids() == ["node2", "node3"]
    assert transports[1].connected_peer_ids() == ["node1", "node3"]
    assert transports[2].connected_peer_ids() == ["node1", "node2"]


def test_all_three_nodes_share_the_same_genesis(network):
    """Sans genesis identique, aucun bloc ne serait jamais accepte."""
    nodes, _transports, _kps, _addrs = network

    hashes = {node._blockchain.genesis_block.block_hash for node in nodes}
    assert len(hashes) == 1, "les genesis divergent"


def test_the_three_nodes_have_distinct_addresses(network):
    nodes, _transports, _kps, _addrs = network
    assert len({node.local_address for node in nodes}) == 3


# ----------------------------------------------------------------------
# Propagation des transactions : A->B, B->C, C->A
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "origin, nonce", [(0, 0), (1, 0), (2, 0)],
    ids=["node1-to-others", "node2-to-others", "node3-to-others"],
)
def test_transaction_from_any_node_reaches_the_two_others(network, ml_dsa, origin, nonce):
    nodes, _transports, keypairs, _addrs = network

    transaction = make_signed_tx(ml_dsa, keypairs[origin], nonce)
    nodes[origin].receive_transaction(transaction)

    others = [i for i in range(3) if i != origin]
    assert wait_until(
        lambda: all(nodes[i]._mempool.contains(transaction.tx_id) for i in others)
    ), "la transaction n'a pas atteint les deux autres noeuds"

    for index in range(3):
        assert nodes[index]._mempool.contains(transaction.tx_id)


def test_directed_paths_node1_node2_node3_node1(network, ml_dsa):
    """
    Les trois chemins demandes, un par un :
        N1 -> N2, N2 -> N3, N3 -> N1
    """
    nodes, _transports, keypairs, _addrs = network

    tx_1 = make_signed_tx(ml_dsa, keypairs[0], 0, value=11)
    nodes[0].receive_transaction(tx_1)
    assert wait_until(lambda: nodes[1]._mempool.contains(tx_1.tx_id)), "N1 -> N2 KO"

    tx_2 = make_signed_tx(ml_dsa, keypairs[1], 0, value=22)
    nodes[1].receive_transaction(tx_2)
    assert wait_until(lambda: nodes[2]._mempool.contains(tx_2.tx_id)), "N2 -> N3 KO"

    tx_3 = make_signed_tx(ml_dsa, keypairs[2], 0, value=33)
    nodes[2].receive_transaction(tx_3)
    assert wait_until(lambda: nodes[0]._mempool.contains(tx_3.tx_id)), "N3 -> N1 KO"


def test_phase5_line_relay_and_non_proposer_inclusion(line_network, ml_dsa):
    """Le client contacte node1 ; node2 propose sans lien node1-node3."""
    nodes, transports, keypairs, _addrs = line_network

    assert transports[0].connected_peer_ids() == ["node2"]
    assert set(transports[1].connected_peer_ids()) == {"node1", "node3"}
    assert transports[2].connected_peer_ids() == ["node2"]

    transaction = make_signed_tx(ml_dsa, keypairs[0], 0)
    nodes[0].receive_transaction(transaction)

    assert wait_until(
        lambda: all(node._mempool.contains(transaction.tx_id) for node in nodes)
    ), "le relais node1 -> node2 -> node3 a échoué"

    # À la hauteur 1, le tour revient à node2 ; node1 reste seulement
    # le nœud d'entrée et n'est pas utilisé comme proposant.
    block = nodes[1].propose_block()

    assert block.height == 1
    assert wait_until(lambda: all(node.height == 1 for node in nodes))
    assert len({node.tip_hash for node in nodes}) == 1
    assert len({node._state_replayer.state_root for node in nodes}) == 1
    assert [node.mempool_size for node in nodes] == [0, 0, 0]


# ----------------------------------------------------------------------
# Propagation des blocs
# ----------------------------------------------------------------------

def test_proposed_block_reaches_all_nodes(network, ml_dsa):
    """
    Le bloc h=1 revient a validators[1 % 3] = node2 (le genesis
    occupe la hauteur 0, ce n'est donc pas node1 qui commence).
    """
    nodes, _transports, keypairs, _addrs = network

    transaction = make_signed_tx(ml_dsa, keypairs[0], 0)
    nodes[0].receive_transaction(transaction)
    assert wait_until(lambda: all(n._mempool.contains(transaction.tx_id) for n in nodes))

    proposer = nodes[1]  # tour de node2 a la hauteur 1
    block = proposer.propose_block()

    assert block.height == 1
    assert wait_until(lambda: all(node.height == 1 for node in nodes)), (
        "hauteurs: " + str([n.height for n in nodes])
    )

    tips = {node._blockchain.get_latest_block().block_hash for node in nodes}
    assert len(tips) == 1
    assert tips.pop() == block.block_hash


def test_transaction_is_removed_from_all_mempools_after_inclusion(network, ml_dsa):
    nodes, _transports, keypairs, _addrs = network

    transaction = make_signed_tx(ml_dsa, keypairs[0], 0)
    nodes[0].receive_transaction(transaction)
    assert wait_until(lambda: all(n._mempool.contains(transaction.tx_id) for n in nodes))

    nodes[1].propose_block()

    assert wait_until(
        lambda: not any(n._mempool.contains(transaction.tx_id) for n in nodes)
    ), "la transaction incluse est restee dans un mempool"


def test_poa_rotation_over_three_blocks(network, ml_dsa):
    """
    Rotation complete : h=1 -> node2, h=2 -> node3, h=3 -> node1.
    Chaque bloc doit etre accepte par les trois noeuds.
    """
    nodes, _transports, keypairs, _addrs = network

    for height in (1, 2, 3):
        proposer_index = height % 3
        transaction = make_signed_tx(ml_dsa, keypairs[proposer_index], height)
        nodes[proposer_index].receive_transaction(transaction)
        assert wait_until(
            lambda: all(n._mempool.contains(transaction.tx_id) for n in nodes)
        )

        block = nodes[proposer_index].propose_block()
        assert block.height == height
        assert block.validator == nodes[proposer_index].local_address

        assert wait_until(lambda: all(n.height == height for n in nodes)), (
            f"h={height}: hauteurs " + str([n.height for n in nodes])
        )

    assert [node.height for node in nodes] == [3, 3, 3]
    assert len({n._blockchain.get_latest_block().block_hash for n in nodes}) == 1


def test_block_from_wrong_proposer_is_rejected_by_peers(network, ml_dsa):
    """
    Un noeud qui propose hors de son tour doit voir son bloc refuse :
    le consensus PoA n'est pas contourne par le reseau.
    """
    from src.node.node import NodeError

    nodes, _transports, _kps, _addrs = network

    # A la hauteur 1, c'est node2. node3 n'a pas le droit de proposer.
    with pytest.raises(NodeError):
        nodes[2].propose_block()

    assert all(node.height == 0 for node in nodes)


def test_tcp_failover_when_initial_proposer_is_offline(network, ml_dsa):
    """Le round 1 produit un bloc TCP quand le proposant du round 0 est absent."""
    nodes, transports, keypairs, _addrs = network

    # A h=1, node2 est le proposant du round 0. Son transport est arrete
    # avant l'injection : node1 et node3 restent directement connectes.
    transports[1].stop()
    assert wait_until(lambda: transports[0].connection_count() == 1)
    assert wait_until(lambda: transports[2].connection_count() == 1)

    transaction = make_signed_tx(ml_dsa, keypairs[0], 0)
    nodes[0].receive_transaction(transaction)
    assert wait_until(
        lambda: nodes[0]._mempool.contains(transaction.tx_id)
        and nodes[2]._mempool.contains(transaction.tx_id)
    ), "la transaction n'est pas arrivee aux validateurs disponibles"

    # Execute the same production loop as src.node.main. No direct call to
    # advance_round_if_timed_out is made: both live validators must cross
    # the timeout on their own, then node3 proposes at the same height.
    stopping = {"flag": False}
    args = SimpleNamespace(no_propose=False, produce_empty_blocks=False)
    workers = [
        threading.Thread(
            target=_production_loop,
            args=(nodes[index], nodes[index]._config, transports[index], args, stopping),
            daemon=True,
        )
        for index in (0, 2)
    ]
    for worker in workers:
        worker.start()

    try:
        assert wait_until(
            lambda: nodes[0].height == 1 and nodes[2].height == 1,
            timeout=10.0,
        ), [nodes[0].height, nodes[2].height]

        blocks = [nodes[0]._blockchain.get_latest_block(), nodes[2]._blockchain.get_latest_block()]
        assert all(block.round == 1 for block in blocks)
        assert all(block.validator == nodes[2].local_address for block in blocks)
        assert blocks[0].block_hash == blocks[1].block_hash
        assert nodes[1].height == 0  # proposer initial remained offline
    finally:
        stopping["flag"] = True
        for worker in workers:
            worker.join(timeout=2.0)


# ----------------------------------------------------------------------
# Anti-boucle en topologie triangulaire
# ----------------------------------------------------------------------

def test_no_broadcast_storm_in_the_triangle(network, ml_dsa):
    """
    Le triangle est le cas ou une boucle apparaitrait : chaque noeud a
    deux voisins qui ont eux-memes un lien direct. Apres propagation,
    le reseau doit se taire.
    """
    nodes, transports, keypairs, _addrs = network

    transaction = make_signed_tx(ml_dsa, keypairs[0], 0)
    nodes[0].receive_transaction(transaction)
    assert wait_until(lambda: all(n._mempool.contains(transaction.tx_id) for n in nodes))

    nodes[1].propose_block()
    assert wait_until(lambda: all(node.height == 1 for node in nodes))

    # Si une boucle existait, l'activite continuerait indefiniment et
    # la hauteur ou les mempools bougeraient encore.
    time.sleep(2.0)

    assert [node.height for node in nodes] == [1, 1, 1]
    assert [node.mempool_size for node in nodes] == [0, 0, 0]
    assert all(t.connection_count() == 2 for t in transports)


def test_rebroadcasting_a_known_block_is_absorbed(network, ml_dsa):
    """Rediffuser manuellement un bloc deja connu ne casse rien."""
    nodes, transports, keypairs, _addrs = network

    transaction = make_signed_tx(ml_dsa, keypairs[0], 0)
    nodes[0].receive_transaction(transaction)
    assert wait_until(lambda: all(n._mempool.contains(transaction.tx_id) for n in nodes))

    block = nodes[1].propose_block()
    assert wait_until(lambda: all(node.height == 1 for node in nodes))

    for _ in range(5):
        transports[0].broadcast_block(block)
    time.sleep(1.0)

    assert [node.height for node in nodes] == [1, 1, 1]


# ----------------------------------------------------------------------
# Resilience
# ----------------------------------------------------------------------

def test_network_survives_one_node_leaving(network, ml_dsa):
    """
    node3 s'arrete. node1 et node2 doivent continuer a echanger.
    (Aucun rattrapage n'est teste : la synchronisation d'historique
    est hors perimetre.)
    """
    nodes, transports, keypairs, _addrs = network

    transports[2].stop()
    assert wait_until(lambda: transports[0].connection_count() == 1)
    assert wait_until(lambda: transports[1].connection_count() == 1)

    transaction = make_signed_tx(ml_dsa, keypairs[0], 0)
    nodes[0].receive_transaction(transaction)
    assert wait_until(lambda: nodes[1]._mempool.contains(transaction.tx_id))

    nodes[1].propose_block()
    assert wait_until(lambda: nodes[0].height == 1 and nodes[1].height == 1)
    assert nodes[2].height == 0  # noeud hors ligne : reste en arriere
