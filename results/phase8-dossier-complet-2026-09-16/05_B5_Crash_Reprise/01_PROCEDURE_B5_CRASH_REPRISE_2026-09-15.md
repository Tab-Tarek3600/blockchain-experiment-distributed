# Fiche B5 — crash d’un nœud secondaire et reprise

**Run ID :** `b5-secondary-crash-20260915`  
**Scénario :** arrêt brutal de node3, puis redémarrage et rattrapage  
**Charge :** 0,2 tx/s, 1 client, 60 s, payload synthétique nul  
**Ingress :** node1 uniquement  
**Important :** scénario crash-only ; ce n’est pas un test Byzantine ni une
preuve de finalité BFT.

## Règles de sécurité

- Exécuter les commandes depuis la machine de développement lorsque la
  commande utilise `ssh` ou `scp`.
- Ne pas utiliser `pkill -f`.
- Préférer `Ctrl+C` dans les terminaux des nœuds. Si le terminal n’est plus
  disponible, rechercher puis arrêter uniquement le PID exact de
  `src.node.main`.
- Ne pas supprimer les clés, les configurations, ni les répertoires
  `data/nodeN`.
- La réinitialisation ci-dessous supprime uniquement le contenu de
  `data/nodeN/blocks/`, après arrêt des nœuds. Elle est facultative mais
  recommandée pour isoler B5 de B4.
- Toutes les transactions et tous les fichiers de test sont synthétiques.

## 1. Arrêter proprement les nœuds B4

Si les trois nœuds sont encore dans trois terminaux SSH, appuyer sur **Ctrl+C**
dans chacun. Sinon, arrêter le PID exact avec les commandes suivantes :

```bash
ssh ismail@192.168.168.101 'PID=$(pgrep -f "[s]rc.node.main.*node1/node.yaml" | head -n1); if [ -n "$PID" ]; then echo "node1 PID=$PID"; kill -INT "$PID"; else echo node1_not_running; fi'
ssh ismail@192.168.168.102 'PID=$(pgrep -f "[s]rc.node.main.*node2/node.yaml" | head -n1); if [ -n "$PID" ]; then echo "node2 PID=$PID"; kill -INT "$PID"; else echo node2_not_running; fi'
ssh ismail@192.168.168.103 'PID=$(pgrep -f "[s]rc.node.main.*node3/node.yaml" | head -n1); if [ -n "$PID" ]; then echo "node3 PID=$PID"; kill -INT "$PID"; else echo node3_not_running; fi'
```

Vérifier qu’aucun processus exact ne reste :

```bash
ssh ismail@192.168.168.101 'pgrep -af "[s]rc.node.main.*node1/node.yaml" || true'
ssh ismail@192.168.168.102 'pgrep -af "[s]rc.node.main.*node2/node.yaml" || true'
ssh ismail@192.168.168.103 'pgrep -af "[s]rc.node.main.*node3/node.yaml" || true'
```

## 2. Réinitialiser uniquement les blocs (recommandé pour un run isolé)

Ces commandes conservent les clés, les fichiers YAML/JSON, les répertoires
`data/nodeN` et les autres artefacts. Elles vident uniquement
`data/nodeN/blocks/` :

```bash
ssh ismail@192.168.168.101 'cd ~/blockchain-experiment-distributed && mkdir -p data/node1/blocks && find data/node1/blocks -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && echo node1_blocks_reset'
ssh ismail@192.168.168.102 'cd ~/blockchain-experiment-distributed && mkdir -p data/node2/blocks && find data/node2/blocks -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && echo node2_blocks_reset'
ssh ismail@192.168.168.103 'cd ~/blockchain-experiment-distributed && mkdir -p data/node3/blocks && find data/node3/blocks -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && echo node3_blocks_reset'
```

Ne pas poursuivre si une commande indique un chemin différent de
`data/nodeN/blocks`.

## 3. Préparer les journaux et démarrer les trois nœuds

Ouvrir trois terminaux sur la machine de développement. Exécuter une commande
par terminal. Les commandes suivantes gardent les journaux sur les VMs dans
`/tmp`.

### Terminal node1

```bash
ssh -t ismail@192.168.168.101 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && python -m src.node.main --config config/nodes/node1/node.yaml --log-level INFO 2>&1 | tee /tmp/b5-secondary-crash-20260915-node1.log'
```

### Terminal node2

```bash
ssh -t ismail@192.168.168.102 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && python -m src.node.main --config config/nodes/node2/node.yaml --log-level INFO 2>&1 | tee /tmp/b5-secondary-crash-20260915-node2.log'
```

### Terminal node3

```bash
ssh -t ismail@192.168.168.103 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && python -m src.node.main --config config/nodes/node3/node.yaml --log-level INFO 2>&1 | tee /tmp/b5-secondary-crash-20260915-node3.log'
```

Attendre dans les trois terminaux : écoute sur `0.0.0.0:9001`, deux pairs et
absence d’erreur de configuration. Les nœuds doivent être lancés à moins de
cinq secondes d’intervalle.

## 4. Lancer B5 et provoquer le crash de node3

Dans un quatrième terminal, lancer la charge sur node1 :

```bash
ssh -t ismail@192.168.168.101 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py --config config/nodes/node1/node.yaml --rate 0.2 --clients 1 --duration 60 --payload-size 0 --run-id b5-secondary-crash-20260915 --drain-timeout 300 --manifest-output results/raw_data/b5-secondary-crash-20260915-node1-manifest.json 2>&1 | tee /tmp/b5-secondary-crash-20260915-generator.log'
```

Pendant les 60 secondes de soumission, dans un cinquième terminal, rechercher
le PID exact de node3 :

```bash
ssh ismail@192.168.168.103 'pgrep -af "[s]rc.node.main.*node3/node.yaml"'
```

Attendre que le processus soit bien visible, remplacer `<PID_NODE3>` par le PID
retourné, puis exécuter **une seule fois** :

```bash
ssh ismail@192.168.168.103 'CRASH_TS=$(date -Is); printf "crash_time=%s\npid=%s\n" "$CRASH_TS" "<PID_NODE3>" > /tmp/b5-secondary-crash-20260915-node3-crash-time.txt; kill -9 "<PID_NODE3>"; echo node3_crashed >> /tmp/b5-secondary-crash-20260915-node3-crash-time.txt'
```

Le terminal du node3 doit alors s’arrêter. Ne pas tuer un autre processus et ne
pas utiliser `pkill -f`.

## 5. Redémarrer node3 et attendre son rattrapage

Attendre environ 15 à 30 secondes après le crash, puis ouvrir un nouveau
terminal et exécuter :

```bash
ssh -t ismail@192.168.168.103 'cd ~/blockchain-experiment-distributed && source .venv/bin/activate && export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" && python -m src.node.main --config config/nodes/node3/node.yaml --log-level INFO 2>&1 | tee -a /tmp/b5-secondary-crash-20260915-node3.log'
```

Attendre la fin du générateur et du drain de 300 secondes avant la collecte.
Ne pas redémarrer ni modifier les clés ou les configurations.

## 6. Préparer la collecte sur la machine de développement

Exécuter depuis `~/Bureau/blockchain-experiment-distributed`, pas depuis
node1 :

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"
mkdir -p results/raw_data/b5-secondary-crash-20260915
mkdir -p /tmp/b5-secondary-crash-20260915/node1 /tmp/b5-secondary-crash-20260915/node2 /tmp/b5-secondary-crash-20260915/node3
```

Copier les journaux, le manifeste et le marqueur de crash avec des commandes
`scp` complètes sur une seule ligne :

```bash
scp ismail@192.168.168.101:/tmp/b5-secondary-crash-20260915-node1.log results/raw_data/b5-secondary-crash-20260915-node1.log
scp ismail@192.168.168.102:/tmp/b5-secondary-crash-20260915-node2.log results/raw_data/b5-secondary-crash-20260915-node2.log
scp ismail@192.168.168.103:/tmp/b5-secondary-crash-20260915-node3.log results/raw_data/b5-secondary-crash-20260915-node3.log
scp ismail@192.168.168.101:/tmp/b5-secondary-crash-20260915-generator.log results/raw_data/b5-secondary-crash-20260915-generator.log
scp ismail@192.168.168.101:/home/ismail/blockchain-experiment-distributed/results/raw_data/b5-secondary-crash-20260915-node1-manifest.json results/raw_data/b5-secondary-crash-20260915-node1-manifest.json
scp ismail@192.168.168.103:/tmp/b5-secondary-crash-20260915-node3-crash-time.txt results/raw_data/b5-secondary-crash-20260915-node3-crash-time.txt
```

Copier ensuite les blocs. La collecte reste sur la machine de développement :

```bash
scp -r ismail@192.168.168.101:/home/ismail/blockchain-experiment-distributed/data/node1/blocks /tmp/b5-secondary-crash-20260915/node1/
scp -r ismail@192.168.168.102:/home/ismail/blockchain-experiment-distributed/data/node2/blocks /tmp/b5-secondary-crash-20260915/node2/
scp -r ismail@192.168.168.103:/home/ismail/blockchain-experiment-distributed/data/node3/blocks /tmp/b5-secondary-crash-20260915/node3/
```

Vérifier les fichiers avant l’analyse :

```bash
find results/raw_data -maxdepth 1 -type f -name 'b5-secondary-crash-20260915*' -printf '%f\n' | sort
find /tmp/b5-secondary-crash-20260915 -type f -printf '%p\n' | sort | head -n 20
```

## 7. Analyser depuis le dépôt de développement

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py --manifest results/raw_data/b5-secondary-crash-20260915-node1-manifest.json --node1-blocks /tmp/b5-secondary-crash-20260915/node1/blocks --node2-blocks /tmp/b5-secondary-crash-20260915/node2/blocks --node3-blocks /tmp/b5-secondary-crash-20260915/node3/blocks --node1-log results/raw_data/b5-secondary-crash-20260915-node1.log --node2-log results/raw_data/b5-secondary-crash-20260915-node2.log --node3-log results/raw_data/b5-secondary-crash-20260915-node3.log --output results/raw_data/b5-secondary-crash-20260915-summary.json
```

Ne pas ajouter `--clocks-synchronised` sans contrôle indépendant des horloges.

Examiner les événements liés au crash, aux rounds et au rattrapage :

```bash
grep -nEi 'BENCHMARK_(ACCEPT|REJECT|COMMIT)|round|timeout|sync|catch|peer|height|error' results/raw_data/b5-secondary-crash-20260915-node3.log | tail -n 200
```

Contrôler les indicateurs de base :

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path('results/raw_data/b5-secondary-crash-20260915-summary.json')
d = json.loads(p.read_text())
print('run_id=', d.get('run_id'))
print('submitted=', d.get('counts', {}).get('submitted'))
print('included_on_all_three=', d.get('counts', {}).get('included_on_all_three'))
print('success_rate_all_three=', d.get('rates', {}).get('success_rate_all_three'))
print('converged=', d.get('validity', {}).get('three_node_chain_converged_to_min_tip'))
print('final_chain=', d.get('final_chain'))
PY
```

Le résultat B5 ne sera déclaré valide qu’après vérification conjointe du
résumé JSON, du marqueur de crash, des journaux des trois nœuds et des blocs
copiés localement. Les nombres effectivement observés doivent remplacer toute
valeur attendue.
