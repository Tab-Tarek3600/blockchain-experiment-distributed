# Fiche B4 — latence d'inclusion, commit et convergence

**Statut :** préparée, lancement à exécuter sur la VM node1  
**Taux retenu :** `1 tx/s`  
**Run ID :** `b4-rate-1p0-20260915`  
**Date :** 15 septembre 2026

## Paramètres fixés

| Paramètre | Valeur |
|---|---:|
| clients logiques | 1 |
| taux offert | 1 tx/s |
| durée T2 | 60 s |
| transactions préconstruites | 60 |
| payload | 0 octet, synthétique |
| ingress | node1 uniquement |
| drain après T2 | 300 s |
| nœuds observés | node1, node2, node3 |
| perturbation réseau | aucune |

Le chemin reste `client/médecin → node1 → diffusion P2P`. Le générateur
`benchmark_b3_clients.py` est réutilisé comme générateur de flux contrôlé ; il
ne contacte jamais directement node2 ou node3 et ne démarre ni n'arrête de VM.

## 1. Préparer les journaux sur les trois VMs

Dans un terminal par VM, lancer les nœuds avec une sortie séparée. Ne pas
supprimer les clés, les configurations ni les blocs existants avant d'avoir
validé le périmètre du run.

Exemple pour conserver les journaux :

```bash
# node1
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main --config config/nodes/node1/node.yaml --log-level INFO \
  2>&1 | tee /tmp/b4-rate-1p0-20260915-node1.log
```

Utiliser la même commande sur node2 et node3 en remplaçant la configuration et
le nom du fichier :

```text
/tmp/b4-rate-1p0-20260915-node2.log
/tmp/b4-rate-1p0-20260915-node3.log
```

Les trois nœuds doivent être démarrés à moins de cinq secondes d'intervalle,
avec leur configuration existante et le port P2P `9001`.

## 2. Lancer le générateur sur node1 uniquement

Dans un second terminal node1 :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
  --config config/nodes/node1/node.yaml \
  --rate 1 \
  --clients 1 \
  --duration 60 \
  --payload-size 0 \
  --run-id b4-rate-1p0-20260915 \
  --drain-timeout 300 \
  --manifest-output results/raw_data/b4-rate-1p0-20260915-node1-manifest.json \
  2>&1 | tee /tmp/b4-rate-1p0-20260915-generator.log
```

Le résultat attendu du générateur est `submitted=60`, sous réserve d'une
connexion et d'une exécution sans erreur. Ce nombre est une charge offerte,
pas une preuve d'acceptation applicative.

## 3. Récupérer les artefacts sur la machine de développement

Depuis le dépôt de développement, utiliser des commandes `scp` simples :

```bash
mkdir -p results/raw_data/b4-rate-1p0-20260915

scp ismail@192.168.168.101:/tmp/b4-rate-1p0-20260915-node1.log \
  results/raw_data/b4-rate-1p0-20260915-node1.log
scp ismail@192.168.168.102:/tmp/b4-rate-1p0-20260915-node2.log \
  results/raw_data/b4-rate-1p0-20260915-node2.log
scp ismail@192.168.168.103:/tmp/b4-rate-1p0-20260915-node3.log \
  results/raw_data/b4-rate-1p0-20260915-node3.log

scp ismail@192.168.168.101:\
  ~/blockchain-experiment-distributed/results/raw_data/b4-rate-1p0-20260915-node1-manifest.json \
  results/raw_data/b4-rate-1p0-20260915-node1-manifest.json
```

Récupérer ensuite les répertoires de blocs sans analyser sur node1 :

```bash
mkdir -p /tmp/b4-rate-1p0-20260915/node1 \
         /tmp/b4-rate-1p0-20260915/node2 \
         /tmp/b4-rate-1p0-20260915/node3

scp -r ismail@192.168.168.101:\
  ~/blockchain-experiment-distributed/data/node1/blocks \
  /tmp/b4-rate-1p0-20260915/node1/
scp -r ismail@192.168.168.102:\
  ~/blockchain-experiment-distributed/data/node2/blocks \
  /tmp/b4-rate-1p0-20260915/node2/
scp -r ismail@192.168.168.103:\
  ~/blockchain-experiment-distributed/data/node3/blocks \
  /tmp/b4-rate-1p0-20260915/node3/
```

## 4. Analyse depuis le dépôt de développement

Ne pas lancer l'analyse sur node1. Depuis la machine de développement :

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py \
  --manifest results/raw_data/b4-rate-1p0-20260915-node1-manifest.json \
  --node1-blocks /tmp/b4-rate-1p0-20260915/node1/blocks \
  --node2-blocks /tmp/b4-rate-1p0-20260915/node2/blocks \
  --node3-blocks /tmp/b4-rate-1p0-20260915/node3/blocks \
  --node1-log results/raw_data/b4-rate-1p0-20260915-node1.log \
  --node2-log results/raw_data/b4-rate-1p0-20260915-node2.log \
  --node3-log results/raw_data/b4-rate-1p0-20260915-node3.log \
  --output results/raw_data/b4-rate-1p0-20260915-summary.json
```

Ne pas ajouter `--clocks-synchronised` sans une vérification indépendante des
horloges. Dans ce cas, le résumé doit laisser la latence numérique inter-VM en
`not_measured`, tout en conservant la convergence de contenu par
`block_hash`/`state_root`.

## Critères de validité

- manifeste unique et `run_id` cohérent ;
- `node1_only_ingress=true` ;
- payload entièrement synthétique ;
- aucune donnée médicale réelle ;
- pas de clé secrète dans le manifeste ;
- journaux des trois nœuds et blocs correspondants récupérés ;
- absence d'erreur du générateur ;
- comparaison par transaction entre émission, commit node1 et présence sur les
  trois chaînes ;
- distinction explicite entre latence locale mesurable et latence numérique
  inter-VM non mesurable sans horloges synchronisées.
