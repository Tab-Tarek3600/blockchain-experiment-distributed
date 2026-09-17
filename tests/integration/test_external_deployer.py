"""Validation du déploiement depuis un processus externe au validateur.

Le client de déploiement utilise uniquement SocketP2P : il ne construit pas de
Node et ne possède aucune clé secrète de validateur. Les trois nœuds locaux
restent le vrai pipeline de production et d'acceptation des blocs.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from src.evm.deployer import DeploymentClient, write_manifest
from src.node.node import NodeError

from tests.integration.test_medical_contracts import (
    ARTIFACTS,
    BASE_TIMESTAMP,
    medical_network,
    ml_dsa,
    validator_keypairs,
)

pytestmark = pytest.mark.integration


def test_external_client_deploys_the_three_medical_contracts(
    medical_network,
    tmp_path,
):
    nodes, transports, _validator_keys, _validator_addresses = medical_network
    client = DeploymentClient(
        targets=[(node._config.host, node._config.port) for node in nodes],
        key_dir=tmp_path / "deployment-key",
        artifact_dir=ARTIFACTS,
        timeout=30.0,
    )

    stopping = threading.Event()

    def produce_pending_transactions() -> None:
        """Produit le prochain bloc uniquement lorsqu'un tx est propagé."""
        while not stopping.is_set():
            height = nodes[0].height
            if all(node.height == height for node in nodes):
                if all(node.mempool_size > 0 for node in nodes):
                    proposer = nodes[(height + 1) % 3]
                    try:
                        proposer.propose_block(timestamp=BASE_TIMESTAMP + height + 1)
                    except NodeError:
                        # La propagation est asynchrone ; le tour suivant
                        # réessaiera après convergence des mempools.
                        pass
            stopping.wait(0.02)

    client.start()
    producer = threading.Thread(
        target=produce_pending_transactions,
        name="test-block-producer",
        daemon=True,
    )
    producer.start()
    try:
        client.wait_until_connected()
        deployments = client.deploy_medical_system()
    finally:
        stopping.set()
        producer.join(timeout=2.0)
        client.close()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if len({node.height for node in nodes}) == 1 and len(
            {node._state_replayer.state_root for node in nodes}
        ) == 1:
            break
        time.sleep(0.05)
    assert len({node.height for node in nodes}) == 1
    assert len({node._state_replayer.state_root for node in nodes}) == 1

    assert [item["contract"] for item in deployments] == [
        "PatientRegistry",
        "ConsentManager",
        "MedicalRecordRegistry",
    ]
    assert [item["nonce"] for item in deployments] == [0, 1, 2]
    assert len({item["address"] for item in deployments}) == 3
    assert all(item["block_height"] > 0 for item in deployments)
    assert all(item["state_root"].startswith("0x") for item in deployments)

    for node in nodes:
        for item in deployments:
            address = bytes.fromhex(item["address"][2:])
            assert node._state_replayer.state.get_code(address)

    manifest_path = tmp_path / "medical-deployment.json"
    write_manifest(
        manifest_path,
        sender=client.sender,
        targets=[(node._config.host, node._config.port) for node in nodes],
        deployments=deployments,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["deployer_address"] == "0x" + client.sender.hex()
    assert len(manifest["contracts"]) == 3

    # La fermeture des transports ne modifie pas les fichiers de chaîne :
    # les trois nœuds ont déjà persisté les blocs de déploiement.
    for transport in transports:
        transport.stop()
