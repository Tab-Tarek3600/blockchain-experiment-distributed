#!/usr/bin/env python3
"""
Etape 2b — a executer UNE SEULE FOIS, sur une seule machine.

Prend les elements publics collectes depuis les 3 machines (adresse +
cle publique) et ecrit les 3 fichiers config/nodes/nodeN/node.yaml.

Ce qui est IDENTIQUE dans les 3 fichiers (configuration reseau) :
    authorized_validators       (meme liste, meme ORDRE)
    genesis_validator_public_key
    genesis_timestamp
    block_interval_seconds
    round_timeout_seconds

Ce qui DIFFERE (configuration locale) :
    node_id, node_name, host, port, data_dir, validator_key_dir, peers

L'ordre de authorized_validators est significatif a deux titres :
  1. le tour de proposition PoA est validators[(height + round) % len]
  2. par convention, genesis_validator_public_key doit deriver vers
     authorized_validators[0]

Les 3 YAML sont valides via NodeConfig.from_dict() avant ecriture :
si la convention genesis est violee, rien n'est ecrit.

Entree : un fichier JSON decrivant les 3 noeuds, ex. nodes.json

    [
      {"node_id": "node1", "host": "192.168.1.101", "port": 5001,
       "address_hex": "...", "public_key_hex": "..."},
      {"node_id": "node2", "host": "192.168.1.102", "port": 5002,
       "address_hex": "...", "public_key_hex": null},
      {"node_id": "node3", "host": "192.168.1.103", "port": 5003,
       "address_hex": "...", "public_key_hex": null}
    ]

Seul le noeud servant de validateur genesis (par defaut le premier)
doit fournir public_key_hex ; pour les autres il est facultatif.

Usage :
    python3 scripts/setup/make_configs.py --nodes nodes.json --out config/nodes/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.crypto.address import ADDRESS_LENGTH, public_key_to_address  # noqa: E402
from src.node.config import (  # noqa: E402
    DEFAULT_BLOCK_INTERVAL_SECONDS,
    DEFAULT_ROUND_TIMEOUT_SECONDS,
    ConfigError,
    NodeConfig,
)

GENESIS_TIMESTAMP = 1_700_000_000


def load_nodes(path: Path) -> list[dict]:
    nodes = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(nodes, list) or len(nodes) < 2:
        raise SystemExit("ERREUR : nodes.json doit etre une liste d'au moins 2 noeuds.")

    seen_ids: set[str] = set()
    seen_addrs: set[str] = set()

    for i, n in enumerate(nodes):
        for field in ("node_id", "host", "port", "address_hex"):
            if field not in n:
                raise SystemExit(f"ERREUR : noeud #{i} : champ '{field}' manquant.")

        addr = n["address_hex"]
        try:
            raw = bytes.fromhex(addr)
        except ValueError:
            raise SystemExit(f"ERREUR : noeud #{i} : address_hex non hexadecimal.")
        if len(raw) != ADDRESS_LENGTH:
            raise SystemExit(
                f"ERREUR : noeud #{i} : adresse de {len(raw)} octets, "
                f"{ADDRESS_LENGTH} attendus. Utilisez la sortie de "
                "gen_validator_key.py."
            )

        if n["node_id"] in seen_ids:
            raise SystemExit(f"ERREUR : node_id duplique : {n['node_id']}")
        if addr in seen_addrs:
            raise SystemExit(
                f"ERREUR : adresse dupliquee : {addr}\n"
                "Chaque noeud doit avoir sa PROPRE paire de cles. "
                "Ne copiez pas keys/ d'une machine a l'autre."
            )
        seen_ids.add(n["node_id"])
        seen_addrs.add(addr)

    return nodes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True, type=Path)
    ap.add_argument("--out", default=Path("config/nodes"), type=Path)
    ap.add_argument(
        "--genesis-index",
        type=int,
        default=0,
        help="index du noeud fournissant la cle publique genesis (defaut 0)",
    )
    ap.add_argument("--block-interval", type=float,
                    default=DEFAULT_BLOCK_INTERVAL_SECONDS)
    ap.add_argument(
        "--round-timeout", type=float,
        default=DEFAULT_ROUND_TIMEOUT_SECONDS,
        help="timeout avant changement de round (defaut: 5 secondes)",
    )
    ap.add_argument("--genesis-timestamp", type=int, default=GENESIS_TIMESTAMP)
    ap.add_argument("--force", action="store_true",
                    help="ecraser des YAML existants")
    args = ap.parse_args()

    nodes = load_nodes(args.nodes)

    gi = args.genesis_index
    if not (0 <= gi < len(nodes)):
        raise SystemExit(f"ERREUR : --genesis-index {gi} hors limites.")

    genesis_node = nodes[gi]
    genesis_pk_hex = genesis_node.get("public_key_hex")
    if not genesis_pk_hex:
        raise SystemExit(
            f"ERREUR : le noeud genesis '{genesis_node['node_id']}' doit fournir "
            "public_key_hex (la cle publique complete, 1312 octets), pas "
            "seulement son adresse."
        )

    try:
        genesis_pk = bytes.fromhex(genesis_pk_hex)
    except ValueError:
        raise SystemExit("ERREUR : public_key_hex du noeud genesis non hexadecimal.")

    derived = public_key_to_address(genesis_pk)
    if derived.hex() != genesis_node["address_hex"]:
        raise SystemExit(
            "ERREUR : incoherence sur le noeud genesis : la cle publique fournie "
            f"derive vers {derived.hex()} mais address_hex vaut "
            f"{genesis_node['address_hex']}.\n"
            "Les deux valeurs doivent provenir du MEME appel a gen_validator_key.py."
        )

    # authorized_validators : le noeud genesis DOIT etre en position 0.
    ordered = [nodes[gi]] + [n for i, n in enumerate(nodes) if i != gi]
    authorized = [n["address_hex"] for n in ordered]

    args.out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for n in nodes:
        peers = [
            {"host": p["host"], "port": p["port"]}
            for p in nodes
            if p["node_id"] != n["node_id"]
        ]

        data = {
            "node_id": n["node_id"],
            "node_name": n.get("node_name", n["node_id"].capitalize()),
            "data_dir": n.get("data_dir", f"data/{n['node_id']}"),
            "host": n["host"],
            "port": n["port"],
            "peers": peers,
            "validator_key_dir": n.get("validator_key_dir", f"keys/{n['node_id']}"),
            "authorized_validators": authorized,
            "genesis_validator_public_key": genesis_pk_hex,
            "genesis_timestamp": args.genesis_timestamp,
            "block_interval_seconds": args.block_interval,
            "round_timeout_seconds": args.round_timeout,
        }

        # Validation reelle avant ecriture.
        try:
            NodeConfig.from_dict(data)
        except ConfigError as exc:
            raise SystemExit(
                f"ERREUR : la configuration generee pour {n['node_id']} est "
                f"invalide : {exc}\nAucun fichier n'a ete ecrit."
            )

        node_dir = args.out / n["node_id"]
        node_dir.mkdir(parents=True, exist_ok=True)
        path = node_dir / "node.yaml"
        if path.exists() and not args.force:
            raise SystemExit(
                f"ERREUR : {path} existe deja. Utilisez --force pour ecraser."
            )
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        written.append(path)

    print(f"Validateur genesis : {genesis_node['node_id']} "
          f"(authorized_validators[0] = {authorized[0]})")
    print()
    print("Ordre PoA (validators[(height + round) % 3]) :")
    for i, a in enumerate(authorized):
        print(f"  [{i}] {ordered[i]['node_id']}  {a}")
    print()
    for p in written:
        print(f"ecrit : {p}")
    print()
    print("Copiez CHAQUE yaml sur sa machine (ou tout config/ partout : "
          "chaque noeud ne lit que le sien).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
