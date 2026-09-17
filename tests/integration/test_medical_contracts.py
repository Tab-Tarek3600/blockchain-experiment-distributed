"""Scénario end-to-end local des contrats médicaux.

Les trois nœuds sont de vrais ``Node`` reliés par ``SocketP2P`` et tournent
sur la machine de développement. Le test exerce les artefacts Solidity dans
le chemin complet : transaction ML-DSA, mempool, bloc PoA, validation par les
pairs, rejeu EVM et persistance ChainStorage.

Ce test ne valide pas encore la connectivité entre VMs, IPFS ou une API
médicale. Il valide la partie blockchain locale avant le déploiement distant.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
from pathlib import Path

import pytest
from eth_utils import keccak

from src.blockchain.transaction import Transaction
from src.crypto.address import public_key_to_address
from src.crypto.ml_dsa import MLDSA
from src.evm.abi import decode_function_output, encode_function_call
from src.evm.addresses import ZERO_ADDRESS, generate_contract_address
from src.evm.executor import EVMExecutor
from src.evm.state import EVMState
from src.node.config import NodeConfig
from src.node.node import Node
from src.node.p2p import NullP2P
from src.node.socket_p2p import SocketP2P

pytestmark = pytest.mark.integration

ARTIFACTS = Path(__file__).resolve().parents[2] / "contracts" / "artifacts"
BASE_TIMESTAMP = 1_700_000_000
DEPLOY_GAS = 5_000_000
CALL_GAS = 1_000_000


def _bytes32(label: str) -> bytes:
    value = label.encode("ascii")
    if len(value) > 32:
        raise ValueError("test identifier is longer than bytes32")
    return value.ljust(32, b"_")


def _artifact(name: str) -> dict:
    with (ARTIFACTS / f"{name}.json").open(encoding="utf-8") as stream:
        return json.load(stream)


def _constructor(types: str, values: list[object]) -> bytes:
    """Encode les arguments ABI d'un constructeur, sans selecteur."""
    return encode_function_call(f"constructor({types})", values)[4:]


def _event_topic(signature: str) -> bytes:
    return keccak(text=signature)


def _address_topic(address: bytes) -> bytes:
    return b"\x00" * 12 + address


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until(predicate, timeout: float = 20.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _assert_artifacts_verified() -> None:
    """Refuse le scénario si un artefact déployé n'est pas celui vérifié."""
    sums_path = ARTIFACTS / "SHA256SUMS"
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        expected, relative_path = line.split(maxsplit=1)
        path = ARTIFACTS.parents[1] / relative_path
        assert path.exists(), f"artefact absent: {path}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, f"SHA-256 incorrect pour {path}"


@pytest.fixture(scope="module")
def ml_dsa():
    return MLDSA()


@pytest.fixture(scope="module")
def validator_keypairs(ml_dsa):
    return [ml_dsa.generate_keypair() for _ in range(3)]


@pytest.fixture
def medical_network(tmp_path, ml_dsa, validator_keypairs):
    """Trois vrais nœuds locaux, avec genesis commun et TCP réel."""
    validator_addresses = [
        public_key_to_address(keypair.public_key)
        for keypair in validator_keypairs
    ]
    ports = [_free_port() for _ in range(3)]
    nodes: list[Node] = []
    transports: list[SocketP2P] = []

    for index, keypair in enumerate(validator_keypairs):
        key_dir = tmp_path / f"keys{index}"
        key_dir.mkdir()
        (key_dir / "validator_public_key.bin").write_bytes(keypair.public_key)
        (key_dir / "validator_secret_key.bin").write_bytes(keypair.secret_key)

        peers = [
            {"host": "127.0.0.1", "port": ports[other]}
            for other in range(3)
            if other != index
        ]
        config = NodeConfig.from_dict(
            {
                "node_id": f"medical-node{index + 1}",
                "node_name": f"Medical Node {index + 1}",
                "data_dir": str(tmp_path / f"data{index}"),
                "host": "127.0.0.1",
                "port": ports[index],
                "peers": peers,
                "validator_key_dir": str(key_dir),
                "authorized_validators": [
                    address.hex() for address in validator_addresses
                ],
                "genesis_validator_public_key": validator_keypairs[0]
                .public_key.hex(),
                "genesis_timestamp": BASE_TIMESTAMP,
                "mempool_max_size": 100,
                "block_interval_seconds": 1.0,
            }
        )
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

    assert _wait_until(
        lambda: all(transport.connection_count() == 2 for transport in transports)
    ), "le triangle TCP médical ne s'est pas formé"
    assert len({node.genesis_hash for node in nodes}) == 1

    yield nodes, transports, validator_keypairs, validator_addresses

    for transport in transports:
        transport.stop()


def _signed_transaction(
    ml_dsa: MLDSA,
    keypair,
    nonce: int,
    recipient: bytes,
    data: bytes,
    *,
    gas_limit: int = CALL_GAS,
) -> Transaction:
    transaction = Transaction.create(
        nonce=nonce,
        public_key=keypair.public_key,
        recipient=recipient,
        value=0,
        gas_limit=gas_limit,
        gas_price=0,
        data=data,
    )
    return transaction.with_signature(
        ml_dsa.sign(transaction.signing_hash, keypair.secret_key)
    )


def _include_on_all_nodes(nodes: list[Node], transaction: Transaction):
    """Diffuse une transaction puis la fait inclure par le proposeur attendu."""
    height = nodes[0].height + 1
    proposer = nodes[height % 3]
    nodes[0].receive_transaction(transaction)

    assert _wait_until(
        lambda: all(node._mempool.contains(transaction.tx_id) for node in nodes)
    ), f"transaction absente d'un mempool à la hauteur {height}"

    block = proposer.propose_block(timestamp=BASE_TIMESTAMP + height)
    assert block.height == height
    assert block.validator == proposer.local_address
    assert _wait_until(
        lambda: all(
            node.height == height
            and node._state_replayer.state_root == block.state_root
            for node in nodes
        )
    ), (
        f"les nœuds n'ont pas convergé à h={height}: "
        + str(
            [
                (node.height, node._state_replayer.applied_height)
                for node in nodes
            ]
        )
    )
    assert len({node.tip_hash for node in nodes}) == 1
    assert _wait_until(
        lambda: not any(node._mempool.contains(transaction.tx_id) for node in nodes)
    )
    return block


def _deploy_transaction_data(name: str, constructor_types: str = "", values=None):
    artifact = _artifact(name)
    arguments = (
        _constructor(constructor_types, values or []) if constructor_types else b""
    )
    return bytes.fromhex(artifact["bytecode"][2:]) + arguments


def _view_record(node: Node, ml_dsa: MLDSA, keypair, records: bytes, record_id: bytes):
    """Lit l'état final depuis une copie EVM, sans modifier le nœud."""
    state = node._state_replayer.state.at_root(node._state_replayer.state_root)
    nonce = state.get_nonce(public_key_to_address(keypair.public_key))
    transaction = _signed_transaction(
        ml_dsa,
        keypair,
        nonce,
        records,
        encode_function_call("getRecord(bytes32)", [record_id]),
    )
    receipt = EVMExecutor(state).execute_transaction(transaction)
    assert receipt.is_success, receipt.error
    return decode_function_output(
        ["bytes32", "bytes", "bytes32", "address", "uint256", "bool", "bytes32"],
        receipt.output,
    )


def _view_bool(
    node: Node,
    ml_dsa: MLDSA,
    keypair,
    recipient: bytes,
    signature: str,
    values: list[object],
) -> bool:
    state = node._state_replayer.state.at_root(node._state_replayer.state_root)
    state.set_block_context(
        block_number=node.height,
        timestamp=BASE_TIMESTAMP + node.height,
        coinbase=ZERO_ADDRESS,
    )
    sender = public_key_to_address(keypair.public_key)
    transaction = _signed_transaction(
        ml_dsa,
        keypair,
        state.get_nonce(sender),
        recipient,
        encode_function_call(signature, values),
    )
    receipt = EVMExecutor(state).execute_transaction(transaction)
    assert receipt.is_success, receipt.error
    return bool(decode_function_output(["bool"], receipt.output)[0])


def test_three_local_nodes_execute_the_complete_medical_workflow(
    medical_network,
    ml_dsa,
):
    """Déploiement, permissions, révocations, rejeu et redémarrage local."""
    _assert_artifacts_verified()
    nodes, transports, validator_keypairs, validator_addresses = medical_network

    controller_key = ml_dsa.generate_keypair()
    beneficiary_key = ml_dsa.generate_keypair()
    outsider_key = ml_dsa.generate_keypair()
    controller = public_key_to_address(controller_key.public_key)
    beneficiary = public_key_to_address(beneficiary_key.public_key)

    nonces = {controller: 0, beneficiary: 0, public_key_to_address(outsider_key.public_key): 0}

    def deploy(name: str, types: str = "", values=None):
        nonce = nonces[controller]
        nonces[controller] += 1
        transaction = _signed_transaction(
            ml_dsa,
            controller_key,
            nonce,
            ZERO_ADDRESS,
            _deploy_transaction_data(name, types, values),
            gas_limit=DEPLOY_GAS,
        )
        block = _include_on_all_nodes(nodes, transaction)
        return generate_contract_address(controller, nonce), block

    patient_registry, _ = deploy("PatientRegistry")
    consent_manager, _ = deploy("ConsentManager", "address", [patient_registry])
    medical_records, _ = deploy(
        "MedicalRecordRegistry",
        "address,address",
        [patient_registry, consent_manager],
    )

    for node in nodes:
        assert node._state_replayer.state.get_code(patient_registry)
        assert node._state_replayer.state.get_code(consent_manager)
        assert node._state_replayer.state.get_code(medical_records)

    patient_id = _bytes32("patient-e2e")
    valid_scope = _bytes32("scope-valid")
    revoked_scope = _bytes32("scope-revoked")
    record_unauthorized = _bytes32("record-unauthorized")
    record_valid = _bytes32("record-valid")
    record_expired = _bytes32("record-expired")
    record_revoked = _bytes32("record-revoked")

    def call(keypair, recipient, signature, values, *, gas_limit=CALL_GAS):
        sender = public_key_to_address(keypair.public_key)
        nonce = nonces[sender]
        nonces[sender] += 1
        return _include_on_all_nodes(
            nodes,
            _signed_transaction(
                ml_dsa,
                keypair,
                nonce,
                recipient,
                encode_function_call(signature, values),
                gas_limit=gas_limit,
            ),
        )

    call(controller_key, patient_registry, "registerPatient(bytes32)", [patient_id])

    # Consent valide aux hauteurs 6 et 7, puis expiration exactement à h=8.
    expires_at = BASE_TIMESTAMP + 8
    call(
        controller_key,
        consent_manager,
        "grantConsent(bytes32,address,bytes32,uint256)",
        [patient_id, beneficiary, valid_scope, expires_at],
    )

    cid = b"cid-encrypted-reference"
    encrypted_hash = _bytes32("encrypted-content-hash")

    # Aucun consentement pour outsider : l'appel revertit, mais le bloc
    # est accepté et le même recordId pourra être créé ensuite.
    call(
        outsider_key,
        medical_records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_unauthorized, patient_id, cid, encrypted_hash, valid_scope],
    )

    call(
        beneficiary_key,
        medical_records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_valid, patient_id, cid, encrypted_hash, valid_scope],
    )

    # À h=8, block.timestamp == expiresAt : l'expiration est stricte.
    call(
        beneficiary_key,
        medical_records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_expired, patient_id, cid, encrypted_hash, valid_scope],
    )

    # Le contrôleur peut enregistrer directement : succès prouvant que le
    # revert de l'appel expiré n'a pas laissé de dossier partiellement créé.
    call(
        controller_key,
        medical_records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_expired, patient_id, cid, encrypted_hash, valid_scope],
    )
    call(
        controller_key,
        medical_records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_unauthorized, patient_id, cid, encrypted_hash, valid_scope],
    )

    call(
        controller_key,
        consent_manager,
        "grantConsent(bytes32,address,bytes32,uint256)",
        [patient_id, beneficiary, revoked_scope, 0],
    )
    call(
        controller_key,
        consent_manager,
        "revokeConsent(bytes32,address,bytes32)",
        [patient_id, beneficiary, revoked_scope],
    )

    # Consent révoqué : le bénéficiaire échoue ; le contrôleur crée ensuite
    # le même recordId, ce qui prouve l'absence d'écriture du revert.
    call(
        beneficiary_key,
        medical_records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_revoked, patient_id, cid, encrypted_hash, revoked_scope],
    )
    final_block = call(
        controller_key,
        medical_records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_revoked, patient_id, cid, encrypted_hash, revoked_scope],
    )

    assert final_block.height == 14
    assert [node.height for node in nodes] == [14, 14, 14]
    assert len({node.genesis_hash for node in nodes}) == 1
    assert len({node.tip_hash for node in nodes}) == 1
    assert len({node._state_replayer.state_root for node in nodes}) == 1

    # La chaîne complète, et pas seulement son tip, est identique sur les
    # trois stockages. La liste vérifie aussi la rotation PoA h % 3.
    for height in range(15):
        blocks = [node._blockchain.get_block(height) for node in nodes]
        assert all(block is not None for block in blocks)
        assert len({block.block_hash for block in blocks}) == 1
        assert len({block.state_root for block in blocks}) == 1
        assert blocks[0].validator == validator_addresses[height % 3]

    # Les appels d'enregistrement ne transportent pas de donnée médicale :
    # leurs bytes ABI sont exactement l'ensemble (ID pseudonymisé, patient,
    # CID, hash chiffré, portée) prévu par le contrat.
    record_signature = "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)"
    record_selector = encode_function_call(
        record_signature,
        [record_valid, patient_id, cid, encrypted_hash, valid_scope],
    )[:4]
    allowed_record_data = {
        encode_function_call(
            record_signature,
            [record_id, patient_id, cid, encrypted_hash, scope],
        )
        for record_id, scope in (
            (record_unauthorized, valid_scope),
            (record_valid, valid_scope),
            (record_expired, valid_scope),
            (record_revoked, revoked_scope),
        )
    }
    record_transactions = [
        transaction
        for height in range(1, 15)
        for transaction in nodes[0]._blockchain.get_block(height).transactions
        if transaction.data[:4] == record_selector
    ]
    assert len(record_transactions) == 7
    assert all(transaction.data in allowed_record_data for transaction in record_transactions)

    expected_records = {
        record_valid: beneficiary,
        record_expired: controller,
        record_unauthorized: controller,
        record_revoked: controller,
    }
    for node in nodes:
        for record_id, registered_by in expected_records.items():
            patient, stored_cid, stored_hash, actual_by, _created, active, scope = _view_record(
                node, ml_dsa, controller_key, medical_records, record_id
            )
            assert patient == patient_id
            assert stored_cid == cid
            assert stored_hash == encrypted_hash
            assert actual_by == registered_by
            assert active is True
            assert scope in (valid_scope, revoked_scope)

        assert _view_bool(
            node,
            ml_dsa,
            beneficiary_key,
            consent_manager,
            "hasValidConsent(bytes32,address,bytes32)",
            [patient_id, beneficiary, valid_scope],
        ) is False
        assert _view_bool(
            node,
            ml_dsa,
            beneficiary_key,
            consent_manager,
            "hasValidConsent(bytes32,address,bytes32)",
            [patient_id, beneficiary, revoked_scope],
        ) is False

    # Les événements de la dernière transaction sont reproductibles depuis
    # le bloc accepté, même si les reçus ne sont pas une racine de consensus.
    last_node = nodes[0]
    previous = last_node._blockchain.get_block(final_block.height - 1)
    assert previous is not None
    replay_state = last_node._state_replayer.state.at_root(previous.state_root)
    replay = EVMExecutor(replay_state).execute_block(
        final_block.transactions,
        block_number=final_block.height,
        timestamp=final_block.timestamp,
        coinbase=final_block.validator,
    )
    assert replay.state_root == final_block.state_root
    receipt = replay.receipts[0]
    assert receipt.is_success
    assert receipt.logs[0].address == medical_records
    assert receipt.logs[0].topics[:4] == (
        _event_topic("RecordRegistered(bytes32,bytes32,address,bytes32,bytes32)"),
        record_revoked,
        patient_id,
        _address_topic(controller),
    )
    assert decode_function_output(["bytes32", "bytes32"], receipt.logs[0].data) == (
        encrypted_hash,
        revoked_scope,
    )

    # Redémarrage local : un nœud reconstruit son EVM uniquement depuis
    # ChainStorage et retrouve exactement la chaîne et la racine finale.
    for transport in transports:
        transport.stop()
    restarted = Node.from_config(
        nodes[0]._config,
        p2p=NullP2P(),
        ml_dsa=ml_dsa,
    )
    assert restarted.height == 14
    assert restarted.tip_hash == nodes[0].tip_hash
    assert restarted._state_replayer.state_root == nodes[0]._state_replayer.state_root
