#!/usr/bin/env python3
"""B8-A -- microbenchmark local de l'exécution EVM des contrats médicaux.

Le benchmark utilise ContractHarness et EVMState en mémoire. Il ne démarre pas
les VMs, ne se connecte pas aux nœuds distants et ne modifie pas data/nodeN.
Les identifiants, CID et hashes sont synthétiques ; aucune donnée médicale
n'est utilisée.

Mesures :
- registerPatient(bytes32)
- grantConsent(bytes32,address,bytes32,uint256)
- registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)
- getRecord(bytes32) sur le chemin transactionnel EVM local
- revokeRecord(bytes32)
- registerRecord sans consentement (échec attendu)

Le temps mesuré couvre l'appel local EVM et la mise à jour de l'état dans le
harness, pas le réseau, la signature ML-DSA réelle, le consensus ou le disque.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from tests.unit.contracts.test_contracts import ContractHarness, _bytes32


ARTIFACTS = Path(__file__).resolve().parents[2] / "contracts" / "artifacts"


def _assert_artifacts_verified() -> None:
    """Refuse le benchmark si un artefact Solidity ne correspond pas au manifeste."""
    sums_path = ARTIFACTS / "SHA256SUMS"
    if not sums_path.is_file():
        raise RuntimeError(f"manifeste SHA-256 absent: {sums_path}")

    for line_number, line in enumerate(
        sums_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            expected, relative_path = line.split(maxsplit=1)
        except ValueError as exc:
            raise RuntimeError(
                f"ligne SHA-256 invalide ({sums_path}:{line_number})"
            ) from exc
        path = ARTIFACTS.parents[1] / relative_path
        if not path.is_file():
            raise RuntimeError(f"artefact absent: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"SHA-256 incorrect pour {path}: attendu {expected}, obtenu {actual}"
            )


CASES = (
    "registerPatient",
    "grantConsent",
    "registerRecord",
    "getRecord",
    "revokeRecord",
    "unauthorizedRegister",
)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _setup_patient(harness: ContractHarness, patient_id: bytes) -> None:
    receipt = harness.call(
        harness.controller_key,
        harness.registry,
        "registerPatient(bytes32)",
        [patient_id],
    )
    if not receipt.is_success:
        raise RuntimeError(f"setup registerPatient failed: {receipt.error}")


def _setup_consent(
    harness: ContractHarness,
    patient_id: bytes,
    scope: bytes,
) -> None:
    _setup_patient(harness, patient_id)
    receipt = harness.call(
        harness.controller_key,
        harness.consent,
        "grantConsent(bytes32,address,bytes32,uint256)",
        [patient_id, harness.beneficiary, scope, 0],
    )
    if not receipt.is_success:
        raise RuntimeError(f"setup grantConsent failed: {receipt.error}")


def _setup_record(
    harness: ContractHarness,
    patient_id: bytes,
    record_id: bytes,
    scope: bytes,
    cid: bytes,
    content_hash: bytes,
) -> None:
    _setup_consent(harness, patient_id, scope)
    receipt = harness.call(
        harness.beneficiary_key,
        harness.records,
        "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
        [record_id, patient_id, cid, content_hash, scope],
    )
    if not receipt.is_success:
        raise RuntimeError(f"setup registerRecord failed: {receipt.error}")


def _timed_call(
    harness: ContractHarness,
    case: str,
    sample: int,
) -> dict[str, object]:
    patient_id = _bytes32(f"b8a-patient-{sample:04d}")
    record_id = _bytes32(f"b8a-record-{sample:04d}")
    scope = _bytes32(f"b8a-scope-{sample:04d}")
    content_hash = _bytes32(f"b8a-hash-{sample:04d}")
    cid = f"bafy-b8a-synthetic-{sample:04d}".encode("ascii")

    if case == "registerPatient":
        call = lambda: harness.call(
            harness.controller_key,
            harness.registry,
            "registerPatient(bytes32)",
            [patient_id],
        )
        expected_success = True
    elif case == "grantConsent":
        _setup_patient(harness, patient_id)
        call = lambda: harness.call(
            harness.controller_key,
            harness.consent,
            "grantConsent(bytes32,address,bytes32,uint256)",
            [patient_id, harness.beneficiary, scope, 0],
        )
        expected_success = True
    elif case == "registerRecord":
        _setup_consent(harness, patient_id, scope)
        call = lambda: harness.call(
            harness.beneficiary_key,
            harness.records,
            "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
            [record_id, patient_id, cid, content_hash, scope],
        )
        expected_success = True
    elif case == "getRecord":
        _setup_record(harness, patient_id, record_id, scope, cid, content_hash)
        call = lambda: harness.call(
            harness.beneficiary_key,
            harness.records,
            "getRecord(bytes32)",
            [record_id],
        )
        expected_success = True
    elif case == "revokeRecord":
        _setup_record(harness, patient_id, record_id, scope, cid, content_hash)
        call = lambda: harness.call(
            harness.controller_key,
            harness.records,
            "revokeRecord(bytes32)",
            [record_id],
        )
        expected_success = True
    elif case == "unauthorizedRegister":
        _setup_patient(harness, patient_id)
        call = lambda: harness.call(
            harness.outsider_key,
            harness.records,
            "registerRecord(bytes32,bytes32,bytes,bytes32,bytes32)",
            [record_id, patient_id, cid, content_hash, scope],
        )
        expected_success = False
    else:
        raise ValueError(f"unknown case: {case}")

    before_root = harness.state.state_root.hex()
    before_block = harness.block_number
    start_ns = time.perf_counter_ns()
    receipt = call()
    elapsed_us = (time.perf_counter_ns() - start_ns) / 1_000.0
    after_root = harness.state.state_root.hex()

    if receipt.is_success != expected_success:
        raise AssertionError(
            f"{case} sample {sample}: status inattendu "
            f"{receipt.status}, erreur={receipt.error!r}"
        )

    return {
        "case": case,
        "sample": sample,
        "elapsed_us": elapsed_us,
        "status": receipt.status,
        "success": receipt.is_success,
        "gas_used": receipt.gas_used,
        "log_count": len(receipt.logs),
        "error": receipt.error,
        "block_number": harness.block_number,
        "block_number_before": before_block,
        "state_root_before": before_root,
        "state_root_after": after_root,
    }


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    durations = [float(row["elapsed_us"]) for row in rows]
    gas = [int(row["gas_used"]) for row in rows]
    successes = sum(1 for row in rows if bool(row["success"]))
    return {
        "samples": len(rows),
        "successes": successes,
        "failures": len(rows) - successes,
        "success_rate": successes / len(rows),
        "elapsed_us": {
            "min": min(durations),
            "mean": statistics.fmean(durations),
            "p50": _percentile(durations, 50),
            "p95": _percentile(durations, 95),
            "max": max(durations),
        },
        "gas_used": {
            "min": min(gas),
            "mean": statistics.fmean(gas),
            "p50": _percentile([float(value) for value in gas], 50),
            "p95": _percentile([float(value) for value in gas], 95),
            "max": max(gas),
        },
        "log_count_values": sorted({int(row["log_count"]) for row in rows}),
        "errors": sorted({row["error"] for row in rows if row["error"]}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/raw_data/b8a-evm-contracts-20260916.json"),
    )
    args = parser.parse_args()
    if args.samples < 2:
        raise SystemExit("--samples doit être >= 2")

    _assert_artifacts_verified()
    rows: list[dict[str, object]] = []

    for case in CASES:
        for sample in range(args.samples):
            harness = ContractHarness()
            harness.registry, harness.consent, harness.records = harness.deploy_system()
            rows.append(_timed_call(harness, case, sample))

    summaries = {case: _summary([row for row in rows if row["case"] == case]) for case in CASES}
    document = {
        "run_id": "b8a-evm-contracts-20260916",
        "benchmark": "phase8-b8a-evm-contract-execution",
        "execution_mode": "local_in_memory_evm",
        "persistent_chain_modified": False,
        "remote_vms_contacted": False,
        "synthetic_data_only": True,
        "samples_per_case": args.samples,
        "cases": list(CASES),
        "summaries": summaries,
        "measurements": rows,
        "interpretation": {
            "elapsed_us": "EVM local + mise à jour d'état du harness; hors réseau, consensus, disque et ML-DSA réel",
            "getRecord": "appel exécuté sur le chemin transactionnel local; ne pas le présenter comme une latence HTTP/API",
            "unauthorizedRegister": "échec attendu et vérifié; il ne doit produire aucun log Solidity",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(f"artifacts_sha256 : OK")
    print(f"persistent_chain : NOT_MODIFIED")
    print(f"output           : {args.output}")
    print()
    print("case                    success  elapsed_p50_us  elapsed_p95_us  gas_p50  logs  errors")
    for case in CASES:
        summary = summaries[case]
        elapsed = summary["elapsed_us"]
        gas = summary["gas_used"]
        print(
            f"{case:23} {summary['success_rate'] * 100:6.1f}% "
            f"{elapsed['p50']:15.2f} {elapsed['p95']:15.2f} "
            f"{gas['p50']:8.0f} {summary['log_count_values']!s:>6} "
            f"{summary['errors']!s}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
