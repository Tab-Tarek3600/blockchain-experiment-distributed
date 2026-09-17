#!/usr/bin/env python3
"""Construit le résumé B8-C à partir des trois JSON fournisseurs."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_operation(value: dict[str, Any]) -> dict[str, Any]:
    keys = ("samples", "successes", "failures", "min_ms", "mean_ms", "p50_ms", "p95_ms", "max_ms")
    return {key: value.get(key) for key in keys}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", nargs=3, metavar="JSON", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--analysis-output", required=True)
    args = parser.parse_args()

    documents: list[dict[str, Any]] = []
    for path in args.input:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        document["_input_path"] = path
        documents.append(document)

    expected_cids: dict[str, str] = {}
    expected_hashes: dict[str, str] = {}
    providers: list[dict[str, Any]] = []
    for document in documents:
        provider: dict[str, Any] = {
            "node": document.get("node"),
            "input": document.get("_input_path"),
            "ok": document.get("ok", False),
            "all_integrity_ok": document.get("all_integrity_ok", False),
            "all_operations_successful": document.get("all_operations_successful", False),
            "errors": document.get("errors", []),
            "versions": {},
            "resources": {
                "before": document.get("resource_before"),
                "after": document.get("resource_after"),
            },
        }
        for version, value in document.get("versions", {}).items():
            provider["versions"][version] = {
                "cid": value.get("cid"),
                "expected_sha256": value.get("expected_sha256"),
                "integrity": value.get("integrity"),
                "replication_fetch": {key: value.get("replication_fetch", {}).get(key) for key in ("success", "duration_ms", "error")},
                "operations": {
                    name: compact_operation(op)
                    for name, op in value.get("operations", {}).items()
                },
            }
            expected_cids.setdefault(version, value.get("cid"))
            expected_hashes.setdefault(version, value.get("expected_sha256"))
        providers.append(provider)

    cid_consistency = all(
        value.get("cid") == expected_cids.get(version)
        for provider in providers
        for version, value in provider.get("versions", {}).items()
    )
    hash_consistency = all(
        value.get("integrity", {}).get("sha256") == expected_hashes.get(version)
        for provider in providers
        for version, value in provider.get("versions", {}).items()
    )
    all_integrity = all(provider.get("all_integrity_ok") for provider in providers) and len(providers) == 3
    all_ops = all(provider.get("all_operations_successful") for provider in providers) and len(providers) == 3

    summary: dict[str, Any] = {
        "schema_version": "b8c-summary-v1",
        "run_id": "b8c-ipfs-20260916",
        "generated_at": now(),
        "scope": {
            "providers": [provider.get("node") for provider in providers],
            "synthetic_ciphertexts_only": True,
            "blockchain_transactions_submitted": False,
            "ipfs_latencies_are_not_blockchain_tps": True,
        },
        "acceptance": {
            "three_provider_files_present": len(providers) == 3,
            "same_cid_on_all_providers": cid_consistency,
            "same_sha256_on_all_providers": hash_consistency,
            "integrity_all_providers": all_integrity,
            "all_measured_operations_successful": all_ops,
            "pass": bool(cid_consistency and hash_consistency and all_integrity and all_ops),
        },
        "expected_cids": expected_cids,
        "expected_sha256": expected_hashes,
        "providers": providers,
        "note": "Les latences sont mesurées avec perf_counter_ns() dans chaque VM; aucune latence inter-VM n'est calculée par horodatage comparé.",
    }
    Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines: list[str] = [
        "# Analyse B8-C — IPFS distribué",
        "",
        f"- Générée : `{summary['generated_at']}`",
        "- Données : ciphertexts synthétiques uniquement, 128 octets par version.",
        "- Blockchain : aucune nouvelle transaction soumise par cette campagne.",
        "- Les latences IPFS ne sont pas du TPS blockchain.",
        "",
        "## Verdict",
        "",
        f"- CID identiques sur les fournisseurs : **{'OK' if cid_consistency else 'ÉCHEC'}**",
        f"- SHA-256 identiques : **{'OK' if hash_consistency else 'ÉCHEC'}**",
        f"- Intégrité de chaque fournisseur : **{'OK' if all_integrity else 'ÉCHEC'}**",
        f"- Opérations mesurées sans échec : **{'OK' if all_ops else 'ÉCHEC'}**",
        f"- Verdict B8-C IPFS : **{'PASS' if summary['acceptance']['pass'] else 'À ANALYSER'}**",
        "",
        "## Mesures locales Kubo",
        "",
        "| Fournisseur | Version | CID | cat p50/p95 ms | has p50/p95 ms | pin_add p50/p95 ms | pin_ls p50/p95 ms |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for provider in providers:
        for version, value in provider.get("versions", {}).items():
            ops = value.get("operations", {})
            def pair(name: str) -> str:
                op = ops.get(name, {})
                return f"{op.get('p50_ms', '—')} / {op.get('p95_ms', '—')}"
            lines.append(
                f"| {provider.get('node')} | {version} | `{value.get('cid')}` | {pair('cat_local')} | {pair('has_block_stat')} | {pair('pin_add')} | {pair('pin_ls')} |"
            )
    lines += [
        "",
        "## Ressources et OOM",
        "",
        "Les JSON fournisseurs conservent les relevés `VmRSS`, `VmSize`, `Threads`, les événements cgroup mémoire et les erreurs OOM visibles sans privilège. Aucun processus n'a été démarré ou arrêté par le script.",
        "",
        "## Vérification blockchain",
        "",
        "La lecture de `read_phase7_records.py` doit être archivée séparément. Elle vérifie les références historiques CID/hash sans inscrire les nouveaux CID B8-C. Ses sorties ne sont pas agrégées aux latences IPFS.",
        "",
        "## Limite de mesure",
        "",
        "`replication_fetch` est une mesure réalisée avec l'horloge monotone locale de la VM et peut inclure Bitswap. Aucun calcul de latence inter-VM n'est déduit de timestamps provenant d'horloges différentes.",
    ]
    Path(args.analysis_output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["acceptance"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
