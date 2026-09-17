#!/usr/bin/env python3
"""
Analyse une exécution B2 à partir du manifeste node1 et des répertoires de
blocs copiés depuis node1, node2 et node3.

Ce post-traitement ne se connecte à aucune VM et ne modifie aucun fichier
source. Il compte uniquement les transactions synthétiques du manifeste,
compare les blocs persistés et vérifie la convergence par hauteur, hash de bloc
et state_root.

Exemple :
    PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py \
        --manifest results/raw_data/b2-pilot-r02-node1-manifest.json \
        --node1-blocks /tmp/b2-pilot-r02/node1/blocks \
        --node2-blocks /tmp/b2-pilot-r02/node2/blocks \
        --node3-blocks /tmp/b2-pilot-r02/node3/blocks \
        --node1-log /tmp/b2-pilot-r02/node1.log \
        --node2-log /tmp/b2-pilot-r02/node2.log \
        --node3-log /tmp/b2-pilot-r02/node3.log \
        --output results/raw_data/b2-pilot-r02-summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.blockchain.block import Block, BlockError  # noqa: E402


def _resolve_blocks_dir(path: Path) -> Path:
    return path if path.name == "blocks" else path / "blocks"


def _load_chain(path: Path) -> tuple[dict[int, Block], list[str]]:
    blocks_dir = _resolve_blocks_dir(path)
    chain: dict[int, Block] = {}
    errors: list[str] = []
    for block_path in sorted(blocks_dir.glob("*.json")):
        try:
            raw = json.loads(block_path.read_text(encoding="utf-8"))
            block = Block.from_dict(raw)
        except (OSError, json.JSONDecodeError, ValueError, TypeError, BlockError) as exc:
            errors.append(f"{block_path}: {exc}")
            continue
        chain[block.height] = block
    return chain, errors


def _tx_locations(chain: dict[int, Block], wanted: set[str]) -> dict[str, list[dict[str, Any]]]:
    locations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for height, block in sorted(chain.items()):
        for transaction in block.transactions:
            tx_id = transaction.tx_id.hex()
            if tx_id in wanted:
                locations[tx_id].append({
                    "height": height,
                    "block_hash": block.block_hash.hex(),
                    "state_root": block.state_root.hex(),
                    "transaction_index": list(block.transactions).index(transaction),
                })
    return dict(locations)


def _parse_node1_acceptance_log(
    path: Path | None,
    wanted: set[str],
) -> dict[str, Any]:
    """Count direct node1 acceptance/rejection events for benchmark tx_ids."""
    if path is None:
        return {
            "status": "not_provided",
            "log_path": None,
            "accepted_ids": [],
            "rejected_ids": [],
            "accepted_count": None,
            "rejected_count": None,
            "accept_wall_ns": {},
        }

    accepted: dict[str, int] = {}
    rejected: set[str] = set()
    errors: list[str] = []
    accept_pattern = re.compile(
        r"BENCHMARK_ACCEPT\s+accept_wall_ns=(\d+)\s+tx_id=([0-9a-f]{64})"
    )
    reject_pattern = re.compile(
        r"BENCHMARK_REJECT\s+reject_wall_ns=(\d+)\s+tx_id=([0-9a-f]{64})"
    )
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            accepted_match = accept_pattern.search(line)
            if accepted_match:
                timestamp_ns = int(accepted_match.group(1))
                tx_id = accepted_match.group(2)
                if tx_id in wanted:
                    accepted.setdefault(tx_id, timestamp_ns)
                continue
            rejected_match = reject_pattern.search(line)
            if rejected_match:
                tx_id = rejected_match.group(2)
                if tx_id in wanted:
                    rejected.add(tx_id)
    except OSError as exc:
        errors.append(str(exc))

    effective_rejected = rejected - set(accepted)
    return {
        "status": "measured" if not errors else "error",
        "log_path": str(path),
        "accepted_ids": sorted(accepted),
        "rejected_ids": sorted(effective_rejected),
        "accepted_count": len(accepted),
        "rejected_count": len(effective_rejected),
        "accept_wall_ns": accepted,
        "errors": errors,
    }


def _parse_commit_log(
    path: Path | None,
    wanted: set[str],
) -> dict[str, Any]:
    """Read BENCHMARK_COMMIT events for the benchmark transaction ids."""
    if path is None:
        return {
            "status": "not_provided",
            "log_path": None,
            "events": {},
            "errors": [],
        }

    events: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    pattern = re.compile(
        r"BENCHMARK_COMMIT\s+commit_wall_ns=(\d+)\s+height=(\d+)\s+"
        r"block_hash=([0-9a-f]{64})\s+state_root=([0-9a-f]{64})\s+"
        r"tx_count=(\d+)\s+tx_ids=([0-9a-f,-]+)"
    )
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = pattern.search(line)
            if not match:
                continue
            commit_wall_ns = int(match.group(1))
            height = int(match.group(2))
            block_hash = match.group(3)
            state_root = match.group(4)
            tx_count = int(match.group(5))
            tx_ids = [tx_id for tx_id in match.group(6).split(",") if tx_id != "-"]
            for tx_id in tx_ids:
                if tx_id in wanted:
                    events.setdefault(tx_id, {
                        "commit_wall_ns": commit_wall_ns,
                        "height": height,
                        "block_hash": block_hash,
                        "state_root": state_root,
                        "tx_count": tx_count,
                    })
    except OSError as exc:
        errors.append(str(exc))

    return {
        "status": "measured" if not errors else "error",
        "log_path": str(path),
        "events": events,
        "errors": errors,
    }


def _sample_summary(samples_ms: list[float], *, status: str = "measured") -> dict[str, Any]:
    samples_ms = sorted(samples_ms)
    if not samples_ms:
        return {
            "status": "not_measured" if status == "measured" else status,
            "unit": "ms",
            "observed_count": 0,
            "samples": [],
            "min": None,
            "p50": None,
            "p95": None,
            "max": None,
        }

    def percentile(percent: float) -> float:
        index = min(len(samples_ms) - 1, max(0, int((len(samples_ms) - 1) * percent)))
        return samples_ms[index]

    return {
        "status": status,
        "unit": "ms",
        "observed_count": len(samples_ms),
        "samples": samples_ms,
        "min": samples_ms[0],
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "max": samples_ms[-1],
    }


def _local_accept_to_commit_latency_summary(
    accept_log: dict[str, Any],
    commit_log: dict[str, Any],
) -> dict[str, Any]:
    """Measure local acceptance-to-commit time on one VM.

    Both timestamps come from the same node, so this metric does not
    require synchronised clocks. It is not end-to-end client latency.
    """
    accept_times = accept_log.get("accept_wall_ns", {})
    commit_events = commit_log.get("events", {})
    samples_ms = [
        (commit_events[tx_id]["commit_wall_ns"] - accept_times[tx_id]) / 1e6
        for tx_id in set(accept_times) & set(commit_events)
    ]
    summary = _sample_summary(samples_ms)
    summary["source"] = "same-node BENCHMARK_COMMIT commit_wall_ns minus BENCHMARK_ACCEPT accept_wall_ns"
    summary["not_end_to_end_client_latency"] = True
    return summary


def _node1_commit_latency_summary(
    manifest: dict[str, Any],
    commit_events: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    submit_wall_by_tx = {
        row.get("tx_id"): row.get("t_submit_wall_ns")
        for row in manifest.get("transactions", [])
        if row.get("tx_id")
    }
    samples_ms = [
        (event["commit_wall_ns"] - submit_wall_by_tx[tx_id]) / 1e6
        for tx_id, event in commit_events.items()
        if isinstance(submit_wall_by_tx.get(tx_id), int)
    ]
    summary = _sample_summary(samples_ms)
    summary["source"] = "node1 BENCHMARK_COMMIT commit_wall_ns minus manifest t_submit_wall_ns"
    summary["missing_submission_time_count"] = len(commit_events) - len(samples_ms)
    return summary


def _convergence_latency_summary(
    commit_logs: dict[str, dict[str, Any]],
    *,
    clocks_synchronised: bool,
) -> dict[str, Any]:
    if not clocks_synchronised:
        return {
            "status": "not_measured",
            "reason": "commit_wall_ns values are local to each VM; pass --clocks-synchronised only after an independent clock-synchronisation check",
            "source": "BENCHMARK_COMMIT commit_wall_ns",
        }

    if any(log["status"] == "not_provided" for log in commit_logs.values()):
        return {
            "status": "not_measured",
            "reason": "node1, node2 and node3 commit logs are required",
            "source": "BENCHMARK_COMMIT commit_wall_ns",
        }

    tx_sets = [set(log["events"]) for log in commit_logs.values()]
    common_tx_ids = set.intersection(*tx_sets) if tx_sets else set()
    samples_ms = []
    for tx_id in common_tx_ids:
        timestamps = [
            log["events"][tx_id]["commit_wall_ns"]
            for log in commit_logs.values()
        ]
        samples_ms.append((max(timestamps) - min(timestamps)) / 1e6)

    summary = _sample_summary(samples_ms)
    summary["source"] = "max/min BENCHMARK_COMMIT commit_wall_ns across node1/node2/node3"
    summary["common_transaction_count"] = len(common_tx_ids)
    return summary


def _latency_summary(manifest: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    """Compute node1 inclusion latencies when the local observer captured them."""
    submit_wall_by_tx = {
        row.get("tx_id"): row.get("t_submit_wall_ns")
        for row in manifest.get("transactions", [])
        if row.get("tx_id")
    }
    samples_ms: list[float] = []
    missing_submission_time = 0
    for tx_id, observation in observations.items():
        submit_wall = submit_wall_by_tx.get(tx_id)
        observed_wall = observation.get("t_observed_node1_wall_ns")
        if not isinstance(submit_wall, int) or not isinstance(observed_wall, int):
            missing_submission_time += 1
            continue
        samples_ms.append((observed_wall - submit_wall) / 1e6)

    samples_ms.sort()
    if not samples_ms:
        return {
            "status": "not_measured",
            "unit": "ms",
            "observed_count": 0,
            "missing_submission_time_count": missing_submission_time,
            "samples": [],
            "min": None,
            "p50": None,
            "p95": None,
            "max": None,
        }

    def percentile(percent: float) -> float:
        index = min(len(samples_ms) - 1, max(0, int((len(samples_ms) - 1) * percent)))
        return samples_ms[index]

    return {
        "status": "measured",
        "unit": "ms",
        "observed_count": len(samples_ms),
        "missing_submission_time_count": missing_submission_time,
        "samples": samples_ms,
        "min": samples_ms[0],
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "max": samples_ms[-1],
    }


def _chain_convergence(chains: dict[str, dict[int, Block]]) -> dict[str, Any]:
    if not chains or any(not chain for chain in chains.values()):
        return {
            "common_prefix_height": None,
            "min_tip_height": None,
            "all_same_to_min_tip": False,
            "per_height_until_first_divergence": [],
        }
    min_tip = min(max(chain) for chain in chains.values())
    common_prefix = -1
    per_height: list[dict[str, Any]] = []
    for height in range(min_tip + 1):
        blocks = [chain[height] for chain in chains.values() if height in chain]
        same_hash = len(blocks) == len(chains) and len({b.block_hash for b in blocks}) == 1
        same_state_root = len(blocks) == len(chains) and len({b.state_root for b in blocks}) == 1
        per_height.append({
            "height": height,
            "same_block_hash": same_hash,
            "same_state_root": same_state_root,
            "block_hashes": {name: chains[name][height].block_hash.hex() for name in chains if height in chains[name]},
            "state_roots": {name: chains[name][height].state_root.hex() for name in chains if height in chains[name]},
        })
        if same_hash and same_state_root:
            common_prefix = height
        else:
            break
    return {
        "min_tip_height": min_tip,
        "common_prefix_height": common_prefix,
        "all_same_to_min_tip": common_prefix == min_tip,
        "per_height_until_first_divergence": per_height,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--node1-blocks", type=Path, required=True)
    parser.add_argument("--node2-blocks", type=Path, required=True)
    parser.add_argument("--node3-blocks", type=Path, required=True)
    parser.add_argument(
        "--node1-log",
        type=Path,
        default=None,
        help="node1 log containing BENCHMARK_ACCEPT/REJECT/COMMIT events",
    )
    parser.add_argument("--node2-log", type=Path, default=None)
    parser.add_argument("--node3-log", type=Path, default=None)
    parser.add_argument(
        "--clocks-synchronised",
        action="store_true",
        help="allow numeric inter-VM convergence latency after an independent clock check",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    transaction_rows = manifest.get("transactions", [])
    wanted = {row["tx_id"] for row in transaction_rows}
    if len(wanted) != len(transaction_rows):
        raise SystemExit("manifest contains duplicate tx_id values")

    log_paths = {
        "node1": args.node1_log,
        "node2": args.node2_log,
        "node3": args.node3_log,
    }
    acceptance_logs = {
        name: _parse_node1_acceptance_log(path, wanted)
        for name, path in log_paths.items()
    }
    acceptance_log = acceptance_logs["node1"]
    commit_logs = {
        name: _parse_commit_log(path, wanted)
        for name, path in log_paths.items()
    }

    chain_paths = {
        "node1": args.node1_blocks,
        "node2": args.node2_blocks,
        "node3": args.node3_blocks,
    }
    chains: dict[str, dict[int, Block]] = {}
    load_errors: dict[str, list[str]] = {}
    for name, path in chain_paths.items():
        chains[name], load_errors[name] = _load_chain(path)

    locations = {
        name: _tx_locations(chain, wanted)
        for name, chain in chains.items()
    }
    included_counts = {name: len(found) for name, found in locations.items()}
    included_on_all = sorted(
        tx_id for tx_id in wanted
        if all(tx_id in locations[name] for name in locations)
    )
    duplicates = {
        name: {
            tx_id: entries
            for tx_id, entries in locations[name].items()
            if len(entries) > 1
        }
        for name in locations
    }

    timing = manifest.get("timing", {})
    submitted_duration_s = float(timing.get("submitted_duration_s", 0.0) or 0.0)
    submitted = len(transaction_rows)
    committed_all = len(included_on_all)
    offered_rate = submitted / submitted_duration_s if submitted_duration_s > 0 else None
    committed_tps = committed_all / submitted_duration_s if submitted_duration_s > 0 else None

    chain_summary: dict[str, Any] = {}
    for name, chain in chains.items():
        heights = sorted(chain)
        bench_heights = sorted({entry["height"] for tx in locations[name].values() for entry in tx})
        tx_per_bench_block = Counter(
            entry["height"] for tx in locations[name].values() for entry in tx
        )
        chain_summary[name] = {
            "tip_height": heights[-1] if heights else None,
            "block_count": len(chain),
            "benchmark_transactions_included": included_counts[name],
            "benchmark_block_heights": bench_heights,
            "benchmark_transactions_per_block": dict(sorted(tx_per_bench_block.items())),
            "load_errors": load_errors[name],
        }

    final_chain: dict[str, Any] = {}
    for name, chain in chains.items():
        if not chain:
            final_chain[name] = None
            continue
        tip_height = max(chain)
        tip = chain[tip_height]
        final_chain[name] = {
            "height": tip.height,
            "block_hash": tip.block_hash.hex(),
            "state_root": tip.state_root.hex(),
            "transaction_count": tip.transaction_count,
        }

    node1_observations = manifest.get("node1_local_observations", {})
    if not isinstance(node1_observations, dict):
        node1_observations = {}
    observation_inclusion_latency = _latency_summary(manifest, node1_observations)
    node1_commit_latency = _node1_commit_latency_summary(
        manifest,
        commit_logs["node1"]["events"],
    )
    local_accept_to_commit_latency = {
        name: _local_accept_to_commit_latency_summary(
            acceptance_logs[name],
            commit_logs[name],
        )
        for name in ("node1", "node2", "node3")
    }
    inclusion_latency = (
        node1_commit_latency
        if node1_commit_latency["status"] == "measured"
        else observation_inclusion_latency
    )
    convergence = _chain_convergence(chains)
    convergence_latency = _convergence_latency_summary(
        commit_logs,
        clocks_synchronised=args.clocks_synchronised,
    )
    result = {
        "benchmark": "phase8-b2-baseline-analysis",
        "run_id": manifest.get("run_id"),
        "source_manifest": str(args.manifest),
        "scope": {
            "ingress": "node1 only",
            "p2p_path": "node1 -> peers",
            "payload": "synthetic controlled data only",
            "tps_definition": "benchmark transactions included on all three nodes / submitted measurement duration",
        },
        "counts": {
            "submitted": submitted,
            "included_node1": included_counts["node1"],
            "included_node2": included_counts["node2"],
            "included_node3": included_counts["node3"],
            "included_on_all_three": committed_all,
            "missing_on_all_three": submitted - committed_all,
            "duplicate_locations": {name: len(value) for name, value in duplicates.items()},
        },
        "acceptance": {
            "accepted_by_node1_direct_observation": acceptance_log["accepted_count"],
            "accepted_by_node1_direct_observation_note": (
                "Counted from BENCHMARK_ACCEPT events in the optional node1 log; "
                "null means no log was supplied."
            ),
            "accepted_by_node1_inferred_lower_bound": included_counts["node1"],
            "inferred_from_node1_block_inclusion": True,
            "rejected_by_node1_direct_observation": acceptance_log["rejected_count"],
            "local_acceptance_observation_by_node": {
                name: {
                    "accepted_count": logs["accepted_count"],
                    "rejected_count": logs["rejected_count"],
                    "status": logs["status"],
                }
                for name, logs in acceptance_logs.items()
            },
            "log": acceptance_log,
        },
        "rates": {
            "offered_rate_from_manifest_tx_s": offered_rate,
            "accepted_rate_node1_direct_observation": (
                acceptance_log["accepted_count"] / submitted
                if isinstance(acceptance_log["accepted_count"], int) and submitted
                else None
            ),
            "committed_tps_all_three_over_submission_window": committed_tps,
            "success_rate_all_three": committed_all / submitted if submitted else None,
        },
        "success_failure": {
            "committed_on_all_three": committed_all,
            "not_committed_on_all_three": submitted - committed_all,
            "rejected_by_node1_direct_observation": acceptance_log["rejected_count"],
            "note": "success means presence on all three persisted chains; no separate EVM receipt status is available here",
        },
        "backlog": {
            "benchmark_transactions_not_committed_on_all_three": submitted - committed_all,
            "node1_local_observation_missing": submitted - len(node1_observations),
            "final_mempool_size_observed": None,
        },
        "latencies": {
            "node1_inclusion": inclusion_latency,
            "node1_local_file_observation": observation_inclusion_latency,
            "node1_commit_event": node1_commit_latency,
            "per_node_local_accept_to_commit": local_accept_to_commit_latency,
            "convergence": convergence_latency,
        },
        "timing": timing,
        "per_node": chain_summary,
        "final_chain": final_chain,
        "transaction_locations": locations,
        "duplicates": duplicates,
        "convergence": convergence,
        "validity": {
            "all_submitted_present_on_all_three": committed_all == submitted,
            "no_benchmark_transaction_duplicate_on_any_node": not any(duplicates.values()),
            "three_node_chain_converged_to_min_tip": convergence.get("all_same_to_min_tip", False),
            "load_files_valid": not any(load_errors.values()),
        },
        "interpretation": {
            "accepted_rate_not_observed": acceptance_log["accepted_count"] is None,
            "remote_commit_times_not_inferred_from_unsynchronised_clocks": True,
            "local_node1_persistence_observations_nonempty": bool(node1_observations),
            "not_a_mlkem_or_aesgcm_measurement": True,
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "run_id": result["run_id"],
        "submitted": submitted,
        "included_on_all_three": committed_all,
        "success_rate_all_three": result["rates"]["success_rate_all_three"],
        "committed_tps_all_three_over_submission_window": committed_tps,
        "converged_to_min_tip": convergence.get("all_same_to_min_tip"),
        "output": str(args.output),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
