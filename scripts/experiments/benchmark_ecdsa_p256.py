#!/usr/bin/env python3
"""Local ECDSA P-256 baseline using the same warm-up/repetition protocol as ML-DSA."""
from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import cryptography
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError as exc:
    raise SystemExit(
        "cryptography absent. Installez-la dans le venv avec: python3 -m pip install cryptography"
    ) from exc


def percentile(values: list[int], q: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * q + 0.999999) - 1))
    return float(ordered[index])


def summary(values: list[int]) -> dict[str, float | int]:
    median = statistics.median(values)
    return {
        "count": len(values),
        "min_us": min(values) / 1_000.0,
        "mean_us": statistics.mean(values) / 1_000.0,
        "median_us": median / 1_000.0,
        "p95_us": percentile(values, 0.95) / 1_000.0,
        "p99_us": percentile(values, 0.99) / 1_000.0,
        "max_us": max(values) / 1_000.0,
        "throughput_ops_s_from_median": 1_000_000_000.0 / median,
    }


def measure(operation, warmup: int, iterations: int, repetitions: int):
    for _ in range(warmup):
        operation()
    all_values: list[int] = []
    per_rep = []
    for rep in range(1, repetitions + 1):
        values = []
        for _ in range(iterations):
            start = time.perf_counter_ns()
            operation()
            values.append(time.perf_counter_ns() - start)
        all_values.extend(values)
        per_rep.append({"repetition": rep, "summary": summary(values)})
    return {"summary_all_repetitions": summary(all_values), "repetitions": per_rep}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-label", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()

    gc.collect()
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    message = bytes(range(32))
    signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))

    def sign_operation():
        private_key.sign(message, ec.ECDSA(hashes.SHA256()))

    def verify_operation():
        try:
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise RuntimeError("ECDSA verification failed") from exc

    validity = {"verify_32B": True}
    verify_operation()
    measurements = {
        "keygen": measure(lambda: ec.generate_private_key(ec.SECP256R1()), args.warmup, args.iterations, args.repetitions),
        "sign_32B": measure(sign_operation, args.warmup, args.iterations, args.repetitions),
        "verify_32B": measure(verify_operation, args.warmup, args.iterations, args.repetitions),
    }

    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    document = {
        "benchmark": "phase8-pqc-baseline-ecdsa-p256",
        "scope": "local cryptographic microbenchmark; not blockchain TPS",
        "algorithm": "ECDSA-P256/SHA-256",
        "node_label": args.node_label,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cryptography_version": cryptography.__version__,
        "parameters": {
            "warmup_operations": args.warmup,
            "measured_iterations_per_repetition": args.iterations,
            "repetitions": args.repetitions,
            "message_bytes": len(message),
            "timer": "time.perf_counter_ns",
        },
        "validity_checks": validity,
        "public_key_der_bytes": len(public_der),
        "signature_der_bytes": len(signature),
        "measurements": measurements,
        "interpretation": {
            "compare_with": "ML-DSA-44 keygen/sign_32B/verify_32B",
            "not_measured": ["network", "consensus", "mempool", "blockchain TPS"],
        },
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document, indent=2))
    print(f"Résultats écrits dans : {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
