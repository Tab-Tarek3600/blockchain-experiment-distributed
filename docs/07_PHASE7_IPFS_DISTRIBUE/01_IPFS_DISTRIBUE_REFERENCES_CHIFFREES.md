# PHASE 7 — IPFS distribué et références de dossiers chiffrés

## Décision d'architecture

La phase 7 conserve la proposition de la version 1 sans ajouter de VMs :
chaque VM blockchain héberge aussi un fournisseur IPFS co-localisé.

```text
node1 + blockchain + IPFS-1
node2 + blockchain + IPFS-2
node3 + blockchain + IPFS-3
```

Le stockage final ne doit pas être un unique daemon IPFS central. Le nombre
de fournisseurs est adapté de quatre dans l'ancien prototype à trois dans la
topologie finale, pour respecter les ressources disponibles tout en gardant
la réplication distribuée.

## Règles de confidentialité

- Le fichier de test est chiffré avant son ajout à IPFS.
- IPFS ne reçoit jamais un dossier médical en clair.
- La blockchain ne contient ni le contenu ni une clé secrète.
- La blockchain contient uniquement le CID, le hash du contenu chiffré et
  les métadonnées d'accès nécessaires à l'audit.
- Les tests utilisent uniquement des fichiers synthétiques.

## Flux de référence V2

```text
client/médecin
    -> chiffrement local du fichier
    -> ajout du contenu chiffré à IPFS-1
    -> obtention du CID
    -> pin du CID sur les fournisseurs disponibles
    -> transaction signée contenant CID + hash chiffré + scope
    -> node1
    -> relais P2P
    -> proposant PoA
    -> bloc diffusé et validé par les trois nœuds
```

La transaction n'est envoyée au réseau blockchain qu'après confirmation que
le contenu possède la réplication minimale prévue par le test.

## Mises à jour

IPFS est adressé par contenu : un objet ne doit jamais être modifié en place.

```text
version 1 -> CID-1
version 2 -> CID-2
```

Une mise à jour crée donc un nouveau CID et une nouvelle référence blockchain.
L'ancienne version reste vérifiable. Avec le contrat actuellement déployé,
une version peut utiliser un nouveau `recordId` et révoquer l'ancienne
référence ; une relation explicite `previousRecordId` pourra être ajoutée dans
une future version du contrat si elle est nécessaire à l'étude.

## Accès

`ConsentManager` reste l'autorité pour le consentement et le scope. IPFS ne
fournit pas à lui seul le contrôle d'accès : le contenu est chiffré et seule
la distribution autorisée de la clé permet le déchiffrement. ML-DSA reste
utilisé pour les signatures ; ML-KEM peut être utilisé pour encapsuler la clé
de contenu destinée aux bénéficiaires autorisés.

## Mode expérimental sous contrainte de ressources

Les trois VMs disposent d'environ 1,6 Gio de RAM chacune, dont environ 1,1 Gio
est disponible après le fonctionnement de base du système. La documentation
Kubo recommande davantage de mémoire pour un nœud généraliste ; cette phase
utilise donc explicitement un mode expérimental limité, adapté uniquement à un
banc d'essai avec des fichiers synthétiques de petite taille.

Les mesures de réduction retenues sont :

- réseau IPFS privé limité aux trois fournisseurs ;
- aucun bootstrap public et aucun trafic DHT public ;
- connexions statiques entre les trois pairs ;
- routage `none`, avec récupération Bitswap après connexion explicite ;
- un seul processus Kubo par VM, `GOMAXPROCS=1` et plafond Go de mémoire ;
- datastore plafonné et garbage collection automatique ;
- gestionnaire de connexions avec un nombre réduit de connexions ;
- API et gateway limitées à loopback ;
- arrêt du test si le noyau signale un OOM ou si la blockchain devient
  instable.

Ce mode ne constitue pas une capacité de production. Les mesures RSS, swap,
latence et éventuels événements OOM seront conservées dans le rapport de
validation.

## Contraintes réseau IPFS

- API IPFS : loopback uniquement sur chaque VM.
- P2P IPFS : port distinct de la blockchain, par défaut 4001.
- API blockchain : port 9001 inchangé.
- Gateway HTTP IPFS : désactivée ou loopback uniquement.
- Un seul daemon IPFS par VM ; aucune VM supplémentaire.
- Les clés des validateurs et les données blockchain ne sont pas remplacées
  par les données IPFS.

## Étapes de réalisation

### 7.1 — Vérification des ressources

Sur les trois VMs, relever la mémoire disponible, l'espace disque, la
présence éventuelle de Kubo/IPFS et les ports 4001/5001. Cette étape ne
modifie rien.

### 7.2 — Installation et configuration

Installer un daemon IPFS co-localisé par VM, créer un réseau privé de pairs,
limiter l'API à localhost et vérifier les trois identités IPFS.

### 7.3 — Adaptateur applicatif

L'adaptateur unique côté client est maintenant présent dans
`src/ipfs/adapter.py`. Il expose les opérations :

```text
add_encrypted_file -> CID
get_file(CID)
pin(CID)
unpin(CID)
has(CID)
```

L'API Kubo reste appelée sur loopback et l'adaptateur ne reçoit que des
ciphertexts déjà chiffrés. Les tests contrôlés sans daemon sont dans
`tests/unit/test_ipfs_adapter.py` ; ils vérifient l'ajout CIDv1, la lecture,
le pin/unpin, la détection d'un bloc absent et la traduction des erreurs HTTP.
La suite locale de l'adaptateur passe avec `5 passed`.

### 7.4 — Intégration blockchain

Utiliser les champs déjà présents dans `MedicalRecordRegistry` :

```text
CID
encryptedContentHash
patientId
scope
```

Ne pas modifier le consensus PoA ni le format des blocs pour intégrer IPFS.

### 7.5 — Validation

Les tests doivent couvrir :

1. contenu chiffré absent en clair d'IPFS ;
2. même contenu => même CID ;
3. CID récupérable sur les trois fournisseurs ;
4. même CID après récupération ;
5. modification => nouveau CID ;
6. ancien CID encore vérifiable ;
7. transaction CID relayée par node1 ;
8. bloc accepté par les trois validateurs ;
9. refus d'un accès sans consentement ;
10. récupération depuis un fournisseur après arrêt d'un autre fournisseur.

## Critère de sortie de la phase 7

La phase est terminée lorsque, avec un fichier synthétique chiffré :

- les trois IPFS sont joignables et distincts ;
- le même CID est disponible sur les trois fournisseurs ;
- le CID et le hash sont inscrits par une transaction entrée par node1 ;
- le bloc converge sur les trois nœuds ;
- la mise à jour crée un nouveau CID ;
- un utilisateur non autorisé ne peut pas déchiffrer le contenu ;
- les mesures de latence et de consommation sont enregistrées.

Aucune donnée médicale réelle ne doit être introduite dans le dépôt ou les
VMs.

## Relevé expérimental du 13 septembre 2026

Le banc d'essai a utilisé uniquement les fichiers synthétiques `v1` et `v2`
chiffrés côté client. Les valeurs d'intégrité observées sont :

| Version | CID | Hash SHA-256 du ciphertext |
|---|---|---|
| v1 | `Qmekbq6kAtwWZDu2K7HSKMTbrYqngVNKQ4wAzGp1Ui6yMA` | `e23583314041fda8336bd3637ceaef805379bd6866da11e31a561c490d41c4a4` |
| v2 | `QmSeS5hq1tyujnbkeEErye1q4z4XHkGqLnG6CQatA5wkZJ` | `995d6d9a210d7347a594d5c86963b4eebe9bdced575783fc2532a687d6e6bd89` |

La v2 utilise un nouveau ciphertext et un nouveau CID ; la v1 est conservée
comme historique. Le flux blockchain v1 a été observé avec la transaction
`a362d708030569dee26c7d8572b3865b98b9d6e3d55c522998d8925870350cb0` pour
l'enregistrement synthétique du patient, puis la transaction
`4403be9bd7be8ed31e82c04703ac70affcbc11b48e934a8872b2d34a579fb2c1` pour la
référence du dossier. Les blocs correspondants étaient la hauteur 4, de hash
`8c42b0e12c1386ee2a1f684676d9e38dda5d77337e0626ad518ae714603c81b5`, puis la
hauteur 5, de hash
`7ade53b7e90dba0267ec1eba2466a68eeb6c4ac9153975d617b58eb6c9299a50`.

La preuve blockchain v2 a ensuite été retrouvée sur les trois nœuds. La
transaction `registerRecord` v2 est :

```text
tx_id      : 6e544a1d9d1998e575ab3f2cf4f69d402029b43c7d5ae0ba9ab7ee8cdd4e96f0
hauteur    : 6
block_hash : 6069eb026a917d2a179a431e2a13f836a57ce2d811107462820810e5c86ed7d1
state_root : 7c1f055464d160b1c1fb978e9f4eb527a362418b579ff7a80f5e4e6450591b16
```

Le `state_root` du bloc v1 contenant `registerRecord` est :

```text
4db949f2489e76555f8f86f9bcdb199246c8b2bb21d62763c429ed6636b3807a
```

Les trois nœuds ont présenté exactement la même hauteur finale (`6`), le même
`tx_id` v2, le même hash de bloc et le même `state_root`. La convergence de la
preuve v1/v2 est donc confirmée sur node1, node2 et node3.

### Ressources observées

| Nœud | RSS Kubo | MemoryCurrent systemd | mémoire disponible | swap utilisée | RepoSize | OOM |
|---|---:|---:|---:|---:|---:|---|
| node1 | ~68,5 MiB | ~98,7 MiB | ~1,1 GiB | 0 B | 71 566 octets | aucun |
| node2 | ~68,6 MiB | ~21,4 MiB | ~1,1 GiB | 4 KiB | 50 420 octets | aucun |
| node3 | ~67,1 MiB | ~13,0 MiB | ~1,1 GiB | 0 B | 50 296 octets | aucun |

Les trois daemons utilisaient `StorageMax=1GB`, `Routing.Type=none`, la
garbage collection (`--enable-gc`) et un gestionnaire de connexions de type
`basic` avec `LowWater=4` et `HighWater=8`. Les différences entre les compteurs
`MemoryCurrent` systemd et le RSS sont conservées car ces compteurs ne mesurent
pas exactement le même périmètre mémoire. Aucun événement OOM n'a été observé.

### Latence et intégrité des récupérations IPFS

La récupération a été mesurée par l'API loopback de Kubo avec :

```text
POST http://127.0.0.1:5001/api/v0/cat?arg=CID
```

Chaque ciphertext récupéré faisait 128 octets. Les SHA-256 obtenus étaient
identiques aux valeurs de référence sur les trois VMs :

| Nœud | v1 | v2 |
|---|---:|---:|
| node1 | 19.894332 ms | 16.383921 ms |
| node2 | 20.452471 ms | 16.749031 ms |
| node3 | 18.818505 ms | 18.449691 ms |

La moyenne v1 est de **19.721769 ms**, la moyenne v2 de **17.194214 ms** et
la moyenne des six récupérations de **18.457992 ms**. Ces valeurs mesurent
l'appel local API vers le daemon de chaque VM ; elles ne sont pas présentées
comme une mesure isolée de transfert inter-VM Bitswap. La réplication et la
récupération sur les trois fournisseurs sont toutefois confirmées par les
hashes identiques.

Au moment du relevé initial, les processus blockchain n'étaient pas lancés par
les cibles `make node1`, `make node2` et `make node3`. Cela ne constitue pas une
réinitialisation : les blocs persistants sont conservés dans les répertoires
`data/nodeN/blocks`. Pour reprendre la blockchain, il faut lancer chaque cible
dans son terminal ou son service respectif ; il ne faut pas exécuter
`make clean-data`.

### Lecture contractuelle `getRecord()` sur les trois nœuds

Le manifeste public a confirmé l'adresse de `MedicalRecordRegistry` :

```text
0x368108079fe315817cde85b3ab02bd70d7024c0f
```

La lecture a été exécutée avec le script en lecture seule
`scripts/testing/read_phase7_records.py`, après activation du virtualenv sur
chaque VM. Le script recharge `ChainStorage`, rejoue l'état EVM jusqu'à la
hauteur 6 et exécute `getRecord(bytes32)` sur une copie de l'état. Il ne crée
aucune transaction et ne lit pas la clé secrète du validateur.

Résultat identique sur node1, node2 et node3 :

```text
height     : 6
state_root : 7c1f055464d160b1c1fb978e9f4eb527a362418b579ff7a80f5e4e6450591b16

v1:
  recordId   : phase7-record-v1-001
  patientId  : phase7-patient-001
  CID        : Qmekbq6kAtwWZDu2K7HSKMTbrYqngVNKQ4wAzGp1Ui6yMA
  hash       : e23583314041fda8336bd3637ceaef805379bd6866da11e31a561c490d41c4a4
  active     : True
  scope      : phase7-test-scope
  createdAt  : 1789308484

v2:
  recordId   : phase7-record-v2-001
  patientId  : phase7-patient-001
  CID        : QmSeS5hq1tyujnbkeEErye1q4z4XHkGqLnG6CQatA5wkZJ
  hash       : 995d6d9a210d7347a594d5c86963b4eebe9bdced575783fc2532a687d6e6bd89
  active     : True
  scope      : phase7-test-scope
  createdAt  : 1789309438
```

Le champ `registeredBy` vaut exactement la même adresse pour les deux versions
et sur les trois nœuds :

```text
0x277899e7c886108693659ea58957934e5b992892
```

Les adresses `view caller` imprimées par le script sont différentes car la
lecture est effectuée avec la clé publique locale de chaque validateur. Cela
n'affecte pas le résultat : `getRecord()` est une fonction `view` publique et
ne vérifie pas le consentement dans le contrat actuel.

La validation d'absence de consentement doit donc porter séparément sur un
appel `registerRecord()` non autorisé, qui doit être rejeté, ainsi que sur
l'impossibilité de déchiffrer le ciphertext sans la clé de chiffrement.

### Test négatif `registerRecord()` sans consentement

Une simulation locale a été exécutée sur l'état final de chaque nœud avec la
clé publique du validateur local comme compte outsider. La tentative utilise
le patient et la portée v2, mais un nouveau `recordId` :

```text
recordId  : phase7-record-negative-001
patientId : phase7-patient-001
scope     : phase7-test-scope
```

La simulation n'a été ni signée ni diffusée : aucun bloc et aucune donnée
persistante n'ont été modifiés. Résultat sur node1, node2 et node3 :

```text
height         : 6
state_root     : 7c1f055464d160b1c1fb978e9f4eb527a362418b579ff7a80f5e4e6450591b16
receipt.status : 0
RESULT         : accès sans consentement REJETÉ
broadcast      : non (simulation locale uniquement)
```

Le sélecteur de revert commun aux trois nœuds est :

```text
0xaa5c5f92
```

Il correspond à l'erreur Solidity :

```text
UnauthorizedRecordRegistration(bytes32,address,bytes32)
```

Le contrôle d'autorisation est donc déterministe et produit le même rejet sur
les trois copies de l'état convergentes.

### Test de confidentialité hors chaîne

La confidentialité a ensuite été vérifiée sur node1 avec un test local contrôlé
et sans donnée médicale réelle. Ce test ne contacte ni la blockchain ni IPFS
et ne démarre aucun nœud. Il modélise deux enveloppes immuables correspondant
aux versions v1 et v2 d'un même dossier synthétique :

```text
plaintext v1 -> ML-KEM-768 -> AES-256-GCM -> envelope v1
plaintext v2 -> ML-KEM-768 -> AES-256-GCM -> envelope v2
```

La même clé publique destinataire/client est utilisée pour les deux versions.
Chaque version reçoit toutefois une nouvelle encapsulation ML-KEM et possède
son propre ciphertext. Le test autorisé réussit avec la clé secrète du client.
Un outsider reçoit une autre clé secrète et échoue lors de l'authentification
AES-GCM ; il ne récupère donc aucun plaintext valide.

Résultat observé :

```text
mode       : test local controle, sans IPFS ni blockchain
algorithm  : ML-KEM-768 + AES-256-GCM
same client: oui (meme cle publique destinataire pour v1 et v2)
plaintext  : synthetique uniquement, aucune donnee medicale reelle

version                 : v1
ciphertext envelope     : 1216 octets
ciphertext sha256       : ffa133533e28825965f728e1f9ae7bcc9c736964040145d94a4347ec6b354916
dechiffrement client    : OK
dechiffrement outsider  : REJETE (authentification AES-GCM echouee)

version                 : v2
ciphertext envelope     : 1216 octets
ciphertext sha256       : 9e9fc3456f9d4d1777263c94a76b0e3568af8a26fd0c51b9c822b35dbd38a570
dechiffrement client    : OK
dechiffrement outsider  : REJETE (authentification AES-GCM echouee)

RESULT                   : confidentialite v1/v2 OK
immutable versions       : v1 et v2 ont des ciphertexts distincts
unauthorized decryption  : rejetee pour v1 et v2
```

Le script utilisé est `scripts/testing/test_phase7_confidentiality.py`.
Les enveloppes de ce test sont générées et conservées uniquement en mémoire :
les deux SHA-256 documentés ci-dessus servent d'empreintes de preuve de cette
exécution, mais ne constituent pas de nouveaux CID IPFS. Les CID v1 et v2
historiques restent inchangés.
