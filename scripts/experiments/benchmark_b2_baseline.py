#!/usr/bin/env python3
"""
Phase 8 — B2 : générateur de charge pour la baseline blockchain à 3 nœuds.

Le client de benchmark ouvre UNE connexion TCP vers node1 et envoie des
transactions synthétiques signées. Il n'envoie jamais directement vers node2
ou node3 : le chemin mesuré reste client/médecin -> node1 -> relais P2P.

Le script ne démarre ni n'arrête de nœud, ne modifie aucune configuration et
ne copie aucune clé. Il doit être exécuté localement sur node1, où la clé
secrète du validateur reste présente. Les transactions sont pré-signées avant
la fenêtre T2 afin que le taux d'émission mesuré ne dépende pas de la durée de
signature ML-DSA ; le coût ML-DSA a déjà été mesuré séparément en B1.

Exemple de pilote :
    PYTHONPATH=. python3 scripts/experiments/benchmark_b2_baseline.py \
        --config config/nodes/node1/node.yaml \
        --rate 0.2 --duration 30 \
        --run-id b2-pilot-r02 \
        --manifest-output results/raw_data/b2-pilot-r02-node1-manifest.json

Le fichier produit ne contient aucune clé secrète, seulement les identifiants
et métadonnées de transactions synthétiques. Les blocs des trois nœuds doivent
ensuite être copiés par scp simple pour l'analyse B2.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.blockchain.block import Block, BlockError  # noqa: E402
from src.blockchain.transaction import Transaction  # noqa: E402
from src.crypto.ml_dsa import MLDSA  # noqa: E402
from src.node.config import NodeConfig, load_or_generate_validator_keys  # noqa: E402

LENGTH_PREFIX_FORMAT = ">I"
LENGTH_PREFIX_SIZE = 4
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


def _encode_frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError(f"message too large: {len(payload)} bytes")
    return struct.pack(LENGTH_PREFIX_FORMAT, len(payload)) + payload


def _read_exactly(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("node1 closed the benchmark connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_frame(sock: socket.socket) -> dict[str, Any]:
    header = _read_exactly(sock, LENGTH_PREFIX_SIZE)
    (length,) = struct.unpack(LENGTH_PREFIX_FORMAT, header)
    if length <= 0 or length > MAX_MESSAGE_BYTES:
        raise ConnectionError(f"invalid frame length from node1: {length}")
    message = json.loads(_read_exactly(sock, length).decode("utf-8"))
    if not isinstance(message, dict):
        raise ConnectionError("node1 HELLO is not a JSON object")
    return message


def _synthetic_payload(size: int) -> bytes:
    """Deterministic non-medical payload used for a controlled load."""
    if size == 0:
        return b""
    prefix = b"B2-SYNTHETIC-NON-MEDICAL-PAYLOAD-"
    return (prefix + bytes((i % 251 for i in range(size))))[:size]


def _block_dir(path: Path) -> Path:
    return path if path.name == "blocks" else path / "blocks"


def _scan_local_transactions(blocks_path: Path) -> dict[str, dict[str, Any]]:
    """Return benchmark tx locations currently persisted on node1."""
    result: dict[str, dict[str, Any]] = {}
    blocks_path = _block_dir(blocks_path)
    if not blocks_path.exists():
        return result

    for path in sorted(blocks_path.glob("*.json")):
        try:
            block = Block.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError, TypeError, BlockError):
            # Atomic storage should prevent partial files; a file being
            # replaced during polling is simply retried at the next scan.
            continue
        for transaction in block.transactions:
            result[transaction.tx_id.hex()] = {
                "height": block.height,
                "block_hash": block.block_hash.hex(),
                "state_root": block.state_root.hex(),
                "block_file": str(path),
            }
    return result


def _build_transactions(
    config: NodeConfig,
    *,
    count: int,
    nonce_start: int,
    payload_size: int,
) -> list[Transaction]:
    ml_dsa = MLDSA()
    key_dir = Path(config.validator_key_dir)
    public_path = key_dir / "validator_public_key.bin"
    secret_path = key_dir / "validator_secret_key.bin"
    if not public_path.is_file() or not secret_path.is_file():
        raise RuntimeError(
            "validator keys are missing; B2 refuses to generate or replace keys"
        )
    keypair = load_or_generate_validator_keys(config.validator_key_dir, ml_dsa)
    recipient = config.authorized_validators[1 % len(config.authorized_validators)]
    payload = _synthetic_payload(payload_size)

    transactions: list[Transaction] = []
    for index in range(count):
        unsigned = Transaction.create(
            nonce=nonce_start + index,
            public_key=keypair.public_key,
            recipient=recipient,
            value=0,
            gas_limit=21_000,
            gas_price=1,
            data=payload,
        )
        transactions.append(unsigned.with_signature(ml_dsa.sign(
            unsigned.signing_hash,
            keypair.secret_key,
        )))
    return transactions


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rate", type=float, required=True,
                        help="offered rate in synthetic transactions/second")
    parser.add_argument("--duration", type=float, required=True,
                        help="T2 measurement duration in seconds")
    parser.add_argument("--payload-size", type=int, default=0,
                        help="synthetic transaction data size in bytes (default: 0)")
    parser.add_argument("--nonce-start", type=int, default=None,
                        help="first nonce; default is a time-derived unique value")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--node-id", default="benchmark-client")
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--drain-timeout", type=float, default=30.0)
    parser.add_argument("--poll-interval", type=float, default=0.05)
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="node1 data directory for local persistence observation")
    parser.add_argument("--no-local-observation", action="store_true",
                        help="do not poll node1 block files after submission")
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    if args.rate <= 0 or args.duration <= 0:
        parser.error("--rate et --duration doivent être positifs")
    if args.payload_size < 0 or args.payload_size > 1024 * 1024:
        parser.error("--payload-size doit être compris entre 0 et 1048576")
    if args.connect_timeout <= 0 or args.drain_timeout < 0 or args.poll_interval <= 0:
        parser.error("timeouts et --poll-interval invalides")
    return args


def main() -> int:
    args = _parse_args()
    config = NodeConfig.from_file(args.config)
    if config.node_id != "node1":
        raise SystemExit(
            f"B2 doit être exécuté sur la configuration node1; reçu {config.node_id!r}"
        )

    # Le nombre est fixé avant T2 : aucun pré-calcul de signature ne déborde
    # sur la fenêtre chronométrée.
    count = max(1, math.ceil(args.rate * args.duration))
    nonce_start = (
        args.nonce_start
        if args.nonce_start is not None
        else (time.time_ns() // 1_000_000) % (2**63 - count - 1)
    )
    transactions = _build_transactions(
        config,
        count=count,
        nonce_start=nonce_start,
        payload_size=args.payload_size,
    )

    host = "127.0.0.1" if config.host in {"0.0.0.0", "::"} else config.host
    sock = socket.create_connection((host, config.port), timeout=args.connect_timeout)
    sock.settimeout(args.connect_timeout)

    try:
        # SocketP2P envoie d'abord son HELLO sur une connexion entrante.
        _read_frame(sock)
        sock.sendall(_encode_frame({
            "type": "hello",
            "node_id": args.node_id,
            "listen_host": "127.0.0.1",
            "listen_port": 0,
        }))

        measurement_start_mono = time.perf_counter_ns()
        measurement_start_wall = time.time_ns()
        schedule_start_mono = time.perf_counter()
        measurement_deadline_mono = schedule_start_mono + args.duration
        next_send_mono = schedule_start_mono
        submitted: list[dict[str, Any]] = []
        interval = 1.0 / args.rate

        for index, transaction in enumerate(transactions):
            delay = next_send_mono - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

            submit_mono = time.perf_counter_ns()
            submit_wall = time.time_ns()
            sock.sendall(_encode_frame({
                "type": "tx",
                "payload": transaction.to_dict(),
            }))
            submitted.append({
                "sequence": index,
                "nonce": transaction.nonce,
                "tx_id": transaction.tx_id.hex(),
                "t_submit_monotonic_ns": submit_mono,
                "t_submit_wall_ns": submit_wall,
            })
            next_send_mono += interval

        # Keep T2 equal to the requested duration even when the last
        # scheduled transaction was sent before the end of the window.
        # This makes submitted/duration an honest offered-rate measure
        # instead of silently inflating it by one inter-arrival interval.
        tail_delay = measurement_deadline_mono - time.perf_counter()
        if tail_delay > 0:
            time.sleep(tail_delay)

        measurement_end_mono = time.perf_counter_ns()
        measurement_end_wall = time.time_ns()
    finally:
        # Toutes les trames ont été envoyées avant la fermeture. Le nœud
        # reçoit encore les octets déjà placés dans le buffer TCP.
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        sock.close()

    local_observations: dict[str, dict[str, Any]] = {}
    data_dir = args.data_dir or config.data_dir
    local_blocks_dir = _block_dir(data_dir).resolve()
    local_blocks_dir_exists_at_start = local_blocks_dir.exists()
    local_last_scan_count = 0
    drain_start_wall = time.time_ns()

    if not args.no_local_observation:
        wanted = {item["tx_id"] for item in submitted}
        deadline = time.monotonic() + args.drain_timeout
        while time.monotonic() <= deadline and len(local_observations) < len(wanted):
            locations = _scan_local_transactions(data_dir)
            local_last_scan_count = len(locations)
            now_wall = time.time_ns()
            for item in submitted:
                tx_id = item["tx_id"]
                if tx_id in wanted and tx_id not in local_observations and tx_id in locations:
                    local_observations[tx_id] = {
                        **locations[tx_id],
                        "t_observed_node1_wall_ns": now_wall,
                    }
            if len(local_observations) < len(wanted):
                time.sleep(args.poll_interval)

    drain_end_wall = time.time_ns()
    submitted_duration_s = (measurement_end_mono - measurement_start_mono) / 1e9
    manifest = {
        "benchmark": "phase8-b2-baseline",
        "benchmark_scope": (
            "three-node blockchain baseline; client sends only to node1; "
            "not a direct-to-three-nodes test"
        ),
        "run_id": args.run_id,
        "node1_config": str(args.config),
        "node1_target": f"{host}:{config.port}",
        "hostname": socket.gethostname(),
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "offered_rate_requested_tx_s": args.rate,
            "duration_requested_s": args.duration,
            "payload_size_bytes": args.payload_size,
            "warmup": "none in pilot generator; use a separate pre-run if required",
            "timer": "time.perf_counter_ns for local submission schedule",
            "transactions_pre_signed_before_t2": True,
            "synthetic_payload_only": True,
            "node1_only_ingress": True,
        },
        "timing": {
            "measurement_start_monotonic_ns": measurement_start_mono,
            "measurement_end_monotonic_ns": measurement_end_mono,
            "measurement_start_wall_ns": measurement_start_wall,
            "measurement_end_wall_ns": measurement_end_wall,
            "drain_start_wall_ns": drain_start_wall,
            "drain_end_wall_ns": drain_end_wall,
            "submitted_duration_s": submitted_duration_s,
        },
        "counts": {
            "prebuilt": len(transactions),
            "submitted": len(submitted),
            "observed_persisted_on_node1": len(local_observations),
            "local_observation_complete": len(local_observations) == len(submitted),
        },
        "transactions": submitted,
        "node1_local_observations": local_observations,
        "node1_local_observation_diagnostics": {
            "data_dir": str(Path(data_dir).resolve()),
            "blocks_dir": str(local_blocks_dir),
            "blocks_dir_exists_at_start": local_blocks_dir_exists_at_start,
            "last_scan_transaction_count": local_last_scan_count,
        },
        "secrets_policy": "validator secret key was read locally and is not serialized",
    }

    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "run_id": args.run_id,
        "submitted": len(submitted),
        "local_observed": len(local_observations),
        "submitted_duration_s": round(submitted_duration_s, 6),
        "manifest": str(args.manifest_output),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
