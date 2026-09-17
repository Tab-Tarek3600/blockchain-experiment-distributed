#!/usr/bin/env python3
"""
Etape 2b — assemble nodes.json a partir des fragments collectes.

Chaque machine a produit son fragment public avec :

    python3 scripts/setup/gen_validator_key.py --key-dir keys/nodeN --json

Ce script rassemble ces fragments (deposes sur une cle USB, par
exemple) et ecrit le nodes.json attendu par make_configs.py, en y
injectant les IP et les ports.

Il n'y a AUCUN secret dans les fragments : gen_validator_key.py
n'exporte que la cle publique et l'adresse derivee. La cle secrete
reste sur sa machine.

Usage typique (sur node1, cle USB montee sur /mnt/usb) :

    python3 scripts/setup/build_nodes_json.py \\
        --fragments /mnt/usb \\
        --node node1=192.168.168.101 \\
        --node node2=192.168.168.102 \\
        --node node3=192.168.168.103 \\
        --out nodes.json

Le port par defaut est 9001 ; il peut etre precise par noeud :

        --node node1=192.168.168.101:9001

L'ORDRE des options --node fixe l'ordre du tour de role PoA
(validators[(height + round) % 3]) et designe le premier comme validateur
genesis. Il doit rester identique pour tous.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_PORT = 9001


def parse_node_spec(spec: str) -> tuple[str, str, int]:
    """
    Analyse "node1=192.168.168.101" ou "node1=192.168.168.101:9001".
    """
    if "=" not in spec:
        raise SystemExit(
            f"ERREUR : --node {spec!r} invalide. "
            "Format attendu : node_id=ip[:port], "
            "ex. node1=192.168.168.101"
        )
    node_id, _, endpoint = spec.partition("=")
    node_id = node_id.strip()
    endpoint = endpoint.strip()

    if not node_id:
        raise SystemExit(f"ERREUR : --node {spec!r} : node_id vide.")

    if ":" in endpoint:
        host, _, port_text = endpoint.partition(":")
        try:
            port = int(port_text)
        except ValueError:
            raise SystemExit(
                f"ERREUR : --node {spec!r} : port {port_text!r} non entier."
            )
    else:
        host, port = endpoint, DEFAULT_PORT

    if not host:
        raise SystemExit(f"ERREUR : --node {spec!r} : adresse IP vide.")

    return node_id, host, port


def load_fragment(fragments_dir: Path, node_id: str) -> dict:
    """
    Charge le fragment public d'un noeud.

    Accepte <node_id>.json, ou tout fichier .json du repertoire dont
    le nom contient le node_id (tolerant aux noms du type
    node1-public.json).
    """
    direct = fragments_dir / f"{node_id}.json"
    candidates = [direct] if direct.exists() else sorted(
        p for p in fragments_dir.glob("*.json") if node_id in p.stem
    )

    if not candidates:
        raise SystemExit(
            f"ERREUR : aucun fragment trouve pour {node_id} dans "
            f"{fragments_dir}.\n"
            f"Attendu : {fragments_dir / (node_id + '.json')}\n"
            "Produisez-le sur la machine concernee avec :\n"
            f"  python3 scripts/setup/gen_validator_key.py "
            f"--key-dir keys/{node_id} --json > {node_id}.json"
        )

    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise SystemExit(
            f"ERREUR : plusieurs fragments possibles pour {node_id} : {names}.\n"
            "Gardez-en un seul, ou renommez-le en "
            f"{node_id}.json."
        )

    path = candidates[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERREUR : {path} n'est pas un JSON valide : {exc}")

    for field in ("address_hex", "public_key_hex"):
        if field not in data:
            raise SystemExit(
                f"ERREUR : {path} : champ '{field}' manquant. "
                "Le fragment doit venir de gen_validator_key.py --json."
            )

    # Filet de securite : un fragment ne doit JAMAIS contenir de secret.
    for suspect in ("secret", "secret_key", "secret_key_hex", "private_key"):
        if suspect in data:
            raise SystemExit(
                f"ERREUR : {path} contient un champ '{suspect}'.\n"
                "Une cle secrete ne doit jamais quitter sa machine. "
                "Supprimez ce fichier et regenerez le fragment avec "
                "gen_validator_key.py --json."
            )

    return data


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assemble nodes.json a partir des fragments publics."
    )
    ap.add_argument(
        "--fragments",
        required=True,
        type=Path,
        help="repertoire contenant nodeN.json (ex: /mnt/usb)",
    )
    ap.add_argument(
        "--node",
        action="append",
        required=True,
        metavar="ID=IP[:PORT]",
        help="a repeter pour chaque noeud, DANS L'ORDRE du tour PoA",
    )
    ap.add_argument("--out", default=Path("nodes.json"), type=Path)
    ap.add_argument(
        "--force",
        action="store_true",
        help="ecraser un nodes.json existant",
    )
    args = ap.parse_args()

    if len(args.node) < 2:
        raise SystemExit("ERREUR : au moins 2 noeuds sont necessaires.")

    if args.out.exists() and not args.force:
        raise SystemExit(
            f"ERREUR : {args.out} existe deja. Utilisez --force pour ecraser."
        )

    if not args.fragments.is_dir():
        raise SystemExit(
            f"ERREUR : {args.fragments} n'est pas un repertoire.\n"
            "La cle USB est-elle montee ?"
        )

    nodes: list[dict] = []
    seen_ids: set[str] = set()
    seen_addrs: dict[str, str] = {}

    for index, spec in enumerate(args.node):
        node_id, host, port = parse_node_spec(spec)

        if node_id in seen_ids:
            raise SystemExit(f"ERREUR : node_id duplique : {node_id}")
        seen_ids.add(node_id)

        fragment = load_fragment(args.fragments, node_id)
        address = fragment["address_hex"]

        if address in seen_addrs:
            raise SystemExit(
                f"ERREUR : {node_id} et {seen_addrs[address]} ont la MEME "
                f"adresse ({address}).\n"
                "Chaque machine doit generer sa PROPRE paire de cles. "
                "Avez-vous copie keys/ d'une machine a l'autre ?"
            )
        seen_addrs[address] = node_id

        entry = {
            "node_id": node_id,
            "node_name": node_id.capitalize(),
            "host": host,
            "port": port,
            "address_hex": address,
            "data_dir": f"data/{node_id}",
            "validator_key_dir": f"keys/{node_id}",
        }

        # Seul le validateur genesis (le premier) doit fournir sa cle
        # publique complete : make_configs.py verifie qu'elle derive
        # bien vers authorized_validators[0].
        if index == 0:
            entry["public_key_hex"] = fragment["public_key_hex"]

        nodes.append(entry)

    args.out.write_text(json.dumps(nodes, indent=2) + "\n", encoding="utf-8")

    print(f"ecrit : {args.out}")
    print()
    print("Ordre PoA (validators[(height + round) % n]) et validateur genesis :")
    for i, n in enumerate(nodes):
        tag = "  <-- genesis" if i == 0 else ""
        print(f"  [{i}] {n['node_id']:8s} {n['host']}:{n['port']}  "
              f"{n['address_hex']}{tag}")
    print()
    print("Etape suivante :")
    print(f"  python3 scripts/setup/make_configs.py --nodes {args.out} "
          "--out config/nodes/ --force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
