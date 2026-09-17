# Architecture complète du projet

## Document de référence pour la compréhension du système et la rédaction de l’article scientifique

**Projet :** blockchain permissionnée post-quantique pour la gestion de références de dossiers médicaux chiffrés  
**Topologie étudiée :** trois VMs, trois validateurs blockchain, trois fournisseurs IPFS co-localisés  
**Version documentaire :** 16 septembre 2026  
**Statut :** architecture de référence et guide de rédaction scientifique

---

## 1. Réponse rapide : combien de machines et où se trouve IPFS ?

### 1.1 Nombre de VMs

L’architecture utilise **exactement trois VMs blockchain** :

| Machine | Adresse IP | Rôle blockchain | IPFS co-localisé | Ports principaux |
|---|---|---|---|---|
| `node1` | `192.168.168.101` | Validateur 1 et nœud d’entrée recommandé | `IPFS-1` sur la même VM | Blockchain `9001`, IPFS P2P `4001`, API Kubo `127.0.0.1:5001` |
| `node2` | `192.168.168.102` | Validateur 2 | `IPFS-2` sur la même VM | Blockchain `9001`, IPFS P2P `4001`, API Kubo `127.0.0.1:5001` |
| `node3` | `192.168.168.103` | Validateur 3 | `IPFS-3` sur la même VM | Blockchain `9001`, IPFS P2P `4001`, API Kubo `127.0.0.1:5001` |

### 1.2 Placement d’IPFS

IPFS n’est pas installé sur une machine centrale et aucune VM supplémentaire
n’est créée :

```text
VM node1 : blockchain node1 + Kubo/IPFS-1
VM node2 : blockchain node2 + Kubo/IPFS-2
VM node3 : blockchain node3 + Kubo/IPFS-3
```

Chaque daemon IPFS est donc **co-localisé** avec un validateur blockchain.
Les trois fournisseurs IPFS forment un réseau privé limité à ces trois pairs.

Règles de réseau IPFS :

- le P2P IPFS utilise son port dédié, normalement `4001` ;
- l’API Kubo reste liée à `loopback` sur chaque VM, normalement
  `127.0.0.1:5001` ;
- l’API Kubo n’est pas exposée directement au réseau entre VMs ;
- le gateway IPFS est désactivé ou limité à loopback ;
- la blockchain conserve son port `9001` ;
- un seul daemon IPFS est prévu par VM ;
- aucun bootstrap public ni trafic DHT public n’est requis pour cette étude.

### 1.3 Machine de développement

La machine de développement est utilisée pour :

- lancer les scripts de campagne lorsque cela est prévu ;
- collecter les blocs et les journaux des trois VMs ;
- calculer les résumés, statistiques, hashes et manifestes ;
- conserver les résultats dans `results/`.

Elle n’est pas un quatrième validateur blockchain. Les blocs et journaux
collectés doivent être analysés et archivés sur la machine de développement,
pas traités comme les artefacts définitifs de `node1`.

---

## 2. Résumé général de l’architecture

Le projet combine six fonctions principales :

```text
┌─────────────────────────────────────────────────────────────────┐
│  Client / médecin / générateur de benchmark                     │
│  - crée une transaction signée                                  │
│  - chiffre éventuellement un dossier synthétique                 │
│  - contacte le nœud d’entrée node1                              │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Couche d’entrée                                                │
│  node1 : validation de la transaction, mempool, relais P2P      │
│  API HTTP éventuelle : séparée du transport blockchain          │
└───────────────────────────────┬─────────────────────────────────┘
                                │ TCP blockchain : port 9001
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Réseau blockchain en triangle                                  │
│  node1 ◄──────────────► node2                                   │
│    ▲                       ▲                                    │
│    └──────────────► node3 ◄┘                                    │
│  PoA round-robin, blocs signés ML-DSA-44                        │
└───────────────┬─────────────────────────────────────────────────┘
                │
       ┌────────┴────────┐
       ▼                 ▼
┌───────────────┐  ┌──────────────────────────────────────────────┐
│ État blockchain│  │ Exécution EVM                               │
│ blocs JSON     │  │ py-evm, contrats, reçus, logs, state_root   │
│ ChainStorage   │  │ PatientRegistry, ConsentManager,            │
│ mempool        │  │ MedicalRecordRegistry                        │
└───────────────┘  └──────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Stockage hors chaîne                                            │
│ IPFS-1 sur node1 ◄──► IPFS-2 sur node2 ◄──► IPFS-3 sur node3    │
│ ciphertext uniquement ; CID + hash inscrits dans la blockchain  │
└─────────────────────────────────────────────────────────────────┘
```

L’idée centrale est la séparation suivante :

```text
Blockchain : identité logique, consentement, CID, hash, audit, état
IPFS       : ciphertext chiffré et réplication hors chaîne
PQC        : signatures ML-DSA et établissement de secret ML-KEM
EVM        : règles applicatives des contrats
P2P        : diffusion des transactions et des blocs
```

---

## 3. Inventaire des composants logiciels

### 3.1 Couche blockchain et réseau

Les principaux composants du dépôt sont :

```text
src/node/main.py          démarrage d’un nœud
src/node/node.py          orchestration du nœud
src/node/socket_p2p.py    transport TCP réel
src/node/p2p.py           abstractions P2P et messages
src/node/consensus.py     proposition et consensus PoA
src/node/validator.py     validation des blocs et transactions
src/node/mempool.py       file des transactions en attente
src/node/config.py        lecture et validation de la configuration
```

Le réseau est une topologie en triangle complet. Chaque nœud connaît les deux
autres nœuds et écoute sur le port `9001`.

### 3.2 Couche blockchain et persistance

```text
src/blockchain/block.py       structure et sérialisation des blocs
src/blockchain/transaction.py transaction signée et données EVM
src/blockchain/blockchain.py  chaîne et validation de séquence
src/blockchain/storage.py     persistance locale des blocs
src/blockchain/validation.py  validations de cohérence
src/blockchain/genesis.py     construction déterministe du genesis
```

La chaîne de chaque nœud est persistée localement. Les blocs sont conservés
dans un répertoire de données propre au nœud, typiquement :

```text
data/node1/blocks/
data/node2/blocks/
data/node3/blocks/
```

Un nœud recharge sa chaîne au redémarrage et reconstruit l’état EVM par rejeu
des blocs de `ChainStorage`. L’état EVM n’est pas un fichier indépendant qui
pourrait être remplacé séparément de la chaîne.

### 3.3 Couche cryptographique

```text
src/crypto/ml_dsa.py       signatures ML-DSA-44
src/crypto/ml_kem.py       ML-KEM-768
src/crypto/address.py      dérivation des adresses
src/crypto/hash.py         fonctions de hachage
src/crypto/serialization.py sérialisation déterministe
```

La blockchain utilise ML-DSA-44 pour :

- signer les transactions ;
- signer les blocs ;
- vérifier l’identité des validateurs ;
- empêcher qu’un nœud non autorisé propose un bloc accepté.

La confidentialité des contenus est séparée du consensus :

```text
ML-KEM-768 : établissement ou encapsulation d’un secret partagé
AES-256-GCM : chiffrement authentifié du contenu
IPFS : stockage et réplication du ciphertext
Blockchain : CID et hash du ciphertext, jamais le contenu en clair
```

### 3.4 Couche EVM

```text
src/evm/executor.py    exécution des transactions EVM
src/evm/state.py       état, rejeu et state_root
src/evm/receipt.py     reçus d’exécution
src/evm/logs.py        événements et logs EVM
src/evm/abi.py         encodage/décodage ABI
src/evm/deployer.py    déploiement externe des contrats
src/evm/replay.py      rejeu et lectures déterministes
```

Les contrats prévus ou utilisés par le scénario sont :

```text
PatientRegistry
ConsentManager
MedicalRecordRegistry
```

Ils gèrent respectivement :

1. l’enregistrement pseudonymisé d’un patient ;
2. l’octroi et la révocation d’un consentement ;
3. l’enregistrement d’une référence de dossier chiffré.

Le contrat ne lit pas le contenu IPFS et ne le déchiffre pas. Il conserve des
métadonnées nécessaires à l’audit : identifiant pseudonymisé, CID, empreinte du
ciphertext, scope, contrôleur et état de la référence.

### 3.5 Couche IPFS

```text
src/ipfs/adapter.py        adaptateur applicatif Kubo
src/ipfs/README.md         documentation de l’adaptateur
```

L’adaptateur reçoit uniquement des ciphertexts déjà chiffrés. Il expose
logiquement des opérations telles que :

```text
add_encrypted_file -> CID
get_file(CID)
pin(CID)
unpin(CID)
has(CID)
```

Le daemon Kubo de chaque VM est local à cette VM. L’application appelle son API
sur loopback et les daemons se connectent entre eux par leur port P2P dédié.

### 3.6 Couche API

Le scénario scientifique prévoit éventuellement une entrée HTTP Flask/Gunicorn
pour séparer l’API applicative du transport P2P. Toutefois, l’état actuel du
dépôt doit être décrit avec prudence :

```text
src/api/.gitkeep uniquement
```

Il n’y a donc pas actuellement d’API Flask/Gunicorn exploitable à présenter
comme un résultat expérimental réalisé. Les campagnes blockchain existantes
utilisent le chemin client/nœud prévu par les scripts et le transport TCP.
Toute campagne HTTP devra être identifiée comme une campagne séparée, après
implémentation et instrumentation réelle de l’API.

---

## 4. Topologie réseau détaillée

### 4.1 Réseau blockchain

```text
                           TCP 9001
             ┌────────────────────────────────┐
             │                                │
             ▼                                │
┌────────────────────────┐          ┌────────┴───────────────┐
│ node1                  │ TCP 9001  │ node2                  │
│ 192.168.168.101        ├──────────►│ 192.168.168.102        │
│ validateur + IPFS-1    │◄──────────┤ validateur + IPFS-2    │
└─────────────┬──────────┘          └──────────┬─────────────┘
              │                                 │
              │           TCP 9001              │
              └────────────────┬────────────────┘
                               ▼
                    ┌────────────────────────┐
                    │ node3                  │
                    │ 192.168.168.103        │
                    │ validateur + IPFS-3    │
                    └────────────────────────┘
```

Chaque nœud :

- écoute sur `0.0.0.0:9001` ou l’interface configurée ;
- contacte les deux autres nœuds ;
- diffuse les transactions et les blocs ;
- possède son propre mempool ;
- possède sa propre copie persistante de la chaîne ;
- possède sa propre paire de clés de validateur.

### 4.2 Réseau IPFS

```text
API locale uniquement                         P2P IPFS privé

127.0.0.1:5001 sur node1  ───────────────┐
                                         │
127.0.0.1:5001 sur node2  ── Kubo P2P ──┼── port 4001
                                         │
127.0.0.1:5001 sur node3  ───────────────┘
```

Les adresses exactes des interfaces d’écoute peuvent être paramétrées selon
Kubo, mais les règles du projet ne changent pas : API en loopback, P2P sur un
port IPFS dédié, pas d’exposition publique inutile.

### 4.3 Séparation des ports

| Fonction | Port | Visibilité |
|---|---:|---|
| Blockchain P2P | `9001` | Réseau entre les trois nœuds |
| IPFS P2P | `4001` | Réseau privé entre les trois daemons Kubo |
| IPFS API Kubo | `5001` | Loopback uniquement sur chaque VM |
| IPFS gateway | selon configuration | Désactivée ou loopback uniquement |
| SSH | `22` | Administration, si nécessaire |

Il ne faut pas confondre :

```text
9001 = blockchain
4001 = IPFS P2P
5001 = API locale Kubo
```

---

## 5. Rôles des trois VMs

### 5.1 node1 — nœud d’entrée et validateur

```text
IP                : 192.168.168.101
Blockchain        : port 9001
IPFS              : IPFS-1 co-localisé
API Kubo          : loopback, normalement 127.0.0.1:5001
Données chaîne    : data/node1/
Clés              : keys/node1/
Pairs blockchain  : node2 et node3
```

node1 est le nœud d’entrée recommandé dans le scénario applicatif et dans les
benchmarks. Cela ne signifie pas qu’il produit tous les blocs. Le proposant est
déterminé par l’ordre PoA des validateurs autorisés.

### 5.2 node2 — validateur et fournisseur IPFS

```text
IP                : 192.168.168.102
Blockchain        : port 9001
IPFS              : IPFS-2 co-localisé
API Kubo          : loopback, normalement 127.0.0.1:5001
Données chaîne    : data/node2/
Clés              : keys/node2/
Pairs blockchain  : node1 et node3
```

node2 possède une clé ML-DSA distincte. La clé secrète ne doit jamais être
copiée depuis node1 ou node3.

### 5.3 node3 — validateur et fournisseur IPFS

```text
IP                : 192.168.168.103
Blockchain        : port 9001
IPFS              : IPFS-3 co-localisé
API Kubo          : loopback, normalement 127.0.0.1:5001
Données chaîne    : data/node3/
Clés              : keys/node3/
Pairs blockchain  : node1 et node2
```

node3 est également le nœud utilisé dans les scénarios de crash/reprise. Son
arrêt ne doit pas entraîner la suppression de ses données persistantes.

### 5.4 Ce qui est partagé et ce qui est local

| Élément | Identique sur les trois VMs | Propre à chaque VM |
|---|---:|---:|
| Code source | Oui | Non |
| Ordre des validateurs autorisés | Oui | Non |
| Clé publique genesis | Oui | Non |
| Timestamp genesis | Oui | Non |
| Intervalle de bloc | Oui | Non |
| Timeout de round | Oui | Non |
| Adresse IP | Non | Oui |
| `node_id` | Non | Oui |
| Clé secrète ML-DSA | Non | Oui |
| Répertoire blockchain | Non | Oui |
| Mempool en mémoire | Non | Oui |
| Daemon IPFS | même version/configuration | identité et datastore propres |
| CID répliqué | même objet logique | copie locale propre |

---

## 6. Consensus et production des blocs

### 6.1 PoA round-robin

Le consensus est un Proof of Authority permissionné avec une liste ordonnée de
validateurs autorisés :

```text
authorized_validators = [node1, node2, node3]
```

Le proposant du bloc de hauteur `h` et de round `r` est déterminé par :

```text
proposer(h, r) = authorized_validators[(h + r) mod 3]
```

Le genesis occupe la hauteur `0`. Avec la configuration actuelle, le premier
bloc produit à la hauteur `1` revient donc au validateur d’index `1`, c’est-à-dire
node2, puis la rotation continue selon la formule.

L’ordre de la liste est une donnée de consensus. Les trois VMs doivent avoir
exactement le même contenu et le même ordre.

### 6.2 Cycle normal

```text
1. Le client crée et signe une transaction.
2. La transaction arrive sur node1.
3. node1 vérifie la signature et les règles de format.
4. La transaction entre dans le mempool.
5. Le proposant attendu récupère les transactions disponibles.
6. Il construit le bloc candidat.
7. Il signe le bloc avec sa clé ML-DSA.
8. Il diffuse le bloc aux deux autres nœuds.
9. Chaque nœud vérifie le proposant, la signature et la chaîne précédente.
10. Chaque nœud exécute éventuellement la transaction EVM.
11. Chaque nœud calcule ou vérifie le state root.
12. Chaque nœud persiste le bloc.
13. Les trois copies convergent vers le même tip.
```

### 6.3 Mempool et production à la demande

Le fonctionnement normal est à la demande :

```text
mempool vide                 → aucun bloc applicatif nécessaire
transaction dans le mempool  → proposition possible
```

Les blocs vides peuvent exister dans certains modes de benchmark, mais ils ne
devraient pas être mélangés aux mesures de débit transactionnel principal.

### 6.4 Timeout et changement de round

Si le proposant attendu ne produit pas à temps :

```text
hauteur h, round r
        ↓ timeout
hauteur h, round r + 1
        ↓
nouveau proposant selon authorized_validators[(h + r + 1) mod 3]
```

Le timeout de configuration est de l’ordre de `5 s`, comme l’intervalle de bloc
actuellement documenté. Ces valeurs sont des paramètres expérimentaux, pas des
constantes universelles de PoA.

### 6.5 Portée de la finalité

Le système produit des blocs signés et des copies convergentes. En revanche, la
version actuelle ne fournit pas un certificat de quorum BFT séparé comparable à
une preuve de finalité forte.

Dans l’article, utiliser plutôt :

```text
finalité applicative observée = même hauteur + même block_hash
                               + même state_root sur les trois nœuds
```

Éviter d’écrire que le système apporte une finalité BFT si cette propriété n’a
pas été implémentée et démontrée.

---

## 7. Flux complet d’une transaction blockchain

### 7.1 Transaction simple

```text
Client
  │ crée les champs transaction
  │ signe avec ML-DSA
  ▼
node1:9001
  │ vérifie adresse, signature, nonce et format
  │ place dans mempool
  ▼
Proposant PoA courant
  │ prend les transactions disponibles
  │ construit et signe le bloc
  ▼
node1 ──────────── node2
  │                  │
  └────── node3 ◄────┘
         │
         ├─ vérification du bloc
         ├─ vérification ML-DSA
         ├─ validation du proposer
         ├─ exécution EVM si nécessaire
         ├─ calcul/vérification state_root
         └─ persistance ChainStorage
```

### 7.2 Ce qui est mesuré

Il faut distinguer les compteurs suivants :

```text
requêtes API
≠ transactions envoyées
≠ transactions acceptées par node1
≠ transactions dans un bloc
≠ transactions réussies (receipt.status = 1)
≠ transactions observées sur les trois nœuds
```

Pour l’article, le débit principal doit être le débit de transactions réellement
commises dans des blocs valides :

```text
committed TPS = transactions incluses et validées / durée de mesure
```

---

## 8. Flux complet d’un dossier médical synthétique

Aucune donnée médicale réelle ne doit être utilisée dans les tests. Le flux
scientifique est le suivant.

### 8.1 Écriture du dossier

```text
1. Le client possède un fichier synthétique.
2. Le client chiffre le fichier localement.
3. ML-KEM-768 protège ou transporte le secret de contenu.
4. AES-256-GCM chiffre et authentifie le contenu.
5. Le ciphertext est ajouté à IPFS-1 via l’API loopback de node1.
6. Kubo retourne un CID.
7. Le CID est pinné/répliqué sur IPFS-2 et IPFS-3.
8. Le client calcule ou conserve le SHA-256 du ciphertext.
9. Le client crée une transaction contenant CID + hash + scope.
10. La transaction est signée ML-DSA.
11. Elle est envoyée à node1.
12. Le contrat vérifie patient, contrôleur et consentement.
13. La transaction est incluse dans un bloc.
14. Les trois nœuds convergent vers le même état.
```

### 8.2 Ce qui va dans la blockchain

La blockchain contient uniquement des métadonnées d’audit :

```text
recordId
patientId pseudonymisé
CID IPFS
hash SHA-256 du ciphertext
scope d’accès
adresse du contrôleur ou de l’auteur
timestamps et statut
```

La blockchain ne contient pas :

```text
fichier médical en clair
clé AES
clé secrète ML-KEM
contenu IPFS complet
identité médicale en clair
```

### 8.3 Lecture autorisée

```text
1. Le bénéficiaire est vérifié par ConsentManager.
2. Le contrat donne accès à la référence si le consentement est valide.
3. Le client récupère le CID.
4. Le ciphertext est lu depuis un fournisseur IPFS.
5. Le hash reçu est comparé au hash blockchain.
6. Le bénéficiaire utilise sa clé autorisée pour déchiffrer.
7. Une mauvaise clé entraîne l’échec de l’authentification AES-GCM.
```

IPFS seul ne fournit pas le contrôle d’accès. La confidentialité dépend du
chiffrement du contenu et de la gestion séparée des clés.

### 8.4 Mise à jour d’un dossier

IPFS est adressé par contenu. Un fichier modifié obtient un nouveau CID :

```text
version 1 → ciphertext 1 → CID-1 → référence blockchain 1
version 2 → ciphertext 2 → CID-2 → référence blockchain 2
```

L’ancienne version peut rester vérifiable. Une nouvelle référence ou une
révocation permet de représenter l’évolution sans modifier le contenu IPFS en
place.

---

## 9. Sécurité et séparation des secrets

### 9.1 Clés de validation

Chaque validateur possède sa propre paire ML-DSA :

```text
node1 → keys/node1/validator_secret_key.bin
node2 → keys/node2/validator_secret_key.bin
node3 → keys/node3/validator_secret_key.bin
```

La clé secrète :

- reste sur sa VM ;
- n’est pas copiée dans `config/nodes/node.yaml` ;
- ne doit pas être ajoutée aux résultats ;
- ne doit pas être envoyée à la machine de développement.

Seules les clés publiques et adresses nécessaires à la vérification circulent.

### 9.2 Données médicales

Les essais utilisent uniquement :

- patients synthétiques ;
- identifiants pseudonymisés ;
- ciphertexts artificiels ;
- CID et hashes de test.

Le dépôt, les VMs et les résultats ne doivent contenir aucun dossier médical
réel.

### 9.3 Surface réseau

La configuration à retenir est :

```text
Blockchain 9001 : accessible entre les trois VMs
IPFS P2P 4001  : accessible uniquement entre les trois pairs IPFS
Kubo API 5001  : loopback sur chaque VM
SSH 22         : administration contrôlée
```

Il ne faut pas exposer l’API Kubo à toutes les interfaces simplement pour
simplifier un test. L’adaptateur applicatif doit appeler l’API locale.

---

## 10. État expérimental et résultats à citer dans l’article

Le dossier de preuves complet est séparé de ce document :

```text
results/phase8-dossier-complet-2026-09-16/
```

Son index est :

```text
results/phase8-dossier-complet-2026-09-16/00_INDEX_DOSSIER_COMPLET_PHASE8.md
```

### 10.1 Résultats blockchain et performance

| Campagne | Résultat à citer | Interprétation prudente |
|---|---|---|
| B2 baseline | `2 tx/s` est la zone de saturation observée ; `119/120` inclusions dans les répétitions disponibles | Ce n’est pas une capacité universelle ni une garantie de production. |
| B3 charge | `180` transactions offertes à `3 tx/s`, `121` incluses, `59` non observées/non incluses, aucun rejet explicite classé | Les 59 ne doivent pas être appelées « rejetées ». |
| B3-N concurrence | À `1 tx/s`, `1`, `2`, `4` et `8` clients logiques : `60/60` inclusions sur les trois nœuds | La latence locale node1 augmente avec la concurrence. |
| B4 latence | `60/60` inclusions à `1 tx/s`, p50 node1 `260,47 ms`, p95 `393,17 ms` | La convergence numérique inter-VM n’est pas mesurée sans horloges synchronisées. |
| B5 crash/reprise | `12/12` transactions finalement incluses après crash/reprise de node3 | Reprise fonctionnelle positive ; temps exact de failover partiellement instrumenté. |
| B6 réseau | `12/12` inclusions sous `50 ms ± 10 ms`, sans perte ajoutée | `tc-netem` a été supprimé et vérifié après le test. |
| B7 ressources | `60/60` inclusions ; environ `99,8 %` CPU par processus ; environ `49 MiB` RSS ; swap nul | Profil de trois VMs VMware, pas comparaison machine physique/VM. |

### 10.2 Résultats cryptographiques et applicatifs

- ML-DSA-44 et ML-KEM-768/AES-GCM sont documentés sur les trois machines.
- Les signatures ML-DSA sont utilisées dans le chemin de validation blockchain.
- ML-KEM/AES-GCM concerne principalement la confidentialité hors chaîne et ne
doit pas être additionné artificiellement au TPS blockchain.
- B8-A contient `180` mesures EVM locales ; les opérations autorisées
réussissent et `unauthorizedRegister` est rejeté comme attendu.
- B8-A ne contacte pas les VMs et ne modifie pas la chaîne persistante.
- B8-C compte `720` opérations IPFS réussies, zéro échec et trois fournisseurs
convergents.
- Les CID et hashes SHA-256 des ciphertexts synthétiques sont cohérents.
- La lecture blockchain B8-C est read-only ; aucune nouvelle transaction
B8-C n’a été soumise.
- La chaîne observée dans B8-C est à la hauteur `242` avec le même
`state_root` sur les trois nœuds :

```text
56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
```

- B8-B n’a pas relancé le chemin TCP déjà couvert par les campagnes
antérieures. Il ne faut pas présenter une nouvelle campagne TCP comme un
benchmark HTTP, Flask ou Gunicorn.

### 10.3 Réserve historique importante

La lecture historique Phase 7 avec `read_phase7_records.py` échoue sur la
chaîne actuelle car une transaction historique n’est pas présente dans le bloc
attendu. Cette lecture ne doit pas être présentée comme une réussite et ne
doit pas conduire à recréer la chaîne, supprimer `data/` ou envoyer une
transaction corrective.

---

## 11. Comment utiliser ce document pour écrire l’article scientifique

### 11.1 Proposition de titre

> **Évaluation expérimentale d’une blockchain permissionnée post-quantique à
> trois nœuds pour la gestion de références de dossiers médicaux chiffrés**

Autre formulation possible :

> **Architecture et évaluation d’un système blockchain PoA intégrant ML-DSA,
> ML-KEM et IPFS distribué pour des données médicales protégées**

### 11.2 Problématique scientifique

La problématique peut être formulée ainsi :

> Comment une blockchain permissionnée à trois validateurs peut-elle combiner
> signatures post-quantiques, confidentialité hors chaîne et stockage IPFS
> distribué tout en conservant une convergence déterministe, un débit mesurable
> et une reprise observable sous perturbation ?

### 11.3 Contributions à annoncer

Les contributions peuvent être présentées en quatre points :

1. **Architecture intégrée :** blockchain PoA à trois nœuds, ML-DSA-44,
   ML-KEM-768/AES-GCM, exécution EVM et IPFS co-localisé.
2. **Séparation de confidentialité :** contenu chiffré hors chaîne, CID et
   hash dans la blockchain, aucune donnée médicale réelle dans les essais.
3. **Méthodologie d’évaluation par couches :** crypto, consensus, EVM, réseau,
   ressources et IPFS mesurés séparément.
4. **Analyse de robustesse expérimentale :** charge, concurrence, latence,
   crash/reprise et délai réseau sur trois VMs VMware.

Ne pas présenter comme contributions démontrées :

- une finalité BFT complète ;
- une tolérance byzantine générale ;
- une API Flask/Gunicorn déjà opérationnelle si elle n’est pas déployée ;
- une capacité industrielle extrapolée à partir de trois nœuds ;
- une comparaison physique/VM qui n’a pas été réalisée.

### 11.4 Questions de recherche

```text
RQ1. Quel débit de transactions commises est obtenu par la blockchain à trois
     nœuds lorsque le taux d’arrivée augmente ?

RQ2. Comment la concurrence des clients influence-t-elle la latence et le
     backlog à débit total constant ?

RQ3. Quel est le coût des signatures ML-DSA-44 dans le chemin de validation ?

RQ4. Quel est l’impact d’un crash de validateur ou d’un délai réseau sur la
     production, la latence et la convergence ?

RQ5. Quel coût supplémentaire l’intégration EVM et IPFS ajoute-t-elle au
     scénario applicatif, par rapport à la blockchain seule ?

RQ6. Les trois copies blockchain et les trois fournisseurs IPFS conservent-ils
     l’intégrité et la cohérence des références de contenu ?
```

### 11.5 Plan d’article recommandé

#### 1. Introduction

- contexte des dossiers médicaux sensibles ;
- limites d’un stockage centralisé ;
- besoin de traçabilité, consentement et confidentialité ;
- intérêt des signatures post-quantiques et du stockage hors chaîne ;
- question scientifique et contributions.

#### 2. Travaux connexes

Comparer avec :

- BLOCKBENCH pour débit, latence, scalabilité et tolérance aux pannes ;
- Hyperledger Caliper pour les moniteurs transactionnels et ressources ;
- architectures blockchain + IPFS ;
- standards NIST FIPS 203 et FIPS 204 ;
- systèmes blockchain médicaux et contrôle de consentement.

#### 3. Architecture proposée

Présenter :

- la topologie des trois VMs ;
- les rôles node1/node2/node3 ;
- le PoA round-robin ;
- le chemin transactionnel ;
- l’EVM et les contrats ;
- la séparation blockchain/IPFS ;
- le chiffrement ML-KEM/AES-GCM ;
- les limites de sécurité.

#### 4. Méthodologie expérimentale

Décrire :

- matériel et virtualisation ;
- IPs, ports et topologie ;
- versions logicielles ;
- charges synthétiques ;
- définition de submitted, accepted, committed et converged ;
- nombre de répétitions ;
- warm-up, fenêtre de mesure et drain ;
- méthode de collecte des ressources ;
- synchronisation ou non-synchronisation des horloges.

#### 5. Résultats

Organiser les résultats par couche :

1. cryptographie ;
2. baseline ;
3. charge et concurrence ;
4. latence ;
5. crash/reprise ;
6. délai réseau ;
7. ressources ;
8. EVM ;
9. IPFS.

#### 6. Discussion

Analyser :

- le point de saturation ;
- le coût de ML-DSA ;
- l’effet du mempool et de l’intervalle de bloc ;
- le coût du timeout ;
- la reprise après crash ;
- l’intérêt de conserver les dossiers hors chaîne ;
- les différences entre les trois VMs ;
- la portée réelle des résultats.

#### 7. Menaces à la validité

Inclure :

- seulement trois validateurs ;
- ressources limitées ;
- trois VMs VMware ;
- absence de machine physique de comparaison ;
- horloges non synchronisées pour certaines mesures inter-VM ;
- transactions et fichiers uniquement synthétiques ;
- API HTTP non disponible dans l’état actuel ;
- absence de campagne byzantine ;
- paramètres PoA spécifiques à l’expérience.

#### 8. Conclusion et travaux futurs

Proposer :

- davantage de validateurs ;
- consensus BFT ou certificat de quorum ;
- instrumentation Prometheus ;
- synchronisation temporelle dédiée ;
- API de production séparée ;
- scénario synthétique plus large ;
- tests de partition et de comportement byzantin ;
- étude de montée en charge IPFS.

---

## 12. Tableaux et figures à mettre dans l’article

### Figure 1 — Architecture globale

Montrer sur une seule figure :

```text
client → node1 → réseau PoA node1/node2/node3
                  │
                  ├─ ChainStorage + EVM + state_root
                  └─ IPFS-1/IPFS-2/IPFS-3
```

### Figure 2 — Flux d’un dossier synthétique

```text
fichier synthétique
    → ML-KEM-768 + AES-256-GCM
    → ciphertext
    → IPFS-1/2/3
    → CID + hash dans transaction
    → contrat et consentement
    → bloc signé ML-DSA
```

### Figure 3 — Débit et saturation

- abscisse : taux offert ;
- ordonnée : transactions commises par seconde ;
- seconde courbe : latence p95 ;
- annotation : zone de saturation observée.

### Figure 4 — Latence

Présenter p50, p95 et p99 de :

- soumission → inclusion ;
- soumission → commit local ;
- soumission → convergence observée.

### Figure 5 — Crash/reprise

Timeline des hauteurs, rounds et commits avant, pendant et après l’arrêt de
node3.

### Figure 6 — Ressources

CPU, RSS, swap, réseau et disque de node1/node2/node3 sous la même charge.

### Figure 7 — Coût cryptographique

ML-DSA-44 et ML-KEM-768 séparés par opération et par taille.

### Tableau 1 — Configuration expérimentale

Inclure les trois IPs, les ports, le nombre de VMs, le matériel visible, les
versions logicielles et les paramètres PoA.

### Tableau 2 — Résultats blockchain

Inclure offered rate, committed TPS, success rate, latence p50/p95/p99,
transactions par bloc et ressources.

### Tableau 3 — Résultats IPFS

Inclure CID, hash ciphertext, fournisseurs disponibles, temps de récupération,
taille du ciphertext, RSS Kubo et résultat de vérification.

### Tableau 4 — Limites

Associer chaque conclusion à son périmètre expérimental réel.

---

## 13. Vocabulaire à employer correctement

| Terme | Définition à utiliser dans l’article |
|---|---|
| Transaction soumise | Écriture ou requête envoyée par le générateur/client |
| Transaction acceptée | Transaction observée comme acceptée par le nœud d’entrée |
| Transaction incluse | Transaction présente dans un bloc persisté |
| Transaction réussie | Transaction dont le reçu indique un succès |
| Transaction convergée | Transaction incluse dans le même bloc observé par les trois nœuds |
| TPS offert | Taux demandé par le générateur |
| TPS commis | Nombre de transactions effectivement incluses par seconde |
| Goodput | Transactions réussies et commises par seconde |
| Latence d’inclusion | Soumission jusqu’à inclusion dans un bloc |
| Latence de commit | Soumission jusqu’à persistance sur un nœud |
| Latence de convergence | Soumission jusqu’à observation cohérente sur les trois nœuds |
| Finalité applicative | Convergence observée, pas certificat BFT |
| CID | Identifiant de contenu IPFS |
| Hash ciphertext | Empreinte du contenu chiffré inscrite dans la blockchain |
| IPFS distribué | Trois fournisseurs Kubo co-localisés et connectés en privé |
| Confidentialité | Chiffrement du contenu et contrôle des clés, pas simple stockage IPFS |
| Résilience crash | Reprise après arrêt d’un processus, pas tolérance byzantine complète |

---

## 14. Checklist de reproductibilité

Avant une nouvelle campagne :

- [ ] les trois VMs sont `node1`, `node2`, `node3` avec les IPs attendues ;
- [ ] le port blockchain `9001` est disponible entre les nœuds ;
- [ ] le P2P IPFS utilise `4001` ;
- [ ] les APIs Kubo restent sur loopback ;
- [ ] aucun daemon IPFS public ou VM supplémentaire n’est utilisé ;
- [ ] le code et les paramètres PoA sont identiques ;
- [ ] chaque validateur possède sa propre clé secrète ;
- [ ] aucune clé secrète ne figure dans les logs ou résultats ;
- [ ] les blocs persistants sont conservés ;
- [ ] aucune commande `make clean-data` n’est exécutée ;
- [ ] aucune règle `tc-netem` résiduelle n’est active avant B8-C ;
- [ ] les fichiers/ciphertexts sont synthétiques ;
- [ ] le `run_id` et la date sont définis avant le test ;
- [ ] le warm-up, la fenêtre de mesure et le drain sont enregistrés ;
- [ ] les transactions submitted/accepted/committed sont comptées séparément ;
- [ ] les hauteurs, `block_hash` et `state_root` sont comparés sur les trois nœuds ;
- [ ] les journaux et blocs sont collectés sur la machine de développement ;
- [ ] un manifeste SHA-256 est produit pour les résultats ;
- [ ] les limites de la campagne sont écrites avant l’interprétation.

---

## 15. Documents complémentaires

### Documentation des phases

- [Phase 1 — Fondations](01_PHASE1_FONDATIONS/00_LIRE_EN_PREMIER.md)
- [Phase 2 — Réseau trois nœuds](02_PHASE2_RESEAU_3_NOEUDS/00_LIRE_EN_PREMIER.md)
- [Phase 3 — Consensus et convergence](03_PHASE3_CONSENSUS_CONVERGENCE/00_LIRE_EN_PREMIER.md)
- [Phase 4 — Contrats médicaux](04_PHASE4_CONTRATS_MEDICAUX/00_LIRE_EN_PREMIER.md)
- [Phase 5 — Relais transactionnel](05_PHASE5_RELAIS_TRANSACTIONNEL/00_LIRE_EN_PREMIER.md)
- [Phase 6 — Liveness PoA](06_PHASE6_LIVENESS_POA/00_LIRE_EN_PREMIER.md)
- [Phase 7 — IPFS distribué](07_PHASE7_IPFS_DISTRIBUE/00_LIRE_EN_PREMIER.md)
- [Phase 8 — Benchmarks](08_PHASE8_BENCHMARKS/00_LIRE_EN_PREMIER.md)

### Dossier de preuves Phase 8

- [Index du dossier complet](../results/phase8-dossier-complet-2026-09-16/00_INDEX_DOSSIER_COMPLET_PHASE8.md)
- [Manifeste SHA-256](../results/phase8-dossier-complet-2026-09-16/99_MANIFEST_SHA256.txt)

### Références méthodologiques

- BLOCKBENCH : débit, latence, scalabilité et tolérance aux pannes.
- Hyperledger Caliper : métriques transactionnelles et ressources.
- NIST FIPS 203 : ML-KEM.
- NIST FIPS 204 : ML-DSA.
- `tc-netem` : délai, gigue et perte réseau contrôlée.
- py-evm : exécution EVM, état, reçus et transactions.
- Gunicorn : métriques API, uniquement si une API est effectivement déployée.

---

## 16. Résumé final en une phrase

Le projet est une **blockchain permissionnée PoA à trois VMs**, signée en
**ML-DSA-44**, exécutant éventuellement des contrats **EVM**, tandis que les
contenus médicaux synthétiques sont chiffrés par **ML-KEM-768/AES-GCM**, stockés
sur **trois IPFS co-localisés** et référencés dans la blockchain uniquement par
leur **CID et leur hash**, avec une évaluation séparée du débit, de la latence,
de la convergence, de la reprise et des ressources.
