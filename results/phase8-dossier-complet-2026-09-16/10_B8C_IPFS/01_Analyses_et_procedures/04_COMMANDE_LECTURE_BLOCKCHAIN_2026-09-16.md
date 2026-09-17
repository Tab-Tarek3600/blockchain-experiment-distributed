# B8-C — lecture blockchain détaillée en lecture seule

Objectif : archiver les lignes CID/hash historiques, le résultat `getRecord v1/v2 OK` et un code retour explicite, sans transaction, sans écriture et sans réinitialisation.

À exécuter depuis la racine du dépôt réel sur chaque VM, avec le `node.yaml` réel de la VM :

```bash
set +e
NODE=node1                         # remplacer par node2 ou node3
REPO="$HOME/blockchain-experiment-distributed"  # adapter uniquement si nécessaire
OUT="/tmp/phase8-b8c-blockchain-detailed-read-2026-09-16-${NODE}.txt"

cd "$REPO" || exit 2
source .venv/bin/activate
export OQS_INSTALL_PATH="$HOME/_oqs"
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"

{
  echo "B8-C read-only blockchain verification"
  echo "node=${NODE}"
  echo "command: PYTHONPATH=. python3 scripts/testing/read_phase7_records.py --node ${NODE}"
  echo "started: $(date -Iseconds)"
  PYTHONPATH=. python3 scripts/testing/read_phase7_records.py --node "$NODE"
  RC=$?
  echo "finished: $(date -Iseconds)"
  echo "EXIT=${RC}"
} > "$OUT" 2>&1

cat "$OUT"
exit "$(sed -n 's/^EXIT=//p' "$OUT" | tail -1)"
```

Résultat attendu dans chaque fichier :

```text
RESULT     : getRecord v1/v2 OK
same client: registeredBy v1 == registeredBy v2
EXIT=0
```

Après exécution, copier les trois fichiers dans `results/raw_data/` sur la machine de développement :

```bash
scp ismail@192.168.168.101:/tmp/phase8-b8c-blockchain-detailed-read-2026-09-16-node1.txt results/raw_data/
scp ismail@192.168.168.102:/tmp/phase8-b8c-blockchain-detailed-read-2026-09-16-node2.txt results/raw_data/
scp ismail@192.168.168.103:/tmp/phase8-b8c-blockchain-detailed-read-2026-09-16-node3.txt results/raw_data/
```

Cette lecture ne relance pas B8-B-TCP, n'ajoute aucune règle `tc-netem`, ne crée aucune transaction et ne touche pas aux données persistantes.
