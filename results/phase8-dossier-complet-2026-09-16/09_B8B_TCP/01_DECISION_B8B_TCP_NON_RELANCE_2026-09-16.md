# Fiche B8-B-TCP — benchmark de l'ingress TCP vers node1

**Date :** 16 septembre 2026  
**Statut :** remplacée — ne pas exécuter comme nouveau benchmark  
**Motif :** le chemin TCP équivalent est déjà couvert par B3, B3-N, B4, B6 et B7  
**Périmètre initial :** ingress TCP existant, sans API Flask/Gunicorn  
**Run ID pilote initial :** `b8b-tcp-1p0-20260916`

> **Décision de suivi :** cette fiche est conservée comme trace de l'option
> examinée, mais aucun run `b8b-tcp-*` ne doit être lancé. Le prochain test
> distinct est B8-C — performance et réplication IPFS distribuées.

## 1. Décision de périmètre

Le dépôt ne contient actuellement pas d'implémentation Flask/Gunicorn exploitable
(`src/api/.gitkeep` uniquement). Le test suivant est donc explicitement un
benchmark **B8-B-TCP** de l'ingress existant, et non un benchmark HTTP/API.

Le scénario reste :

```text
client(s) TCP → node1:9001 → diffusion P2P → node2/node3
```

Les résultats devront être nommés et interprétés comme :

- latence d'ingress/commit local observée sur node1 ;
- débit de transactions commises ;
- convergence du contenu sur les trois nœuds ;
- charge TCP et blockchain synthétique.

Ils ne devront pas être présentés comme des mesures Flask, Gunicorn ou HTTP.

## 2. Objectif

Mesurer séparément le comportement de la couche d'entrée TCP déjà utilisée par
le générateur B3, tout en conservant le chemin client → node1 → P2P.

Pour chaque run, relever :

- transactions préparées et soumises ;
- erreurs du générateur ;
- acceptations/rejets observés dans les journaux ;
- transactions incluses sur node1, node2 et node3 ;
- débit commis sur la fenêtre de soumission ;
- p50/p95/max de la latence locale node1 ;
- backlog et transactions non commises ;
- doublons ;
- hauteur, `block_hash` et `state_root` des trois chaînes ;
- convergence du préfixe commun ;
- journaux et ressources disponibles pour une analyse ultérieure.

La latence numérique inter-VM doit rester `not_measured` tant que les horloges
des trois VMs ne sont pas synchronisées et vérifiées indépendamment.

## 3. Règles de sécurité et d'intégrité

- Ce test est B8-B-TCP ; ne pas le confondre avec la clôture de B7.
- Les trois nœuds doivent être démarrés manuellement ; le générateur ne lance
  ni n'arrête de VM.
- Le port P2P reste `9001`.
- Seul node1 reçoit les transactions du générateur.
- Ne rien envoyer directement à node2 ou node3.
- Utiliser uniquement des transactions et payloads synthétiques.
- Ne supprimer aucune clé de validateur, configuration ou donnée de chaîne.
- Ne pas utiliser `pkill -f`.
- Ne pas appliquer de nouvelle règle `tc-netem`.
- Arrêter les nœuds avec `Ctrl-C` dans leurs terminaux respectifs après la
  collecte des journaux.
- Copier les blocs et journaux sur la machine de développement avant tout run
  suivant lorsque l'on veut conserver une photographie intermédiaire.
- L'analyse est exécutée depuis le dépôt de développement, pas sur node1.

## 4. Matrice prévue

Les runs utilisent `benchmark_b3_clients.py`, déjà utilisé et validé pour le
chemin TCP. Chaque run dure 60 secondes, avec un client logique et un payload
synthétique nul.

| Run ID | Taux offert | Clients | Durée T2 | Payload | Rôle |
|---|---:|---:|---:|---:|---|
| `b8b-tcp-0p5-20260916` | 0,5 tx/s | 1 | 60 s | 0 octet | charge basse |
| `b8b-tcp-1p0-20260916` | 1,0 tx/s | 1 | 60 s | 0 octet | pilote et référence |
| `b8b-tcp-2p0-20260916` | 2,0 tx/s | 1 | 60 s | 0 octet | zone de saturation connue |
| `b8b-tcp-3p0-20260916` | 3,0 tx/s | 1 | 60 s | 0 octet | surcharge exploratoire |

Le pilote `b8b-tcp-1p0-20260916` doit être exécuté en premier. Ne passer aux
runs suivants qu'après avoir vérifié son manifeste, son analyse et la
convergence des trois chaînes.

Les quatre runs doivent être séquentiels. Attendre le drain et la convergence
avant le run suivant. Utiliser un `run_id` différent à chaque fois ; ne pas
réinitialiser la chaîne.

## 5. Préparation des VMs

Les commandes suivantes sont des contrôles en lecture seule. Adapter le nom
SSH si nécessaire ; les adresses et le port sont ceux de l'architecture retenue.

```bash
ssh -tt ismail@192.168.168.101 \
  'IFACE=$(ip route get 192.168.168.102 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "node1 IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"; ss -ltn | grep ":9001" || true'

ssh -tt ismail@192.168.168.102 \
  'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "node2 IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"; ss -ltn | grep ":9001" || true'

ssh -tt ismail@192.168.168.103 \
  'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "node3 IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"; ss -ltn | grep ":9001" || true'
```

La sortie `tc qdisc` ne doit pas contenir `qdisc netem`. Le port `9001` doit être
écouté lorsque le nœud est démarré.

## 6. Démarrage manuel des trois nœuds

Ouvrir trois terminaux SSH distincts et conserver les journaux cumulés dans
`/tmp`.

### node1

```bash
ssh -tt ismail@192.168.168.101
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main \
  --config config/nodes/node1/node.yaml \
  --log-level INFO \
  2>&1 | tee /tmp/b8b-tcp-20260916-node1-all.log
```

### node2

```bash
ssh -tt ismail@192.168.168.102
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main \
  --config config/nodes/node2/node.yaml \
  --log-level INFO \
  2>&1 | tee /tmp/b8b-tcp-20260916-node2-all.log
```

### node3

```bash
ssh -tt ismail@192.168.168.103
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main \
  --config config/nodes/node3/node.yaml \
  --log-level INFO \
  2>&1 | tee /tmp/b8b-tcp-20260916-node3-all.log
```

Attendre que les trois nœuds aient formé leurs connexions P2P avant de lancer le
pilote. Ne pas lancer B7 ; ce démarrage concerne uniquement B8-B-TCP.

## 7. Exécution du pilote sur node1

Dans un quatrième terminal SSH vers node1 :

```bash
ssh -tt ismail@192.168.168.101
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"

PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
  --config config/nodes/node1/node.yaml \
  --rate 1.0 \
  --clients 1 \
  --duration 60 \
  --payload-size 0 \
  --drain-timeout 300 \
  --poll-interval 0.05 \
  --data-dir "$PWD/data/node1" \
  --run-id b8b-tcp-1p0-20260916 \
  --manifest-output results/raw_data/b8b-tcp-1p0-20260916-node1-manifest.json \
  2>&1 | tee /tmp/b8b-tcp-1p0-20260916-generator.log
```

Résultat minimal attendu du générateur :

```text
submitted     : 60
errors        : []
manifest      : results/raw_data/b8b-tcp-1p0-20260916-node1-manifest.json
```

`submitted=60` indique la charge écrite sur la connexion TCP. Ce n'est pas à
lui seul une preuve d'acceptation blockchain.

## 8. Collecte sur la machine de développement

Les commandes ci-dessous doivent être exécutées depuis le dépôt de

développement, et non depuis node1.

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
run=b8b-tcp-1p0-20260916
mkdir -p "/tmp/$run/node1" "/tmp/$run/node2" "/tmp/$run/node3"
```

Récupérer les journaux, le manifeste et les blocs :

```bash
scp ismail@192.168.168.101:/tmp/b8b-tcp-20260916-node1-all.log \
  "results/raw_data/${run}-node1.log"
scp ismail@192.168.168.102:/tmp/b8b-tcp-20260916-node2-all.log \
  "results/raw_data/${run}-node2.log"
scp ismail@192.168.168.103:/tmp/b8b-tcp-20260916-node3-all.log \
  "results/raw_data/${run}-node3.log"
scp ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/results/raw_data/${run}-node1-manifest.json \
  "results/raw_data/${run}-node1-manifest.json"

scp -r ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/data/node1/blocks "/tmp/$run/node1/"
scp -r ismail@192.168.168.102:~/Bureau/blockchain-experiment-distributed/data/node2/blocks "/tmp/$run/node2/"
scp -r ismail@192.168.168.103:~/Bureau/blockchain-experiment-distributed/data/node3/blocks "/tmp/$run/node3/"
```

Avant un run suivant, attendre et vérifier la convergence. Si une photographie
intermédiaire des blocs est nécessaire, elle doit avoir été copiée à ce stade.

## 9. Analyse locale du pilote

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py \
  --manifest "results/raw_data/${run}-node1-manifest.json" \
  --node1-blocks "/tmp/$run/node1/blocks" \
  --node2-blocks "/tmp/$run/node2/blocks" \
  --node3-blocks "/tmp/$run/node3/blocks" \
  --node1-log "results/raw_data/${run}-node1.log" \
  --node2-log "results/raw_data/${run}-node2.log" \
  --node3-log "results/raw_data/${run}-node3.log" \
  --output "results/raw_data/${run}-summary.json"
```

Ne pas ajouter `--clocks-synchronised` sans mesure indépendante de la
synchronisation des horloges. L'analyse doit alors conserver la convergence
numérique à `not_measured`, tout en vérifiant la convergence de contenu par
hauteur, `block_hash` et `state_root`.

## 10. Critères d'acceptation du pilote

Le pilote est exploitable si :

- le manifeste contient `node1_only_ingress=true` ;
- les 60 transactions sont synthétiques ;
- les nonces sont valides et les `tx_id` sont uniques ;
- `errors=[]` côté générateur ;
- les transactions acceptées et rejetées sont distinguées ;
- les trois chaînes peuvent être chargées sans erreur ;
- les transactions du run sont comptées séparément des anciennes transactions ;
- aucun doublon du run n'est observé ;
- les chaînes convergent jusqu'au plus petit tip disponible ;
- les latences node1 locales sont exprimées en p50/p95/max ;
- les temps inter-VM restent explicitement `not_measured` si nécessaire ;
- les journaux et le résumé JSON sont archivés dans `results/raw_data/`.

Un échec ou une transaction non observée ne doit pas être supprimé du résultat.
Il doit être classé comme erreur générateur, rejet explicite, transaction non
commise, timeout ou observation incomplète.

## 11. Runs complémentaires après validation du pilote

Réutiliser exactement la même procédure avec ces substitutions :

```text
b8b-tcp-0p5-20260916 : --rate 0.5 --run-id b8b-tcp-0p5-20260916
b8b-tcp-2p0-20260916 : --rate 2.0 --run-id b8b-tcp-2p0-20260916
b8b-tcp-3p0-20260916 : --rate 3.0 --run-id b8b-tcp-3p0-20260916
```

Le chemin des journaux `/tmp/b8b-tcp-20260916-...` peut rester le même si les
nœuds restent actifs ; l'analyse filtre les `tx_id` présents dans le manifeste.
Pour une traçabilité maximale, il est préférable de capturer un fichier de log
par run ou de signaler explicitement que les logs sont cumulatifs.

## 12. Arrêt et nettoyage

Après la collecte et l'analyse du dernier run :

1. arrêter chaque nœud avec `Ctrl-C` dans son terminal SSH ;
2. ne pas utiliser `pkill -f` ;
3. vérifier que le port `9001` est fermé ;
4. vérifier que `tc qdisc` ne contient pas `netem` ;
5. conserver les manifestes, journaux, blocs copiés et résumés JSON ;
6. ne supprimer aucune clé ou configuration.

## 13. Livrables attendus

Pour le pilote :

```text
results/raw_data/b8b-tcp-1p0-20260916-node1-manifest.json
results/raw_data/b8b-tcp-1p0-20260916-node1.log
results/raw_data/b8b-tcp-1p0-20260916-node2.log
results/raw_data/b8b-tcp-1p0-20260916-node3.log
results/raw_data/b8b-tcp-1p0-20260916-summary.json
```

Après la matrice complète, ajouter les mêmes artefacts pour `0p5`, `2p0` et
`3p0`, puis produire une note d'analyse comparative séparant clairement :

- débit TCP offert ;
- transactions acceptées par node1 ;
- transactions commises sur les trois nœuds ;
- latence locale node1 ;
- convergence de contenu ;
- limites d'observation.
