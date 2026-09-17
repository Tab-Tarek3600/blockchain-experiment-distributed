"""Client de déploiement des contrats médicaux par transaction TCP.

Ce module est volontairement séparé de ``Node`` : un validateur ne porte pas
la clé secrète de l'opérateur qui déploie les contrats. Le client détient une
paire ML-DSA propre au déploiement, ouvre une connexion ``SocketP2P`` vers un
nœud, puis diffuse des transactions de création signées.

Le client ne déclare pas de reçus EVM persistés : ``Node`` n'en expose pas.
Il attend donc l'inclusion de chaque transaction dans un bloc reçu par le
transport et conserve les preuves disponibles dans ce bloc (nonce, hash de
transaction, hauteur, hash et racine d'état du bloc). Les adresses de contrats
sont calculées avec la formule CREATE déterministe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

from src.blockchain.block import Block
from src.blockchain.transaction import Transaction
from src.crypto.address import public_key_to_address
from src.crypto.ml_dsa import MLDSA, MLDSAKeyPair
from src.evm.abi import encode_function_call
from src.evm.addresses import ZERO_ADDRESS, generate_contract_address
from src.node.socket_p2p import SocketP2P, SocketP2PError

logger = logging.getLogger("evm.deployer")

DEPLOYMENT_PUBLIC_KEY_FILENAME = "deployment_public_key.bin"
DEPLOYMENT_SECRET_KEY_FILENAME = "deployment_secret_key.bin"
DEPLOYMENT_GAS_LIMIT = 5_000_000


class DeploymentError(Exception):
    """Erreur de préparation, transport ou inclusion d'un déploiement."""


def load_or_generate_deployment_keypair(
    key_dir: str | Path,
    ml_dsa: Optional[MLDSA] = None,
) -> MLDSAKeyPair:
    """Charge ou crée une paire de déploiement, sans jamais afficher le secret.

    Les noms de fichiers sont distincts de ceux des validateurs afin qu'une
    clé d'opérateur ne puisse pas être confondue avec une identité PoA.
    """
    directory = Path(key_dir)
    directory.mkdir(parents=True, exist_ok=True)
    public_path = directory / DEPLOYMENT_PUBLIC_KEY_FILENAME
    secret_path = directory / DEPLOYMENT_SECRET_KEY_FILENAME

    public_exists = public_path.exists()
    secret_exists = secret_path.exists()
    if public_exists != secret_exists:
        raise DeploymentError(
            f"paire de déploiement incomplète dans {directory}: "
            "les deux fichiers public/secret sont requis"
        )

    signer = ml_dsa or MLDSA()
    if public_exists:
        public_key = public_path.read_bytes()
        secret_key = secret_path.read_bytes()
        if not public_key or not secret_key:
            raise DeploymentError(f"paire de déploiement vide dans {directory}")
        return MLDSAKeyPair(public_key=public_key, secret_key=secret_key)

    keypair = signer.generate_keypair()
    public_path.write_bytes(keypair.public_key)
    secret_path.write_bytes(keypair.secret_key)
    try:
        os.chmod(secret_path, 0o600)
    except OSError:
        # Le contrôle de permission peut être indisponible sur certains
        # systèmes de test ; le contenu ne quitte de toute façon pas ce
        # répertoire local.
        logger.debug("cannot chmod deployment secret %s", secret_path)
    return keypair


def _verified_artifact(artifact_dir: Path, contract_name: str) -> tuple[dict, str]:
    """Charge un artefact et retourne son JSON ainsi que son SHA-256 vérifié."""
    artifact_path = artifact_dir / f"{contract_name}.json"
    sums_path = artifact_dir / "SHA256SUMS"
    if not artifact_path.exists():
        raise DeploymentError(f"artefact absent: {artifact_path}")
    if not sums_path.exists():
        raise DeploymentError(f"fichier de sommes absent: {sums_path}")

    expected: Optional[str] = None
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) == 2 and Path(fields[1]).name == artifact_path.name:
            expected = fields[0]
            break
    if expected is None:
        raise DeploymentError(
            f"aucune somme SHA-256 pour {artifact_path.name} dans {sums_path}"
        )

    actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if actual != expected:
        raise DeploymentError(
            f"SHA-256 incorrect pour {artifact_path}: attendu {expected}, "
            f"obtenu {actual}"
        )

    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DeploymentError(f"artefact JSON invalide: {artifact_path}") from exc

    bytecode = artifact.get("bytecode")
    if not isinstance(bytecode, str) or not bytecode.startswith("0x"):
        raise DeploymentError(f"bytecode absent ou invalide dans {artifact_path}")
    if len(bytecode) <= 2 or len(bytecode[2:]) % 2:
        raise DeploymentError(f"bytecode hex invalide dans {artifact_path}")
    return artifact, actual


def _constructor_data(types: str, values: Iterable[object]) -> bytes:
    if not types:
        return b""
    return encode_function_call(f"constructor({types})", list(values))[4:]


def _deployment_data(
    artifact: dict,
    constructor_types: str = "",
    constructor_values: Iterable[object] = (),
) -> bytes:
    bytecode = bytes.fromhex(artifact["bytecode"][2:])
    return bytecode + _constructor_data(constructor_types, constructor_values)


class DeploymentClient:
    """Diffuseur externe de transactions de création via ``SocketP2P``."""

    def __init__(
        self,
        *,
        targets: Iterable[tuple[str, int]],
        key_dir: str | Path,
        artifact_dir: str | Path,
        local_node_id: str = "deployment-client",
        timeout: float = 120.0,
        starting_nonce: int = 0,
        ml_dsa: Optional[MLDSA] = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if starting_nonce < 0:
            raise ValueError("starting_nonce must be >= 0")

        self._ml_dsa = ml_dsa or MLDSA()
        self._keypair = load_or_generate_deployment_keypair(key_dir, self._ml_dsa)
        self._sender = public_key_to_address(self._keypair.public_key)
        self._artifact_dir = Path(artifact_dir)
        self._targets = tuple((host, int(port)) for host, port in targets)
        if not self._targets:
            raise ValueError("at least one deployment target is required")
        self._timeout = timeout
        self._next_nonce = starting_nonce
        self._blocks: list[Block] = []
        self._condition = threading.Condition()
        self._transport = SocketP2P(
            host="127.0.0.1",
            port=0,
            peers=self._targets,
            node_id=local_node_id,
            dial_interval=0.1,
        )
        self._transport.register_block_handler(self._on_block)

    @property
    def sender(self) -> bytes:
        """Adresse EVM du compte de déploiement."""
        return self._sender

    def start(self) -> None:
        """Démarre le transport TCP du client."""
        try:
            self._transport.start()
        except SocketP2PError as exc:
            raise DeploymentError(f"impossible de démarrer le transport: {exc}") from exc

    def close(self) -> None:
        """Arrête proprement le transport TCP du client."""
        self._transport.stop()

    def wait_until_connected(self) -> None:
        """Attend que le client ait un lien vers chacun des nœuds cibles."""
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if self._transport.connection_count() >= len(self._targets):
                return
            time.sleep(0.05)
        raise DeploymentError(
            "le client de déploiement n'a pas rejoint tous les nœuds cibles "
            f"({self._transport.connection_count()}/{len(self._targets)})"
        )

    def deploy_medical_system(self) -> list[dict[str, object]]:
        """Déploie les trois contrats médicaux dans l'ordre dépendant."""
        patient_artifact, patient_hash = _verified_artifact(
            self._artifact_dir, "PatientRegistry"
        )
        consent_artifact, consent_hash = _verified_artifact(
            self._artifact_dir, "ConsentManager"
        )
        records_artifact, records_hash = _verified_artifact(
            self._artifact_dir, "MedicalRecordRegistry"
        )

        patient = self._deploy_one(
            "PatientRegistry",
            patient_artifact,
            patient_hash,
        )
        consent = self._deploy_one(
            "ConsentManager",
            consent_artifact,
            consent_hash,
            constructor_types="address",
            constructor_values=[patient["contract_address_bytes"]],
        )
        records = self._deploy_one(
            "MedicalRecordRegistry",
            records_artifact,
            records_hash,
            constructor_types="address,address",
            constructor_values=[
                patient["contract_address_bytes"],
                consent["contract_address_bytes"],
            ],
        )

        # Les bytes internes ne doivent pas apparaître dans le manifeste
        # public ; ils ne servent qu'à encoder les constructeurs suivants.
        for item in (patient, consent, records):
            item.pop("contract_address_bytes", None)
        return [patient, consent, records]

    def _deploy_one(
        self,
        contract_name: str,
        artifact: dict,
        artifact_sha256: str,
        *,
        constructor_types: str = "",
        constructor_values: Iterable[object] = (),
    ) -> dict[str, object]:
        nonce = self._next_nonce
        unsigned = Transaction.create(
            nonce=nonce,
            public_key=self._keypair.public_key,
            recipient=ZERO_ADDRESS,
            value=0,
            gas_limit=DEPLOYMENT_GAS_LIMIT,
            gas_price=0,
            data=_deployment_data(artifact, constructor_types, constructor_values),
        )
        transaction = unsigned.with_signature(
            self._ml_dsa.sign(unsigned.signing_hash, self._keypair.secret_key)
        )
        self._next_nonce += 1

        self._transport.broadcast_transaction(transaction)
        included = self._wait_for_transaction(transaction.tx_id)
        contract_address = generate_contract_address(self._sender, nonce)
        return {
            "contract": contract_name,
            "address": "0x" + contract_address.hex(),
            "contract_address_bytes": contract_address,
            "nonce": nonce,
            "transaction_hash": "0x" + transaction.tx_id.hex(),
            "block_height": included.height,
            "block_hash": "0x" + included.block_hash.hex(),
            "state_root": "0x" + included.state_root.hex(),
            "artifact_sha256": artifact_sha256,
        }

    def _wait_for_transaction(self, transaction_id: bytes) -> Block:
        deadline = time.monotonic() + self._timeout
        with self._condition:
            while True:
                for block in self._blocks:
                    if any(tx.tx_id == transaction_id for tx in block.transactions):
                        return block
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DeploymentError(
                        f"transaction {transaction_id.hex()} non incluse dans le délai"
                    )
                self._condition.wait(timeout=remaining)

    def _on_block(self, block: Block) -> None:
        with self._condition:
            self._blocks.append(block)
            self._condition.notify_all()


def write_manifest(
    path: str | Path,
    *,
    sender: bytes,
    targets: Iterable[tuple[str, int]],
    deployments: list[dict[str, object]],
) -> None:
    """Écrit un manifeste public et atomique des contrats déployés."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "deployer_address": "0x" + sender.hex(),
        "targets": [
            {"host": host, "port": port} for host, port in targets
        ],
        "contracts": deployments,
    }
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.evm.deployer",
        description="Déploie les trois contrats médicaux via SocketP2P.",
    )
    parser.add_argument(
        "--target-host",
        action="append",
        required=True,
        help="adresse d'un validateur cible ; répéter pour les trois nœuds",
    )
    parser.add_argument("--target-port", default=9001, type=int)
    parser.add_argument("--key-dir", required=True, type=Path)
    parser.add_argument("--artifact-dir", default=Path("contracts/artifacts"), type=Path)
    parser.add_argument("--manifest", default=Path("medical-deployment.json"), type=Path)
    parser.add_argument("--timeout", default=120.0, type=float)
    parser.add_argument("--starting-nonce", default=0, type=int)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    )
    client: Optional[DeploymentClient] = None
    targets = [(host, args.target_port) for host in args.target_host]
    try:
        client = DeploymentClient(
            targets=targets,
            key_dir=args.key_dir,
            artifact_dir=args.artifact_dir,
            timeout=args.timeout,
            starting_nonce=args.starting_nonce,
        )
        client.start()
        client.wait_until_connected()
        deployments = client.deploy_medical_system()
        write_manifest(
            args.manifest,
            sender=client.sender,
            targets=targets,
            deployments=deployments,
        )
        print(f"adresse de déploiement : 0x{client.sender.hex()}")
        for item in deployments:
            print(
                f"{item['contract']}: {item['address']} "
                f"h={item['block_height']} tx={item['transaction_hash']}"
            )
        print(f"manifeste : {args.manifest}")
        return 0
    except (DeploymentError, ValueError, OSError) as exc:
        logger.error("déploiement impossible: %s", exc)
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
