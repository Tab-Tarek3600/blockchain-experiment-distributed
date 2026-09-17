# PHASE 3 — Transmission aux 3 VMs et vérification inter-VMs

Étape 4/4 du point 2 (D6). Objectif : les trois nœuds exécutent le même
code EVM, et un bloc à racine falsifiée ou hors plafond de gas est
rejeté **sur les trois machines**.

Toutes les commandes se tapent **depuis node1**
(`~/blockchain-experiment-distributed`), sauf mention contraire.

| Rôle  | IP                | Utilisateur |
|-------|-------------------|-------------|
| node1 | 192.168.168.101   | ismail      |
| node2 | 192.168.168.102   | ismail      |
| node3 | 192.168.168.103   | ismail      |

---

## 0. Prérequis à vérifier AVANT de copier

### 0.1 py-evm doit être installé sur les 3 VMs

C'est bloquant : sans lui, `src/evm/state.py` ne s'importe pas et
**aucun** test EVM ne tourne. Sur **chaque** VM :

```bash
cd ~/blockchain-experiment-distributed
python3 -c "import eth, rlp; print('py-evm OK', eth.__version__)"
```

Si la commande échoue, sur la VM concernée :

```bash
pip install "git+https://github.com/ethereum/py-evm.git@ffce74fa3c5d95682cdd5d84de82c80d60a56172" "rlp==4.1.0"
```

L'installation dure entre 2 et 5 minutes et exige un accès réseau. Si
les VMs n'ont pas Internet, il faut passer par le kit de wheels hors
ligne (`--python-version 312 --only-binary=:all: --platform
manylinux2014_x86_64`, jamais de wheel `cp313`).

### 0.2 Python 3.12

```bash
python3 --version        # 3.12.x attendu sur les 3 VMs
```

---

## 1. Copie des fichiers (20 fichiers)

7 fichiers ont changé depuis la dernière transmission
(`errors.py`, `executor.py`, `replay.py`, `node.py` et 3 fichiers de
tests) et `requirements.txt` est ajouté au manifeste. Le plus simple
est de tout recopier : l'ensemble ne pèse que 234 Ko.

### 1.1 Purger les anciens dossiers EVM

Indispensable : `scp -r src/evm host:.../src/` sur un dossier existant
crée `src/evm/evm`. Sur node2 **et** node3 :

```bash
ssh ismail@192.168.168.102 "rm -rf ~/blockchain-experiment-distributed/src/evm ~/blockchain-experiment-distributed/tests/unit/evm"
ssh ismail@192.168.168.103 "rm -rf ~/blockchain-experiment-distributed/src/evm ~/blockchain-experiment-distributed/tests/unit/evm"
```

### 1.2 Recréer l'arborescence

```bash
ssh ismail@192.168.168.102 "mkdir -p ~/blockchain-experiment-distributed/src/evm ~/blockchain-experiment-distributed/tests/unit/evm"
ssh ismail@192.168.168.103 "mkdir -p ~/blockchain-experiment-distributed/src/evm ~/blockchain-experiment-distributed/tests/unit/evm"
```

### 1.3 Copier vers node2

`$P` est volontairement un chemin **relatif** (`scp` le résout depuis
le home distant). Ne pas écrire `P=~/blockchain-experiment-distributed` :
le `~` serait expansé par votre shell **local**, pas par celui de la VM.

```bash
cd ~/blockchain-experiment-distributed
P=blockchain-experiment-distributed

scp requirements.txt              ismail@192.168.168.102:$P/requirements.txt
scp src/blockchain/block.py       ismail@192.168.168.102:$P/src/blockchain/block.py
scp src/node/consensus.py         ismail@192.168.168.102:$P/src/node/consensus.py
scp src/node/node.py              ismail@192.168.168.102:$P/src/node/node.py

scp src/evm/__init__.py           ismail@192.168.168.102:$P/src/evm/__init__.py
scp src/evm/addresses.py          ismail@192.168.168.102:$P/src/evm/addresses.py
scp src/evm/errors.py             ismail@192.168.168.102:$P/src/evm/errors.py
scp src/evm/executor.py           ismail@192.168.168.102:$P/src/evm/executor.py
scp src/evm/receipt.py            ismail@192.168.168.102:$P/src/evm/receipt.py
scp src/evm/replay.py             ismail@192.168.168.102:$P/src/evm/replay.py
scp src/evm/state.py              ismail@192.168.168.102:$P/src/evm/state.py

scp tests/unit/evm/__init__.py       ismail@192.168.168.102:$P/tests/unit/evm/__init__.py
scp tests/unit/evm/test_addresses.py ismail@192.168.168.102:$P/tests/unit/evm/test_addresses.py
scp tests/unit/evm/test_errors.py    ismail@192.168.168.102:$P/tests/unit/evm/test_errors.py
scp tests/unit/evm/test_executor.py  ismail@192.168.168.102:$P/tests/unit/evm/test_executor.py
scp tests/unit/evm/test_receipt.py   ismail@192.168.168.102:$P/tests/unit/evm/test_receipt.py
scp tests/unit/evm/test_replay.py    ismail@192.168.168.102:$P/tests/unit/evm/test_replay.py
scp tests/unit/evm/test_state.py     ismail@192.168.168.102:$P/tests/unit/evm/test_state.py

scp tests/unit/node/test_main.py     ismail@192.168.168.102:$P/tests/unit/node/test_main.py
scp tests/unit/node/test_node.py     ismail@192.168.168.102:$P/tests/unit/node/test_node.py

scp scripts/setup/MANIFEST-phase3.sha256 ismail@192.168.168.102:$P/scripts/setup/MANIFEST-phase3.sha256
```

### 1.4 Copier vers node3

Les mêmes commandes, avec `192.168.168.103` :

```bash
scp requirements.txt              ismail@192.168.168.103:$P/requirements.txt
scp src/blockchain/block.py       ismail@192.168.168.103:$P/src/blockchain/block.py
scp src/node/consensus.py         ismail@192.168.168.103:$P/src/node/consensus.py
scp src/node/node.py              ismail@192.168.168.103:$P/src/node/node.py

scp src/evm/__init__.py           ismail@192.168.168.103:$P/src/evm/__init__.py
scp src/evm/addresses.py          ismail@192.168.168.103:$P/src/evm/addresses.py
scp src/evm/errors.py             ismail@192.168.168.103:$P/src/evm/errors.py
scp src/evm/executor.py           ismail@192.168.168.103:$P/src/evm/executor.py
scp src/evm/receipt.py            ismail@192.168.168.103:$P/src/evm/receipt.py
scp src/evm/replay.py             ismail@192.168.168.103:$P/src/evm/replay.py
scp src/evm/state.py              ismail@192.168.168.103:$P/src/evm/state.py

scp tests/unit/evm/__init__.py       ismail@192.168.168.103:$P/tests/unit/evm/__init__.py
scp tests/unit/evm/test_addresses.py ismail@192.168.168.103:$P/tests/unit/evm/test_addresses.py
scp tests/unit/evm/test_errors.py    ismail@192.168.168.103:$P/tests/unit/evm/test_errors.py
scp tests/unit/evm/test_executor.py  ismail@192.168.168.103:$P/tests/unit/evm/test_executor.py
scp tests/unit/evm/test_receipt.py   ismail@192.168.168.103:$P/tests/unit/evm/test_receipt.py
scp tests/unit/evm/test_replay.py    ismail@192.168.168.103:$P/tests/unit/evm/test_replay.py
scp tests/unit/evm/test_state.py     ismail@192.168.168.103:$P/tests/unit/evm/test_state.py

scp tests/unit/node/test_main.py     ismail@192.168.168.103:$P/tests/unit/node/test_main.py
scp tests/unit/node/test_node.py     ismail@192.168.168.103:$P/tests/unit/node/test_node.py

scp scripts/setup/MANIFEST-phase3.sha256 ismail@192.168.168.103:$P/scripts/setup/MANIFEST-phase3.sha256
```

---

## 2. Vérification de l'intégrité — sur les 3 VMs

Sur **chaque** VM, y compris node1 :

```bash
cd ~/blockchain-experiment-distributed
sha256sum -c scripts/setup/MANIFEST-phase3.sha256
```

Attendu : **20 lignes `OK`**, aucun `FAILED`. Un `FAILED` signifie que
la copie est incomplète ou que le fichier a été édité localement : ne
pas continuer avant de l'avoir résolu.

Puis, toujours sur chaque VM :

```bash
python3 -m py_compile $(awk '{print $2}' scripts/setup/MANIFEST-phase3.sha256 | grep '\.py$')
echo "compilation OK"
```

---

## 3. Suite de tests sur les 3 VMs

Sur **chaque** VM :

```bash
cd ~/blockchain-experiment-distributed
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:$LD_LIBRARY_PATH
PYTHONPATH=. python3 -m pytest tests/unit/ -q
```

Attendu : **369 passed** (identique au poste de développement). Un
total différent signale un fichier manquant ; comparer avec :

```bash
PYTHONPATH=. python3 -m pytest tests/unit/ --collect-only -q | tail -3
```

`PYTHONPATH=.` est requis sur node2 et node3.

Puis la suite d'intégration (16 tests), qui ouvre de vraies sockets TCP
en local :

```bash
PYTHONPATH=. python3 -m pytest tests/integration/ -q
```

Attendu : **16 passed**, soit **385 au total**. Voir §6 sur les deux
tests *flaky* de ce répertoire.

---

## 4. Vérification inter-VMs proprement dite

C'est le critère de fin du point 2. Il ne suffit pas que les tests
passent sur chaque machine isolément : il faut constater le rejet
**entre** machines réelles.

### 4.1 Repartir d'une chaîne vide

Sur les 3 VMs :

```bash
cd ~/blockchain-experiment-distributed
rm -rf data/node1/blocks/* data/node2/blocks/* data/node3/blocks/* 2>/dev/null
ls data/*/blocks/ 2>/dev/null    # doit être vide
```

Chaque VM ne possède que son propre dossier ; la commande ignore
silencieusement les autres.

### 4.2 Lancer les 3 nœuds

Sur node1, node2, node3 (dans cet ordre, un terminal par VM) :

```bash
cd ~/blockchain-experiment-distributed
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:$LD_LIBRARY_PATH
PYTHONPATH=. python3 -m src.node.main --config config/nodes/nodeN/node.yaml
```

(remplacer `nodeN` par `node1`, `node2`, `node3` selon la machine).

### 4.3 Contrôle 1 — convergence avec état EVM

Laisser tourner 2 à 3 minutes, puis sur chaque VM (second terminal) :

```bash
cd ~/blockchain-experiment-distributed
PYTHONPATH=. python3 -c "
from src.blockchain.storage import ChainStorage
s = ChainStorage('data/nodeN')
h = s.get_tip_height()
b = s.get_latest_block()
print('hauteur    :', h)
print('block_hash :', b.block_hash.hex())
print('state_root :', b.state_root.hex())
"
```

Les trois VMs doivent afficher, à la même hauteur, **le même
`block_hash` et le même `state_root`**. Le `state_root` est le point
nouveau : jusqu'à D5 il n'était qu'un commentaire signé, il est
désormais recalculé par chaque receveur.

### 4.4 Contrôle 2 — un bloc à racine falsifiée est rejeté

Le test unitaire le prouve en mémoire ; ici on le prouve **sur le
réseau**. Depuis node1, avec les 3 nœuds arrêtés :

```bash
cd ~/blockchain-experiment-distributed
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:$LD_LIBRARY_PATH
PYTHONPATH=. python3 -m pytest tests/unit/node/test_node.py -q -k "racine_falsifiee or plafond_de_gas or producteur"
```

Attendu : **5 passed** — les 3 tests de racine falsifiée, celui du
plafond de gas côté receveur, et celui du producteur qui ne fabrique
pas de bloc hors plafond.

### 4.5 Contrôle 3 — même verdict sur les 3 machines

Le déterminisme est la propriété critique : un bloc refusé par node2
doit l'être aussi par node3, sinon la chaîne fourche. Sur **chaque**
VM :

```bash
cd ~/blockchain-experiment-distributed
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:$LD_LIBRARY_PATH
PYTHONPATH=. python3 -c "
from src.evm.state import EVMState, BLOCK_GAS_LIMIT
from src.evm.executor import EVMExecutor
from src.evm.errors import BlockGasLimitExceeded
from src.blockchain.transaction import Transaction
from src.crypto.address import public_key_to_address

PK = b'\x11' * 1312
sender = public_key_to_address(PK)
st = EVMState(); st.set_balance(sender, 10**20); st.commit()
ex = EVMExecutor(st)

def tx(n, gl):
    return Transaction.create(nonce=n, public_key=PK, recipient=b'\x77'*20,
                              value=1, gas_limit=gl, gas_price=0, data=b'')

# 1) bloc honnete annoncant large : doit PASSER (restitution du gas)
r = ex.execute_block([tx(i, 1_000_000) for i in range(31)],
                     block_number=1, timestamp=1)
print('bloc honnete   : ACCEPTE, gas =', r.gas_used)
print('state_root     :', r.state_root.hex())

# 2) bloc hors plafond : doit ETRE REFUSE
st2 = EVMState(); st2.set_balance(sender, 10**20); st2.commit()
try:
    EVMExecutor(st2).execute_block([tx(0, BLOCK_GAS_LIMIT), tx(1, BLOCK_GAS_LIMIT)],
                                   block_number=1, timestamp=1)
    print('bloc hors plafond : ACCEPTE  <-- ANOMALIE')
except BlockGasLimitExceeded as e:
    print('bloc hors plafond : REFUSE  ', e)
"
```

Attendu, **identique mot pour mot sur les 3 VMs** :

```
bloc honnete   : ACCEPTE, gas = 651000
state_root     : 16f06d3becd8c8a2314f485057ec2a2098fe7e33dca842c7b7eba99e24204d21
bloc hors plafond : REFUSE   block gas limit exceeded: transaction 1 announces 30000000 gas, only 29979000 remains (limit 30000000)
```

Ces trois valeurs sont celles obtenues sur le poste de développement.
`gas = 651000` correspond à 31 × 21 000 : les 31 transactions annoncent
1 000 000 chacune (31 M au total, au-dessus du plafond) mais n'en
consomment que 21 000. **C'est précisément le cas que l'ancienne
pré-passe rejetait à tort** ; le voir passer sur les 3 VMs valide le
correctif du point 1.

Le `state_root` identique sur trois machines distinctes est la preuve
que le rejeu EVM est déterministe. S'il diffère, il y a divergence de
version de py-evm : comparer `pip show py-evm rlp` sur les 3 VMs.

---

## 5. Critères de fin du point 2 (D6)

| # | Critère | Où le vérifier |
|---|---|---|
| 1 | Suite verte sur les 3 VMs (369 + 16 = 385) | §3 |
| 2 | Bloc à racine falsifiée rejeté | §4.4 |
| 3 | Bloc hors plafond de gas rejeté | §4.4 et §4.5 |
| 4 | Bloc honnête annonçant large accepté | §4.5 |
| 5 | 3 VMs convergentes (`block_hash` + `state_root`) | §4.3 |
| 6 | Verdict identique sur les 3 machines | §4.5 |

---

## 6. Points d'attention connus

- **`docs/INSTALL-py-evm.md` est référencé par `requirements.txt` mais
  n'existe pas.** La procédure d'installation est reprise en §0.1
  ci-dessus. À créer si vous souhaitez que la référence soit valide.
- **`test_socket_p2p.py::test_node_started_later_still_connects`** est
  *flaky* (préexistant, ligne 309 sans `wait_until`). Un échec isolé de
  ce test n'invalide pas la transmission : le relancer seul.
- **`test_three_nodes_tcp.py::test_transaction_is_removed_from_all_mempools_after_inclusion`**
  est également *flaky* en suite combinée : la fixture `network` est de
  portée module, une socket morte contamine les tests suivants.
- Clé USB Windows : `sed -i 's/\r$//'` sur les fichiers transférés, et
  `chmod +x` sur les scripts shell.
- Ne jamais faire `pkill -f "src.node.main"` depuis une session SSH que
  vous voulez conserver.
