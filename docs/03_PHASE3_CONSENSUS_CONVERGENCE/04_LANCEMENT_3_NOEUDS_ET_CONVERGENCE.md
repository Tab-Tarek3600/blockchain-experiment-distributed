# Étapes 4e et 4f — Lancer les 3 nœuds et vérifier l'accord

Les tests passent partout (4d ✅). Dernière ligne droite de D6.

- **4e** : les 3 nœuds tournent ensemble et convergent
- **4f** : les 3 machines rendent le **même verdict**

---

## 4e — Lancer les 3 nœuds

### 1. Repartir d'une chaîne vide

Sur **chaque** VM, dans son propre dossier :

```bash
cd ~/blockchain-experiment-distributed
rm -rf data/node1/blocks/* data/node2/blocks/* data/node3/blocks/*
```

> Indispensable. Les blocs déjà sur disque datent d'avant `state_root` ;
> les relire donnerait `BlockError: missing field 'state_root'`.

### 2. Démarrer, un terminal par VM

**node1** (192.168.168.101) :

```bash
cd ~/blockchain-experiment-distributed
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:$LD_LIBRARY_PATH
PYTHONPATH=. python3 -m src.node.main --config config/nodes/node1/node.yaml
```

**node2** (192.168.168.102) : idem avec `node2/node.yaml`
**node3** (192.168.168.103) : idem avec `node3/node.yaml`

Laisser tourner **2 à 3 minutes** (un bloc toutes les 5 s, round-robin
sur 3 validateurs).

### 3. Ce que vous devez voir défiler

```
block accepted at height 1 from validator ...
block accepted at height 2 from validator ...
```

**Signaux d'alarme** — s'ils apparaissent, arrêter et me les envoyer :

| Message | Signification |
|---|---|
| `STATE ROOT MISMATCH` | les nœuds calculent des états différents |
| `state verification failed` | le rejeu EVM a échoué |
| `missing field 'state_root'` | anciens blocs non purgés (revoir l'étape 1) |
| `is not in authorized_validators` | mauvaise config sur cette VM |

---

## 4f — Vérifier l'accord des 3 machines

### Contrôle 1 — même chaîne, même état

Laisser les nœuds tourner. Dans un **second terminal** sur chaque VM
(remplacer `nodeN` par la machine courante) :

```bash
cd ~/blockchain-experiment-distributed
PYTHONPATH=. python3 -c "
from src.blockchain.storage import ChainStorage
s = ChainStorage('data/nodeN')
b = s.get_latest_block()
print('hauteur    :', s.get_tip_height())
print('block_hash :', b.block_hash.hex())
print('state_root :', b.state_root.hex())
"
```

**Attendu : à hauteur égale, `block_hash` et `state_root` identiques
sur les 3 VMs.**

Les hauteurs peuvent différer d'une unité (une VM vient de recevoir un
bloc que l'autre n'a pas encore). Dans ce cas, relancer la commande sur
la VM en retard quelques secondes plus tard et comparer à hauteur
égale.

`state_root` est le point nouveau : jusqu'à D5 ce n'était qu'un
commentaire signé, il est désormais **recalculé par chaque receveur**.

### Contrôle 2 — même verdict sur un bloc hostile

Le cœur de D6. Sur **chaque** VM :

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

r = ex.execute_block([tx(i, 1_000_000) for i in range(31)],
                     block_number=1, timestamp=1)
print('bloc honnete   : ACCEPTE, gas =', r.gas_used)
print('state_root     :', r.state_root.hex())

st2 = EVMState(); st2.set_balance(sender, 10**20); st2.commit()
try:
    EVMExecutor(st2).execute_block(
        [tx(0, BLOCK_GAS_LIMIT), tx(1, BLOCK_GAS_LIMIT)],
        block_number=1, timestamp=1)
    print('bloc hors plafond : ACCEPTE  <-- ANOMALIE')
except BlockGasLimitExceeded as e:
    print('bloc hors plafond : REFUSE  ', e)
"
```

**Attendu, mot pour mot, sur les 3 VMs :**

```
bloc honnete   : ACCEPTE, gas = 651000
state_root     : 16f06d3becd8c8a2314f485057ec2a2098fe7e33dca842c7b7eba99e24204d21
bloc hors plafond : REFUSE   block gas limit exceeded: transaction 1 announces 30000000 gas, only 29979000 remains (limit 30000000)
```

Lecture des deux lignes :

- **`gas = 651000`** = 31 × 21 000. Les 31 transactions annoncent
  1 000 000 chacune (31 M, au-dessus du plafond) mais n'en consomment
  que 21 000. **C'est exactement le bloc que l'ancienne version
  rejetait à tort.** Le voir accepté sur les 3 VMs valide le
  correctif A.
- **`29979000 remains`** = 30 000 000 − 21 000. Le gas non consommé par
  la première transaction a bien été **rendu au pool** : c'est la
  restitution, visible en clair.

Si le `state_root` diffère d'une VM à l'autre, c'est une divergence de
version py-evm :

```bash
pip show py-evm rlp | grep -E "Name|Version"
```

---

## Arrêter les nœuds

`Ctrl+C` dans chaque terminal.

> Ne **jamais** faire `pkill -f "src.node.main"` depuis une session SSH
> que vous voulez garder : la commande tue la session elle-même.

---

## Critères de fin de D6

| # | Critère | Étape |
|---|---|---|
| 1 | Suite verte sur les 3 VMs | 4d ✅ |
| 2 | Racine falsifiée rejetée | 4d ✅ |
| 3 | Bloc hors plafond rejeté | 4f, contrôle 2 |
| 4 | Bloc honnête annonçant large accepté | 4f, contrôle 2 |
| 5 | 3 VMs convergentes | 4f, contrôle 1 |
| 6 | Verdict identique partout | 4f, contrôle 2 |

Les 6 remplis ⇒ **D6 terminé**, la PHASE 3 passe à D8 (déploiement de
contrats de bout en bout), qui ouvre la PHASE 4.

---

## À me renvoyer

1. les 3 sorties du **contrôle 1** (hauteur, `block_hash`, `state_root`) ;
2. les 3 sorties du **contrôle 2** ;
3. toute ligne `MISMATCH`, `REJECTED` ou `Traceback` vue dans les
   terminaux des nœuds.
