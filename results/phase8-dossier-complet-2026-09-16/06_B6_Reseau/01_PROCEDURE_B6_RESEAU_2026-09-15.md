# Fiche B6 — délai réseau contrôlé avec `tc-netem`

**Run ID :** `b6-delay50ms-20260915`  
**Scénario :** délai `50 ms ± 10 ms` sur les trois VMs  
**Charge :** 0,2 tx/s, 1 client, 60 s, payload synthétique nul  
**Ingress :** node1 uniquement  
**Important :** un seul scénario réseau doit être exécuté à la fois.

## Règles de sécurité

- Exécuter les commandes `ssh`/`scp` depuis la machine de développement.
- Ne pas utiliser `pkill -f`.
- Préférer Ctrl+C pour arrêter les nœuds ; sinon arrêter uniquement le PID
  exact de `src.node.main`.
- Ne pas supprimer les clés, les configurations ou les répertoires `data/nodeN`.
- La réinitialisation ne vide que `data/nodeN/blocks/`.
- `tc-netem` peut affecter SSH : garder une console locale ou une session de
  secours sur chaque VM.
- Ne pas appliquer une nouvelle qdisc si une qdisc existante autre que
  `noqueue` est déjà présente sans l’identifier et la documenter.
- Toutes les transactions et tous les fichiers sont synthétiques.

## 1. Arrêter les nœuds B5

Appuyer sur **Ctrl+C** dans les trois terminaux des nœuds si possible.
Sinon utiliser les PID exacts :

```bash
ssh ismail@192.168.168.101 'PID=$(pgrep -f "[s]rc.node.main.*node1/node.yaml" | head -n1); if [ -n "$PID" ]; then echo "node1 PID=$PID"; kill -INT "$PID"; else echo node1_not_running; fi'
```

```bash
ssh ismail@192.168.168.102 'PID=$(pgrep -f "[s]rc.node.main.*node2/node.yaml" | head -n1); if [ -n "$PID" ]; then echo "node2 PID=$PID"; kill -INT "$PID"; else echo node2_not_running; fi'
```

```bash
ssh ismail@192.168.168.103 'PID=$(pgrep -f "[s]rc.node.main.*node3/node.yaml" | head -n1); if [ -n "$PID" ]; then echo "node3 PID=$PID"; kill -INT "$PID"; else echo node3_not_running; fi'
```

## 2. Réinitialiser uniquement les blocs

```bash
ssh ismail@192.168.168.101 'cd ~/blockchain-experiment-distributed && mkdir -p data/node1/blocks && find data/node1/blocks -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && echo node1_blocks_reset'
```

```bash
ssh ismail@192.168.168.102 'cd ~/blockchain-experiment-distributed && mkdir -p data/node2/blocks && find data/node2/blocks -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && echo node2_blocks_reset'
```

```bash
ssh ismail@192.168.168.103 'cd ~/blockchain-experiment-distributed && mkdir -p data/node3/blocks && find data/node3/blocks -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && echo node3_blocks_reset'
```

## 3. Vérifier l’interface réseau et la qdisc actuelle

Ne pas appliquer `netem` si la sortie montre déjà une qdisc autre que
`noqueue`, sauf si elle a été identifiée et documentée.

### node1

```bash
ssh ismail@192.168.168.101 'IFACE=$(ip route get 192.168.168.102 | awk "{for (i=1;i<=NF;i++) if (\$i==\"dev\") {print \$(i+1); exit}} "); echo IFACE=$IFACE; tc qdisc show dev "$IFACE"'
```

### node2

```bash
ssh ismail@192.168.168.102 'IFACE=$(ip route get 192.168.168.101 | awk "{for (i=1;i<=NF;i++) if (\$i==\"dev\") {print \$(i+1); exit}} "); echo IFACE=$IFACE; tc qdisc show dev "$IFACE"'
```

### node3

```bash
ssh ismail@192.168.168.103 'IFACE=$(ip route get 192.168.168.101 | awk "{for (i=1;i<=NF;i++) if (\$i==\"dev\") {print \$(i+1); exit}} "); echo IFACE=$IFACE; tc qdisc show dev "$IFACE"'
```

Noter le nom d’interface retourné par chaque commande, généralement `ens33`,
`ens160` ou `eth0`.

## 4. Démarrer les trois nœuds

Ouvrir trois terminaux et exécuter une commande par terminal.

### node1

```bash
ssh -t ismail@192.168.168.101 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && python -m src.node.main --config config/nodes/node1/node.yaml --log-level INFO 2>&1 | tee /tmp/b6-delay50ms-20260915-node1.log'
```

### node2

```bash
ssh -t ismail@192.168.168.102 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && python -m src.node.main --config config/nodes/node2/node.yaml --log-level INFO 2>&1 | tee /tmp/b6-delay50ms-20260915-node2.log'
```

### node3

```bash
ssh -t ismail@192.168.168.103 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && python -m src.node.main --config config/nodes/node3/node.yaml --log-level INFO 2>&1 | tee /tmp/b6-delay50ms-20260915-node3.log'
```

Attendre dans chaque terminal l’écoute sur `0.0.0.0:9001`, deux pairs et
l’absence d’erreur de configuration.

## 5. Appliquer le délai `50 ms ± 10 ms`

Exécuter une commande par VM. Le nom d’interface est recalculé automatiquement.

### node1

```bash
ssh -t ismail@192.168.168.101 'IFACE=$(ip route get 192.168.168.102 | awk "{for (i=1;i<=NF;i++) if (\$i==\"dev\") {print \$(i+1); exit}} "); echo IFACE=$IFACE; sudo tc qdisc add dev "$IFACE" root netem delay 50ms 10ms; tc qdisc show dev "$IFACE"'
```

### node2

```bash
ssh -t ismail@192.168.168.102 'IFACE=$(ip route get 192.168.168.101 | awk "{for (i=1;i<=NF;i++) if (\$i==\"dev\") {print \$(i+1); exit}} "); echo IFACE=$IFACE; sudo tc qdisc add dev "$IFACE" root netem delay 50ms 10ms; tc qdisc show dev "$IFACE"'
```

### node3

```bash
ssh -t ismail@192.168.168.103 'IFACE=$(ip route get 192.168.168.101 | awk "{for (i=1;i<=NF;i++) if (\$i==\"dev\") {print \$(i+1); exit}} "); echo IFACE=$IFACE; sudo tc qdisc add dev "$IFACE" root netem delay 50ms 10ms; tc qdisc show dev "$IFACE"'
```

Si une commande retourne `RTNETLINK answers: File exists`, ne pas enchaîner avec
une autre commande `add`. Arrêter et vérifier la qdisc existante.

## 6. Lancer le générateur B6 sur node1

```bash
ssh -t ismail@192.168.168.101 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py --config config/nodes/node1/node.yaml --rate 0.2 --clients 1 --duration 60 --payload-size 0 --run-id b6-delay50ms-20260915 --drain-timeout 300 --manifest-output results/raw_data/b6-delay50ms-20260915-node1-manifest.json 2>&1 | tee /tmp/b6-delay50ms-20260915-generator.log'
```

Attendre la fin de la soumission et du drain.

## 7. Supprimer impérativement le délai après le run

Exécuter ces commandes avant de récupérer les blocs.

### node1

```bash
ssh -tt ismail@192.168.168.101 'IFACE=$(ip route get 192.168.168.102 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; sudo tc qdisc del dev "$IFACE" root; echo "qdisc_after:"; tc qdisc show dev "$IFACE"'
```

### node2

```bash
ssh -tt ismail@192.168.168.102 'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; sudo tc qdisc del dev "$IFACE" root; echo "qdisc_after:"; tc qdisc show dev "$IFACE"'
```

### node3

```bash
ssh -tt ismail@192.168.168.103 'IFACE=$(ip route get 192.168.168.101 | sed -n "s/.* dev \([^ ]*\).*/\1/p"); printf "IFACE=%s\n" "$IFACE"; sudo tc qdisc del dev "$IFACE" root; echo "qdisc_after:"; tc qdisc show dev "$IFACE"'
```

Ensuite appuyer sur Ctrl+C dans les terminaux node1, node2 et node3.

## 8. Collecter depuis la machine de développement

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
mkdir -p results/raw_data/b6-delay50ms-20260915
mkdir -p /tmp/b6-delay50ms-20260915/node1 /tmp/b6-delay50ms-20260915/node2 /tmp/b6-delay50ms-20260915/node3
```

Copier les journaux, le générateur et le manifeste avec des commandes sur une
seule ligne :

```bash
scp ismail@192.168.168.101:/tmp/b6-delay50ms-20260915-node1.log results/raw_data/b6-delay50ms-20260915-node1.log
```

```bash
scp ismail@192.168.168.102:/tmp/b6-delay50ms-20260915-node2.log results/raw_data/b6-delay50ms-20260915-node2.log
```

```bash
scp ismail@192.168.168.103:/tmp/b6-delay50ms-20260915-node3.log results/raw_data/b6-delay50ms-20260915-node3.log
```

```bash
scp ismail@192.168.168.101:/tmp/b6-delay50ms-20260915-generator.log results/raw_data/b6-delay50ms-20260915-generator.log
```

```bash
scp ismail@192.168.168.101:/home/ismail/blockchain-experiment-distributed/results/raw_data/b6-delay50ms-20260915-node1-manifest.json results/raw_data/b6-delay50ms-20260915-node1-manifest.json
```

Copier ensuite les blocs après suppression de `netem` :

```bash
scp -r ismail@192.168.168.101:/home/ismail/blockchain-experiment-distributed/data/node1/blocks /tmp/b6-delay50ms-20260915/node1/
```

```bash
scp -r ismail@192.168.168.102:/home/ismail/blockchain-experiment-distributed/data/node2/blocks /tmp/b6-delay50ms-20260915/node2/
```

```bash
scp -r ismail@192.168.168.103:/home/ismail/blockchain-experiment-distributed/data/node3/blocks /tmp/b6-delay50ms-20260915/node3/
```

## 9. Analyser B6 depuis le dépôt de développement

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py --manifest results/raw_data/b6-delay50ms-20260915-node1-manifest.json --node1-blocks /tmp/b6-delay50ms-20260915/node1/blocks --node2-blocks /tmp/b6-delay50ms-20260915/node2/blocks --node3-blocks /tmp/b6-delay50ms-20260915/node3/blocks --node1-log results/raw_data/b6-delay50ms-20260915-node1.log --node2-log results/raw_data/b6-delay50ms-20260915-node2.log --node3-log results/raw_data/b6-delay50ms-20260915-node3.log --output results/raw_data/b6-delay50ms-20260915-summary.json
```

Ne pas ajouter `--clocks-synchronised` sans contrôle indépendant des horloges.

Vérifier le résumé :

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path('results/raw_data/b6-delay50ms-20260915-summary.json')
d = json.loads(p.read_text())
print('run_id=', d.get('run_id'))
print('submitted=', d.get('counts', {}).get('submitted'))
print('included_on_all_three=', d.get('counts', {}).get('included_on_all_three'))
print('success_rate_all_three=', d.get('rates', {}).get('success_rate_all_three'))
print('committed_tps=', d.get('rates', {}).get('committed_tps_all_three_over_submission_window'))
print('converged=', d.get('validity', {}).get('three_node_chain_converged_to_min_tip'))
print('final_chain=', d.get('final_chain'))
PY
```

Le scénario B6 ne sera déclaré valide qu’après vérification de la qdisc avant et
après le run, des journaux, du manifeste et des trois copies de blocs.
