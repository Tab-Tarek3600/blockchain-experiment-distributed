#!/usr/bin/env python3
"""B8-C: mesure IPFS locale sur une VM.

Ce script ne démarre ni n'arrête de processus, ne modifie pas la blockchain,
ne touche pas aux clés et n'applique aucune règle réseau. Il utilise uniquement
l'API Kubo loopback de la VM courante.

Commandes :
  precheck  : contrôles en lecture seule et JSON de pré-vérification
  seed      : ajoute deux ciphertexts synthétiques sur node1 et écrit un manifeste
  measure   : réplique les CIDs puis mesure cat/has/pin_add/pin_ls localement
              pendant 30 échantillons (ou --samples demandé)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Permet l'exécution directe depuis le dépôt distant.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ipfs import IPFSClient  # noqa: E402

DEFAULT_API = "http://127.0.0.1:5001/api/v0"
DEFAULT_TIMEOUT = 120.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_command(args: list[str], timeout: float = 10.0) -> str:
    try:
        completed = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"ERROR: {exc}"


def find_kubo_pids() -> list[int]:
    pids: list[int] = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                errors="replace"
            )
        except (OSError, ValueError):
            continue
        lower = cmdline.lower()
        if ("ipfs" in lower or "kubo" in lower) and "daemon" in lower:
            pids.append(int(entry.name))
    return sorted(set(pids))


def read_proc_status(pid: int) -> dict[str, Any]:
    result: dict[str, Any] = {"pid": pid}
    try:
        for line in (Path(f"/proc/{pid}/status")).read_text(errors="replace").splitlines():
            if line.startswith(("VmRSS:", "VmSize:", "Threads:", "voluntary_ctxt_switches:", "nonvoluntary_ctxt_switches:")):
                key, value = line.split(":", 1)
                result[key] = value.strip()
    except OSError as exc:
        result["error"] = str(exc)
    return result


def memory_events() -> dict[str, str]:
    for candidate in (Path("/sys/fs/cgroup/memory.events"), Path("/sys/fs/cgroup/memory/memory.failcnt")):
        if candidate.exists():
            try:
                text = candidate.read_text(errors="replace").strip()
                if candidate.name == "memory.events":
                    return dict(
                        line.split(maxsplit=1) if len(line.split(maxsplit=1)) == 2 else (line, "")
                        for line in text.splitlines()
                    )
                return {"memory.failcnt": text}
            except OSError as exc:
                return {"error": str(exc)}
    return {"unavailable": "cgroup memory events not readable"}


def resource_snapshot() -> dict[str, Any]:
    return {
        "timestamp": utc_now(),
        "hostname": socket.gethostname(),
        "kubo_pids": [read_proc_status(pid) for pid in find_kubo_pids()],
        "memory_events": memory_events(),
        "free_h": run_command(["free", "-h"]),
        "disk_ipfs": run_command(["df", "-h", "/var/lib/ipfs"]),
        "oom_errors_last_24h": run_command(
            ["sh", "-c", "dmesg --level=err,crit,alert,emerg --since '24 hours ago' 2>/dev/null | grep -i oom | tail -20 || true"]
        ),
    }


def api_call(client: IPFSClient, operation: str, **params: Any) -> Any:
    response = client.session.post(
        f"{client.api_url}/{operation}",
        params=params,
        timeout=client.timeout,
    )
    if not response.ok:
        detail = response.text.strip()[:500]
        raise RuntimeError(f"Kubo {operation} HTTP {response.status_code}: {detail}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def api_version_and_id(client: IPFSClient) -> dict[str, Any]:
    return {
        "version": api_call(client, "version"),
        "id": api_call(client, "id"),
    }


def synthetic_ciphertext(version: str) -> bytes:
    """Produit exactement 128 octets explicitement synthétiques."""
    prefix = f"PHASE8-B8C-SYNTHETIC-CIPHERTEXT-{version}-20260916|".encode("ascii")
    material = prefix + hashlib.sha256(prefix).digest() + hashlib.sha512(prefix).digest() * 3
    return material[:128]


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def timed(call: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        value = call()
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        return {"success": True, "duration_ms": elapsed_ms, "value": value}
    except Exception as exc:  # conserver l'erreur dans l'artefact même si un échantillon échoue
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        return {"success": False, "duration_ms": elapsed_ms, "error": f"{type(exc).__name__}: {exc}"}


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def operation_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [float(item["duration_ms"]) for item in samples if item.get("success")]
    failures = [item for item in samples if not item.get("success")]
    return {
        "samples": len(samples),
        "successes": len(successes),
        "failures": len(failures),
        "min_ms": min(successes) if successes else None,
        "mean_ms": (sum(successes) / len(successes)) if successes else None,
        "p50_ms": percentile(successes, 0.50),
        "p95_ms": percentile(successes, 0.95),
        "max_ms": max(successes) if successes else None,
        "errors": [item.get("error") for item in failures[:5]],
        "durations_ms": [round(value, 6) for value in successes],
    }


def cmd_precheck(args: argparse.Namespace) -> int:
    client = IPFSClient(args.api, timeout=args.timeout)
    result: dict[str, Any] = {
        "schema_version": "b8c-precheck-v1",
        "timestamp": utc_now(),
        "node": args.node,
        "api_url": args.api,
        "api_loopback_used": args.api.startswith("http://127.0.0.1:") or args.api.startswith("http://localhost:"),
    }
    try:
        result["kubo"] = api_version_and_id(client)
        result["api_ok"] = True
    except Exception as exc:
        result["api_ok"] = False
        result["api_error"] = f"{type(exc).__name__}: {exc}"
    result["listeners"] = run_command(["sh", "-c", "ss -ltn 2>/dev/null | grep -E ':(4001|5001)\\b' || true"])
    result["resources"] = resource_snapshot()
    client.close()
    write_json(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("api_ok") else 2


def cmd_seed(args: argparse.Namespace) -> int:
    client = IPFSClient(args.api, timeout=args.timeout)
    result: dict[str, Any] = {
        "schema_version": "b8c-manifest-v1",
        "run_id": "b8c-ipfs-20260916",
        "created_at": utc_now(),
        "source_node": args.node,
        "api_url": args.api,
        "synthetic_only": True,
        "size_bytes_expected": 128,
        "versions": {},
    }
    try:
        result["kubo"] = api_version_and_id(client)
        for version in ("v1", "v2"):
            payload = synthetic_ciphertext(version)
            started = time.perf_counter_ns()
            cid = client.add_encrypted_file(payload, filename=f"b8c-{version}-synthetic-ciphertext.bin")
            add_ms = (time.perf_counter_ns() - started) / 1_000_000
            get_result = timed(lambda cid=cid: client.get_file(cid))
            if not get_result.get("success"):
                raise RuntimeError(f"cat après add échoué pour {version}: {get_result.get('error')}")
            raw = get_result["value"]
            if raw != payload:
                raise RuntimeError(f"intégrité locale échouée pour {version}")
            pin_result = timed(lambda cid=cid: client.pin(cid))
            if not pin_result.get("success"):
                raise RuntimeError(f"pin local échoué pour {version}: {pin_result.get('error')}")
            result["versions"][version] = {
                "cid": cid,
                "sha256": sha256_hex(payload),
                "size_bytes": len(payload),
                "filename": f"b8c-{version}-synthetic-ciphertext.bin",
                "add_latency_ms": add_ms,
                "cat_verify_latency_ms": get_result["duration_ms"],
                "pin_add_latency_ms": pin_result["duration_ms"],
            }
        result["cid_v1_ne_cid_v2"] = result["versions"]["v1"]["cid"] != result["versions"]["v2"]["cid"]
        result["sha256_v1_ne_sha256_v2"] = result["versions"]["v1"]["sha256"] != result["versions"]["v2"]["sha256"]
        result["seed_ok"] = bool(result["cid_v1_ne_cid_v2"] and result["sha256_v1_ne_sha256_v2"])
    except Exception as exc:
        result["seed_ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        client.close()
    write_json(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("seed_ok") else 2


def check_pin_ls(client: IPFSClient, cid: str) -> Any:
    payload = api_call(client, "pin/ls", arg=cid)
    if isinstance(payload, dict) and isinstance(payload.get("Keys"), dict):
        if cid not in payload["Keys"]:
            raise RuntimeError(f"CID absent de pin/ls: {cid}")
    return payload


def cmd_measure(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    client = IPFSClient(args.api, timeout=args.timeout)
    result: dict[str, Any] = {
        "schema_version": "b8c-provider-result-v1",
        "run_id": manifest.get("run_id", "b8c-ipfs-20260916"),
        "measured_at": utc_now(),
        "node": args.node,
        "api_url": args.api,
        "manifest_source_node": manifest.get("source_node"),
        "samples_per_operation_requested": args.samples,
        "synthetic_only": True,
        "kubo": {},
        "resource_before": resource_snapshot(),
        "versions": {},
        "errors": [],
    }
    try:
        result["kubo"] = api_version_and_id(client)
    except Exception as exc:
        result["errors"].append(f"Kubo precheck: {type(exc).__name__}: {exc}")

    for version, expected in manifest.get("versions", {}).items():
        cid = expected["cid"]
        version_result: dict[str, Any] = {
            "cid": cid,
            "expected_sha256": expected.get("sha256"),
            "expected_size_bytes": expected.get("size_bytes"),
            "replication_fetch": {},
            "integrity": {},
            "operations": {},
        }
        fetch = timed(lambda cid=cid: client.get_file(cid))
        version_result["replication_fetch"] = {
            key: value for key, value in fetch.items() if key != "value"
        }
        if fetch.get("success"):
            raw = fetch["value"]
            actual_sha = sha256_hex(raw)
            actual_size = len(raw)
            version_result["integrity"] = {
                "sha256": actual_sha,
                "size_bytes": actual_size,
                "sha256_matches": actual_sha == expected.get("sha256"),
                "size_matches": actual_size == expected.get("size_bytes"),
                "bytes_match": actual_sha == expected.get("sha256") and actual_size == expected.get("size_bytes"),
            }
        else:
            version_result["integrity"] = {"bytes_match": False}
            result["errors"].append(f"{args.node}/{version}: réplication/cat initial échoué")

        operations: dict[str, Callable[[], Any]] = {
            "cat_local": lambda cid=cid: client.get_file(cid),
            "has_block_stat": lambda cid=cid: True if client.has(cid) else (_ for _ in ()).throw(RuntimeError("block absent")),
            "pin_add": lambda cid=cid: client.pin(cid),
            "pin_ls": lambda cid=cid: check_pin_ls(client, cid),
        }
        for name, operation in operations.items():
            samples = [timed(operation) for _ in range(args.samples)]
            version_result["operations"][name] = operation_summary(samples)
        result["versions"][version] = version_result

    result["resource_after"] = resource_snapshot()
    result["all_integrity_ok"] = all(
        value.get("integrity", {}).get("bytes_match") is True
        for value in result["versions"].values()
    ) and bool(result["versions"])
    result["all_operations_successful"] = all(
        operation.get("failures", 1) == 0
        for version in result["versions"].values()
        for operation in version.get("operations", {}).values()
    ) and bool(result["versions"])
    result["ok"] = bool(
        result["all_integrity_ok"] and result["all_operations_successful"] and not result["errors"]
    )
    client.close()
    write_json(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API, help="API Kubo loopback")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    sub = parser.add_subparsers(dest="command", required=True)

    precheck = sub.add_parser("precheck")
    precheck.add_argument("--node", required=True)
    precheck.add_argument("--output", required=True)
    precheck.set_defaults(func=cmd_precheck)

    seed = sub.add_parser("seed")
    seed.add_argument("--node", required=True)
    seed.add_argument("--output", required=True)
    seed.set_defaults(func=cmd_seed)

    measure = sub.add_parser("measure")
    measure.add_argument("--node", required=True)
    measure.add_argument("--manifest", required=True)
    measure.add_argument("--output", required=True)
    measure.add_argument("--samples", type=int, default=30)
    measure.set_defaults(func=cmd_measure)
    return parser


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    raise SystemExit(arguments.func(arguments))
