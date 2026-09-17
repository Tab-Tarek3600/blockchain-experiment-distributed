# Fiche B7 — profil de ressources des trois VMs

**Date :** 15 septembre 2026  
**Run ID :** `b7-profile-1p0-20260915`  
**Statut :** exécutée, analysée et clôturée opérationnellement ; nœuds arrêtés et port `9001` fermé selon confirmation de l'opérateur  
**Objectif :** mesurer CPU, RSS/mémoire, E/S disque et trafic réseau des trois VMs sous une charge contrôlée

## 1. Paramètres fixés

| Paramètre | Valeur |
|---|---:|
| Clients logiques | 1 |
| Taux offert | 1 tx/s |
| Durée T2 | 60 s |
| Payload | 0 octet, synthétique |
| Ingress | node1 uniquement |
| Drain générateur | 300 s |
| Échantillonnage ressources | 1 s, 120 échantillons |
| Interface réseau | `ens33` |
| Perturbation réseau | aucune ; ne pas ajouter `tc-netem` |

La série B7 mesure les trois nœuds virtualisés VMware. Elle ne compare pas une
machine physique à une VM et ne modifie ni clés, ni configurations, ni données
de chaîne.

## 2. Préparation sur la machine de développement

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
mkdir -p results/raw_data/b7-profile-1p0-20260915
```

Vérifier que `pidstat` et `vmstat` existent localement sur chaque VM, depuis la
machine de développement :

```bash
ssh -tt ismail@192.168.168.101 'command -v pidstat; command -v vmstat; command -v pgrep'
ssh -tt ismail@192.168.168.102 'command -v pidstat; command -v vmstat; command -v pgrep'
ssh -tt ismail@192.168.168.103 'command -v pidstat; command -v vmstat; command -v pgrep'
```

Vérifier que `tc-netem` n'est pas présent :

```bash
ssh -tt ismail@192.168.168.101 'IFACE=$(ip route get 192.168.168.102 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"'
ssh -tt ismail@192.168.168.102 'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"'
ssh -tt ismail@192.168.168.103 'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; tc qdisc show dev "$IFACE"'
```

Aucune sortie ne doit contenir `qdisc netem`.

## 3. Démarrer les trois nœuds

Ouvrir trois terminaux SSH distincts et laisser les processus actifs.

### node1

```bash
ssh -tt ismail@192.168.168.101
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main --config config/nodes/node1/node.yaml --log-level INFO 2>&1 | tee /tmp/b7-profile-1p0-20260915-node1.log
```

### node2

```bash
ssh -tt ismail@192.168.168.102
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main --config config/nodes/node2/node.yaml --log-level INFO 2>&1 | tee /tmp/b7-profile-1p0-20260915-node2.log
```

### node3

```bash
ssh -tt ismail@192.168.168.103
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
python -m src.node.main --config config/nodes/node3/node.yaml --log-level INFO 2>&1 | tee /tmp/b7-profile-1p0-20260915-node3.log
```

## 4. Identifier les PID des nœuds

Exécuter depuis la machine de développement :

```bash
ssh -tt ismail@192.168.168.101 'pgrep -af "src.node.main"'
ssh -tt ismail@192.168.168.102 'pgrep -af "src.node.main"'
ssh -tt ismail@192.168.168.103 'pgrep -af "src.node.main"'
```

Relever le PID du processus correspondant à la configuration `node1`, `node2`
ou `node3`. Ne pas utiliser `pkill -f`.

## 5. Démarrer les collecteurs de ressources

Ouvrir un terminal SSH supplémentaire par VM. Remplacer `PID_NODE1` par le
PID réel affiché à l'étape précédente.

### Collecteur node1

```bash
ssh -tt ismail@192.168.168.101
cd ~/Bureau/blockchain-experiment-distributed
PID=PID_NODE1
IFACE=ens33
date -Ins > /tmp/b7-profile-1p0-20260915-node1-sampler-start.txt
free -h > /tmp/b7-profile-1p0-20260915-node1-free-before.txt
df -h > /tmp/b7-profile-1p0-20260915-node1-df-before.txt
du -sh data/node1 > /tmp/b7-profile-1p0-20260915-node1-data-before.txt
ip -s link show dev "$IFACE" > /tmp/b7-profile-1p0-20260915-node1-net-before.txt
pidstat -u -r -d -p "$PID" 1 120 > /tmp/b7-profile-1p0-20260915-node1-pidstat.txt 2>&1 & P1=$!
vmstat 1 120 > /tmp/b7-profile-1p0-20260915-node1-vmstat.txt 2>&1 & P2=$!
wait "$P1" "$P2"
ip -s link show dev "$IFACE" > /tmp/b7-profile-1p0-20260915-node1-net-after.txt
free -h > /tmp/b7-profile-1p0-20260915-node1-free-after.txt
df -h > /tmp/b7-profile-1p0-20260915-node1-df-after.txt
du -sh data/node1 > /tmp/b7-profile-1p0-20260915-node1-data-after.txt
date -Ins > /tmp/b7-profile-1p0-20260915-node1-sampler-end.txt
```

### Collecteur node2

```bash
ssh -tt ismail@192.168.168.102
cd ~/Bureau/blockchain-experiment-distributed
PID=PID_NODE2
IFACE=ens33
date -Ins > /tmp/b7-profile-1p0-20260915-node2-sampler-start.txt
free -h > /tmp/b7-profile-1p0-20260915-node2-free-before.txt
df -h > /tmp/b7-profile-1p0-20260915-node2-df-before.txt
du -sh data/node2 > /tmp/b7-profile-1p0-20260915-node2-data-before.txt
ip -s link show dev "$IFACE" > /tmp/b7-profile-1p0-20260915-node2-net-before.txt
pidstat -u -r -d -p "$PID" 1 120 > /tmp/b7-profile-1p0-20260915-node2-pidstat.txt 2>&1 & P1=$!
vmstat 1 120 > /tmp/b7-profile-1p0-20260915-node2-vmstat.txt 2>&1 & P2=$!
wait "$P1" "$P2"
ip -s link show dev "$IFACE" > /tmp/b7-profile-1p0-20260915-node2-net-after.txt
free -h > /tmp/b7-profile-1p0-20260915-node2-free-after.txt
df -h > /tmp/b7-profile-1p0-20260915-node2-df-after.txt
du -sh data/node2 > /tmp/b7-profile-1p0-20260915-node2-data-after.txt
date -Ins > /tmp/b7-profile-1p0-20260915-node2-sampler-end.txt
```

### Collecteur node3

```bash
ssh -tt ismail@192.168.168.103
cd ~/Bureau/blockchain-experiment-distributed
PID=PID_NODE3
IFACE=ens33
date -Ins > /tmp/b7-profile-1p0-20260915-node3-sampler-start.txt
free -h > /tmp/b7-profile-1p0-20260915-node3-free-before.txt
df -h > /tmp/b7-profile-1p0-20260915-node3-df-before.txt
du -sh data/node3 > /tmp/b7-profile-1p0-20260915-node3-data-before.txt
ip -s link show dev "$IFACE" > /tmp/b7-profile-1p0-20260915-node3-net-before.txt
pidstat -u -r -d -p "$PID" 1 120 > /tmp/b7-profile-1p0-20260915-node3-pidstat.txt 2>&1 & P1=$!
vmstat 1 120 > /tmp/b7-profile-1p0-20260915-node3-vmstat.txt 2>&1 & P2=$!
wait "$P1" "$P2"
ip -s link show dev "$IFACE" > /tmp/b7-profile-1p0-20260915-node3-net-after.txt
free -h > /tmp/b7-profile-1p0-20260915-node3-free-after.txt
df -h > /tmp/b7-profile-1p0-20260915-node3-df-after.txt
du -sh data/node3 > /tmp/b7-profile-1p0-20260915-node3-data-after.txt
date -Ins > /tmp/b7-profile-1p0-20260915-node3-sampler-end.txt
```

Les collecteurs doivent être démarrés avant le générateur. Ils échantillonnent
120 secondes à 1 seconde d'intervalle.

## 6. Lancer le générateur B7 sur node1

Dans un terminal séparé connecté à node1 :

```bash
ssh -tt ismail@192.168.168.101
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
set -o pipefail
PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py --config config/nodes/node1/node.yaml --rate 1.0 --clients 1 --duration 60 --payload-size 0 --drain-timeout 300 --poll-interval 0.05 --data-dir "$PWD/data/node1" --run-id b7-profile-1p0-20260915 --manifest-output results/raw_data/b7-profile-1p0-20260915-node1-manifest.json 2>&1 | tee /tmp/b7-profile-1p0-20260915-generator.log
```

Le résultat attendu est proche de :

```text
submitted : 60
errors    : []
```

## 7. Récupérer les artefacts sur la machine de développement

Depuis le dépôt de développement, utiliser des commandes `scp` complètes :

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
mkdir -p /tmp/b7-profile-1p0-20260915/node1 /tmp/b7-profile-1p0-20260915/node2 /tmp/b7-profile-1p0-20260915/node3
```

```bash
scp ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/results/raw_data/b7-profile-1p0-20260915-node1-manifest.json results/raw_data/b7-profile-1p0-20260915-node1-manifest.json
```

```bash
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-generator.log results/raw_data/b7-profile-1p0-20260915-generator.log
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1.log results/raw_data/b7-profile-1p0-20260915-node1.log
scp ismail@192.168.168.102:/tmp/b7-profile-1p0-20260915-node2.log results/raw_data/b7-profile-1p0-20260915-node2.log
scp ismail@192.168.168.103:/tmp/b7-profile-1p0-20260915-node3.log results/raw_data/b7-profile-1p0-20260915-node3.log
```

Récupérer les ressources node1 :

```bash
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-pidstat.txt results/raw_data/b7-profile-1p0-20260915-node1-pidstat.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-vmstat.txt results/raw_data/b7-profile-1p0-20260915-node1-vmstat.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-net-before.txt results/raw_data/b7-profile-1p0-20260915-node1-net-before.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-net-after.txt results/raw_data/b7-profile-1p0-20260915-node1-net-after.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-free-before.txt results/raw_data/b7-profile-1p0-20260915-node1-free-before.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-free-after.txt results/raw_data/b7-profile-1p0-20260915-node1-free-after.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-df-before.txt results/raw_data/b7-profile-1p0-20260915-node1-df-before.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-df-after.txt results/raw_data/b7-profile-1p0-20260915-node1-df-after.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-data-before.txt results/raw_data/b7-profile-1p0-20260915-node1-data-before.txt
scp ismail@192.168.168.101:/tmp/b7-profile-1p0-20260915-node1-data-after.txt results/raw_data/b7-profile-1p0-20260915-node1-data-after.txt
```

Récupérer les mêmes fichiers pour node2 et node3 en remplaçant l'adresse IP et
le numéro du nœud dans les commandes ci-dessus. Les fichiers nécessaires sont
`pidstat`, `vmstat`, `net-before`, `net-after`, `free-before`, `free-after`,
`df-before`, `df-after`, `data-before`, `data-after`, ainsi que les timestamps
de début et de fin.

Copier les blocs :

```bash
scp -r ismail@192.168.168.101:~/Bureau/blockchain-experiment-distributed/data/node1/blocks /tmp/b7-profile-1p0-20260915/node1/
scp -r ismail@192.168.168.102:~/Bureau/blockchain-experiment-distributed/data/node2/blocks /tmp/b7-profile-1p0-20260915/node2/
scp -r ismail@192.168.168.103:~/Bureau/blockchain-experiment-distributed/data/node3/blocks /tmp/b7-profile-1p0-20260915/node3/
```

## 8. Analyse depuis le dépôt de développement

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py --manifest results/raw_data/b7-profile-1p0-20260915-node1-manifest.json --node1-blocks /tmp/b7-profile-1p0-20260915/node1/blocks --node2-blocks /tmp/b7-profile-1p0-20260915/node2/blocks --node3-blocks /tmp/b7-profile-1p0-20260915/node3/blocks --node1-log results/raw_data/b7-profile-1p0-20260915-node1.log --node2-log results/raw_data/b7-profile-1p0-20260915-node2.log --node3-log results/raw_data/b7-profile-1p0-20260915-node3.log --output results/raw_data/b7-profile-1p0-20260915-summary.json
```

Ne pas ajouter de synchronisation d'horloges sans preuve indépendante. La
convergence de contenu reste vérifiable même si la latence numérique inter-VM
reste `not_measured`.

## 9. Fin du run

Après la collecte, arrêter les trois nœuds avec `Ctrl-C` dans leurs terminaux
respectifs. Ne pas utiliser `pkill -f`. Vérifier que le port `9001` est fermé et
que `tc qdisc show` ne contient toujours pas `qdisc netem`.

## 10. Résultat archivé

Le run a été exécuté et analysé. Le manifeste et le résumé JSON sont valides ;
les `60/60` transactions sont présentes sur les trois nœuds, sans rejet
explicite ni doublon. La note d'analyse est :

`results/raw_data/b7-profile-1p0-20260915-analysis-note.md`
