#!/usr/bin/env python3
"""
Phase 8 — B3 : charge et concurrence par clients logiques.

Le programme ouvre plusieurs connexions TCP indépendantes vers node1 et
répartit une séquence de transactions synthétiques entre elles. Il ne contacte
jamais node2 ou node3 directement : le scénario reste
client(s) -> node1 -> diffusion P2P.

Ce fichier est un générateur de benchmark, pas un orchestrateur de VMs : il ne
lance ni n'arrête de nœud, ne modifie ni clés ni configurations et n'applique
aucune règle réseau. Les nœuds doivent être démarrés manuellement et les blocs
sont ensuite copiés par scp pour analyse locale.

Les signatures ML-DSA sont pré-calculées avant T2, comme en B2. Les clients
logiques utilisent des plages de nonces disjointes afin de mesurer la
concurrence sans créer de conflits artificiels dans le mempool.
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LENGTH_PREFIX_SIZE = 4  # retained as a visible protocol invariant in this file


def _b2_helper(name: str):
    """Load B2 helpers lazily; local development need not have liboqs installed."""
    from scripts.experiments import benchmark_b2_baseline
    return getattr(benchmark_b2_baseline, name)


def _block_dir(path: Path) -> Path:
    return _b2_helper("_block_dir")(path)


def _build_transactions(*args, **kwargs):
    return _b2_helper("_build_transactions")(*args, **kwargs)


def _encode_frame(message: dict[str, Any]) -> bytes:
    return _b2_helper("_encode_frame")(message)


def _read_frame(sock: socket.socket) -> dict[str, Any]:
    return _b2_helper("_read_frame")(sock)


def _scan_local_transactions(path: Path) -> dict[str, dict[str, Any]]:
    return _b2_helper("_scan_local_transactions")(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rate", type=float, required=True,
                        help="total offered rate in synthetic transactions/second")
    parser.add_argument("--clients", type=int, required=True,
                        help="number of concurrent logical client connections")
    parser.add_argument("--duration", type=float, required=True,
                        help="T2 measurement duration in seconds")
    parser.add_argument("--payload-size", type=int, default=0,
                        help="synthetic transaction data size in bytes (default: 0)")
    parser.add_argument("--nonce-start", type=int, default=None,
                        help="first nonce; default is a time-derived unique value")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--drain-timeout", type=float, default=300.0)
    parser.add_argument("--poll-interval", type=float, default=0.05)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--no-local-observation", action="store_true")
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()

    if args.rate <= 0 or args.duration <= 0:
        parser.error("--rate et --duration doivent être positifs")
    if args.clients <= 0:
        parser.error("--clients doit être positif")
    if args.payload_size < 0 or args.payload_size > 1024 * 1024:
        parser.error("--payload-size doit être compris entre 0 et 1048576")
    if args.connect_timeout <= 0 or args.drain_timeout < 0 or args.poll_interval <= 0:
        parser.error("timeouts et --poll-interval invalides")
    return args


def _split_counts(total: int, clients: int) -> list[int]:
    """Distribute total transactions without changing the requested total."""
    if clients > total:
        raise ValueError(
            f"clients ({clients}) cannot exceed prebuilt transactions ({total})"
        )
    quotient, remainder = divmod(total, clients)
    return [quotient + (1 if index < remainder else 0) for index in range(clients)]


def _client_worker(
    *,
    client_index: int,
    transactions: list[Any],
    host: str,
    port: int,
    connect_timeout: float,
    ready: threading.Barrier,
    start_event: threading.Event,
    measurement_start: dict[str, int],
    rows: list[dict[str, Any]],
    rows_lock: threading.Lock,
    errors: list[dict[str, Any]],
    errors_lock: threading.Lock,
    duration: float,
) -> None:
    client_id = f"b3-client-{client_index + 1:02d}"
    sock: socket.socket | None = None
    try:
        sock = socket.create_connection((host, port), timeout=connect_timeout)
        sock.settimeout(connect_timeout)
        _read_frame(sock)
        sock.sendall(_encode_frame({
            "type": "hello",
            "node_id": client_id,
            "listen_host": "127.0.0.1",
            "listen_port": 0,
        }))

        # All client streams enter T2 together. A broken barrier means another
        # client failed before the measurement; no partial run is presented as
        # a valid B3 result.
        ready.wait(timeout=connect_timeout + 10.0)
        start_event.wait(timeout=connect_timeout + 10.0)
        start_mono = measurement_start["mono_ns"] / 1e9
        count = len(transactions)
        interval = duration / count

        for sequence, transaction in enumerate(transactions):
            target = start_mono + sequence * interval
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

            submit_mono = time.perf_counter_ns()
            submit_wall = time.time_ns()
            sock.sendall(_encode_frame({
                "type": "tx",
                "payload": transaction.to_dict(),
            }))
            row = {
                "client_id": client_id,
                "client_sequence": sequence,
                "nonce": transaction.nonce,
                "tx_id": transaction.tx_id.hex(),
                "t_submit_monotonic_ns": submit_mono,
                "t_submit_wall_ns": submit_wall,
            }
            with rows_lock:
                rows.append(row)
    except (OSError, ConnectionError, TimeoutError, threading.BrokenBarrierError) as exc:
        with errors_lock:
            errors.append({"client_id": client_id, "error": repr(exc)})
        try:
            ready.abort()
        except threading.BrokenBarrierError:
            pass
    finally:
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def main() -> int:
    args = _parse_args()
    from src.node.config import NodeConfig

    config = NodeConfig.from_file(args.config)
    if config.node_id != "node1":
        raise SystemExit(
            f"B3 doit être exécuté avec la configuration node1; reçu {config.node_id!r}"
        )

    count = max(1, math.ceil(args.rate * args.duration))
    if args.clients > count:
        raise SystemExit(
            f"--clients ({args.clients}) ne peut pas dépasser les {count} "
            "transactions préconstruites"
        )

    nonce_start = (
        args.nonce_start
        if args.nonce_start is not None
        else (time.time_ns() // 1_000_000) % (2**63 - count - 1)
    )
    counts = _split_counts(count, args.clients)
    transactions_by_client: list[list[Any]] = []
    next_nonce = nonce_start
    for client_count in counts:
        client_transactions = _build_transactions(
            config,
            count=client_count,
            nonce_start=next_nonce,
            payload_size=args.payload_size,
        )
        transactions_by_client.append(client_transactions)
        next_nonce += client_count

    host = "127.0.0.1" if config.host in {"0.0.0.0", "::"} else config.host
    ready = threading.Barrier(args.clients + 1)
    start_event = threading.Event()
    measurement_start: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    rows_lock = threading.Lock()
    errors: list[dict[str, Any]] = []
    errors_lock = threading.Lock()

    threads = [
        threading.Thread(
            target=_client_worker,
            kwargs={
                "client_index": index,
                "transactions": transactions_by_client[index],
                "host": host,
                "port": config.port,
                "connect_timeout": args.connect_timeout,
                "ready": ready,
                "start_event": start_event,
                "measurement_start": measurement_start,
                "rows": rows,
                "rows_lock": rows_lock,
                "errors": errors,
                "errors_lock": errors_lock,
                "duration": args.duration,
            },
            name=f"{args.run_id}-client-{index + 1:02d}",
        )
        for index in range(args.clients)
    ]

    for thread in threads:
        thread.start()

    measurement_start["mono_ns"] = time.perf_counter_ns()
    measurement_start["wall_ns"] = time.time_ns()
    try:
        ready.wait(timeout=args.connect_timeout + 10.0)
        start_event.set()
    except threading.BrokenBarrierError as exc:
        with errors_lock:
            errors.append({"client_id": "coordinator", "error": repr(exc)})
        start_event.set()

    for thread in threads:
        thread.join(timeout=args.duration + args.connect_timeout + 20.0)

    measurement_end_mono = time.perf_counter_ns()
    measurement_end_wall = time.time_ns()
    rows.sort(key=lambda row: (row["t_submit_monotonic_ns"], row["client_id"]))

    data_dir = args.data_dir or config.data_dir
    local_observations: dict[str, dict[str, Any]] = {}
    local_blocks_dir = _block_dir(data_dir).resolve()
    local_blocks_dir_exists_at_start = local_blocks_dir.exists()
    local_last_scan_count = 0
    drain_start_wall = time.time_ns()

    if not args.no_local_observation and not errors:
        wanted = {row["tx_id"] for row in rows}
        deadline = time.monotonic() + args.drain_timeout
        while time.monotonic() <= deadline and len(local_observations) < len(wanted):
            locations = _scan_local_transactions(data_dir)
            local_last_scan_count = len(locations)
            now_wall = time.time_ns()
            for tx_id in wanted - local_observations.keys():
                if tx_id in locations:
                    local_observations[tx_id] = {
                        **locations[tx_id],
                        "t_observed_node1_wall_ns": now_wall,
                    }
            if len(local_observations) < len(wanted):
                time.sleep(args.poll_interval)

    drain_end_wall = time.time_ns()
    submitted_duration_s = args.duration
    manifest = {
        "benchmark": "phase8-b3-client-concurrency",
        "benchmark_scope": (
            "logical concurrent client streams; every stream sends only to node1; "
            "node2 and node3 receive transactions through normal P2P relay"
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
            "logical_clients": args.clients,
            "transactions_pre_signed_before_t2": True,
            "synthetic_payload_only": True,
            "node1_only_ingress": True,
            "nonce_ranges_disjoint_by_client": True,
        },
        "timing": {
            "measurement_start_monotonic_ns": measurement_start.get("mono_ns"),
            "measurement_end_monotonic_ns": measurement_end_mono,
            "measurement_start_wall_ns": measurement_start.get("wall_ns"),
            "measurement_end_wall_ns": measurement_end_wall,
            "drain_start_wall_ns": drain_start_wall,
            "drain_end_wall_ns": drain_end_wall,
            "submitted_duration_s": submitted_duration_s,
        },
        "counts": {
            "prebuilt": count,
            "submitted": len(rows),
            "observed_persisted_on_node1": len(local_observations),
            "local_observation_complete": len(local_observations) == len(rows),
        },
        "client_allocation": {
            f"b3-client-{index + 1:02d}": allocation
            for index, allocation in enumerate(counts)
        },
        "transactions": rows,
        "node1_local_observations": local_observations,
        "node1_local_observation_diagnostics": {
            "data_dir": str(Path(data_dir).resolve()),
            "blocks_dir": str(local_blocks_dir),
            "blocks_dir_exists_at_start": local_blocks_dir_exists_at_start,
            "last_scan_transaction_count": local_last_scan_count,
        },
        "errors": errors,
        "secrets_policy": "validator secret key was read locally and is not serialized",
    }

    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "run_id": args.run_id,
        "clients": args.clients,
        "submitted": len(rows),
        "local_observed": len(local_observations),
        "errors": errors,
        "manifest": str(args.manifest_output),
    }, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
