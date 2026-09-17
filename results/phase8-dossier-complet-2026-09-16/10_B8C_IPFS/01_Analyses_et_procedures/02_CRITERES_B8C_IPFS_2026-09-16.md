# Fiche B8-C — performance et réplication IPFS distribuées

**Date :** 16 septembre 2026  
**Statut :** exécutée — PASS B8-C-IPFS ; cohérence blockchain en lecture seule confirmée ; aucune transaction blockchain soumise  
**Périmètre :** trois fournisseurs IPFS co-localisés avec node1, node2 et node3  
**Données :** ciphertexts synthétiques uniquement  
**Vérification blockchain :** lecture des références CID existantes, sans nouvelle transaction dans le pilote

## 1. Pourquoi B8-C est le prochain test

Les essais TCP équivalents ont déjà été réalisés :

- B3 : charge vers node1 et saturation ;
- B3-N : 1, 2, 4 et 8 clients logiques ;
- B4 : inclusion et commit à 1 tx/s ;
- B6 : délai réseau contrôlé ;
- B7 : ressources des trois VMs.

Il ne faut donc pas lancer un nouveau `b8b-tcp-*` qui dupliquerait ces
résultats. B8-C apporte une mesure distincte : coût et réplication du stockage
hors chaîne IPFS.

La fiche TCP correspondante est conservée comme trace, mais marquée remplacée :

```text
results/raw_data/phase8-b8b-tcp-ingress-run-sheet-2026-09-16.md
```

## 2. Architecture et règles

```text
node1 + blockchain + IPFS-1
node2 + blockchain + IPFS-2
node3 + blockchain + IPFS-3
```

Contraintes :

- aucune VM IPFS supplémentaire ;
- API Kubo uniquement sur `127.0.0.1:5001` de chaque VM ;
- P2P IPFS sur le port distinct `4001` ;
- port blockchain `9001` inchangé ;
- réseau IPFS privé limité aux trois fournisseurs ;
- aucun bootstrap public ni DHT public ;
- aucun document médical en clair ;
- les données de test sont des ciphertexts synthétiques ;
- les versions sont immuables : nouveau contenu = nouveau CID ;
- aucune clé de validateur ni configuration blockchain ne doit être supprimée ;
- les mesures et l'analyse sont conservées sur la machine de développement.

Le pilote ne modifie pas la blockchain persistante. Il mesure IPFS séparément et
réutilise les CID synthétiques déjà inscrits en phase 7 pour une vérification
lecture seule. Une campagne ultérieure pourra mesurer le flux complet
`IPFS → CID → transaction blockchain`, avec un nouveau `run_id` et des données
synthétiques distinctes.

## 3. Critères d'acceptation du pilote

Le pilote sera valide si :

1. les trois APIs Kubo répondent localement ;
2. les trois identités IPFS sont distinctes et les pairs attendus sont présents ;
3. l'ajout d'un ciphertext produit un CID ;
4. la récupération restitue exactement les mêmes octets ;
5. le même CID est récupérable sur les trois fournisseurs ;
6. les SHA-256 des trois récupérations sont identiques ;
7. `pin` et `has` réussissent sur les trois fournisseurs ;
8. une seconde version synthétique produit un CID différent ;
9. aucun plaintext médical n'est présent dans les fichiers de test ;
10. les latences p50/p95 sont rapportées séparément pour chaque fournisseur ;
11. les ressources Kubo sont relevées pendant ou après le test ;
12. la lecture des références blockchain existantes confirme CID + hash, sans
    nouvelle transaction dans le pilote.

Les latences IPFS ne doivent pas être ajoutées au TPS blockchain. Elles seront
présentées comme latences de stockage/récupération hors chaîne.

## 4. Pré-vérifications sur les trois VMs

Exécuter en lecture seule :

```bash
ssh ismail@192.168.168.101 'curl -fsS -X POST http://127.0.0.1:5001/api/v0/version; echo; ipfs id 2>/dev/null || true; ss -ltn | grep -E ":(4001|5001)" || true'
ssh ismail@192.168.168.102 'curl -fsS -X POST http://127.0.0.1:5001/api/v0/version; echo; ipfs id 2>/dev/null || true; ss -ltn | grep -E ":(4001|5001)" || true'
ssh ismail@192.168.168.103 'curl -fsS -X POST http://127.0.0.1:5001/api/v0/version; echo; ipfs id 2>/dev/null || true; ss -ltn | grep -E ":(4001|5001)" || true'
```

Vérifier également les ressources :

```bash
ssh ismail@192.168.168.101 'free -h; df -h /var/lib/ipfs; pgrep -af "[i]pfs daemon" || true'
ssh ismail@192.168.168.102 'free -h; df -h /var/lib/ipfs; pgrep -af "[i]pfs daemon" || true'
ssh ismail@192.168.168.103 'free -h; df -h /var/lib/ipfs; pgrep -af "[i]pfs daemon" || true'
```

Ne pas continuer si une VM signale un OOM, si l'API Kubo n'est pas locale ou si
les trois fournisseurs ne sont pas correctement distincts.

## 5. Jeu de test synthétique

Le contenu doit être créé côté client sous forme de ciphertext simulé, sans
plaintext médical. Exemple accepté :

```text
PHASE8-B8C-CIPHERTEXT-v1-sample-0000
PHASE8-B8C-CIPHERTEXT-v2-sample-0000
```

Les noms et contenus doivent rester explicitement synthétiques. La taille du
ciphertext pilote est fixée à 128 octets pour rester comparable aux mesures de
phase 7. Une campagne séparée pourra ensuite varier la taille.

## 6. Pilote manuel sur node1

Créer puis publier un ciphertext synthétique sur IPFS-1 :

```bash
ssh -tt ismail@192.168.168.101
printf 'PHASE8-B8C-CIPHERTEXT-v1-20260916' > /tmp/b8c-ciphertext-v1.bin
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate

python3 - <<'PY'
from pathlib import Path
from src.ipfs import IPFSClient

path = Path('/tmp/b8c-ciphertext-v1.bin')
client = IPFSClient('http://127.0.0.1:5001/api/v0', timeout=60)
cid = client.add_encrypted_file(path, filename=path.name)
raw = client.get_file(cid)
assert raw == path.read_bytes()
print(f'CID={cid}')
print(f'SIZE={len(raw)}')
client.close()
PY
```

Noter le CID imprimé comme `<CID_V1>`. Cette opération ne crée aucune
transaction blockchain.

## 7. Vérification sur IPFS-1, IPFS-2 et IPFS-3

Depuis la machine de développement, remplacer `<CID_V1>` et exécuter :

```bash
CID=<CID_V1>

ssh ismail@192.168.168.101 \
  "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/cat?arg=$CID' > /tmp/b8c-v1-node1.bin && sha256sum /tmp/b8c-v1-node1.bin"
ssh ismail@192.168.168.102 \
  "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/cat?arg=$CID' > /tmp/b8c-v1-node2.bin && sha256sum /tmp/b8c-v1-node2.bin"
ssh ismail@192.168.168.103 \
  "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/cat?arg=$CID' > /tmp/b8c-v1-node3.bin && sha256sum /tmp/b8c-v1-node3.bin"
```

Les trois SHA-256 doivent être identiques. Si IPFS-2 ou IPFS-3 ne possède pas
encore le bloc, attendre la récupération Bitswap puis répéter la lecture. Ne
pas introduire le CID dans une nouvelle transaction pendant ce pilote.

Pinner le CID sur les trois fournisseurs :

```bash
ssh ismail@192.168.168.101 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/add?arg=$CID'"
ssh ismail@192.168.168.102 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/add?arg=$CID'"
ssh ismail@192.168.168.103 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/add?arg=$CID'"
```

Puis vérifier :

```bash
ssh ismail@192.168.168.101 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/ls?arg=$CID'"
ssh ismail@192.168.168.102 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/ls?arg=$CID'"
ssh ismail@192.168.168.103 "curl -fsS -X POST 'http://127.0.0.1:5001/api/v0/pin/ls?arg=$CID'"
```

## 8. Mesure de 30 échantillons par fournisseur

Le pilote fonctionnel doit être suivi d'une mesure répétée séparée. Pour chaque
fournisseur, relever au minimum 30 durées de :

- `cat` local d'un CID déjà présent ;
- `has`/`block/stat` local ;
- `pin/ls` local.

Les mesures doivent utiliser `time.perf_counter_ns()` dans un script exécuté
sur la VM concernée, afin d'éviter de mélanger la latence SSH à la latence
Kubo. Pour chaque opération et chaque fournisseur, conserver :

```text
samples=30
min
mean
p50
p95
max
successes
failures
cid
sha256
size_bytes
```

Le fichier de résultat doit être copié sur la machine de développement sous :

```text
results/raw_data/b8c-ipfs-20260916-node1.json
results/raw_data/b8c-ipfs-20260916-node2.json
results/raw_data/b8c-ipfs-20260916-node3.json
```

Si un script de mesure est ajouté pour automatiser ces 30 échantillons, il doit
être exécuté séparément sur chaque VM et ne doit pas devenir un orchestrateur
de démarrage/arrêt ou de copie de clés.

## 9. Versionnement immuable

Créer une seconde version synthétique différente :

```bash
printf 'PHASE8-B8C-CIPHERTEXT-v2-20260916' > /tmp/b8c-ciphertext-v2.bin
```

L'ajouter à IPFS-1 avec le même adaptateur. Vérifier :

```text
CID_V2 != CID_V1
SHA256_V2 != SHA256_V1
```

Récupérer et pinner la v2 sur les trois fournisseurs. Ne jamais modifier un
objet existant en place et ne jamais réutiliser `CID_V1` pour la v2.

## 10. Vérification blockchain en lecture seule

Après les vérifications IPFS, lire les références synthétiques déjà inscrites
sur les trois nœuds :

```bash
ssh ismail@192.168.168.101 '
  cd ~/Bureau/blockchain-experiment-distributed && source .venv/bin/activate &&
  python3 scripts/testing/read_phase7_records.py --node node1
'
ssh ismail@192.168.168.102 '
  cd ~/Bureau/blockchain-experiment-distributed && source .venv/bin/activate &&
  python3 scripts/testing/read_phase7_records.py --node node2
'
ssh ismail@192.168.168.103 '
  cd ~/Bureau/blockchain-experiment-distributed && source .venv/bin/activate &&
  python3 scripts/testing/read_phase7_records.py --node node3
'
```

Comparer pour chaque version :

- CID ;
- hash SHA-256 du ciphertext ;
- `recordId` ;
- hauteur ;
- `block_hash` ;
- `state_root`.

Cette lecture ne modifie pas la chaîne. Les CID v1/v2 de phase 7 constituent
la preuve de référence ; les nouveaux CID B8-C ne seront inscrits sur chaîne
qu'après validation explicite d'une campagne end-to-end distincte.

## 11. Critères d'interprétation

Les résultats doivent distinguer :

- publication locale IPFS ;
- récupération locale loopback ;
- récupération distante via réplication Bitswap ;
- pinning ;
- présence du bloc ;
- preuve blockchain CID + hash ;
- latence API Kubo ;
- latence réseau IPFS.

Une mesure `POST http://127.0.0.1:5001/api/v0/cat` est une latence API Kubo
locale sur la VM. Elle ne doit pas être appelée latence end-to-end client/IPFS
sans mesure séparée depuis la machine de développement.

## 12. Arrêt et archivage

Après le test :

1. conserver les JSON et logs sur la machine de développement ;
2. ne pas supprimer le datastore IPFS existant ;
3. ne pas supprimer les clés IPFS ou blockchain ;
4. arrêter uniquement les processus démarrés pour le test, avec `Ctrl-C` dans
   leur terminal si nécessaire ;
5. vérifier que le port blockchain `9001` et les ports IPFS sont dans l'état
   prévu ;
6. conserver les CIDs, hashes et tailles ;
7. rédiger l'analyse B8-C avant toute nouvelle campagne.

## 13. Livrables

```text
results/raw_data/b8c-ipfs-20260916-node1.json
results/raw_data/b8c-ipfs-20260916-node2.json
results/raw_data/b8c-ipfs-20260916-node3.json
results/raw_data/b8c-ipfs-20260916-summary.json
results/raw_data/b8c-ipfs-20260916.log
results/raw_data/phase8-b8c-ipfs-analysis-2026-09-16.md
```

Les trois premiers JSON doivent rester séparés par fournisseur. Le résumé
comparera p50/p95, succès, ressources et intégrité, sans additionner ces
latences au TPS blockchain.
