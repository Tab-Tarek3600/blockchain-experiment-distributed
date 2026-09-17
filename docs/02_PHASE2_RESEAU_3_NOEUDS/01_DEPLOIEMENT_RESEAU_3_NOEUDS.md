# Déploiement du réseau 3 nœuds (PHASE 2)

Procédure complète et vérifiée pour lancer la blockchain sur trois VMs
Ubuntu Server. Chaque étape a été exécutée réellement ; les pièges
signalés ont tous été rencontrés en conditions réelles.

**Résultat attendu** : trois nœuds qui se connectent en TCP, produisent
des blocs à tour de rôle (PoA round-robin) et convergent sur la même
chaîne.

---

## 0. Topologie

| Nœud  | IP                | Port | Rôle                          |
|-------|-------------------|------|-------------------------------|
| node1 | 192.168.168.101   | 9001 | validateur, index 0 (genesis) |
| node2 | 192.168.168.102   | 9001 | validateur, index 1           |
| node3 | 192.168.168.103   | 9001 | validateur, index 2           |

Les VMs sont en mode **bridge** et doivent se pinger mutuellement.

Le proposeur du round `r` d'un bloc de hauteur `h` est déterminé par
`authorized_validators[(h + r) % 3]`. Le round 0 est le tour normal ; après
expiration de `round_timeout_seconds`, le validateur suivant reprend la
même hauteur. L'**ordre** de cette liste est donc une donnée de consensus :
il doit être strictement identique sur les trois machines.

### Ce qui doit être identique sur les 3 VMs

- `authorized_validators` — même contenu **et même ordre**
- `genesis_validator_public_key`
- `genesis_timestamp`
- `block_interval_seconds`
- `round_timeout_seconds`
- le code source (`src/`, `Makefile`, `scripts/`)

### Ce qui est propre à chaque VM

- `keys/nodeN/` — la paire ML-DSA. **La clé secrète ne quitte jamais sa
  machine.**
- `data/nodeN/` — la chaîne stockée localement
- `.venv/`
- le chemin absolu du projet et le nom d'utilisateur (peuvent différer)

---

## 1. Prérequis système (sur chaque VM)

```bash
sudo apt update
sudo apt install -y build-essential cmake gcc ninja-build git \
                    libssl-dev python3-dev python3-pip openssh-server make
```

`libssl-dev` est requis : les en-têtes OpenSSL sont nécessaires à la
compilation de liboqs. Le paquet runtime `libssl.so.3` ne suffit pas.

`openssh-server` est requis pour `scp` entre VMs. Sans lui :
`connect to host ... port 22: connection refused`.

Si `ufw` est actif, ouvrez les deux ports :

```bash
sudo ufw status
sudo ufw allow 22/tcp
sudo ufw allow 9001/tcp
```

---

## 2. liboqs natif (sur chaque VM)

```bash
cd ~/blockchain-experiment-distributed
bash scripts/setup/install_liboqs.sh
```

Le script vérifie d'abord la présence de `git`, `cmake`, `gcc` et des
en-têtes OpenSSL, puis compile liboqs 0.16.0 dans `$HOME/_oqs`.

Voir `docs/01_PHASE1_FONDATIONS/01_INSTALLATION_ENVIRONNEMENT_LIBOQS.md` pour la procédure manuelle.

> **Ne jamais relancer une compilation liboqs sur une VM peu dotée en
> RAM** : le build parallèle peut déclencher un OOM.

---

## 3. Environnement Python (sur chaque VM)

```bash
cd ~/blockchain-experiment-distributed
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -e . --no-build-isolation

export OQS_INSTALL_PATH=$HOME/_oqs
pytest tests/ -q
```

Les trois VMs doivent afficher **le même nombre de tests passés**.

### `pip install -e .` échoue sans réseau

```
Failed to establish a new connection: [Errno -3] Temporary failure in name resolution
ERROR: No matching distribution found for setuptools>=40.8.0
```

`pip` tente de télécharger `setuptools` dans un environnement de build
isolé. L'option `--no-build-isolation` réutilise celui du venv.

`pip install -e .` reste **optionnel** : `pytest.ini` définit
`pythonpath = .`, les scripts font leur propre `sys.path.insert`, et
`make nodeN` lance `python -m` depuis la racine. En cas de blocage,
préfixez les scripts par `PYTHONPATH=.` et passez outre.

---

## 4. Génération des clés (sur chaque VM)

Chaque nœud génère **sa propre** paire ML-DSA-44. La clé secrète reste
sur sa machine ; seule la partie publique circule.

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate

# écrire d'abord en local, pas directement sur la clé USB
PYTHONPATH=. python3 scripts/setup/gen_validator_key.py \
  --key-dir keys/node1 --json > /tmp/node1.json     # adapter N

# vérifier avant de copier
python3 -c "
import json; d = json.load(open('/tmp/node1.json'))
print(d['address_hex'], len(d['public_key_hex']), d['reused_existing'])
"
# attendu : 40 caractères d'adresse, 2624 pour la clé publique

cp /tmp/node1.json /mnt/usb/node1.json
```

Le fragment ne contient que `key_dir`, `public_key_hex`, `address_hex`
et `reused_existing`. **Aucun secret.**

Le script est **idempotent** : relancé sur un `--key-dir` existant, il
recharge la paire au lieu d'en générer une nouvelle
(`reused_existing: true`). On peut le rejouer sans risque.

> **N'écrivez jamais directement sur la destination finale.** Le shell
> crée le fichier de sortie *avant* d'exécuter la commande : en cas
> d'échec, vous obtenez un fichier vide et un faux sentiment de
> réussite. Écrivez dans `/tmp`, vérifiez, puis copiez.

Démontez proprement la clé après écriture :

```bash
sudo umount /mnt/usb
```

---

## 5. Assemblage de `nodes.json` (sur VM1 uniquement)

Rassemblez les trois fragments sur une seule machine, puis :

```bash
PYTHONPATH=. python3 scripts/setup/build_nodes_json.py \
  --fragments /mnt/usb \
  --node node1=192.168.168.101 \
  --node node2=192.168.168.102 \
  --node node3=192.168.168.103 \
  --out nodes.json --force
```

Le script affiche un récapitulatif de l'ordre PoA :

```
[0] node1  192.168.168.101:9001  b26dcbc8...  <-- genesis
[1] node2  192.168.168.102:9001  72027e0f...
[2] node3  192.168.168.103:9001  00126cd9...
```

Garde-fous intégrés : fragment manquant, répertoire absent, sortie
existante sans `--force`, et surtout **deux nœuds ayant la même
adresse** — signe qu'un `keys/` a été copié d'une VM à l'autre, ce qui
casserait le round-robin.

Vérifiez le résultat :

```bash
python3 -c "
import json
for n in json.load(open('nodes.json')):
    print(n['node_id'], n['address_hex'][:16], len(n['public_key_hex']))
"
```

Trois adresses **distinctes**, `public_key_hex` de 2624 caractères.

---

## 6. Génération des configs YAML (sur VM1)

```bash
PYTHONPATH=. python3 scripts/setup/make_configs.py \
  --nodes nodes.json --out config/nodes/ --force

grep -rc REMPLACER config/nodes/ ; echo "--- attendu : 0 partout"
```

### Piège : `--force` est obligatoire

Les gabarits `config/nodes/nodeN/node.yaml` sont versionnés dans le
dépôt. Sans `--force`, le script s'arrête sur :

```
ERREUR : config/nodes/node1/node.yaml existe deja. Utilisez --force pour ecraser.
```

Message facile à rater dans le défilement. Les gabarits restent alors en
place avec leurs 7 placeholders `REMPLACER_*`, et le lancement échoue
plus tard sur :

```
ConfigError: invalid config field: non-hexadecimal number found in fromhex() arg at position 0
```

Cette erreur signifie qu'une valeur de `authorized_validators` commence
par un caractère non hexadécimal — typiquement le `R` de `REMPLACER`.

### Piège : ne pas doubler le chemin

`--out` attend le répertoire **parent** ; le script ajoute lui-même
`/nodeN/node.yaml`. Un chemin déjà suffixé produit
`config/nodes/nodes/node1/node.yaml`, et les vrais fichiers restent des
gabarits. Vérifiez :

```bash
find config -name 'node.yaml' | sort
# attendu : exactement 3 fichiers, sans "nodes/nodes"
```

---

## 7. Distribution des configs

Chaque VM ne reçoit **que la sienne** :

```bash
scp config/nodes/node2/node.yaml \
    ismail@192.168.168.102:~/blockchain-experiment-distributed/config/nodes/node2/node.yaml

scp config/nodes/node3/node.yaml \
    ismail@192.168.168.103:~/blockchain-experiment-distributed/config/nodes/node3/node.yaml
```

Copier le fichier seul plutôt que `scp -r` sur le dossier évite de
recréer un niveau imbriqué.

Contrôle sur chaque VM :

```bash
cd ~/blockchain-experiment-distributed
grep -c REMPLACER config/nodes/node2/node.yaml    # 0 attendu

python3 -c "
from src.node.config import NodeConfig
c = NodeConfig.from_file('config/nodes/node2/node.yaml')
print('écoute :', c.host, c.port)
print('peers  :', [(p.host, p.port) for p in c.peers])
print('genesis:', c.genesis_validator_public_key.hex()[:32])
print('vals   :', [v.hex()[:12] for v in c.authorized_validators])
"
```

Le `genesis` et la liste `vals` doivent être **identiques sur les trois
VMs**. Deux peers par nœud, jamais soi-même.

---

## 8. Vérifier que le code est identique

Étape indispensable. Un fichier divergent produit des symptômes
déroutants : pairs qui se connectent puis se déconnectent, protocole de
synchronisation absent, `make: *** No rule to make target 'node1'`.

Sur les **trois** VMs :

```bash
cd ~/blockchain-experiment-distributed
md5sum Makefile src/node/socket_p2p.py src/node/node.py \
       src/node/main.py src/node/p2p.py src/node/config.py
```

Les six sommes doivent correspondre. En cas d'écart, resynchronisez
depuis la VM de référence :

```bash
rsync -av --delete \
  --exclude '.venv' --exclude 'keys' --exclude 'data' \
  --exclude '__pycache__' --exclude '*.egg-info' --exclude 'config/nodes' \
  ./ ismail@192.168.168.102:~/blockchain-experiment-distributed/
```

Les exclusions sont critiques : `keys/` contient la paire ML-DSA propre
à chaque nœud, `config/nodes` sa configuration, `data/` sa chaîne.

---

## 9. Lancement

Un terminal par VM, démarrés à **moins de 5 secondes d'intervalle**
(délai de grâce pour l'établissement des connexions).

```bash
# VM1
cd ~/blockchain-experiment-distributed && source .venv/bin/activate
make node1

# VM2 -> make node2      # VM3 -> make node3
```

Sans Makefile à jour, la commande équivalente :

```bash
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:$LD_LIBRARY_PATH
python3 -m src.node.main --config config/nodes/node1/node.yaml
```

Options utiles :

| Option | Effet |
|---|---|
| `--log-level DEBUG` | trace détaillée du transport |
| `--no-propose` | écoute et relaie, ne produit jamais de bloc |
| `--send-tx` | soumet une transaction de test au démarrage |
| `--tx-value N` | montant de cette transaction (défaut 100) |

### Sortie attendue

Le format est `HH:MM:SS NIVEAU  [node] message` :

```
21:58:03 INFO    [node] node_id           : node2 (Node2)
21:58:03 INFO    [node] local address     : 017daee614c53683272671...
21:58:03 INFO    [node] listening on      : 192.168.168.102:9001
21:58:03 INFO    [node] peers             : 192.168.168.101:9001, 192.168.168.103:9001
21:58:03 INFO    [node] validators        : 3
21:58:03 INFO    [node] genesis hash      : 9fd9cd250ad5fc29660953655b4cc77844e324bffa...
21:58:03 INFO    [node] chain height      : 0
21:58:03 INFO    [node] waiting 5s for peers to connect...
21:58:08 INFO    [node] connected peers   : ['node1', 'node3']
21:58:13 INFO    [node] PROPOSED block h=1 hash=4d72820bc0f44f6b txs=0 -> broadcast to 2 peer(s)
21:58:28 INFO    [node] status: height=7 mempool=0 peers=['node1', 'node3']
```

Le récapitulatif `status:` est réémis toutes les 15 secondes. À l'arrêt,
`final height:` et `final tip:` closent le journal.

---

## 10. Critères de validation

| # | Critère | Comment le vérifier |
|---|---|---|
| 1 | Suite de tests verte | `pytest tests/ -q` sur les 3 VMs |
| 2 | Installation reproductible | étapes 1→3 sur une VM neuve |
| 3 | Point d'entrée fonctionnel | `python -m src.node.main --config ...` |
| 4 | Genesis identique | `genesis hash` identique dans les 3 logs |
| 5 | 2 liens par nœud | `connected peers` liste les 2 autres |
| 6 | Propagation réelle | la hauteur progresse sur les 3 |
| 7 | Convergence | même `final tip` après `Ctrl+C` |
| 8 | Tour PoA respecté | nodeN propose les hauteurs `h % 3 == N-1` |
| 9 | Arrêt propre | `Ctrl+C` → `final height` / `final tip`, pas de traceback |
| 10 | Preuve inter-VMs | les 9 points ci-dessus sur 3 machines distinctes |

### Preuve de convergence

Arrêtez les trois nœuds au même moment, puis sur chaque VM :

```bash
N=2   # adapter
echo "blocs : $(ls data/node$N/blocks/*.json | wc -l)"
cat $(ls data/node$N/blocks/*.json | sort) | md5sum
```

Même nombre de blocs et même empreinte = chaînes strictement
identiques, signatures ML-DSA comprises.

Vérification ciblée d'un bloc précis :

```bash
md5sum data/node2/blocks/00000004.json
```

Même somme sur les trois machines : le bloc produit et signé par node2 a
été transmis et persisté sans altération chez node1 et node3.

---

## 11. Comportement à connaître

### La production est déclenchée par une transaction

Par défaut, aucun bloc n'est produit avec un mempool vide. Lorsqu'une
transaction est disponible, le proposant du round courant peut produire.
Si son timeout expire, les nœuds actifs passent au round suivant et le
validateur désigné reprend la même hauteur. Le mode historique avec blocs
vides reste disponible uniquement avec `--produce-empty-blocks`, pour les
benchmarks.

Pour observer une transaction réelle, lancez un nœud d'entrée avec
`--send-tx`.

### Les blocs sont persistés sur disque

`ChainStorage` écrit un fichier JSON par bloc dans
`data/nodeN/blocks/`, en écriture atomique.

```bash
ls data/node2/blocks/ | head
python3 -m json.tool data/node2/blocks/00000001.json | head -20
```

Chaque bloc contient `validator`, `validator_public_key` et `signature`
— cette dernière fait environ 2420 octets (ML-DSA-44).

### Redémarrage

Au relancement, un nœud **recharge sa chaîne** et repart de sa hauteur
enregistrée, pas de zéro. Pour repartir à neuf, effacez sur les **trois**
VMs :

```bash
rm -rf data/nodeN/blocks
```

Le genesis sera recréé à l'identique : il est déterministe, dérivé de
`genesis_validator_public_key` et `genesis_timestamp`.

### La signature ML-DSA est active

Elle n'est pas reportée à une phase ultérieure. À la production,
`consensus.build_candidate_block()` signe le bloc avec la clé secrète
locale. À la réception, `validate_block_for_acceptance()` applique cinq
contrôles, dont la vérification ML-DSA de la signature du bloc et de
chaque transaction, et l'appartenance à `authorized_validators`.

Un nœud étranger, même avec une signature valide, est rejeté : c'est le
caractère permissionné du PoA.

---

## 12. Pièges rencontrés — récapitulatif

| Symptôme | Cause | Correctif |
|---|---|---|
| `ModuleNotFoundError: No module named 'src'` | `pip install -e .` absent | `PYTHONPATH=. python3 scripts/...` |
| `No matching distribution found for setuptools` | pas de réseau, build isolé | `pip install -e . --no-build-isolation` |
| `JSONDecodeError: line 1 column 1` | ligne `liboqs-python faulthandler...` en tête | corrigé dans le script ; sinon `sed -i '/^liboqs-python/d' fichier.json` |
| Fichier JSON vide | `>` crée le fichier même si la commande échoue | écrire dans `/tmp`, vérifier, puis copier |
| `non-hexadecimal number ... at position 0` | placeholder `REMPLACER_*` ou BOM UTF-8 | `make_configs.py --force` ; ou `sed -i '1s/^\xEF\xBB\xBF//'` |
| `config/nodes/nodes/...` | `--out` déjà suffixé | passer `--out config/nodes/` |
| `No rule to make target 'node1'` | Makefile obsolète ou nommé `Makefile.txt` | mettre à jour ; `mv Makefile.txt Makefile` |
| `missing separator` (make) | espaces au lieu de tabulations | `sed -i 's/^    /\t/' Makefile` |
| `connect to host ... port 22: connection refused` | `sshd` absent | `sudo apt install openssh-server` |
| `Could NOT find OpenSSL` (cmake) | en-têtes manquants | `sudo apt install libssl-dev` |
| `The file system wasn't safely closed on Windows` | clé USB montée depuis Windows | `sed -i 's/\r$//' fichier` après copie |
| Deux nœuds, même adresse | `keys/` copié d'une VM à l'autre | régénérer sur la VM concernée |
| Hauteur figée à 0 | PoA strict, un nœud manquant | démarrer les 3 |

---

## 13. Hors périmètre PHASE 2

Reporté à la PHASE 7 (intégration complète) :

- redémarrage d'un nœud et resynchronisation
- comportement à 1 ou 2 nœuds sur 3
- perte puis retour d'un pair
- récupération après crash

Le protocole de synchronisation (`getblocks` / `blocks`, plafonné à 50
blocs) est implémenté et couvert par
`tests/integration/test_late_node_sync.py`, mais le scénario complet de
reprise n'a pas été validé sur les VMs.
