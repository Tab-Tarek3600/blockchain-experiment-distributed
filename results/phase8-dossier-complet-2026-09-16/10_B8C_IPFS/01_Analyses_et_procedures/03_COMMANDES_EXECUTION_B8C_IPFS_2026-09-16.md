# Commandes d'exécution B8-C — 16 septembre 2026

Ces commandes exécutent **B8-C IPFS uniquement**. Elles ne lancent aucun
`b8b-tcp-*`, ne créent aucune transaction blockchain, ne suppriment aucune
clé/donnée et n'appliquent pas `tc-netem`.

## Variables à adapter

Depuis la machine de développement :

```bash
cd /home/user/repo
export REMOTE_USER=ismail
export REMOTE_REPO='~/Bureau/blockchain-experiment-distributed'
export SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=15'
```

Si le dépôt distant se trouve dans `~/blockchain-experiment-distributed`,
remplacer `REMOTE_REPO` partout. Vérifier d'abord que les VMs sont accessibles.

## 1. Pré-vérification lecture seule

```bash
for pair in 'node1 192.168.168.101' 'node2 192.168.168.102' 'node3 192.168.168.103'; do
  set -- $pair; NODE=$1; IP=$2
  echo "===== $NODE $IP ====="
  ssh $SSH_OPTS "$REMOTE_USER@$IP" "
    hostname
    curl -fsS -X POST http://127.0.0.1:5001/api/v0/version; echo
    curl -fsS -X POST http://127.0.0.1:5001/api/v0/id; echo
    ss -ltn | grep -E ':(4001|5001)\\b' || true
    free -h
    df -h /var/lib/ipfs || true
    pgrep -af '[i]pfs daemon' || true
    cat /sys/fs/cgroup/memory.events 2>/dev/null || true
    IFACE=\$(ip route get 192.168.168.101 | sed -n 's/.* dev \\([^ ]*\\).*/\\1/p')
    tc qdisc show dev \"\$IFACE\"
  " | tee "results/raw_data/b8c-precheck-$NODE.txt"
done
```

Conditions d'arrêt : API Kubo indisponible, API non liée à loopback, absence
des pairs attendus, OOM signalé ou qdisc réseau inattendue. Pour la qdisc,
choisir une route vers un pair : node1 vers `192.168.168.102`, node2/node3
vers `192.168.168.101`; une qdisc `netem` existante doit être signalée et non
modifiée.

## 2. Installer le script de mesure sur les trois VMs

Le script ne démarre ni n'arrête aucun daemon :

```bash
for pair in 'node1 192.168.168.101' 'node2 192.168.168.102' 'node3 192.168.168.103'; do
  set -- $pair; NODE=$1; IP=$2
  ssh $SSH_OPTS "$REMOTE_USER@$IP" "mkdir -p $REMOTE_REPO/scripts/testing"
  scp $SSH_OPTS scripts/testing/b8c_ipfs_vm_measure.py \
    "$REMOTE_USER@$IP:$REMOTE_REPO/scripts/testing/b8c_ipfs_vm_measure.py"
done
```

Si le code du dépôt n'est pas identique sur les VMs, copier aussi `src/ipfs/`
et `src/__init__.py` depuis une version contrôlée ; ne pas copier de clés,
configurations ou datastore.

## 3. Pré-vérification JSON par VM

```bash
for pair in 'node1 192.168.168.101' 'node2 192.168.168.102' 'node3 192.168.168.103'; do
  set -- $pair; NODE=$1; IP=$2
  ssh $SSH_OPTS "$REMOTE_USER@$IP" "
    cd $REMOTE_REPO && source .venv/bin/activate && PYTHONPATH=. \\
    python3 scripts/testing/b8c_ipfs_vm_measure.py precheck \\
      --node $NODE --output /tmp/b8c-precheck-$NODE.json
  " > "results/raw_data/b8c-precheck-$NODE.json"
done
```

## 4. Créer les deux ciphertexts synthétiques sur node1

Le script crée les octets en mémoire ; il n'y a aucun plaintext médical et
chaque version fait exactement 128 octets. L'ajout IPFS pinne les objets sur
node1, puis le script vérifie CID, SHA-256 et octets récupérés.

```bash
IP1=192.168.168.101
ssh $SSH_OPTS "$REMOTE_USER@$IP1" "
  cd $REMOTE_REPO && source .venv/bin/activate && PYTHONPATH=. \\
  python3 scripts/testing/b8c_ipfs_vm_measure.py seed \\
    --node node1 --output /tmp/b8c-seed-node1.json
" | tee results/raw_data/b8c-seed-node1.log

scp $SSH_OPTS "$REMOTE_USER@$IP1:/tmp/b8c-seed-node1.json" \
  results/raw_data/b8c-seed-node1.json
```

Le résultat doit contenir `seed_ok: true`, deux CID différents et deux
SHA-256 différents. En cas d'échec, arrêter ici.

## 5. Distribuer le manifeste, récupérer et pinner sur node1/2/3

Le manifeste ne contient que les CID, hashes, tailles et latences de seed ; il
ne contient pas de clé.

```bash
for pair in 'node1 192.168.168.101' 'node2 192.168.168.102' 'node3 192.168.168.103'; do
  set -- $pair; NODE=$1; IP=$2
  scp $SSH_OPTS results/raw_data/b8c-seed-node1.json \
    "$REMOTE_USER@$IP:/tmp/b8c-seed-node1.json"
done
```

## 6. Mesurer chaque fournisseur — 30 échantillons locaux

Le premier `cat` de chaque CID peut inclure Bitswap et est conservé sous
`replication_fetch`. Les 30 mesures suivantes utilisent `perf_counter_ns()`
sur la VM concernée et mesurent séparément `cat_local`, `has_block_stat`,
`pin_add` et `pin_ls`.

```bash
for pair in 'node1 192.168.168.101' 'node2 192.168.168.102' 'node3 192.168.168.103'; do
  set -- $pair; NODE=$1; IP=$2
  ssh $SSH_OPTS "$REMOTE_USER@$IP" "
    cd $REMOTE_REPO && source .venv/bin/activate && PYTHONPATH=. \\
    python3 scripts/testing/b8c_ipfs_vm_measure.py measure \\
      --node $NODE --manifest /tmp/b8c-seed-node1.json \\
      --samples 30 --output /tmp/b8c-ipfs-20260916-$NODE.json
  " | tee "results/raw_data/b8c-ipfs-20260916-$NODE-run.log"
  scp $SSH_OPTS "$REMOTE_USER@$IP:/tmp/b8c-ipfs-20260916-$NODE.json" \
    "results/raw_data/b8c-ipfs-20260916-$NODE.json"
done
```

Chaque commande doit finir avec `ok: true`, `all_integrity_ok: true`,
`all_operations_successful: true`, zéro échec dans chaque opération et
`replication_fetch` réussi sur node2/node3.

## 7. Lire les références blockchain historiques — lecture seule

Ces commandes ne soumettent aucune transaction. Elles lisent uniquement les
références déjà enregistrées en phase 7 :

```bash
for pair in 'node1 192.168.168.101' 'node2 192.168.168.102' 'node3 192.168.168.103'; do
  set -- $pair; NODE=$1; IP=$2
  ssh $SSH_OPTS "$REMOTE_USER@$IP" "
    cd $REMOTE_REPO && source .venv/bin/activate && \\
    python3 scripts/testing/read_phase7_records.py --node $NODE
  " | tee "results/raw_data/b8c-blockchain-readonly-$NODE.txt"
done
```

Conserver ces sorties séparément. Elles servent à vérifier les CID/hash
historiques, pas à inscrire les nouveaux CID B8-C.

## 8. Produire le résumé et l'analyse

```bash
python3 scripts/testing/summarize_b8c_ipfs.py \
  --input \
    results/raw_data/b8c-ipfs-20260916-node1.json \
    results/raw_data/b8c-ipfs-20260916-node2.json \
    results/raw_data/b8c-ipfs-20260916-node3.json \
  --output results/raw_data/b8c-ipfs-20260916-summary.json \
  --analysis-output results/raw_data/phase8-b8c-ipfs-analysis-2026-09-16.md
```

Le code retour `0` signifie que le résumé passe les critères CID, SHA-256,
intégrité et opérations. Le code retour `2` signifie qu'un résultat doit être
analysé ; il ne faut pas le transformer en succès.

## 9. Fichiers à me renvoyer

```text
results/raw_data/b8c-precheck-node1.txt
results/raw_data/b8c-precheck-node2.txt
results/raw_data/b8c-precheck-node3.txt
results/raw_data/b8c-precheck-node1.json
results/raw_data/b8c-precheck-node2.json
results/raw_data/b8c-precheck-node3.json
results/raw_data/b8c-seed-node1.json
results/raw_data/b8c-ipfs-20260916-node1.json
results/raw_data/b8c-ipfs-20260916-node2.json
results/raw_data/b8c-ipfs-20260916-node3.json
results/raw_data/b8c-ipfs-20260916-node1-run.log
results/raw_data/b8c-ipfs-20260916-node2-run.log
results/raw_data/b8c-ipfs-20260916-node3-run.log
results/raw_data/b8c-blockchain-readonly-node1.txt
results/raw_data/b8c-blockchain-readonly-node2.txt
results/raw_data/b8c-blockchain-readonly-node3.txt
results/raw_data/b8c-ipfs-20260916-summary.json
results/raw_data/phase8-b8c-ipfs-analysis-2026-09-16.md
```

Ne pas envoyer de clés privées, de configuration sensible ou de datastore IPFS.
