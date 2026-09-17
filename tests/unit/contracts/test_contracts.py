"""Tests d'integration locale des contrats Solidity PHASE 3.

Ces tests utilisent les artefacts verifies dans ``contracts/artifacts`` et
le chemin d'execution reel du projet : Transaction -> EVMExecutor ->
EVMState. Ils ne simulent pas les contrats et ne modifient pas
``Node._accept_block``.

La signature ML-DSA n'est pas verifiee par EVMExecutor (elle est validee en
amont par le pipeline blockchain). Les transactions de test portent donc une
signature deterministe non vide.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eth_utils import keccak

from src.blockchain.transaction import Transaction
from src.crypto.address import public_key_to_address
from src.evm.abi import decode_function_output, encode_function_call
from src.evm.addresses import ZERO_ADDRESS
from src.evm.executor import EVMExecutor
from src.evm.state import EVMState


ARTIFACTS = Path(__file__).resolve().parents[3] / "contracts" / "artifacts"
SIGNATURE = b"contract-test-signature"
BASE_TIMESTAMP = 1_700_000_000


def _artifact(name: str) -> dict:
    with (ARTIFACTS / f"{name}.json").open(encoding="utf-8") as stream:
        return json.load(stream)


def _constructor(types: str, values: list[object]) -> bytes:
    """Encode les arguments d'un constructeur, sans selecteur ABI."""
    # L'ABI des constructeurs n'a pas de selecteur. L'encodeur partage
    # toutefois le meme format de tete/queue pour les arguments ; le
    # selecteur synthetique est retire avant d'etre ajoute a l'initcode.
    return encode_function_call(f"constructor({types})", values)[4:]


def _event_topic(signature: str) -> bytes:
    return keccak(text=signature)


def _bytes32(label: str) -> bytes:
    """Fabrique un identifiant de test exactement large de 32 octets."""
    value = label.encode("ascii")
    if len(value) > 32:
        raise ValueError("test identifier is longer than bytes32")
    return value.ljust(32, b"_")


def _address_topic(address: bytes) -> bytes:
    return b"\x00" * 12 + address


class ContractHarness:
    """Petit adaptateur de test autour du chemin d'execution de production."""

    def __init__(self) -> None:
        self.controller_key = b"controller-public-key"
        self.beneficiary_key = b"beneficiary-public-key"
        self.outsider_key = b"outsider-public-key"
        self.controller = public_key_to_address(self.controller_key)
        self.beneficiary = public_key_to_address(self.beneficiary_key)
        self.outsider = public_key_to_address(self.outsider_key)

        self.state = EVMState()
        for address in (self.controller, self.beneficiary, self.outsider):
            self.state.set_balance(address, 10**18)
        self.state.commit()
        self.executor = EVMExecutor(self.state)
        self.nonces = {
            self.controller: 0,
            self.beneficiary: 0,
            self.outsider: 0,
        }
        self.block_number = 0
        self.last_timestamp = BASE_TIMESTAMP

    def transaction(self, public_key: bytes, recipient: bytes, data: bytes) -> Transaction:
        sender = public_key_to_address(public_key)
        nonce = self.nonces[sender]
        self.nonces[sender] += 1
        return Transaction.create(
            nonce=nonce,
            public_key=public_key,
            recipient=recipient,
            value=0,
            gas_limit=5_000_000,
            gas_price=0,
            data=data,
        ).with_signature(SIGNATURE)

    def mine(self, transactions: list[Transaction]):
        self.block_number += 1
        self.last_timestamp = BASE_TIMESTAMP + self.block_number
        return self.executor.execute_block(
            transactions,
            block_number=self.block_number,
            timestamp=self.last_timestamp,
            coinbase=ZERO_ADDRESS,
        )

    def deploy(self, name: str, constructor_types: str = "", values: list[object] | None = None) -> bytes:
        artifact = _artifact(name)
        arguments = _constructor(constructor_types, values or []) if constructor_types else b""
        initcode = bytes.fromhex(artifact["bytecode"][2:]) + arguments
        transaction = self.transaction(self.controller_key, ZERO_ADDRESS, initcode)
        receipt = self.mine([transaction]).receipts[0]
        assert receipt.is_success, receipt.error
        assert receipt.contract_address is not None
        return receipt.contract_address

    def deploy_system(self) -> tuple[bytes, bytes, bytes]:
        patient_registry = self.deploy("PatientRegistry")
        consent_manager = self.deploy(
            "ConsentManager", "address", [patient_registry]
        )
        medical_records = self.deploy(
            "MedicalRecordRegistry",
            "address,address",
            [patient_registry, consent_manager],
        )
        return patient_registry, consent_manager, medical_records

    def call(
        self,
        public_key: bytes,
        recipient: bytes,
        signature: str,
        values: list[object],
    ):
        data = encode_function_call(signature, values)
        return self.mine([self.transaction(public_key, recipient, data)]).receipts[0]


@pytest.fixture
def harness() -> ContractHarness:
    return ContractHarness()


def test_patient_registry_lifecycle_events_and_non_destructive_deactivation(harness):
    registry = harness.deploy("PatientRegistry")
    patient_id = _bytes32("patient-registered")

    registered = harness.call(
        harness.controller_key,
        registry,
        "registerPatient(bytes32)",
        [patient_id],
    )
    assert registered.is_success
    assert len(registered.logs) == 1
    log = registered.logs[0]
    assert log.address == registry
    assert log.topics == (
        _event_topic("PatientRegistered(bytes32,address,uint256)"),
        patient_id,
        _address_topic(harness.controller),
    )
    assert decode_function_output(["uint256"], log.data) == (harness.last_timestamp,)

    assert decode_function_output(
        ["bool"], harness.call(
            harness.controller_key,
            registry,
            "isRegistered(bytes32)",
            [patient_id],
        ).output
    ) == (True,)
    assert decode_function_output(
        ["bool"], harness.call(
            harness.controller_key,
            registry,
            "isActive(bytes32)",
            [patient_id],
        ).output
    ) == (True,)
    assert decode_function_output(
        ["address"], harness.call(
            harness.controller_key,
            registry,
            "controllerOf(bytes32)",
            [patient_id],
        ).output
    ) == (harness.controller,)

    unauthorized = harness.call(
        harness.beneficiary_key,
        registry,
        "deactivatePatient(bytes32)",
        [patient_id],
    )
    assert unauthorized.is_failure
    assert not unauthorized.logs

    deactivated = harness.call(
        harness.controller_key,
        registry,
        "deactivatePatient(bytes32)",
        [patient_id],
    )
    assert deactivated.is_success
    assert len(deactivated.logs) == 1
    assert deactivated.logs[0].topics == (
        _event_topic("PatientDeactivated(bytes32,address,uint256)"),
        patient_id,
        _address_topic(harness.controller),
    )

    # La desactivation conserve l'existence et le controleur historique.
    assert decode_function_output(
        ["bool"], harness.call(
            harness.controller_key,
            registry,
            "isRegistered(bytes32)",
            [patient_id],
        ).output
    ) == (True,)
    assert decode_function_output(
        ["bool"], harness.call(
            harness.controller_key,
            registry,
            "isActive(bytes32)",
            [patient_id],
        ).output
    ) == (False,)


def test_consent_expiration_is_strict_and_revoke_is_explicit(harness):
    registry, consent, _ = harness.deploy_system()
    patient_id = _bytes32("patient-consent")
    scope = _bytes32("scope-read")

    assert harness.call(
        harness.controller_key,
        registry,
        "registerPatient(bytes32)",
        [patient_id],
    ).is_success

    expires_at = BASE_TIMESTAMP + harness.block_number + 3
    granted = harness.call(
        harness.controller_key,
        consent,
        "grantConsent(bytes32,address,bytes32,uint256)",
        [patient_id, harness.beneficiary, scope, expires_at],
    )
    assert granted.is_success
    assert granted.logs[0].topics == (
        _event_topic("ConsentGranted(bytes32,address,bytes32,uint256)"),
        patient_id,
        _address_topic(harness.beneficiary),
        scope,
    )

    # Bloc suivant : timestamp strictement inferieur a expiresAt.
    valid = harness.call(
        harness.beneficiary_key,
        consent,
        "hasValidConsent(bytes32,address,bytes32)",
        [patient_id, harness.beneficiary, scope],
    )
    assert decode_function_output(["bool"], valid.output) == (True,)

    # Le bloc suivant tombe exactement sur expiresAt : le consentement
    # expire car le contrat applique block.timestamp < expiresAt.
    at_expiration = harness.call(
        harness.beneficiary_key,
        consent,
        "hasValidConsent(bytes32,address,bytes32)",
        [patient_id, harness.beneficiary, scope],
    )
    assert harness.last_timestamp == expires_at
    assert decode_function_output(["bool"], at_expiration.output) == (False,)

    # expiresAt == 0 signifie sans expiration explicite ; revoke reste
    # une action distincte du controleur et rend le consentement invalide.
    assert harness.call(
        harness.controller_key,
        consent,
        "grantConsent(bytes32,address,bytes32,uint256)",
        [patient_id, harness.beneficiary, scope, 0],
    ).is_success
    revoked = harness.call(
        harness.controller_key,
        consent,
        "revokeConsent(bytes32,address,bytes32)",
        [patient_id, harness.beneficiary, scope],
    )
    assert revoked.is_success
    assert revoked.logs[0].topics == (
        _event_topic("ConsentRevoked(bytes32,address,bytes32)"),
        patient_id,
        _address_topic(harness.beneficiary),
        scope,
    )

    invalid_after_revoke = harness.call(
        harness.beneficiary_key,
        consent,
        "hasValidConsent(bytes32,address,bytes32)",
        [patient_id, harness.beneficiary, scope],
    )
    assert decode_function_output(["bool"], invalid_after_revoke.output) == (False,)


def test_medical_record_requires_consent_preserves_metadata_and_emits_logs(harness):
    registry, consent, records = harness.deploy_system()
    patient_id = _bytes32("patient-record")
    record_id = _bytes32("record-1")
    scope = _bytes32("scope-lab")
    content_hash = _bytes32("encrypted-content-hash")
    cid = b"bafybeigdyrzt5examplecid"

    assert harness.call(
        harness.controller_key,
        registry,
        "registerPatient(bytes32)",
        [patient_id],
    ).is_success

    unauthorized = harness.call(
        harness.outsider_key,
        records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_id, patient_id, cid, content_hash, scope],
    )
    assert unauthorized.is_failure
    assert not unauthorized.logs
    assert decode_function_output(
        ["bool"], harness.call(
            harness.controller_key,
            records,
            "isRecordActive(bytes32)",
            [record_id],
        ).output
    ) == (False,)

    assert harness.call(
        harness.controller_key,
        consent,
        "grantConsent(bytes32,address,bytes32,uint256)",
        [patient_id, harness.beneficiary, scope, 0],
    ).is_success

    registered = harness.call(
        harness.beneficiary_key,
        records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_id, patient_id, cid, content_hash, scope],
    )
    assert registered.is_success
    assert len(registered.logs) == 1
    record_log = registered.logs[0]
    assert record_log.address == records
    assert record_log.topics == (
        _event_topic("RecordRegistered(bytes32,bytes32,address,bytes32,bytes32)"),
        record_id,
        patient_id,
        _address_topic(harness.beneficiary),
    )
    assert decode_function_output(
        ["bytes32", "bytes32"], record_log.data
    ) == (content_hash, scope)

    stored = harness.call(
        harness.beneficiary_key,
        records,
        "getRecord(bytes32)",
        [record_id],
    )
    patient, stored_cid, stored_hash, registered_by, created_at, active, stored_scope = decode_function_output(
        ["bytes32", "bytes", "bytes32", "address", "uint256", "bool", "bytes32"],
        stored.output,
    )
    assert (patient, stored_cid, stored_hash, registered_by, active, stored_scope) == (
        patient_id,
        cid,
        content_hash,
        harness.beneficiary,
        True,
        scope,
    )
    assert created_at == BASE_TIMESTAMP + harness.block_number - 1

    revoked = harness.call(
        harness.controller_key,
        records,
        "revokeRecord(bytes32)",
        [record_id],
    )
    assert revoked.is_success
    assert revoked.logs[0].topics == (
        _event_topic("RecordRevoked(bytes32,address)"),
        record_id,
        _address_topic(harness.controller),
    )

    stored_after_revoke = harness.call(
        harness.controller_key,
        records,
        "getRecord(bytes32)",
        [record_id],
    )
    decoded_after_revoke = decode_function_output(
        ["bytes32", "bytes", "bytes32", "address", "uint256", "bool", "bytes32"],
        stored_after_revoke.output,
    )
    assert decoded_after_revoke[:4] == (patient_id, cid, content_hash, harness.beneficiary)
    assert decoded_after_revoke[5] is False
    assert decoded_after_revoke[6] == scope


def test_reexecuting_same_contract_transaction_from_same_root_reproduces_root(harness):
    registry = harness.deploy("PatientRegistry")
    patient_id = _bytes32("patient-root")
    transaction = harness.transaction(
        harness.controller_key,
        registry,
        encode_function_call("registerPatient(bytes32)", [patient_id]),
    )

    root_before = harness.state.state_root
    first = harness.mine([transaction])
    replay_state = harness.state.at_root(root_before)
    replay = EVMExecutor(replay_state).execute_block(
        [transaction],
        block_number=harness.block_number,
        timestamp=harness.last_timestamp,
        coinbase=ZERO_ADDRESS,
    )

    assert first.state_root == replay.state_root
    assert first.receipts[0].tx_id == replay.receipts[0].tx_id
    assert first.receipts[0].logs == replay.receipts[0].logs
