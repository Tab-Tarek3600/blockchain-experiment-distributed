#!/usr/bin/env python3
"""
Phase 8 — étape 2 : microbenchmark ML-DSA-44.

Ce programme mesure uniquement la couche cryptographique locale, via le
wrapper MLDSA utilisé par le projet. Il ne mesure ni le réseau, ni le consensus,
ni le débit blockchain/TPS.

Aucune clé n'est écrite sur disque et aucune clé secrète n'est affichée.
La paire de référence créée pour les mesures de signature/vérification reste en
mémoire puis est détruite à la fin du processus.

Exemple :
    python3 scripts/experiments/benchmark_mldsa44.py \
        --node-label node1 \
        --iterations 1000 \
        --warmup 100 \
        --repetitions 5 \
        --json-output results/raw_data/mldsa44-node1-2026-09-13.json
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import socket
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

# Permet l'exécution directe depuis la racine du dépôt sans installation
# supplémentaire du projet.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.crypto.ml_dsa import DEFAULT_VARIANT, MLDSA  # noqa: E402


Operation = Callable[[], object]


def percentile(values: list[int], quantile: float) -> float:
    """Percentile nearest-rank, en nanosecondes."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * quantile) + 0.999999) - 1))
    return float(ordered[index])


def summarize(samples_ns: list[int]) -> dict[str, float | int]:
    if not samples_ns:
        raise ValueError("Aucun échantillon mesuré")

    median_ns = statistics.median(samples_ns)
    return {
        "count": len(samples_ns),
        "min_us": min(samples_ns) / 1_000.0,
        "mean_us": statistics.mean(samples_ns) / 1_000.0,
        "median_us": median_ns / 1_000.0,
        "p95_us": percentile(samples_ns, 0.95) / 1_000.0,
        "p99_us": percentile(samples_ns, 0.99) / 1_000.0,
        "p25_us": percentile(samples_ns, 0.25) / 1_000.0,
        "p75_us": percentile(samples_ns, 0.75) / 1_000.0,
        "iqr_us": (percentile(samples_ns, 0.75) - percentile(samples_ns, 0.25))
        / 1_000.0,
        "max_us": max(samples_ns) / 1_000.0,
        "throughput_ops_s_from_median": 1_000_000_000.0 / median_ns,
    }


def measure(
    operation: Operation,
    *,
    warmup: int,
    iterations: int,
    repetitions: int,
) -> dict[str, object]:
    """Warm-up puis répétitions chronométrées avec perf_counter_ns."""
    for _ in range(warmup):
        operation()

    repetitions_data: list[dict[str, object]] = []
    all_samples: list[int] = []
    for repetition in range(1, repetitions + 1):
        samples: list[int] = []
        for _ in range(iterations):
            start = time.perf_counter_ns()
            operation()
            samples.append(time.perf_counter_ns() - start)
        all_samples.extend(samples)
        repetitions_data.append(
            {
                "repetition": repetition,
                "summary": summarize(samples),
            }
        )

    return {
        "summary_all_repetitions": summarize(all_samples),
        "repetitions": repetitions_data,
    }


def bytes_hex_size(value: bytes) -> dict[str, int]:
    return {"bytes": len(value), "hex_characters": len(value.hex())}


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-label", required=True, help="node1, node2 ou node3")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument(
        "--json-output",
        type=Path,
        required=True,
        help="fichier JSON de résultats, sans clé secrète",
    )
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup < 0 or args.repetitions < 1:
        parser.error("iterations et repetitions doivent être positifs; warmup >= 0")
    return args


def main() -> int:
    args = get_args()
    gc.collect()
    gc.disable()

    ml_dsa = MLDSA(DEFAULT_VARIANT)
    message_32 = bytes(range(32))
    message_1k = bytes((index % 251 for index in range(1024)))

    # Cette paire de référence n'est pas incluse dans la mesure de keygen.
    reference = ml_dsa.generate_keypair()
    signature_32 = ml_dsa.sign(message_32, reference.secret_key)
    signature_1k = ml_dsa.sign(message_1k, reference.secret_key)

    validity = {
        "verify_32B": ml_dsa.verify(message_32, signature_32, reference.public_key),
        "verify_1KiB": ml_dsa.verify(message_1k, signature_1k, reference.public_key),
        "signature_32B_length_matches": len(signature_32) > 0,
        "signature_1KiB_length_matches": len(signature_1k) > 0,
    }
    if not all(validity.values()):
        raise RuntimeError(f"Contrôle de validité ML-DSA échoué: {validity}")

    # Chaque appel passe par le wrapper MLDSA du projet. La création du contexte
    # liboqs effectuée par ce wrapper est donc incluse dans sign/verify, ce qui
    # reflète le chemin applicatif actuel des transactions et des blocs.
    def verify_32_operation() -> None:
        if not ml_dsa.verify(message_32, signature_32, reference.public_key):
            raise RuntimeError("verify_32B a échoué pendant la mesure")

    def verify_1k_operation() -> None:
        if not ml_dsa.verify(message_1k, signature_1k, reference.public_key):
            raise RuntimeError("verify_1KiB a échoué pendant la mesure")

    operations: dict[str, Operation] = {
        "keygen": ml_dsa.generate_keypair,
        "sign_32B": lambda: ml_dsa.sign(message_32, reference.secret_key),
        "sign_1KiB": lambda: ml_dsa.sign(message_1k, reference.secret_key),
        "verify_32B": verify_32_operation,
        "verify_1KiB": verify_1k_operation,
    }

    measurements: dict[str, object] = {}
    for name, operation in operations.items():
        result = measure(
            operation,
            warmup=args.warmup,
            iterations=args.iterations,
            repetitions=args.repetitions,
        )
        measurements[name] = result

    result_document = {
        "benchmark": "phase8-step2-mldsa44",
        "benchmark_scope": "local cryptographic microbenchmark; not blockchain TPS",
        "algorithm": DEFAULT_VARIANT,
        "api_level": "project src.crypto.ml_dsa.MLDSA wrapper",
        "wrapper_context_policy": (
            "sign/verify timings include the liboqs Signature context creation "
            "performed by the project wrapper; keygen is fully measured"
        ),
        "node_label": args.node_label,
        "hostname": socket.gethostname(),
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count_visible": os.cpu_count(),
        "liboqs_version": __import__("oqs").oqs_version(),
        "parameters": {
            "warmup_operations": args.warmup,
            "measured_iterations_per_repetition": args.iterations,
            "repetitions": args.repetitions,
            "timer": "time.perf_counter_ns",
            "messages": {"32B": 32, "1KiB": 1024},
        },
        "validity_checks": validity,
        "sizes": {
            "public_key": bytes_hex_size(reference.public_key),
            "secret_key": {
                "bytes": len(reference.secret_key),
                "hex_characters": len(reference.secret_key.hex()),
                "reported": False,
            },
            "signature_32B": bytes_hex_size(signature_32),
            "signature_1KiB": bytes_hex_size(signature_1k),
        },
        "measurements": measurements,
        "interpretation": {
            "in_blockchain_path": [
                "sign_32B represents signing a transaction/block signing hash",
                "verify_32B represents verification of a transaction/block hash",
            ],
            "not_measured": [
                "network propagation",
                "block production",
                "mempool admission",
                "consensus convergence",
                "transactions per second",
            ],
        },
    }

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(result_document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(result_document, indent=2, ensure_ascii=False))
    print(f"\nRésultats écrits dans : {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
