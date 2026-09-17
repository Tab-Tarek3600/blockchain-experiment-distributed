#!/usr/bin/env python3
"""
Etape 2a — a executer SUR CHAQUE MACHINE (node1, node2, node3).

Genere (ou recharge) la paire de cles ML-DSA du validateur local dans
son propre repertoire, puis affiche UNIQUEMENT les elements publics :

    - la cle publique en hexadecimal  (a transmettre)
    - l'adresse 20 octets derivee     (a transmettre)

La cle secrete est ecrite sur disque et n'est JAMAIS affichee ni
transmise. C'est la regle de securite du projet : seule la cle
publique est une configuration partagee.

Ce script ne lit aucun fichier de configuration : il n'en existe pas
encore a ce stade (les YAML ont besoin des adresses que ce script
produit). Il n'a besoin que d'un repertoire de cles.

Usage sur node1 :
    python3 scripts/setup/gen_validator_key.py --key-dir keys/node1

Idempotent : relance sur des cles existantes, il les recharge et
reaffiche les memes valeurs sans rien regenerer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.crypto.address import public_key_to_address  # noqa: E402
from src.node.config import (  # noqa: E402
    VALIDATOR_PUBLIC_KEY_FILENAME,
    VALIDATOR_SECRET_KEY_FILENAME,
    load_or_generate_validator_keys,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--key-dir",
        required=True,
        type=Path,
        help="repertoire des cles du validateur, ex: keys/node1",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="sortie JSON (pour scripter la collecte)",
    )
    args = ap.parse_args()

    existed = (args.key_dir / VALIDATOR_PUBLIC_KEY_FILENAME).exists()

    keypair = load_or_generate_validator_keys(args.key_dir)
    address = public_key_to_address(keypair.public_key)

    if args.json:
        print(
            json.dumps(
                {
                    "key_dir": str(args.key_dir),
                    "public_key_hex": keypair.public_key.hex(),
                    "address_hex": address.hex(),
                    "reused_existing": existed,
                }
            )
        )
        return 0

    action = "rechargees depuis" if existed else "GENEREES dans"
    print(f"Cles {action} : {args.key_dir}")
    print(f"  {VALIDATOR_PUBLIC_KEY_FILENAME}  ({len(keypair.public_key)} octets)")
    print(f"  {VALIDATOR_SECRET_KEY_FILENAME}  (secret, ne pas transmettre)")
    print()
    print("A TRANSMETTRE (public, sans risque) :")
    print()
    print(f"adresse    : {address.hex()}")
    print()
    print("cle publique (hex) :")
    print(keypair.public_key.hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
