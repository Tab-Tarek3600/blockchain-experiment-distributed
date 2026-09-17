"""
Tests d'intégration de Node : cycle complet mono-nœud avec vraies
clés ML-DSA, stockage réel sur disque (tmp_path), et simulation
de communication inter-nœuds via InMemoryP2P.

Genesis convention:
    All nodes share the same genesis block. The genesis validator
    public key is part of the network configuration (passed via
    NodeConfig.genesis_validator_public_key), ensuring all nodes
    produce an identical genesis block_hash.
"""

from dataclasses import replace
import time

import pytest

from src.blockchain.block import EMPTY_STATE_ROOT, Block
from src.blockchain.blockchain import Blockchain
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
from src.crypto.ml_dsa import MLDSA
from src.evm.state import BLOCK_GAS_LIMIT
from src.node.config import NodeConfig
from src.node.consensus import Consensus
from src.node.mempool import Mempool, MempoolError
from src.node.node import Node, NodeError
from src.node.p2p import InMemoryP2P, NullP2P

RECIPIENT = b"\x01" * ADDRESS_LENGTH


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def validator_keypairs(ml_dsa):
    return [ml_dsa.generate_keypair() for _ in range(3)]


@pytest.fixture
def validator_addresses(validator_keypairs):
    return [public_key_to_address(kp.public_key) for kp in validator_keypairs]


def make_config_dict(validator_keypairs, validator_addresses, node_index, data_dir, key_dir):
    return {
        "node_id": f"node{node_index + 1}",
        "node_name": f"Node {node_index + 1}",
        "data_dir": str(data_dir),
        "host": "127.0.0.1",
        "port": 5001 + node_index,
        "peers": [],
        "validator_key_dir": str(key_dir),
        "authorized_validators": [addr.hex() for addr in validator_addresses],
        "genesis_validator_public_key": validator_keypairs[0].public_key.hex(),
        "genesis_timestamp": 1_700_000_000,
        "mempool_max_size": 100,
        "block_interval_seconds": 1.0,
    }


def make_node(
    tmp_path,
    ml_dsa,
    validator_keypairs,
    validator_addresses,
    node_index,
    p2p=None,
):
    """
    Build a fully-wired Node with injected components.

    The NodeConfig is built FIRST and is the single source of truth for
    the genesis parameters: the genesis block is derived from
    config.genesis_validator_public_key / config.genesis_timestamp,
    never from the local node's own validator key. Otherwise the test
    would bypass the very mechanism it is supposed to exercise.
    """
    keypair = validator_keypairs[node_index]
    local_address = validator_addresses[node_index]

    config = NodeConfig.from_dict(
        make_config_dict(
            validator_keypairs,
            validator_addresses,
            node_index,
            tmp_path / f"data{node_index}",
            tmp_path / f"keys{node_index}",
        )
    )

    storage = ChainStorage(config.data_dir)
    blockchain = Blockchain.open(
        storage,
        validator_public_key=config.genesis_validator_public_key,
        timestamp=config.genesis_timestamp,
    )
    mempool = Mempool(ml_dsa=ml_dsa, max_size=config.mempool_max_size)
    consensus = Consensus(
        authorized_validators=config.authorized_validators,
        local_address=local_address,
    )

    return Node(
        config=config,
        blockchain=blockchain,
        keypair=keypair,
        mempool=mempool,
        consensus=consensus,
        p2p=p2p or NullP2P(),
        ml_dsa=ml_dsa,
    )


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


# ---------------------------------------------------------------------
# Démarrage et état initial
# ---------------------------------------------------------------------


def test_node_starts_with_genesis_block(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)
    assert node.height == 0


def test_node_local_address_matches_keypair(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)
    expected = public_key_to_address(validator_keypairs[0].public_key)
    assert node.local_address == expected


def test_node_starts_with_empty_mempool(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)
    assert node.mempool_size == 0


def test_all_nodes_share_identical_genesis_block_hash(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Regression guard: all nodes must produce an identical genesis
    block_hash (root cause of the chain-link validation failures).
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    genesis_hashes = [n._blockchain.genesis_block.block_hash for n in nodes]
    assert genesis_hashes[0] == genesis_hashes[1] == genesis_hashes[2]


def test_genesis_is_independent_of_local_validator_key(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    The genesis validator comes from the shared network configuration,
    not from the node's own key: node 2 must carry a genesis signed by
    validator 0.
    """
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 2)
    genesis = node._blockchain.genesis_block

    assert node.local_address == validator_addresses[2]
    assert genesis.validator == validator_addresses[0]
    assert node.local_address != genesis.validator


# ---------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------


def test_from_config_creates_node_successfully(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    key_dir = tmp_path / "keys0"
    key_dir.mkdir(parents=True)
    keypair = validator_keypairs[0]
    (key_dir / "validator_public_key.bin").write_bytes(keypair.public_key)
    (key_dir / "validator_secret_key.bin").write_bytes(keypair.secret_key)

    config = NodeConfig.from_dict(
        make_config_dict(
            validator_keypairs,
            validator_addresses,
            0,
            tmp_path / "data0",
            key_dir,
        )
    )
    node = Node.from_config(config, ml_dsa=ml_dsa)
    assert node.height == 0


def test_from_config_rejects_unknown_local_validator(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    unknown_keypair = ml_dsa.generate_keypair()
    key_dir = tmp_path / "unknown_keys"
    key_dir.mkdir(parents=True)
    (key_dir / "validator_public_key.bin").write_bytes(unknown_keypair.public_key)
    (key_dir / "validator_secret_key.bin").write_bytes(unknown_keypair.secret_key)

    config = NodeConfig.from_dict(
        make_config_dict(
            validator_keypairs,
            validator_addresses,
            0,
            tmp_path / "data0",
            key_dir,
        )
    )

    with pytest.raises(NodeError, match="not in authorized_validators"):
        Node.from_config(config, ml_dsa=ml_dsa)


# ---------------------------------------------------------------------
# receive_transaction
# ---------------------------------------------------------------------


def test_receive_transaction_adds_to_mempool(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)
    sender_keypair = ml_dsa.generate_keypair()
    tx = make_signed_tx(ml_dsa, sender_keypair)

    node.receive_transaction(tx)

    assert node.mempool_size == 1


def test_receive_transaction_rejects_invalid_transaction(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)
    sender_keypair = ml_dsa.generate_keypair()

    unsigned_tx = Transaction.create(
        nonce=0,
        public_key=sender_keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )

    with pytest.raises(MempoolError):
        node.receive_transaction(unsigned_tx)

    assert node.mempool_size == 0


# ---------------------------------------------------------------------
# propose_block — cycle complet mono-nœud
# ---------------------------------------------------------------------


def test_propose_block_adds_to_blockchain(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)

    block = node.propose_block(timestamp=1_700_000_010)

    assert node.height == 1
    assert block.height == 1


def test_propose_block_persists_to_storage(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)
    node.propose_block(timestamp=1_700_000_010)

    storage = ChainStorage(tmp_path / "data1")
    assert storage.has_block(1)


def test_propose_block_includes_mempool_transactions(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)

    sender_keypair = ml_dsa.generate_keypair()
    tx = make_signed_tx(ml_dsa, sender_keypair)
    node.receive_transaction(tx)

    block = node.propose_block(timestamp=1_700_000_010)

    assert block.transaction_count == 1
    assert block.transactions[0].tx_id == tx.tx_id


def test_propose_block_removes_transactions_from_mempool(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)

    sender_keypair = ml_dsa.generate_keypair()
    tx = make_signed_tx(ml_dsa, sender_keypair)
    node.receive_transaction(tx)
    assert node.mempool_size == 1

    node.propose_block(timestamp=1_700_000_010)

    assert node.mempool_size == 0


def test_propose_block_raises_when_not_local_turn(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    with pytest.raises(NodeError, match="cannot propose block"):
        node.propose_block(timestamp=1_700_000_010)

    assert node.height == 0


def test_propose_block_does_not_alter_state_on_failure(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    sender_keypair = ml_dsa.generate_keypair()
    tx = make_signed_tx(ml_dsa, sender_keypair)
    node.receive_transaction(tx)

    with pytest.raises(NodeError):
        node.propose_block(timestamp=1_700_000_010)

    assert node.height == 0
    assert node.mempool_size == 1


# ---------------------------------------------------------------------
# receive_block
# ---------------------------------------------------------------------


def test_receive_block_accepts_valid_block_from_peer(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node_0 = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)
    node_1 = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)

    assert (
        node_0._blockchain.genesis_block.block_hash
        == node_1._blockchain.genesis_block.block_hash
    )

    block = node_1.propose_block(timestamp=1_700_000_010)

    node_0.receive_block(block)

    assert node_0.height == 1


def test_receive_block_ignores_obsolete_block(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node_0 = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)
    node_1 = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)

    block = node_1.propose_block(timestamp=1_700_000_010)
    node_0.receive_block(block)
    assert node_0.height == 1

    node_0.receive_block(block)
    assert node_0.height == 1


def test_receive_block_rejects_wrong_turn(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node_0 = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0)

    genesis_hash = node_0._blockchain.get_latest_block().block_hash
    bad_block = Block.create(
        height=1,
        previous_block_hash=genesis_hash,
        timestamp=1_700_000_010,
        transactions=(),
        validator_public_key=validator_keypairs[0].public_key,
    )
    sig = ml_dsa.sign(bad_block.signing_hash, validator_keypairs[0].secret_key)
    signed_block = bad_block.with_signature(sig)

    with pytest.raises(NodeError, match="not the expected proposer"):
        node_0._accept_block(signed_block, broadcast=False)

    assert node_0.height == 0


# ---------------------------------------------------------------------
# Redémarrage
# ---------------------------------------------------------------------


def test_node_reloads_chain_after_restart(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)
    node.propose_block(timestamp=1_700_000_010)
    assert node.height == 1

    restarted_node = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1
    )
    assert restarted_node.height == 1
    assert (
        restarted_node._blockchain.get_latest_block().block_hash
        == node._blockchain.get_latest_block().block_hash
    )


# ---------------------------------------------------------------------
# Communication P2P
# ---------------------------------------------------------------------


def test_p2p_transaction_propagation_between_nodes(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    p2p_0 = InMemoryP2P("node-0")
    p2p_1 = InMemoryP2P("node-1")
    p2p_0.connect(p2p_1)

    node_0 = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0, p2p=p2p_0
    )
    node_1 = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1, p2p=p2p_1
    )

    sender_keypair = ml_dsa.generate_keypair()
    tx = make_signed_tx(ml_dsa, sender_keypair)

    node_0.receive_transaction(tx)

    assert node_1.mempool_size == 1
    assert node_1._mempool.contains(tx.tx_id)


def test_p2p_transaction_is_relayed_across_a_line_topology(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Un noeud d'entrée doit relayer vers un pair non directement connecté."""
    p2p_0 = InMemoryP2P("node-0")
    p2p_1 = InMemoryP2P("node-1")
    p2p_2 = InMemoryP2P("node-2")
    p2p_0.connect(p2p_1)
    p2p_1.connect(p2p_2)

    nodes = [
        make_node(
            tmp_path,
            ml_dsa,
            validator_keypairs,
            validator_addresses,
            index,
            p2p=p2p,
        )
        for index, p2p in enumerate((p2p_0, p2p_1, p2p_2))
    ]

    tx = make_signed_tx(ml_dsa, ml_dsa.generate_keypair())
    nodes[0].receive_transaction(tx)

    assert all(node._mempool.contains(tx.tx_id) for node in nodes)
    assert [node.mempool_size for node in nodes] == [1, 1, 1]


def test_line_topology_deduplicates_relay_and_converges_after_inclusion(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """node1 reçoit, node2 propose et node3 accepte le même bloc."""
    p2p_0 = InMemoryP2P("node-0")
    p2p_1 = InMemoryP2P("node-1")
    p2p_2 = InMemoryP2P("node-2")
    p2p_0.connect(p2p_1)
    p2p_1.connect(p2p_2)

    nodes = [
        make_node(
            tmp_path,
            ml_dsa,
            validator_keypairs,
            validator_addresses,
            index,
            p2p=p2p,
        )
        for index, p2p in enumerate((p2p_0, p2p_1, p2p_2))
    ]

    tx = make_signed_tx(ml_dsa, ml_dsa.generate_keypair())
    nodes[0].receive_transaction(tx)
    # Une répétition du même message reçu par node2 ne doit pas créer
    # une seconde entrée ni repartir vers node1/node3.
    p2p_1._receive_transaction(tx)

    assert [node.mempool_size for node in nodes] == [1, 1, 1]
    block = nodes[1].propose_block(timestamp=1_700_000_010)

    assert block.height == 1
    assert [node.height for node in nodes] == [1, 1, 1]
    assert len({node.tip_hash for node in nodes}) == 1
    assert len({node._state_replayer.state_root for node in nodes}) == 1
    assert [node.mempool_size for node in nodes] == [0, 0, 0]


def test_invalid_relay_is_rejected_before_forwarding(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    p2p_0 = InMemoryP2P("node-0")
    p2p_1 = InMemoryP2P("node-1")
    p2p_2 = InMemoryP2P("node-2")
    p2p_0.connect(p2p_1)
    p2p_1.connect(p2p_2)

    nodes = [
        make_node(
            tmp_path,
            ml_dsa,
            validator_keypairs,
            validator_addresses,
            index,
            p2p=p2p,
        )
        for index, p2p in enumerate((p2p_0, p2p_1, p2p_2))
    ]

    unsigned_tx = Transaction.create(
        nonce=0,
        public_key=ml_dsa.generate_keypair().public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
    )
    p2p_1._receive_transaction(unsigned_tx)

    assert [node.mempool_size for node in nodes] == [0, 0, 0]
    assert unsigned_tx.tx_id not in nodes[1]._seen_transaction_ids


def test_p2p_block_propagation_between_nodes(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    p2p_0 = InMemoryP2P("node-0")
    p2p_1 = InMemoryP2P("node-1")
    p2p_0.connect(p2p_1)

    node_0 = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0, p2p=p2p_0
    )
    node_1 = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1, p2p=p2p_1
    )

    node_1.propose_block(timestamp=1_700_000_010)

    assert node_0.height == 1


def test_p2p_invalid_block_from_peer_is_silently_dropped(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    p2p_0 = InMemoryP2P("node-0")
    p2p_1 = InMemoryP2P("node-1")
    p2p_0.connect(p2p_1)

    node_0 = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0, p2p=p2p_0
    )

    genesis_hash = node_0._blockchain.get_latest_block().block_hash
    bad_block = Block.create(
        height=1,
        previous_block_hash=genesis_hash,
        timestamp=1_700_000_010,
        transactions=(),
        validator_public_key=validator_keypairs[0].public_key,
    )
    sig = ml_dsa.sign(bad_block.signing_hash, validator_keypairs[0].secret_key)
    signed_bad = bad_block.with_signature(sig)

    node_0._on_block_received(signed_bad)

    assert node_0.height == 0


# --- state_root : branchement du calcul reel (PHASE 3, D5) ------------


def test_le_bloc_produit_porte_la_racine_de_l_etat(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Un bloc contenant une transaction qui modifie l'etat doit annoncer
    une racine non vide. Tant que ce fil n'etait pas branche, tous les
    blocs portaient EMPTY_STATE_ROOT.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]

    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    proposeur._state_replayer.state.set_balance(validator_addresses[0], 10**18)
    proposeur._state_replayer.state.commit()
    proposeur._mempool.add_transaction(
        make_signed_tx(ml_dsa, validator_keypairs[0], nonce=0)
    )

    block = proposeur.propose_block(timestamp=1_700_000_005)

    assert block.state_root != EMPTY_STATE_ROOT
    assert len(block.transactions) == 1


def test_un_bloc_vide_conserve_la_racine_vide(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Sans transaction, rien n'est ecrit : la racine reste celle du vide."""
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))

    block = proposeur.propose_block(timestamp=1_700_000_005)

    assert block.state_root == EMPTY_STATE_ROOT


def test_la_racine_est_couverte_par_la_signature(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Falsifier la racine apres signature doit invalider le bloc : c'est
    tout l'interet d'avoir mis state_root du cote signe (decision D3).
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    block = proposeur.propose_block(timestamp=1_700_000_005)

    assert ml_dsa.verify(
        block.signing_hash, block.signature, block.validator_public_key
    )

    falsifie = replace(block, state_root=b"\x07" * 32)

    assert not ml_dsa.verify(
        falsifie.signing_hash, falsifie.signature, falsifie.validator_public_key
    )


def test_le_round_est_persiste_et_couvert_par_la_signature(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """Le round est transporte et toute modification invalide la signature."""
    node = make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, 1)
    block = node.propose_block(timestamp=1_700_000_005)

    assert block.round == 0
    assert Block.from_dict(block.to_dict()) == block

    falsifie = replace(block, round=1)
    assert not ml_dsa.verify(
        falsifie.signing_hash, falsifie.signature, falsifie.validator_public_key
    )

    legacy_payload = block.to_dict()
    legacy_payload.pop("round")
    assert Block.from_dict(legacy_payload).round == 0


def test_l_etat_rattrape_les_blocs_des_autres_validateurs(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Le cas qui justifie tout le mecanisme : en round-robin a 3 noeuds,
    un proposeur doit tenir compte des blocs qu'il n'a pas produits.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]

    premier = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    bloc1 = premier.propose_block(timestamp=1_700_000_005)
    for node in nodes:
        if node is not premier:
            node.receive_block(bloc1)

    second = next(n for n in nodes if n._consensus.is_local_node_turn(2))

    # Depuis D6, l'etat avance des la reception : verifier un bloc
    # impose de le rejouer, et le resultat est engage une fois le bloc
    # en chaine. Cette assertion valait 0 tant que le rattrapage etait
    # differe jusqu'au tour du noeud ; ce n'est plus le cas.
    assert second._state_replayer.applied_height == 1

    second.propose_block(timestamp=1_700_000_010)

    assert second._state_replayer.applied_height == 2


def test_l_etat_est_rejoue_au_demarrage(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Un noeud qui redemarre sur une chaine existante doit etre a jour
    des sa construction, sans attendre son premier tour.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    premier = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    bloc1 = premier.propose_block(timestamp=1_700_000_005)
    for node in nodes:
        if node is not premier:
            node.receive_block(bloc1)

    indice = nodes.index(premier)
    redemarre = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, indice
    )

    assert redemarre.height == 1
    assert redemarre._state_replayer.applied_height == 1
    assert redemarre._state_replayer.state_root == premier._state_replayer.state_root


# --- state_root : verification par le receveur (PHASE 3, D6) ----------


def _resigne(block, ml_dsa, keypair):
    """
    Re-signe un bloc modifie.

    Indispensable : sans cela l'etape 1 du pipeline rejetterait le bloc
    sur sa signature, et la verification de racine ne serait jamais
    atteinte. Le test ne prouverait alors rien.
    """
    non_signe = replace(block, signature=None)
    return non_signe.with_signature(
        ml_dsa.sign(non_signe.signing_hash, keypair.secret_key)
    )


def test_un_bloc_a_racine_falsifiee_est_rejete(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Le coeur du point 2. Un validateur autorise annonce une racine
    qu'il n'a pas produite, et signe correctement son bloc. Avant
    cette verification, ses pairs l'acceptaient sans broncher.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    indice = nodes.index(proposeur)

    honnete = proposeur.propose_block(timestamp=1_700_000_005)
    falsifie = _resigne(
        replace(honnete, state_root=b"\xde\xad\xbe\xef" * 8),
        ml_dsa,
        validator_keypairs[indice],
    )

    receveur = next(n for n in nodes if n is not proposeur)

    with pytest.raises(NodeError, match="state_root mismatch"):
        receveur.receive_block(falsifie)


def test_un_bloc_a_racine_falsifiee_n_entre_pas_dans_la_chaine(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Le rejet doit etre effectif : ni dans la chaine, ni dans l'etat.
    Un bloc refuse ne doit laisser aucune trace.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    indice = nodes.index(proposeur)

    honnete = proposeur.propose_block(timestamp=1_700_000_005)
    falsifie = _resigne(
        replace(honnete, state_root=b"\x11" * 32),
        ml_dsa,
        validator_keypairs[indice],
    )

    receveur = next(n for n in nodes if n is not proposeur)
    hauteur_avant = receveur.height
    etat_avant = receveur._state_replayer.state_root

    with pytest.raises(NodeError):
        receveur.receive_block(falsifie)

    assert receveur.height == hauteur_avant
    assert receveur._state_replayer.state_root == etat_avant


def test_un_bloc_a_racine_falsifiee_n_est_pas_rediffuse(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Un bloc invalide ne doit jamais etre relaye : le propager avant de
    s'apercevoir qu'il est faux contaminerait tout le reseau.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    indice = nodes.index(proposeur)

    honnete = proposeur.propose_block(timestamp=1_700_000_005)
    falsifie = _resigne(
        replace(honnete, state_root=b"\x22" * 32),
        ml_dsa,
        validator_keypairs[indice],
    )

    receveur = next(n for n in nodes if n is not proposeur)

    # Espion pose sur le transport : on veut constater qu'aucune
    # rediffusion n'a lieu, pas le supposer.
    diffuses = []
    receveur._p2p.broadcast_block = diffuses.append

    with pytest.raises(NodeError):
        receveur.receive_block(falsifie)

    assert diffuses == []


def test_un_bloc_depassant_le_plafond_de_gas_est_rejete(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    La faille de deni de service du point 2 (§3 de l'analyse) : un
    validateur autorise remplit un bloc de transactions couteuses. Sans
    plafond, chaque pair les executait toutes avant de conclure quoi
    que ce soit. Le refus doit intervenir sur le gas ANNONCE, donc
    avant la moindre execution.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    indice = nodes.index(proposeur)

    # Deux transactions annoncant chacune le plafond entier. La
    # premiere passe et consomme 21 000 ; la seconde en annonce
    # 30 000 000 alors qu'il n'en reste que 29 979 000 : le pool refuse
    # de la demarrer. Le refus porte donc bien sur le solde RESTANT.
    gourmandes = []
    for nonce in range(2):
        tx = Transaction.create(
            nonce=nonce,
            public_key=validator_keypairs[indice].public_key,
            recipient=RECIPIENT,
            value=0,
            gas_limit=BLOCK_GAS_LIMIT,
            gas_price=0,
            data=b"",
        )
        gourmandes.append(
            tx.with_signature(
                ml_dsa.sign(tx.signing_hash, validator_keypairs[indice].secret_key)
            )
        )

    honnete = proposeur.propose_block(timestamp=1_700_000_005)
    trop_gros = _resigne(
        replace(honnete, transactions=tuple(gourmandes)),
        ml_dsa,
        validator_keypairs[indice],
    )

    receveur = next(n for n in nodes if n is not proposeur)

    with pytest.raises(NodeError, match="state verification failed"):
        receveur.receive_block(trop_gros)

    # Le refus ne doit laisser aucune trace : ni bloc, ni etat avance.
    assert receveur.height == 0
    assert receveur._state_replayer.applied_height == 0


def test_le_producteur_ne_fabrique_pas_de_bloc_hors_plafond(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Les deux corrections doivent tenir ENSEMBLE. Le mempool contient
    bien plus de gas annonce qu'un bloc n'en peut porter ; le
    producteur doit filtrer avec la meme regle que le receveur.

    Sans ce filtrage, propose_block construirait un bloc que
    _accept_block -- le sien comme celui de ses pairs -- rejetterait :
    un noeud honnete deviendrait incapable de produire.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))

    # 40 transactions a 1 000 000 de gas annonce = 40 M > 30 M.
    emetteur = ml_dsa.generate_keypair()
    for nonce in range(40):
        tx = Transaction.create(
            nonce=nonce,
            public_key=emetteur.public_key,
            recipient=RECIPIENT,
            value=0,
            gas_limit=1_000_000,
            gas_price=0,
            data=b"",
        )
        proposeur.receive_transaction(
            tx.with_signature(ml_dsa.sign(tx.signing_hash, emetteur.secret_key))
        )

    bloc = proposeur.propose_block(timestamp=1_700_000_005)

    # Le bloc est produit, et il tient dans le plafond.
    assert sum(t.gas_limit for t in bloc.transactions) <= BLOCK_GAS_LIMIT
    assert len(bloc.transactions) < 40, "aucun filtrage n'a eu lieu"

    # Et surtout : ses pairs l'acceptent.
    receveur = next(n for n in nodes if n is not proposeur)
    receveur.receive_block(bloc)
    assert receveur.height == 1


def test_les_transactions_ecartees_restent_dans_le_mempool(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Une transaction trop grosse pour le bloc courant est differee, pas
    perdue : elle doit rester disponible pour un bloc ulterieur.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))

    emetteur = ml_dsa.generate_keypair()
    for nonce in range(40):
        tx = Transaction.create(
            nonce=nonce,
            public_key=emetteur.public_key,
            recipient=RECIPIENT,
            value=0,
            gas_limit=1_000_000,
            gas_price=0,
            data=b"",
        )
        proposeur.receive_transaction(
            tx.with_signature(ml_dsa.sign(tx.signing_hash, emetteur.secret_key))
        )

    bloc = proposeur.propose_block(timestamp=1_700_000_005)
    incluses = {t.tx_id for t in bloc.transactions}

    restantes = proposeur._mempool.get_pending()
    assert restantes, "les transactions differees ont disparu du mempool"
    assert all(t.tx_id not in incluses for t in restantes)


def test_un_bloc_honnete_reste_accepte(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Garde-fou : la verification ne doit pas rejeter les blocs valides.
    Sans ce test, un refus systematique passerait pour un succes.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    proposeur._state_replayer.state.set_balance(validator_addresses[0], 10**18)
    proposeur._state_replayer.state.commit()
    proposeur._mempool.add_transaction(
        make_signed_tx(ml_dsa, validator_keypairs[0], nonce=0)
    )

    bloc = proposeur.propose_block(timestamp=1_700_000_005)

    for receveur in nodes:
        if receveur is proposeur:
            continue
        receveur._state_replayer.state.set_balance(
            validator_addresses[0], 10**18
        )
        receveur._state_replayer.state.commit()
        receveur.receive_block(bloc)
        assert receveur.height == 1


def test_l_etat_avance_apres_acceptation(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    L'etat du receveur doit suivre la chaine, et coincider avec celui
    du proposeur : c'est la convergence recherchee (critere n.12).
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))
    bloc = proposeur.propose_block(timestamp=1_700_000_005)

    receveur = next(n for n in nodes if n is not proposeur)
    assert receveur._state_replayer.applied_height == 0

    receveur.receive_block(bloc)

    assert receveur._state_replayer.applied_height == 1
    assert (
        receveur._state_replayer.state_root
        == proposeur._state_replayer.state_root
    )


def test_le_bloc_de_genese_ne_passe_pas_par_la_verification(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    Exigence explicite : le genese ne doit PAS etre traite par un cas
    particulier dans le code de verification, mais ne jamais l'atteindre.

    Il est installe directement par Blockchain, donc _accept_block ne le
    voit jamais. On le prouve : un noeud neuf a bien son genese en
    chaine, alors qu'aucun bloc n'a ete accepte par le pipeline.
    """
    node = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0
    )

    assert node.height == 0
    assert node._blockchain.genesis_block is not None
    assert node._blockchain.genesis_block.state_root == EMPTY_STATE_ROOT
    # Le genese est applique a l'etat par le rattrapage initial, pas
    # par une verification de racine.
    assert node._state_replayer.applied_height == 0


def test_le_proposeur_verifie_son_propre_bloc(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    propose_block passe par _accept_block : le producteur se soumet
    donc a sa propre verification. Un bug de calcul cote producteur est
    ainsi detecte chez lui, avant diffusion, et non chez ses pairs.
    """
    nodes = [
        make_node(tmp_path, ml_dsa, validator_keypairs, validator_addresses, i)
        for i in range(3)
    ]
    proposeur = next(n for n in nodes if n._consensus.is_local_node_turn(1))

    bloc = proposeur.propose_block(timestamp=1_700_000_005)

    assert proposeur.height == 1
    assert proposeur._state_replayer.applied_height == 1
    assert bloc.state_root == proposeur._state_replayer.state_root

# ---------------------------------------------------------------------
# Liveness: changement de round apres indisponibilite du proposeur
# ---------------------------------------------------------------------


def test_un_proposeur_indisponible_est_remplace_apres_timeout(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    A la hauteur 1, le validateur d'index 1 est le proposeur du round 0.
    S'il est indisponible, les noeuds actifs passent au round 1 et le
    validateur d'index 2 produit le bloc a la MEME hauteur.
    """
    node0 = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0
    )
    node2 = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 2
    )

    transaction = make_signed_tx(ml_dsa, validator_keypairs[0], nonce=0)
    node0.receive_transaction(transaction)
    node2.receive_transaction(transaction)

    assert node0.current_round(1) == 0
    assert node2.current_round(1) == 0
    assert not node0._consensus.is_local_node_turn(1, node0.current_round(1))
    assert not node2._consensus.is_local_node_turn(1, node2.current_round(1))

    # Le premier appel confirme l'instant de reference ; le second
    # simule l'expiration du timeout sans faire attendre le test.
    base = time.monotonic()
    assert not node0.advance_round_if_timed_out(1, 1.0, now=base)
    assert not node2.advance_round_if_timed_out(1, 1.0, now=base)
    assert node0.advance_round_if_timed_out(1, 1.0, now=base + 1.1)
    assert node2.advance_round_if_timed_out(1, 1.0, now=base + 1.1)

    assert node2.current_round(1) == 1
    assert node2._consensus.is_local_node_turn(1, 1)

    block = node2.propose_block(timestamp=1_700_000_020)
    assert block.height == 1
    assert block.round == 1

    node0.receive_block(block)
    assert node0.height == node2.height == 1
    assert node0.tip_hash == node2.tip_hash
    assert node0.mempool_size == node2.mempool_size == 0


def test_aucun_timeout_n_est_arme_avec_un_mempool_vide(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """La production a la demande reste vraie sans transaction."""
    node = make_node(
        tmp_path, ml_dsa, validator_keypairs, validator_addresses, 0
    )

    assert not node.advance_round_if_timed_out(1, 0.1, now=100.0)
    assert not node.advance_round_if_timed_out(1, 0.1, now=100.1)
    assert node.current_round(1) == 0
    assert node.height == 0
