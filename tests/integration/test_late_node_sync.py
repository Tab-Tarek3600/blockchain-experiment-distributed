"""
Test d'integration : un noeud demarre EN RETARD rattrape la chaine.

Scenario reel que l'implementation sans synchronisation ne savait pas
traiter :

    1. node1 et node2 demarrent et produisent plusieurs blocs.
    2. node3 demarre alors que la chaine est deja a une hauteur > 0.
    3. node3 doit rattraper l'integralite de la chaine et converger
       vers le meme tip que les deux autres.

Sans synchronisation, node3 recevrait uniquement les blocs suivants,
tous rejetes comme non chainables, et resterait bloque au genesis
indefiniment.

Ce test tourne sur des sockets TCP reelles, en loopback, dans un seul
processus. Il ne prouve rien sur le comportement entre machines
distinctes (VM <-> physique).
"""

from __future__ import annotations

import socket
import time

import pytest

from src.crypto.address import public_key_to_address
from src.crypto.ml_dsa import MLDSA
from src.node.config import NodeConfig
from src.node.node import Node
from src.node.socket_p2p import SocketP2P

pytestmark = pytest.mark.integration


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(predicate, timeout=20.0, interval=0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture(scope="module")
def ml_dsa():
    return MLDSA()


@pytest.fixture(scope="module")
def keypairs(ml_dsa):
    return [ml_dsa.generate_keypair() for _ in range(3)]


def _genesis_public_key(keypairs, addresses, authorized):
    """
    Retourne la cle publique correspondant a authorized_validators[0].

    NodeConfig exige que le genesis derive vers le premier validateur
    autorise ; ce helper preserve cet invariant quel que soit l'ordre
    du tour de role choisi par le test.
    """
    first = (authorized if authorized is not None else addresses)[0]
    for keypair, address in zip(keypairs, addresses):
        if address == first:
            return keypair.public_key
    raise AssertionError("authorized_validators[0] absent des keypairs")


def build_node(tmp_path, ml_dsa, keypairs, addresses, ports, index, authorized=None):
    """
    Construit un noeud sans le demarrer.

    Identique a la sequence de src/node/main.py : NodeConfig ->
    SocketP2P -> Node.from_config. Le transport n'est PAS demarre ici,
    afin de pouvoir decaler volontairement le demarrage d'un noeud.

    `authorized` permet de choisir l'ORDRE du tour de role PoA, qui est
    `authorized_validators[(height + round) % 3]`. Avec `round=0`, cet ordre
    reste le tour normal et doit etre identique sur les trois noeuds.
    """
    key_dir = tmp_path / f"keys{index}"
    key_dir.mkdir(exist_ok=True)
    (key_dir / "validator_public_key.bin").write_bytes(keypairs[index].public_key)
    (key_dir / "validator_secret_key.bin").write_bytes(keypairs[index].secret_key)

    peers = [
        {"host": "127.0.0.1", "port": ports[other]}
        for other in range(3)
        if other != index
    ]

    config = NodeConfig.from_dict({
        "node_id": f"node{index + 1}",
        "node_name": f"Node {index + 1}",
        "data_dir": str(tmp_path / f"data{index}"),
        "host": "127.0.0.1",
        "port": ports[index],
        "peers": peers,
        "validator_key_dir": str(key_dir),
        "authorized_validators": [
            addr.hex() for addr in (authorized if authorized is not None else addresses)
        ],
        # Invariant impose par NodeConfig : la cle publique du genesis
        # doit deriver vers authorized_validators[0].
        "genesis_validator_public_key": _genesis_public_key(
            keypairs, addresses, authorized
        ).hex(),
        "genesis_timestamp": 1_700_000_000,
        "mempool_max_size": 100,
        "block_interval_seconds": 1.0,
    })

    transport = SocketP2P(
        host=config.host,
        port=config.port,
        peers=config.peers,
        node_id=config.node_id,
        dial_interval=0.2,
    )
    node = Node.from_config(config, p2p=transport, ml_dsa=ml_dsa)
    return node, transport


def test_late_node_catches_up_with_the_chain(tmp_path, ml_dsa, keypairs):
    """
    Un noeud rejoignant un reseau deja avance rattrape toute la chaine.

    C'est LE test de la synchronisation : il echoue necessairement
    sans elle.
    """
    addresses = [public_key_to_address(kp.public_key) for kp in keypairs]
    ports = [free_port() for _ in range(3)]

    # Ordre du tour de role PoA a round 0 :
    # validators[(height + round) % 3]. Le genesis occupe la hauteur 0.
    # On place node3 en DERNIERE position, de
    # sorte que son tour tombe sur h=3 : node1 et node2 peuvent alors
    # produire h=1 et h=2 pendant son absence, ce qui cree un retard
    # de PLUSIEURS blocs a rattraper (et non un seul).
    #
    #   h=1 -> authorized[1] = node2
    #   h=2 -> authorized[2] = node3   <-- absent
    #   h=3 -> authorized[0] = node1
    #
    # Avec node3 en position 2, la chaine se bloque des h=2. On utilise
    # donc l'ordre (node3, node1, node2) : h=1 -> node1, h=2 -> node2,
    # h=3 -> node3. node1 et node2 produisent deux blocs consecutifs
    # avant que le tour ne revienne a node3.
    authorized = [addresses[2], addresses[0], addresses[1]]

    node1, t1 = build_node(
        tmp_path, ml_dsa, keypairs, addresses, ports, 0, authorized=authorized
    )
    node2, t2 = build_node(
        tmp_path, ml_dsa, keypairs, addresses, ports, 1, authorized=authorized
    )
    node3, t3 = build_node(
        tmp_path, ml_dsa, keypairs, addresses, ports, 2, authorized=authorized
    )

    t1.start()
    t2.start()
    try:
        # --- Phase 1 : node1 et node2 seuls, la chaine avance --------
        assert wait_until(lambda: t1.connection_count() == 1), \
            "node1 et node2 ne se sont pas connectes"

        # h=1 -> node1, h=2 -> node2 : deux blocs produits sans node3.
        assert node1.is_my_turn(1), "ordre PoA inattendu pour h=1"
        node1.propose_block()
        assert wait_until(lambda: node2.height == 1), "bloc 1 non propage"

        assert node2.is_my_turn(2), "ordre PoA inattendu pour h=2"
        node2.propose_block()
        assert wait_until(lambda: node1.height == 2), "bloc 2 non propage"

        assert wait_until(lambda: node1.height == node2.height == 2), \
            f"node1={node1.height} node2={node2.height}"

        advanced_height = node1.height
        advanced_tip = node1.tip_hash
        assert advanced_height >= 2, (
            "le scenario doit creer un retard de PLUSIEURS blocs, "
            f"or la chaine n'est qu'a la hauteur {advanced_height}"
        )
        assert node3.height == 0, "node3 ne devrait pas avoir demarre"

        # --- Phase 2 : node3 rejoint le reseau en retard -------------
        t3.start()

        assert wait_until(lambda: node3.height == advanced_height, timeout=25.0), (
            f"node3 n'a pas rattrape la chaine : height={node3.height}, "
            f"attendu {advanced_height}"
        )

        # --- Phase 3 : convergence complete --------------------------
        assert node3.tip_hash == advanced_tip, \
            "node3 a la bonne hauteur mais un tip different"
        assert node3.genesis_hash == node1.genesis_hash, \
            "genesis divergent"
    finally:
        for transport in (t1, t2, t3):
            transport.stop()


def test_node_restarted_reloads_and_resyncs(tmp_path, ml_dsa, keypairs):
    """
    Un noeud arrete puis redemarre recharge sa chaine persistee, puis
    se resynchronise sur ce qu'il a manque pendant son absence.
    """
    addresses = [public_key_to_address(kp.public_key) for kp in keypairs]
    ports = [free_port() for _ in range(3)]

    node1, t1 = build_node(tmp_path, ml_dsa, keypairs, addresses, ports, 0)
    node2, t2 = build_node(tmp_path, ml_dsa, keypairs, addresses, ports, 1)

    t1.start()
    t2.start()
    try:
        assert wait_until(lambda: t1.connection_count() == 1)

        # node2 produit le bloc de hauteur 1 (1 % 3 == 1).
        assert node2.is_my_turn(1)
        node2.propose_block()
        assert wait_until(lambda: node1.height == 1), \
            f"node1 n'a pas recu le bloc 1 (height={node1.height})"

        height_before = node1.height
        tip_before = node1.tip_hash
    finally:
        t1.stop()
        t2.stop()

    time.sleep(0.5)

    # Redemarrage complet : nouveaux objets, memes data_dir.
    node1b, t1b = build_node(tmp_path, ml_dsa, keypairs, addresses, ports, 0)

    # La chaine est rechargee depuis le disque, avant tout reseau.
    assert node1b.height == height_before, \
        f"chaine non rechargee : {node1b.height} != {height_before}"
    assert node1b.tip_hash == tip_before, "tip different apres rechargement"

    t1b.stop()
