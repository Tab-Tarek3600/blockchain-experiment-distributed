# Fiche B3-N — concurrence par clients logiques

**Phase :** 8 — B3, complément scalabilité par concurrence  
**Date de préparation :** 15 septembre 2026  
**Statut :** exécutée et analysée ; les quatre résumés JSON sont archivés  
**Scénario invariant :** clients logiques → node1 → diffusion P2P → node2/node3

## 1. Objectif

Mesurer l'effet du nombre de clients logiques tout en gardant le débit total
constant. Les clients sont des flux TCP concurrents exécutés sur node1 ; ils ne
sont pas des machines clientes distinctes et ne contactent jamais directement
node2 ou node3.

La série principale est :

| Run ID | Clients logiques | Taux total offert | Durée T2 | Payload |
|---|---:|---:|---:|---:|
| `b3-client-01-1p0-20260915` | 1 | 1 tx/s | 60 s | 0 octet |
| `b3-client-02-1p0-20260915` | 2 | 1 tx/s | 60 s | 0 octet |
| `b3-client-04-1p0-20260915` | 4 | 1 tx/s | 60 s | 0 octet |
| `b3-client-08-1p0-20260915` | 8 | 1 tx/s | 60 s | 0 octet |

Chaque run préconstruit donc 60 transactions synthétiques. La répartition est
faite par le générateur avec des plages de nonces disjointes ; le taux total
reste `1 tx/s`, quelle que soit la valeur de `--clients`.

## 2. Règles impératives

- node1 est le seul ingress ; ne rien envoyer directement à node2 ou node3 ;
- conserver le chemin `client(s) → node1 → P2P` ;
- utiliser uniquement des payloads synthétiques contrôlés ;
- ne supprimer aucune clé de validateur ni configuration générée ;
- ne pas utiliser `pkill -f` ; arrêter par PID ou par `Ctrl-C` dans le terminal
  qui exécute le processus ;
- ne pas appliquer de nouvelle règle `tc-netem` ; le B6 précédent est déjà
  nettoyé ;
- exécuter les quatre runs séquentiellement, jamais en parallèle ;
- attendre que le mempool soit vide et que les trois nœuds aient convergé avant
  de passer au run suivant ;
- analyser les blocs et journaux depuis la machine de développement, jamais sur
  node1 ;
- ne pas réinitialiser ou supprimer les données de chaîne entre les runs ; les
  transactions sont distinguées par leurs `tx_id` et les manifestes propres à
  chaque run ;
- utiliser `~/Bureau/blockchain-experiment-distributed` sur les VMs, conformément
  au dépôt réellement utilisé.

## 3. Préparation sur les trois VMs

Vérifier d'abord que les processus des runs précédents sont arrêtés et que le
réseau est normal. La commande `tc` est en lecture seule :

```bash
ssh -tt ismail@192.168.168.101 'IFACE=$(ip route get 192.168.168.102 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"'
ssh -tt ismail@192.168.168.102 'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"'
ssh -tt ismail@192.168.168.103 'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"'
```

La sortie ne doit pas contenir `qdisc netem`. Une qdisc normale telle que
`fq_codel` est attendue.

Démarrer ensuite les trois nœuds dans trois terminaux SSH distincts. Les
journaux sont conservés dans `/tmp` et les nœuds restent actifs pendant la
série ; ne fermer les terminaux qu'après le quatrième run et la collecte.

### node1 — `192.168.168.101`

```bash
ssh -tt ismail@192.168.168.101
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main --config config/nodes/node1/node.yaml --log-level INFO 2>&1 | tee /tmp/b3n-20260915-node1-all.log
```

### node2 — `192.168.168.102`

```bash
ssh -tt ismail@192.168.168.102
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main --config config/nodes/node2/node.yaml --log-level INFO 2>&1 | tee /tmp/b3n-20260915-node2-all.log
```

### node3 — `192.168.168.103`

```bash
ssh -tt ismail@192.168.168.103
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main --config config/nodes/node3/node.yaml --log-level INFO 2>&1 | tee /tmp/b3n-20260915-node3-all.log
```

Vérifier avant le premier run que les trois nœuds sont actifs, que le port P2P
`9001` est ouvert et qu'aucun mempool résiduel ne vient d'un run précédent.

## 4. Commandes du générateur sur node1

Les commandes suivantes sont à exécuter **une par une** dans un quatrième
terminal SSH vers node1. Attendre la fin complète du générateur et du drain
avant de lancer la commande suivante.

Préparer le terminal :

```bash
ssh -tt ismail@192.168.168.101
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
```

### Run 1 — 1 client

```bash
PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
  --config config/nodes/node1/node.yaml \
  --rate 1.0 \
  --clients 1 \
  --duration 60 \
  --payload-size 0 \
  --drain-timeout 300 \
  --poll-interval 0.05 \
  --data-dir "$PWD/data/node1" \
  --run-id b3-client-01-1p0-20260915 \
  --manifest-output results/raw_data/b3-client-01-1p0-20260915-node1-manifest.json \
  2>&1 | tee /tmp/b3-client-01-1p0-20260915-generator.log
```

### Run 2 — 2 clients

```bash
PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
  --config config/nodes/node1/node.yaml \
  --rate 1.0 \
  --clients 2 \
  --duration 60 \
  --payload-size 0 \
  --drain-timeout 300 \
  --poll-interval 0.05 \
  --data-dir "$PWD/data/node1" \
  --run-id b3-client-02-1p0-20260915 \
  --manifest-output results/raw_data/b3-client-02-1p0-20260915-node1-manifest.json \
  2>&1 | tee /tmp/b3-client-02-1p0-20260915-generator.log
```

### Run 3 — 4 clients

```bash
PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
  --config config/nodes/node1/node.yaml \
  --rate 1.0 \
  --clients 4 \
  --duration 60 \
  --payload-size 0 \
  --drain-timeout 300 \
  --poll-interval 0.05 \
  --data-dir "$PWD/data/node1" \
  --run-id b3-client-04-1p0-20260915 \
  --manifest-output results/raw_data/b3-client-04-1p0-20260915-node1-manifest.json \
  2>&1 | tee /tmp/b3-client-04-1p0-20260915-generator.log
```

### Run 4 — 8 clients

```bash
PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
  --config config/nodes/node1/node.yaml \
  --rate 1.0 \
  --clients 8 \
  --duration 60 \
  --payload-size 0 \
  --drain-timeout 300 \
  --poll-interval 0.05 \
  --data-dir "$PWD/data/node1" \
  --run-id b3-client-08-1p0-20260915 \
  --manifest-output results/raw_data/b3-client-08-1p0-20260915-node1-manifest.json \
  2>&1 | tee /tmp/b3-client-08-1p0-20260915-generator.log
```

Pour chaque run, le résultat standard attendu est proche de :

```text
clients       : valeur du run
submitted     : 60
errors        : []
manifest      : results/raw_data/<run-id>-node1-manifest.json
```

`submitted=60` est une mesure de charge envoyée par le générateur, pas une
preuve d'acceptation blockchain. Il faut conserver le champ `errors` tel quel,
y compris lorsqu'il est vide.

## 5. Collecte depuis la machine de développement

Les commandes ci-dessous sont à exécuter dans le dépôt de développement, pas
sur node1. Depuis le terminal local :

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
mkdir -p results/raw_data/b3n-20260915
```

Après les quatre runs, récupérer les journaux cumulés, les générateurs et les
manifestes :

```bash
scp ismail@192.168.168.101:/tmp/b3n-20260915-node1-all.log \
  results/raw_data/b3n-20260915/node1-all.log
scp ismail@192.168.168.102:/tmp/b3n-20260915-node2-all.log \
  results/raw_data/b3n-20260915/node2-all.log
scp ismail@192.168.168.103:/tmp/b3n-20260915-node3-all.log \
  results/raw_data/b3n-20260915/node3-all.log

scp ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/results/raw_data/b3-client-01-1p0-20260915-node1-manifest.json \
  results/raw_data/b3-client-01-1p0-20260915-node1-manifest.json
scp ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/results/raw_data/b3-client-02-1p0-20260915-node1-manifest.json \
  results/raw_data/b3-client-02-1p0-20260915-node1-manifest.json
scp ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/results/raw_data/b3-client-04-1p0-20260915-node1-manifest.json \
  results/raw_data/b3-client-04-1p0-20260915-node1-manifest.json
scp ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/results/raw_data/b3-client-08-1p0-20260915-node1-manifest.json \
  results/raw_data/b3-client-08-1p0-20260915-node1-manifest.json
```

Pour l'analyse, copier les journaux dans des noms par run afin que chaque
résumé soit autoportant. Les journaux sont cumulatifs ; l'analyse filtrera les
transactions du manifeste correspondant :

```bash
for run in b3-client-01-1p0-20260915 b3-client-02-1p0-20260915 b3-client-04-1p0-20260915 b3-client-08-1p0-20260915; do
  cp results/raw_data/b3n-20260915/node1-all.log "results/raw_data/${run}-node1.log"
  cp results/raw_data/b3n-20260915/node2-all.log "results/raw_data/${run}-node2.log"
  cp results/raw_data/b3n-20260915/node3-all.log "results/raw_data/${run}-node3.log"
done
```

Pour préserver une photographie de blocs par run, exécuter **après chaque run,
avant le run suivant**, depuis la machine de développement :

```bash
run=b3-client-01-1p0-20260915
mkdir -p "/tmp/${run}/node1" "/tmp/${run}/node2" "/tmp/${run}/node3"
scp -r ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/data/node1/blocks "/tmp/${run}/node1/"
scp -r ismail@192.168.168.102:~/Bureau/blockchain-experiment-distributed/data/node2/blocks "/tmp/${run}/node2/"
scp -r ismail@192.168.168.103:~/Bureau/blockchain-experiment-distributed/data/node3/blocks "/tmp/${run}/node3/"
```

Remplacer `run=` par `b3-client-02-1p0-20260915`, puis
`b3-client-04-1p0-20260915` et enfin `b3-client-08-1p0-20260915` après les
runs correspondants. Les commandes `scp` doivent rester complètes sur une
seule ligne logique ; ne pas utiliser de continuation suivie d'une ligne vide.
Ne pas analyser les blocs sur node1.

Si une copie historique n'a pas été faite avant le run suivant, conserver les
quatre manifestes et journaux, analyser le tip final avec prudence et signaler
que la photographie historique des blocs intermédiaires n'est pas disponible.

## 6. Analyse de chaque run

Pour chaque `run_id`, exécuter depuis le dépôt de développement :

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py \
  --manifest results/raw_data/<run-id>-node1-manifest.json \
  --node1-blocks /tmp/<run-id>/node1/blocks \
  --node2-blocks /tmp/<run-id>/node2/blocks \
  --node3-blocks /tmp/<run-id>/node3/blocks \
  --node1-log results/raw_data/<run-id>-node1.log \
  --node2-log results/raw_data/<run-id>-node2.log \
  --node3-log results/raw_data/<run-id>-node3.log \
  --output results/raw_data/<run-id>-summary.json
```

Ne pas ajouter de drapeau de synchronisation d'horloges sans preuve
indépendante. Les latences distantes restent `not_measured` numériquement si
les horloges des VMs ne sont pas synchronisées ; la convergence de contenu
(hash, racine d'état et hauteur) reste analysable.

## 7. Critères de validité

Un run B3-N est exploitable si :

- `run_id`, nombre de clients et taux total offert figurent dans le manifeste ;
- `submitted` est distingué de `included_node1/node2/node3` ;
- `node1_only_ingress=true` ;
- les 60 transactions sont synthétiques et les nonces sont disjoints par client ;
- aucun `errors` inattendu n'est présent ;
- les blocs et journaux des trois nœuds correspondent au run ;
- le mempool est drainé avant le run suivant ;
- les trois chaînes sont comparées sur leur préfixe commun ;
- les doublons et transactions manquantes sont rapportés ;
- les latences inter-VM non comparables sont explicitement marquées
  `not_measured`.

## 8. Arrêt et nettoyage après le quatrième run

Ne fermer les trois terminaux de nœud qu'après avoir récupéré les logs et les
blocs nécessaires. Ensuite, arrêter proprement chaque nœud avec `Ctrl-C` dans
son propre terminal SSH. Ne pas utiliser `pkill -f`.

Vérifier ensuite depuis la machine de développement que les processus sont
arrêtés et archiver toute sortie utile. La qdisc doit rester normale et ne doit
pas contenir `qdisc netem`.

## 9. Livrables attendus

- quatre manifestes `b3-client-*-1p0-20260915-node1-manifest.json` ;
- logs node1/node2/node3 par run ou, à défaut, logs cumulés explicitement
  signalés ;
- copies des blocs des trois nœuds par run ;
- quatre résumés JSON produits depuis le dépôt de développement ;
- une note comparative avec succès, TPS, latences, backlog, doublons et
  divergence/convergence par nombre de clients.
