#!/usr/bin/env python3
"""Lecture en lecture seule des dossiers synthétiques v1/v2 de la phase 7.

Le script recharge la chaîne locale depuis ChainStorage, rejoue l'état EVM,
puis exécute getRecord(bytes32) sur les deux transactions registerRecord déjà
confirmées. Il ne produit aucune transaction, ne modifie aucun bloc et ne lit
pas la clé secrète du validateur.

Exécution depuis la racine du dépôt :

    source .venv/bin/activate
    python3 scripts/testing/read_phase7_records.py --node node1
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Permet l'exécution depuis n'importe quel répertoire du dépôt.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from src.blockchain.blockchain import Blockchain
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.crypto.address import hex_to_address, public_key_to_address
from src.evm.abi import decode_function_output, encode_function_call
from src.evm.executor import EVMExecutor
from src.evm.replay import StateReplayer
from src.node.config import NodeConfig


CONTRACT_ADDRESS = "0x368108079fe315817cde85b3ab02bd70d7024c0f"

EXPECTED = {
    5: {
        "version": "v1",
        "tx": "4403be9bd7be8ed31e82c04703ac70affcbc11b48e934a8872b2d34a579fb2c1",
        "cid": "Qmekbq6kAtwWZDu2K7HSKMTbrYqngVNKQ4wAzGp1Ui6yMA",
        "hash": "e23583314041fda8336bd3637ceaef805379bd6866da11e31a561c490d41c4a4",
    },
    6: {
        "version": "v2",
        "tx": "6e544a1d9d1998e575ab3f2cf4f69d402029b43c7d5ae0ba9ab7ee8cdd4e96f0",
        "cid": "QmSeS5hq1tyujnbkeEErye1q4z4XHkGqLnG6CQatA5wkZJ",
        "hash": "995d6d9a210d7347a594d5c86963b4eebe9bdced575783fc2532a687d6e6bd89",
    },
}

EXPECTED_PATIENT = "phase7-patient-001"
EXPECTED_SCOPE = "phase7-test-scope"
EXPECTED_V2_RECORD = "phase7-record-v2-001"


def clean_bytes32(value: bytes) -> str:
    """Convertit un identifiant bytes32 ASCII rembourré en texte lisible."""
    return value.rstrip(b"\x00_").decode("ascii", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--node",
        required=True,
        choices=("node1", "node2", "node3"),
        help="nœud dont le ChainStorage doit être lu",
    )
    parser.add_argument(
        "--contract",
        default=CONTRACT_ADDRESS,
        help="adresse publique de MedicalRecordRegistry",
    )
    return parser.parse_args()


def decode_register_call(data: bytes) -> tuple[bytes, bytes, bytes, bytes, bytes]:
    """Extrait les cinq arguments de registerRecord depuis calldata ABI."""
    if len(data) < 164:
        raise RuntimeError("calldata registerRecord trop courte")

    record_id = data[4:36]
    patient_id = data[36:68]
    cid_offset = int.from_bytes(data[68:100], "big")
    encrypted_hash = data[100:132]
    scope = data[132:164]

    cid_length_pos = 4 + cid_offset
    if cid_length_pos + 32 > len(data):
        raise RuntimeError("offset CID ABI invalide")

    cid_length = int.from_bytes(
        data[cid_length_pos:cid_length_pos + 32],
        "big",
    )
    cid_start = cid_length_pos + 32
    cid = data[cid_start:cid_start + cid_length]

    if len(cid) != cid_length:
        raise RuntimeError("CID ABI tronqué")

    return record_id, patient_id, cid, encrypted_hash, scope


def read_record(
    replayer: StateReplayer,
    chain: Blockchain,
    contract: bytes,
    public_key: bytes,
    record_id: bytes,
):
    """Effectue un appel view local sur une copie de l'état final."""
    latest = chain.get_latest_block()
    state = replayer.state.at_root(replayer.state_root)
    state.set_block_context(
        block_number=latest.height,
        timestamp=latest.timestamp,
        coinbase=latest.validator,
    )

    caller = public_key_to_address(public_key)
    call = Transaction.create(
        nonce=state.get_nonce(caller),
        public_key=public_key,
        recipient=contract,
        value=0,
        gas_limit=1_000_000,
        gas_price=0,
        data=encode_function_call("getRecord(bytes32)", [record_id]),
    )

    receipt = EVMExecutor(state).execute_transaction(call)
    if not receipt.is_success:
        raise RuntimeError(f"getRecord a échoué : {receipt.error}")

    return decode_function_output(
        ["bytes32", "bytes", "bytes32", "address", "uint256", "bool", "bytes32"],
        receipt.output,
    )


def main() -> int:
    args = parse_args()
    contract = hex_to_address(args.contract)
    config_path = REPO_ROOT / "config" / "nodes" / args.node / "node.yaml"
    config = NodeConfig.from_file(config_path)

    storage = ChainStorage(config.data_dir)
    chain = Blockchain.load(storage)
    replayer = StateReplayer(storage)
    replayer.sync_to(chain.height)

    public_key_path = config.validator_key_dir / "validator_public_key.bin"
    public_key = public_key_path.read_bytes()
    view_caller = public_key_to_address(public_key)

    print(f"node       : {args.node}")
    print(f"height     : {chain.height}")
    print(f"state_root : {replayer.state_root.hex()}")
    print(f"contract   : 0x{contract.hex()}")
    print(f"view caller: 0x{view_caller.hex()}")

    registered_by_values: list[bytes] = []

    for height, expected in EXPECTED.items():
        block = chain.get_block(height)
        if block is None:
            raise RuntimeError(f"bloc absent à la hauteur {height}")

        tx = next(
            (transaction for transaction in block.transactions
             if transaction.tx_id.hex() == expected["tx"]),
            None,
        )
        if tx is None:
            raise RuntimeError(
                f"transaction {expected['tx']} absente du bloc {height}"
            )

        record_id, patient_id, cid, encrypted_hash, scope = decode_register_call(
            tx.data
        )

        if cid.decode("ascii") != expected["cid"]:
            raise RuntimeError(f"CID {expected['version']} inattendu")
        if encrypted_hash.hex() != expected["hash"]:
            raise RuntimeError(f"hash {expected['version']} inattendu")

        result = read_record(
            replayer,
            chain,
            contract,
            public_key,
            record_id,
        )
        (
            returned_patient,
            returned_cid,
            returned_hash,
            registered_by,
            created_at,
            active,
            returned_scope,
        ) = result

        if returned_patient != patient_id:
            raise RuntimeError(f"patientId {expected['version']} incohérent")
        if returned_cid != cid:
            raise RuntimeError(f"CID {expected['version']} incohérent")
        if returned_hash != encrypted_hash:
            raise RuntimeError(f"hash {expected['version']} incohérent")
        if returned_scope != scope:
            raise RuntimeError(f"scope {expected['version']} incohérent")
        if not active:
            raise RuntimeError(f"record {expected['version']} inactif")

        if clean_bytes32(returned_patient) != EXPECTED_PATIENT:
            raise RuntimeError(f"patientId textuel inattendu : {clean_bytes32(returned_patient)}")
        if clean_bytes32(returned_scope) != EXPECTED_SCOPE:
            raise RuntimeError(f"scope textuel inattendu : {clean_bytes32(returned_scope)}")
        if expected["version"] == "v2" and clean_bytes32(record_id) != EXPECTED_V2_RECORD:
            raise RuntimeError(f"recordId v2 inattendu : {clean_bytes32(record_id)}")

        registered_by_values.append(registered_by)
        print()
        print(f"version    : {expected['version']}")
        print(f"recordId   : {clean_bytes32(record_id)}")
        print(f"patientId  : {clean_bytes32(returned_patient)}")
        print(f"CID        : {returned_cid.decode('ascii')}")
        print(f"hash       : {returned_hash.hex()}")
        print(f"registered : 0x{registered_by.hex()}")
        print(f"createdAt  : {created_at}")
        print(f"active     : {active}")
        print(f"scope      : {clean_bytes32(returned_scope)}")

    if registered_by_values[0] != registered_by_values[1]:
        raise RuntimeError("v1 et v2 n'ont pas le même compte registeredBy")

    print()
    print("RESULT     : getRecord v1/v2 OK")
    print("same client: registeredBy v1 == registeredBy v2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
