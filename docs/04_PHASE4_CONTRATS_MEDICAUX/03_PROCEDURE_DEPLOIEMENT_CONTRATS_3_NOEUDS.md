# PHASE 4 — Procédure complète de déploiement des contrats sur les 3 VMs

## Réponse importante avant de commencer

Oui : **si tu supprimes les blocs actuels, les contrats actuellement déployés seront perdus sur la chaîne**.

Dans cette architecture :

- les transactions de création des contrats sont enregistrées dans les blocs ;
- l'état EVM n'est pas conservé dans un fichier séparé ;
- au démarrage, chaque nœud reconstruit l'état EVM en rejouant les blocs de `ChainStorage`.

Donc :

```text
suppression des blocs
        ↓
perte des transactions de déploiement
        ↓
état EVM vide après rejeu
        ↓
contrats absents
```

Si tu veux **conserver les contrats actuels**, ne supprime pas `data/nodeN/blocks`.

Si tu veux repartir sur une blockchain neuve, tu peux supprimer les blocs sur les **trois VMs**, puis tu dois redéployer les trois contrats par transactions.

Le manifeste situé dans `/tmp` n'est pas la blockchain. Il ne contient que les informations publiques du déploiement. Sa disparition après un redémarrage est normale et n'efface pas les contrats.

---

## 1. Paramètres utilisés

| Élément | Valeur |
|---|---|
| Utilisateur distant | `ismail` |
| node1 | `192.168.168.101` |
| node2 | `192.168.168.102` |
| node3 | `192.168.168.103` |
| Port P2P | `9001` |
| Projet | `~/blockchain-experiment-distributed` |
| Config node1 | `config/nodes/node1/node.yaml` |
| Config node2 | `config/nodes/node2/node.yaml` |
| Config node3 | `config/nodes/node3/node.yaml` |
| Données node1 | `data/node1/blocks` |
| Données node2 | `data/node2/blocks` |
| Données node3 | `data/node3/blocks` |

La machine administrateur doit posséder le dépôt, les artefacts Solidity et l'environnement Python nécessaires au client externe.

---

## 2. Choisir le scénario

### Scénario A — conserver la blockchain actuelle

Ne pas exécuter les commandes de suppression de la section 5.

Arrêter puis redémarrer les nœuds avec les commandes des sections 6 et 9. Les contrats seront reconstruits automatiquement depuis les blocs existants.

### Scénario B — repartir d'une blockchain neuve

Exécuter toutes les sections dans l'ordre :

1. arrêter les nœuds ;
2. vérifier les configurations ;
3. supprimer les blocs sur les trois VMs ;
4. redémarrer les trois nœuds ;
5. vérifier le réseau ;
6. déployer les contrats depuis le client externe ;
7. vérifier la présence des contrats ;
8. redémarrer sans supprimer les blocs ;
9. vérifier à nouveau les contrats après redémarrage.

---

## 3. Vérifier les configurations avant toute suppression

Ces commandes ne modifient rien.

### node1

```bash
ssh ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed &&
  grep -nE "^(node_id|data_dir|host|port|genesis_timestamp|block_interval_seconds):|^[[:space:]]+- host:|^[[:space:]]+port:|REMPLACER" config/nodes/node1/node.yaml
'
```

### node2

```bash
ssh ismail@192.168.168.102 '
  cd ~/blockchain-experiment-distributed &&
  grep -nE "^(node_id|data_dir|host|port|genesis_timestamp|block_interval_seconds):|^[[:space:]]+- host:|^[[:space:]]+port:|REMPLACER" config/nodes/node2/node.yaml
'
```

### node3

```bash
ssh ismail@192.168.168.103 '
  cd ~/blockchain-experiment-distributed &&
  grep -nE "^(node_id|data_dir|host|port|genesis_timestamp|block_interval_seconds):|^[[:space:]]+- host:|^[[:space:]]+port:|REMPLACER" config/nodes/node3/node.yaml
'
```

Il faut confirmer :

- `port: 9001` sur les trois VMs ;
- aucune ligne `REMPLACER` ;
- les pairs utilisent les IP `192.168.168.101`, `.102` et `.103` ;
- `genesis_timestamp` est identique ;
- `genesis_validator_public_key` est identique ;
- `authorized_validators` est identique et dans le même ordre.

> Attention : si les fichiers affichent encore `port: 5000`, `192.168.1.x` ou `REMPLACER`, ne démarre pas les nœuds et ne déploie pas les contrats. Il faut d'abord distribuer les bonnes configurations générées.

---

## 4. Arrêter les trois nœuds

Si les trois terminaux SSH sont ouverts, appuyer sur `Ctrl+C` dans chaque terminal.

Sinon, depuis la machine administrateur :

```bash
ssh ismail@192.168.168.101 'pkill -TERM -f "[s]rc.node.main" 2>/dev/null || true'
```

```bash
ssh ismail@192.168.168.102 'pkill -TERM -f "[s]rc.node.main" 2>/dev/null || true'
```

```bash
ssh ismail@192.168.168.103 'pkill -TERM -f "[s]rc.node.main" 2>/dev/null || true'
```

Vérifier qu'aucun nœud ne tourne encore :

```bash
ssh ismail@192.168.168.101 'pgrep -af "[s]rc.node.main" || true'
```

```bash
ssh ismail@192.168.168.102 'pgrep -af "[s]rc.node.main" || true'
```

```bash
ssh ismail@192.168.168.103 'pgrep -af "[s]rc.node.main" || true'
```

---

## 5. Réinitialiser la blockchain — uniquement pour le scénario B

Ces commandes suppriment les blocs actuels. Elles ne suppriment pas les clés des validateurs et ne suppriment pas les configurations.

### node1

```bash
ssh ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed &&
  rm -rf data/node1/blocks &&
  mkdir -p data/node1/blocks &&
  echo "node1 : blocs supprimés"
'
```

### node2

```bash
ssh ismail@192.168.168.102 '
  cd ~/blockchain-experiment-distributed &&
  rm -rf data/node2/blocks &&
  mkdir -p data/node2/blocks &&
  echo "node2 : blocs supprimés"
'
```

### node3

```bash
ssh ismail@192.168.168.103 '
  cd ~/blockchain-experiment-distributed &&
  rm -rf data/node3/blocks &&
  mkdir -p data/node3/blocks &&
  echo "node3 : blocs supprimés"
'
```

Vérifier que les trois répertoires sont vides :

```bash
ssh ismail@192.168.168.101 'find ~/blockchain-experiment-distributed/data/node1/blocks -type f -print'
```

```bash
ssh ismail@192.168.168.102 'find ~/blockchain-experiment-distributed/data/node2/blocks -type f -print'
```

```bash
ssh ismail@192.168.168.103 'find ~/blockchain-experiment-distributed/data/node3/blocks -type f -print'
```

Ces commandes ne doivent rien afficher.

Le genesis sera recréé automatiquement au prochain démarrage, à condition que la configuration soit strictement identique sur les trois VMs.

---

## 6. Démarrer les trois nœuds

Ouvrir trois terminaux séparés et lancer rapidement les commandes suivantes.

### Terminal node1

```bash
ssh -t ismail@192.168.168.101 '
  cd ~/blockchain-experiment-distributed &&
  source .venv/bin/activate &&
  export OQS_INSTALL_PATH=$HOME/_oqs &&
  export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}" &&
  python -m src.node.main \
    --config config/nodes/node1/node.yaml \
    --log-level INFO
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
    --log-level INFO
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
    --log-level INFO
'
```

Ne pas utiliser `--no-propose` : les trois nœuds doivent produire et accepter les blocs.

Ne pas utiliser `--send-tx` : les transactions de contrats seront envoyées par le client externe.

Les logs doivent afficher :

```text
listening on      : 0.0.0.0:9001
connected peers   : ['node...', 'node...']
genesis hash      : ...
status: height=...
```

Le `genesis hash` doit être identique sur les trois nœuds.

---

## 7. Tester le port P2P

Depuis la machine administrateur :

```bash
nc -vz -w 5 192.168.168.101 9001
```

```bash
nc -vz -w 5 192.168.168.102 9001
```

```bash
nc -vz -w 5 192.168.168.103 9001
```

Les trois commandes doivent afficher `succeeded`.

Attendre ensuite que chaque nœud ait deux pairs connectés et que les hauteurs commencent à progresser.

---

## 8. Déployer les contrats depuis la machine administrateur

Cette étape ne copie pas les contrats dans `data/` ou dans les nœuds.

Le client lit les artefacts Solidity sur la machine administrateur, construit les transactions de création, les signe avec une clé de déploiement distincte et envoie le bytecode par TCP aux validateurs.

Exécuter depuis la machine administrateur :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate

export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"

mkdir -p ~/.blockchain-medical

python -m src.evm.deployer \
  --target-host 192.168.168.101 \
  --target-host 192.168.168.102 \
  --target-host 192.168.168.103 \
  --target-port 9001 \
  --key-dir ~/.blockchain-medical/deployment-key-3vms \
  --artifact-dir contracts/artifacts \
  --manifest ~/.blockchain-medical/medical-deployment-3vms.json \
  --timeout 180
```

L'ordre des créations est :

1. `PatientRegistry` ;
2. `ConsentManager(address patient_registry)` ;
3. `MedicalRecordRegistry(address patient_registry, address consent_manager)`.

Le client doit afficher les trois adresses, les hauteurs d'inclusion et le chemin du manifeste.

Ne relance pas cette commande si le déploiement a déjà réussi sur cette chaîne : les nonces et les transactions seraient différents ou déjà utilisés.

---

## 9. Copier le manifeste pour vérifier les contrats

Le manifeste n'est pas requis pour faire tourner la blockchain. Il sert à vérifier les adresses et les blocs d'inclusion.

Après le déploiement, le copier sur chaque VM :

```bash
scp ~/.blockchain-medical/medical-deployment-3vms.json \
    ismail@192.168.168.101:/tmp/medical-deployment-3vms.json
```

```bash
scp ~/.blockchain-medical/medical-deployment-3vms.json \
    ismail@192.168.168.102:/tmp/medical-deployment-3vms.json
```

```bash
scp ~/.blockchain-medical/medical-deployment-3vms.json \
    ismail@192.168.168.103:/tmp/medical-deployment-3vms.json
```

`/tmp` peut être vidé après un redémarrage. Dans ce cas, recopier simplement le manifeste depuis la machine administrateur. Ne pas redéployer les contrats uniquement parce que la copie temporaire du manifeste a disparu.

---

## 10. Vérifier les contrats dans un nœud

La vérification rejoue les blocs persistés et vérifie que du bytecode est présent aux trois adresses du manifeste.

### Vérification node1

```bash
ssh -t ismail@192.168.168.101
```

Puis :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate

NODE=node1 PYTHONPATH=. python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

from src.blockchain.storage import ChainStorage
from src.evm.replay import StateReplayer

node = os.environ["NODE"]
manifest = json.loads(Path("/tmp/medical-deployment-3vms.json").read_text())
storage = ChainStorage(f"data/{node}")
tip = storage.get_tip_height()

if tip is None:
    raise SystemExit(f"ECHEC : {node} ne contient aucun bloc")

replayer = StateReplayer(storage)
final_root = replayer.sync_to(tip)
final_block = storage.load_block(tip)

print(f"{node} hauteur       : {tip}")
print(f"{node} dernier bloc  : 0x{final_block.block_hash.hex()}")
print(f"{node} state_root     : 0x{final_root.hex()}")

ok = final_block.state_root == final_root

for item in manifest["contracts"]:
    address = bytes.fromhex(item["address"][2:])
    code = replayer.state.get_code(address)
    block = storage.load_block(item["block_height"])

    code_ok = bool(code)
    block_ok = "0x" + block.block_hash.hex() == item["block_hash"]
    root_ok = "0x" + block.state_root.hex() == item["state_root"]

    print(
        f"{item['contract']}: "
        f"code={'OK' if code_ok else 'ECHEC'}, "
        f"bloc={'OK' if block_ok else 'ECHEC'}, "
        f"state_root={'OK' if root_ok else 'ECHEC'}, "
        f"code_bytes={len(code)}, "
        f"code_sha256={hashlib.sha256(code).hexdigest() if code else '-'}"
    )

    ok = ok and code_ok and block_ok and root_ok

if not ok:
    raise SystemExit(f"VERIFICATION {node} : ECHEC")

print(f"VERIFICATION {node} : OK")
PY

exit
```

Pour node2 et node3, exécuter le même bloc en remplaçant :

```text
ssh ismail@192.168.168.102     et     NODE=node2
ssh ismail@192.168.168.103     et     NODE=node3
```

Le résultat attendu sur chaque VM est :

```text
PatientRegistry: code=OK
ConsentManager: code=OK
MedicalRecordRegistry: code=OK
VERIFICATION nodeN : OK
```

Les `code_sha256` doivent être identiques sur les trois nœuds.

---

## 11. Vérification obligatoire après redémarrage

Après un premier déploiement réussi :

1. arrêter les trois nœuds avec `Ctrl+C` ;
2. ne supprimer aucun fichier dans `data/nodeN/blocks` ;
3. redémarrer les trois nœuds avec les commandes de la section 6 ;
4. attendre que les pairs se reconnectent ;
5. vérifier que la hauteur est supérieure à `0` ;
6. recopier le manifeste dans `/tmp` si nécessaire ;
7. relancer la vérification de la section 10 sur les trois VMs.

Il est normal que node1 affiche initialement une hauteur inférieure d'un bloc s'il a été arrêté avant node2 et node3. Après reconnexion, il doit récupérer le bloc manquant et converger.

La valeur exacte de la hauteur peut dépasser `35`, car le réseau continue à produire des blocs. Le critère important est la convergence :

- même hauteur après rattrapage ;
- même hash du dernier bloc ;
- même `state_root` ;
- mêmes `code_sha256` pour les trois contrats.

---

## 12. Critères finaux de réussite

La procédure est terminée lorsque :

- [ ] les trois nœuds écoutent sur `9001` ;
- [ ] chaque nœud voit les deux autres pairs ;
- [ ] les trois genesis sont identiques ;
- [ ] les blocs sont persistés dans `data/nodeN/blocks` ;
- [ ] le client externe a déployé les trois contrats ;
- [ ] le manifeste contient les trois adresses et les preuves d'inclusion ;
- [ ] le bytecode est présent dans l'état EVM des trois nœuds ;
- [ ] les trois nœuds convergent sur la hauteur, le tip et le `state_root` ;
- [ ] les trois contrats sont toujours présents après redémarrage.

Les contrats ne sont jamais copiés manuellement dans les nœuds. Ils sont créés par transactions et reconstruits par rejeu EVM à partir des blocs persistés.
