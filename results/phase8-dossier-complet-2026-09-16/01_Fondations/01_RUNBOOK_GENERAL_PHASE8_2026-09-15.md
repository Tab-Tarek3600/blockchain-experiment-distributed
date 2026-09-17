# Runbook accéléré — fin des tests Phase 8

**Important :** ce document donne des commandes à exécuter manuellement, dans
l'ordre. Il ne crée pas de script d'orchestration. Les tests sont exécutés sur
les VMs ; la collecte et l'analyse restent sur la machine de développement.

Le mode accéléré produit **un essai par scénario**. Il ne remplace pas les
répétitions scientifiques 3–5 fois prévues dans le protocole. Les résultats
accélérés doivent être étiquetés exploratoires.

Ne jamais exécuter `make clean-data`, `rm -rf data`, ni remplacer les clés ou les
fichiers de configuration. Tous les contenus IPFS ci-dessous sont synthétiques
et non médicaux.

## 0. Variables et vérification locale

Sur la machine de développement :

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"

make check-oqs
python3 --version
```

Les tests B0, B1, B2 et B3 à `3 tx/s` sont déjà documentés. Ne pas les
recompter comme nouveaux résultats.

## 1. Démarrer ou vérifier les trois nœuds

Ouvrir trois terminaux sur la machine de développement. Exécuter une commande
par terminal. Les commandes démarrent uniquement le nœud prévu et conservent
les journaux dans `/tmp` de la VM.

### Terminal node1

```bash
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed &&
  source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs &&
  export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  python -m src.node.main \
    --config config/nodes/node1/node.yaml \
    --log-level INFO \
    2>&1 | tee /tmp/phase8-current-node1.log
'
```

### Terminal node2

```bash
ssh -t ismail@192.168.168.102 '
  cd ~/blockchain-experiment-distributed &&
  source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs &&
  export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  python -m src.node.main \
    --config config/nodes/node2/node.yaml \
    --log-level INFO \
    2>&1 | tee /tmp/phase8-current-node2.log
'
```

### Terminal node3

```bash
ssh -t ismail@192.168.168.103 '
  cd ~/blockchain-experiment-distributed &&
  source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs &&
  export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  python -m src.node.main \
    --config config/nodes/node3/node.yaml \
    --log-level INFO \
    2>&1 | tee /tmp/phase8-current-node3.log
'
```

Vérifier dans les trois terminaux : `listening on 0.0.0.0:9001`, deux pairs et
aucune erreur de configuration. Les nœuds doivent être lancés à moins de cinq
secondes d'intervalle.

## 2. B4 — 1 tx/s, inclusion et commit

Dans un quatrième terminal :

```bash
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed &&
  source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs &&
  export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
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
'
```

Attendre la fin du drain avant de copier les fichiers.

### Collecte B4

Depuis le dépôt de développement :

```bash
cd ~/Bureau/blockchain-experiment-distributed
mkdir -p results/raw_data/b4-rate-1p0-20260915
mkdir -p /tmp/b4-rate-1p0-20260915/node1 /tmp/b4-rate-1p0-20260915/node2 /tmp/b4-rate-1p0-20260915/node3

scp ismail@192.168.168.101:/tmp/phase8-current-node1.log \
  results/raw_data/b4-rate-1p0-20260915-node1.log
scp ismail@192.168.168.102:/tmp/phase8-current-node2.log \
  results/raw_data/b4-rate-1p0-20260915-node2.log
scp ismail@192.168.168.103:/tmp/phase8-current-node3.log \
  results/raw_data/b4-rate-1p0-20260915-node3.log
scp ismail@192.168.168.101:/tmp/b4-rate-1p0-20260915-generator.log \
  results/raw_data/b4-rate-1p0-20260915-generator.log
scp ismail@192.168.168.101:\
  ~/blockchain-experiment-distributed/results/raw_data/b4-rate-1p0-20260915-node1-manifest.json \
  results/raw_data/b4-rate-1p0-20260915-node1-manifest.json

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

### Analyse B4

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

Ne pas ajouter `--clocks-synchronised` sans contrôle indépendant des horloges.

## 3. B3-N — clients logiques supplémentaires

À exécuter après B4, un run à la fois, avec les nœuds inchangés. Chaque commande
reste envoyée à node1 uniquement.

```bash
# 2 clients
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
    --config config/nodes/node1/node.yaml --rate 1 --clients 2 --duration 60 \
    --payload-size 0 --run-id b3-clients2-1p0-20260915 --drain-timeout 300 \
    --manifest-output results/raw_data/b3-clients2-1p0-20260915-node1-manifest.json
'

# 4 clients
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
    --config config/nodes/node1/node.yaml --rate 1 --clients 4 --duration 60 \
    --payload-size 0 --run-id b3-clients4-1p0-20260915 --drain-timeout 300 \
    --manifest-output results/raw_data/b3-clients4-1p0-20260915-node1-manifest.json
'

# 8 clients
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
    --config config/nodes/node1/node.yaml --rate 1 --clients 8 --duration 60 \
    --payload-size 0 --run-id b3-clients8-1p0-20260915 --drain-timeout 300 \
    --manifest-output results/raw_data/b3-clients8-1p0-20260915-node1-manifest.json
'
```

Pour chaque run, récupérer le manifeste, les trois journaux et les trois
répertoires de blocs comme pour B4, en remplaçant le `run_id`.

## 4. B5 — crash/reprise accéléré

Ce scénario mesure un crash d'un nœud secondaire. Il ne modifie ni les clés ni
la chaîne persistée.

1. Démarrer les trois nœuds avec des journaux B5 dédiés, ou conserver les
   nœuds courants et filtrer ensuite par le manifeste.
2. Lancer une faible charge sur node1 :

```bash
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
    --config config/nodes/node1/node.yaml --rate 0.2 --clients 1 --duration 60 \
    --payload-size 0 --run-id b5-secondary-crash-20260915 --drain-timeout 300 \
    --manifest-output results/raw_data/b5-secondary-crash-20260915-node1-manifest.json
'
```

3. Pendant la charge, dans un autre terminal, identifier le PID node3 :

```bash
ssh ismail@192.168.168.103 \
  "pgrep -af '[s]rc.node.main.*node3/node.yaml'"
```

4. Arrêter uniquement le PID affiché (remplacer `<PID_NODE3>`). Ne jamais
   utiliser `pkill -f` :

```bash
ssh ismail@192.168.168.103 \
  "date -Is; kill -9 <PID_NODE3>; echo node3_crashed"
```

5. Après 15–30 secondes, redémarrer node3 dans un terminal séparé :

```bash
ssh -t ismail@192.168.168.103 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  python -m src.node.main --config config/nodes/node3/node.yaml --log-level INFO \
    2>&1 | tee -a /tmp/phase8-current-node3.log
'
```

6. Attendre le rattrapage, puis collecter les journaux, le manifeste et les
   blocs. Mesurer : hauteur avant crash, hauteur au redémarrage, temps de
   rattrapage, transactions incluses et hash/state_root finaux.

Ce run ne doit pas être présenté comme un test de panne Byzantine ni comme une
preuve de finalité BFT.

## 5. B6 — réseau dégradé avec `tc-netem`

Faire un seul scénario à la fois. Commencer par un délai de `50 ms ± 10 ms`,
puis éventuellement un run séparé avec `1 %` de perte.

### Trouver l'interface sur chaque VM

```bash
# node1 : route vers node2
IFACE=$(ip route get 192.168.168.102 | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
echo "$IFACE"
tc qdisc show dev "$IFACE"
```

Sur node2 utiliser `ip route get 192.168.168.101`. Sur node3 utiliser
`ip route get 192.168.168.101`.

Si une qdisc autre que `noqueue` est déjà présente, ne pas la remplacer sans
l'identifier. L'ajout peut perturber SSH ; garder une console locale de secours.

### Appliquer le délai sur les trois VMs

À exécuter localement dans un terminal de chaque VM :

```bash
sudo tc qdisc add dev "$IFACE" root netem delay 50ms 10ms
sudo tc qdisc show dev "$IFACE"
```

Lancer ensuite une faible charge sur node1 :

```bash
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs && export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
    --config config/nodes/node1/node.yaml --rate 0.2 --clients 1 --duration 60 \
    --payload-size 0 --run-id b6-delay50ms-20260915 --drain-timeout 300 \
    --manifest-output results/raw_data/b6-delay50ms-20260915-node1-manifest.json
'
```

Supprimer impérativement la perturbation sur les trois VMs après le run :

```bash
sudo tc qdisc del dev "$IFACE" root || true
tc qdisc show dev "$IFACE"
```

### Run séparé avec 1 % de perte, si nécessaire

Appliquer sur les trois VMs :

```bash
sudo tc qdisc add dev "$IFACE" root netem loss 1%
```

Lancer avec `run_id=b6-loss1pct-20260915` et supprimer ensuite :

```bash
sudo tc qdisc del dev "$IFACE" root || true
```

Ne récupérer les blocs par `scp` qu'après suppression de `netem`.

## 6. B7 — profil de ressources des trois VMs

À lancer avant un run B4 ou B6. Sur chaque VM, adapter le chemin `nodeN`.

```bash
NODE=node1
PID=$(pgrep -f "[s]rc.node.main.*${NODE}/node.yaml" | head -n1)
IFACE=$(ip route get 192.168.168.102 | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')
mkdir -p /tmp/phase8-b7
printf 'date='; date -Is
printf 'pid=%s iface=%s\n' "$PID" "$IFACE"
lscpu > /tmp/phase8-b7/${NODE}-lscpu.txt
free -h > /tmp/phase8-b7/${NODE}-memory.txt
df -h > /tmp/phase8-b7/${NODE}-disk.txt
ip -s link show "$IFACE" > /tmp/phase8-b7/${NODE}-network-before.txt
ps -p "$PID" -o pid,ppid,etime,%cpu,%mem,rss,vsz,cmd > /tmp/phase8-b7/${NODE}-process-before.txt
timeout 90 vmstat 1 > /tmp/phase8-b7/${NODE}-vmstat.txt
```

Dans un autre terminal, lancer le run B4 ou B6. Puis capturer l'état final :

```bash
ip -s link show "$IFACE" > /tmp/phase8-b7/${NODE}-network-after.txt
ps -p "$PID" -o pid,ppid,etime,%cpu,%mem,rss,vsz,cmd > /tmp/phase8-b7/${NODE}-process-after.txt
```

Pour node2 et node3, utiliser respectivement `NODE=node2`/`NODE=node3` et une
route vers une autre VM. Récupérer les fichiers :

```bash
scp -r ismail@192.168.168.101:/tmp/phase8-b7 ./results/raw_data/b7-node1
scp -r ismail@192.168.168.102:/tmp/phase8-b7 ./results/raw_data/b7-node2
scp -r ismail@192.168.168.103:/tmp/phase8-b7 ./results/raw_data/b7-node3
```

## 7. B8 — tests locaux EVM, contrats et confidentialité

Depuis le dépôt de développement :

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"

make check-oqs
python3 scripts/testing/test_phase7_confidentiality.py
python3 -m pytest tests/unit/test_ipfs_adapter.py -q
python3 -m pytest tests/integration/test_medical_contracts.py -q
```

Les trois tests de lecture/contrôle de la chaîne phase 7 se lancent sur chaque
VM, sans diffuser de transaction :

```bash
ssh ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  python3 scripts/testing/read_phase7_records.py --node node1 &&
  python3 scripts/testing/test_phase7_unauthorized_register.py --node node1
'
ssh ismail@192.168.168.102 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  python3 scripts/testing/read_phase7_records.py --node node2 &&
  python3 scripts/testing/test_phase7_unauthorized_register.py --node node2
'
ssh ismail@192.168.168.103 '
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate &&
  python3 scripts/testing/read_phase7_records.py --node node3 &&
  python3 scripts/testing/test_phase7_unauthorized_register.py --node node3
'
```

### B8-IPFS — ciphertext synthétique et réplication

Vérifier d'abord Kubo localement sur chaque VM :

```bash
curl -fsS -X POST http://127.0.0.1:5001/api/v0/version
```

Sur node1, créer un fichier explicitement synthétique (aucun plaintext médical)
et l'ajouter au fournisseur IPFS local :

```bash
ssh ismail@192.168.168.101 '
  printf "PHASE8-CIPHERTEXT-SYNTHETIC-v1-20260915" > /tmp/phase8-ciphertext-v1.bin
  cd ~/blockchain-experiment-distributed && source .venv/bin/activate
  python3 - <<"PY"
from pathlib import Path
from src.ipfs import IPFSClient

path = Path("/tmp/phase8-ciphertext-v1.bin")
client = IPFSClient("http://127.0.0.1:5001/api/v0", timeout=60)
cid = client.add_encrypted_file(path, filename=path.name)
raw = client.get_file(cid)
assert raw == path.read_bytes()
print(cid)
print(len(raw))
client.close()
PY
'
```

Noter le CID imprimé dans la sortie comme `<CID>`. Depuis la machine de
développement, demander le même CID à chaque fournisseur local :

```bash
CID=<CID>

ssh ismail@192.168.168.101 \
  "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/cat?arg=$CID' > /tmp/phase8-ciphertext-node1.bin && sha256sum /tmp/phase8-ciphertext-node1.bin"
ssh ismail@192.168.168.102 \
  "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/cat?arg=$CID' > /tmp/phase8-ciphertext-node2.bin && sha256sum /tmp/phase8-ciphertext-node2.bin"
ssh ismail@192.168.168.103 \
  "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/cat?arg=$CID' > /tmp/phase8-ciphertext-node3.bin && sha256sum /tmp/phase8-ciphertext-node3.bin"
```

Les trois SHA-256 doivent être identiques. Pinner ensuite le CID sur les trois
fournisseurs :

```bash
ssh ismail@192.168.168.101 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/add?arg=$CID'"
ssh ismail@192.168.168.102 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/add?arg=$CID'"
ssh ismail@192.168.168.103 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/add?arg=$CID'"
```

Ce test mesure la couche IPFS et la réplication du ciphertext ; il ne doit pas
être compté dans le TPS blockchain. La création d'une nouvelle version doit
produire un nouveau fichier/CID, jamais modifier le CID v1.

### API Flask/Gunicorn

Le dépôt courant contient `src/api/.gitkeep` mais pas d'application Flask ou
d'endpoint Gunicorn déployé. Ne pas déclarer cette sous-partie mesurée. Vérifier
et archiver explicitement :

```bash
find src/api -maxdepth 2 -type f -print
```

## 8. Suite de tests Python du dépôt

Sur la machine de développement, exécuter à la fin :

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
make test-unit
make test-integration
```

Les tests d'intégration sont des réseaux TCP locaux simulés sur la machine de
développement ; ils ne remplacent pas les runs VM B4–B7.

## 9. Contrôle final des artefacts

```bash
find results/raw_data -maxdepth 1 -type f -printf '%f\n' | sort
sha256sum results/raw_data/b4-rate-1p0-20260915-* 2>/dev/null || true
```

Pour chaque scénario, conserver : manifeste, journaux node1/node2/node3, blocs
node1/node2/node3, paramètres, erreurs éventuelles et résumé JSON. Ne jamais
publier une latence inter-VM numérique sans synchronisation indépendante des
horloges.
