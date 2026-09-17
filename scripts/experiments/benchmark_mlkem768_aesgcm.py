#!/usr/bin/env python3
"""
Phase 8 — étape 3 : microbenchmark ML-KEM-768 + AES-256-GCM.

Ce programme mesure la confidentialité hors chaîne utilisée pour les charges
utiles chiffrées avant stockage IPFS. Il ne mesure ni le réseau, ni IPFS, ni la
blockchain, ni le TPS.

Les opérations ML-KEM utilisent le wrapper src.crypto.ml_kem.MLKEM du projet.
Les opérations AES-GCM reproduisent le chemin de la phase 7 : dérivation
SHA-256 d'une clé AES-256, nonce de 12 octets, AAD de version et tag GCM de
16 octets.

Aucune clé ni donnée en clair n'est écrite sur disque ou affichée. Le résultat
JSON ne contient que les tailles, contrôles booléens et statistiques.

Exemple :
    python3 scripts/experiments/benchmark_mlkem768_aesgcm.py \
        --node-label node1 \
        --iterations 1000 \
        --warmup 100 \
        --repetitions 5 \
        --json-output results/raw_data/mlkem768-aesgcm-node1-2026-09-13.json
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import platform
import socket
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
except ImportError as exc:  # pragma: no cover - message d'installation
    raise SystemExit(
        "pycryptodome est requis : activez .venv puis installez requirements.txt"
    ) from exc

from src.crypto.ml_kem import DEFAULT_VARIANT, MLKEM  # noqa: E402


Operation = Callable[[], object]
AAD_PREFIX = b"phase7/aes-gcm/"
AAD_VERSION = b"v1"
PLAINTEXT = bytes((index % 251 for index in range(1024)))


def percentile(values: list[int], quantile: float) -> float:
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, int((len(ordered) * quantile) + 0.999999) - 1),
    )
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
        "iqr_us": (
            percentile(samples_ns, 0.75) - percentile(samples_ns, 0.25)
        )
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
    for _ in range(warmup):
        operation()

    all_samples: list[int] = []
    repetitions_data: list[dict[str, object]] = []
    for repetition in range(1, repetitions + 1):
        samples: list[int] = []
        for _ in range(iterations):
            start = time.perf_counter_ns()
            operation()
            samples.append(time.perf_counter_ns() - start)
        all_samples.extend(samples)
        repetitions_data.append(
            {"repetition": repetition, "summary": summarize(samples)}
        )

    return {
        "summary_all_repetitions": summarize(all_samples),
        "repetitions": repetitions_data,
    }


def size(value: bytes) -> dict[str, int]:
    return {"bytes": len(value), "hex_characters": len(value.hex())}


def derive_aes_key(shared_secret: bytes) -> bytes:
    return hashlib.sha256(AAD_PREFIX + shared_secret).digest()


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-label", required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup < 0 or args.repetitions < 1:
        parser.error("iterations et repetitions doivent être positifs; warmup >= 0")
    return args


def main() -> int:
    args = get_args()
    gc.collect()
    gc.disable()

    kem = MLKEM(DEFAULT_VARIANT)

    # Ces valeurs de référence sont hors des fenêtres de mesure correspondantes.
    recipient = kem.generate_keypair()
    encapsulation = kem.encapsulate(recipient.public_key)
    recovered_shared_secret = kem.decapsulate(
        encapsulation.ciphertext, recipient.secret_key
    )
    if recovered_shared_secret != encapsulation.shared_secret:
        raise RuntimeError("Le secret partagé ML-KEM de référence ne correspond pas")

    aes_key = derive_aes_key(encapsulation.shared_secret)
    fixed_nonce = b"phase8-step3"  # 12 octets, uniquement pour le vecteur de contrôle
    cipher = AES.new(aes_key, AES.MODE_GCM, nonce=fixed_nonce)
    cipher.update(AAD_VERSION)
    fixed_ciphertext, fixed_tag = cipher.encrypt_and_digest(PLAINTEXT)

    # Contrôles positifs et négatifs hors mesure.
    decryptor = AES.new(aes_key, AES.MODE_GCM, nonce=fixed_nonce)
    decryptor.update(AAD_VERSION)
    recovered_plaintext = decryptor.decrypt_and_verify(fixed_ciphertext, fixed_tag)
    if recovered_plaintext != PLAINTEXT:
        raise RuntimeError("Le déchiffrement AES-GCM de référence a échoué")

    wrong_key = hashlib.sha256(b"wrong-key-for-phase8-step3").digest()
    try:
        wrong_decryptor = AES.new(wrong_key, AES.MODE_GCM, nonce=fixed_nonce)
        wrong_decryptor.update(AAD_VERSION)
        wrong_decryptor.decrypt_and_verify(fixed_ciphertext, fixed_tag)
    except (ValueError, KeyError):
        wrong_key_rejected = True
    else:
        wrong_key_rejected = False

    modified_ciphertext = fixed_ciphertext[:-1] + bytes(
        [fixed_ciphertext[-1] ^ 1]
    )
    try:
        modified_decryptor = AES.new(aes_key, AES.MODE_GCM, nonce=fixed_nonce)
        modified_decryptor.update(AAD_VERSION)
        modified_decryptor.decrypt_and_verify(modified_ciphertext, fixed_tag)
    except (ValueError, KeyError):
        modified_ciphertext_rejected = True
    else:
        modified_ciphertext_rejected = False

    if not wrong_key_rejected or not modified_ciphertext_rejected:
        raise RuntimeError("Un contrôle négatif AES-GCM n'a pas été rejeté")

    def decapsulate_operation() -> None:
        shared_secret = kem.decapsulate(
            encapsulation.ciphertext, recipient.secret_key
        )
        if shared_secret != encapsulation.shared_secret:
            raise RuntimeError("Décapsulation ML-KEM incohérente pendant la mesure")

    def aes_encrypt_operation() -> bytes:
        # Le nonce aléatoire est inclus : c'est le chemin utilisé par la phase 7.
        nonce = get_random_bytes(12)
        encryptor = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
        encryptor.update(AAD_VERSION)
        ciphertext, tag = encryptor.encrypt_and_digest(PLAINTEXT)
        return ciphertext + tag

    def aes_decrypt_operation() -> bytes:
        decryptor = AES.new(aes_key, AES.MODE_GCM, nonce=fixed_nonce)
        decryptor.update(AAD_VERSION)
        return decryptor.decrypt_and_verify(fixed_ciphertext, fixed_tag)

    operations: dict[str, Operation] = {
        "keygen": kem.generate_keypair,
        "encapsulate": lambda: kem.encapsulate(recipient.public_key),
        "decapsulate": decapsulate_operation,
        "derive_aes256_key_sha256": lambda: derive_aes_key(
            encapsulation.shared_secret
        ),
        "aes_gcm_encrypt_1KiB": aes_encrypt_operation,
        "aes_gcm_decrypt_1KiB": aes_decrypt_operation,
    }

    measurements: dict[str, object] = {}
    for name, operation in operations.items():
        measurements[name] = measure(
            operation,
            warmup=args.warmup,
            iterations=args.iterations,
            repetitions=args.repetitions,
        )

    result_document = {
        "benchmark": "phase8-step3-mlkem768-aesgcm",
        "benchmark_scope": (
            "local off-chain confidentiality microbenchmark; not blockchain TPS"
        ),
        "algorithm": DEFAULT_VARIANT,
        "api_level": "project src.crypto.ml_kem.MLKEM wrapper + PyCryptodome AES-GCM",
        "kem_context_policy": (
            "ML-KEM keygen/encapsulate/decapsulate timings include the context "
            "creation performed by the project wrapper"
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
            "plaintext_size_bytes": len(PLAINTEXT),
            "aes_mode": "AES-256-GCM",
            "aes_nonce_size_bytes": 12,
            "aes_tag_size_bytes": len(fixed_tag),
            "aad": AAD_VERSION.decode("ascii"),
            "aes_encrypt_includes_nonce_rng": True,
        },
        "validity_checks": {
            "kem_shared_secret_matches": True,
            "aes_gcm_round_trip": recovered_plaintext == PLAINTEXT,
            "wrong_key_rejected": wrong_key_rejected,
            "modified_ciphertext_rejected": modified_ciphertext_rejected,
        },
        "sizes": {
            "public_key": size(recipient.public_key),
            "secret_key": {
                "bytes": len(recipient.secret_key),
                "hex_characters": len(recipient.secret_key.hex()),
                "reported": False,
            },
            "kem_ciphertext": size(encapsulation.ciphertext),
            "shared_secret": size(encapsulation.shared_secret),
            "derived_aes256_key": size(aes_key),
            "plaintext_1KiB": size(PLAINTEXT),
            "aes_gcm_ciphertext_1KiB": size(fixed_ciphertext),
            "aes_gcm_nonce": size(fixed_nonce),
            "aes_gcm_tag": size(fixed_tag),
            "envelope_serialized_phase7_style": {
                "bytes": (
                    4 + 2
                    + 4 + len(encapsulation.ciphertext)
                    + 4 + len(fixed_nonce)
                    + 4 + len(fixed_tag)
                    + 4 + len(fixed_ciphertext)
                ),
                "description": (
                    "version + KEM ciphertext + nonce + tag + ciphertext, "
                    "each field prefixed by a 4-byte length"
                ),
            },
        },
        "measurements": measurements,
        "interpretation": {
            "scope": "confidentialité hors chaîne avant stockage IPFS",
            "not_measured": [
                "IPFS upload/download",
                "blockchain transaction throughput",
                "P2P propagation",
                "consensus convergence",
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
