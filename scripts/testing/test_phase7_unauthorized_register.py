#!/usr/bin/env python3
"""Simulation en lecture seule d'un registerRecord sans consentement.

Le script recharge l'état final de la phase 7, puis exécute localement sur une
copie de cet état une tentative registerRecord émise par le validateur local.
Ce compte n'est ni le contrôleur du patient ni un bénéficiaire autorisé.

Les bytes32 patientId et scope sont extraits de la transaction v2 déjà présente
dans le bloc 6. Cela évite toute ambiguïté de remplissage ABI (octets nuls ou
caractères de remplissage) et garantit que le test cible exactement le patient
et la portée du scénario validé.

La transaction n'est ni signée ni diffusée et aucun bloc n'est produit. Le but
est de vérifier le contrôle Solidity sans modifier la chaîne convergée.

Exécution depuis la racine du dépôt :

    source .venv/bin/activate
    python3 scripts/testing/test_phase7_unauthorized_register.py --node node1
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from eth_utils import keccak

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from src.blockchain.blockchain import Blockchain
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.crypto.address import hex_to_address, public_key_to_address
from src.evm.abi import encode_function_call
from src.evm.executor import EVMExecutor
from src.evm.replay import StateReplayer
from src.node.config import NodeConfig


CONTRACT_ADDRESS = "0x368108079fe315817cde85b3ab02bd70d7024c0f"
V2_TX_ID = "6e544a1d9d1998e575ab3f2cf4f69d402029b43c7d5ae0ba9ab7ee8cdd4e96f0"
NEGATIVE_RECORD_ID = b"phase7-record-negative-001".ljust(32, b"_")
UNAUTHORIZED_ERROR = keccak(
    text="UnauthorizedRecordRegistration(bytes32,address,bytes32)"
)[:4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--node",
        required=True,
        choices=("node1", "node2", "node3"),
    )
    parser.add_argument(
        "--contract",
        default=CONTRACT_ADDRESS,
    )
    return parser.parse_args()


def extract_v2_arguments(chain: Blockchain) -> tuple[bytes, bytes, bytes, bytes]:
    """Retourne patientId, CID, hash et scope exactement comme dans tx v2."""
    block = chain.get_block(6)
    if block is None:
        raise RuntimeError("bloc 6 absent")

    transaction = next(
        (tx for tx in block.transactions if tx.tx_id.hex() == V2_TX_ID),
        None,
    )
    if transaction is None:
        raise RuntimeError("transaction registerRecord v2 absente du bloc 6")

    data = transaction.data
    if len(data) < 164:
        raise RuntimeError("calldata v2 trop courte")

    patient_id = data[36:68]
    cid_offset = int.from_bytes(data[68:100], "big")
    encrypted_hash = data[100:132]
    scope = data[132:164]

    cid_length_pos = 4 + cid_offset
    cid_length = int.from_bytes(
        data[cid_length_pos:cid_length_pos + 32],
        "big",
    )
    cid_start = cid_length_pos + 32
    cid = data[cid_start:cid_start + cid_length]

    return patient_id, cid, encrypted_hash, scope


def clean_bytes32(value: bytes) -> str:
    return value.rstrip(b"\x00_").decode("ascii", errors="replace")


def main() -> int:
    args = parse_args()
    config = NodeConfig.from_file(
        REPO_ROOT / "config" / "nodes" / args.node / "node.yaml"
    )
    storage = ChainStorage(config.data_dir)
    chain = Blockchain.load(storage)
    replayer = StateReplayer(storage)
    replayer.sync_to(chain.height)

    latest = chain.get_latest_block()
    contract = hex_to_address(args.contract)
    patient_id, cid, encrypted_hash, scope = extract_v2_arguments(chain)

    public_key = (
        config.validator_key_dir / "validator_public_key.bin"
    ).read_bytes()
    outsider = public_key_to_address(public_key)

    state = replayer.state.at_root(replayer.state_root)
    state.set_block_context(
        block_number=latest.height,
        timestamp=latest.timestamp,
        coinbase=latest.validator,
    )

    call = Transaction.create(
        nonce=state.get_nonce(outsider),
        public_key=public_key,
        recipient=contract,
        value=0,
        gas_limit=1_000_000,
        gas_price=0,
        data=encode_function_call(
            "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
            [NEGATIVE_RECORD_ID, patient_id, cid, encrypted_hash, scope],
        ),
    )

    receipt = EVMExecutor(state).execute_transaction(call)

    print(f"node           : {args.node}")
    print(f"height         : {chain.height}")
    print(f"state_root     : {replayer.state_root.hex()}")
    print(f"outsider       : 0x{outsider.hex()}")
    print(f"recordId       : {clean_bytes32(NEGATIVE_RECORD_ID)}")
    print(f"patientId      : {clean_bytes32(patient_id)}")
    print(f"scope          : {clean_bytes32(scope)}")
    print(f"receipt.status : {receipt.status}")
    print(f"receipt.error  : {receipt.error}")
    print(f"revert_data   : 0x{receipt.output.hex()}")

    if receipt.is_success:
        raise RuntimeError(
            "ERREUR : registerRecord a réussi alors que le compte est sans consentement"
        )

    if not receipt.output.startswith(UNAUTHORIZED_ERROR):
        raise RuntimeError(
            "ERREUR : le revert n'est pas UnauthorizedRecordRegistration"
        )

    print("RESULT         : accès sans consentement REJETÉ")
    print("broadcast      : non (simulation locale uniquement)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
