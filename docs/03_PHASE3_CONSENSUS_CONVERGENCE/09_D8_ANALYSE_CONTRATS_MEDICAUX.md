# D8 — Analyse des smart contracts médicaux

> **Mise à jour du 15 septembre 2026.** Cette page conserve l'analyse initiale
> de conception. Les contrats et leur intégration ont depuis été créés et
> validés dans la PHASE 4/7 ; voir `contracts/`,
> `docs/04_PHASE4_CONTRATS_MEDICAUX/02_DEPLOIEMENT_CONTRATS.md` et `docs/07_PHASE7_IPFS_DISTRIBUE/01_IPFS_DISTRIBUE_REFERENCES_CHIFFREES.md`.

**Statut actuel :** conception validée, contrats intégrés et preuves de lecture,
de convergence et de rejet sans consentement disponibles. La campagne de
performance EVM/IPFS reste distincte et n'est pas encore complète.

D6 est terminé : les trois VMs ont produit la même empreinte de chaîne, le même
`state_root` pour les contrôles, et les mêmes verdicts. D8 a ouvert la PHASE 4.

L'objectif n'est pas de mettre des dossiers médicaux sur la blockchain.
La blockchain ne conservera que des identifiants pseudonymisés, des
permissions et des références vers des contenus chiffrés hors chaîne.

---

## 1. Inspection de l'existant

### 1.1 Capacités déjà présentes

L'inspection de `src/evm/` montre que le socle nécessaire existe déjà :

- `Transaction.data` transporte les données d'appel ou l'initcode ;
- la signature de transaction reste ML-DSA ;
- les adresses sont sur 20 octets ;
- `EVMExecutor` déploie un contrat lorsque `recipient == ZERO_ADDRESS` ;
- l'adresse de contrat est déterministe à partir de `(sender, nonce)` ;
- l'appel d'un contrat est exécuté par py-evm ;
- `EVMState` expose le code et le stockage EVM (`get_code`, `get_storage`,
  `set_storage`) ;
- `SSTORE`, `SLOAD`, `REVERT` et l'out-of-gas sont déjà couverts par les
  tests de l'exécuteur ;
- l'état est rejoué depuis les blocs et produit un `state_root` déterministe ;
- une transaction qui revert produit un reçu en échec sans invalider le bloc.

### 1.2 Absences constatées

Aucun contrat médical, ABI ou helper d'encodage n'existe actuellement.

Le projet n'a pas encore :

- `PatientRegistry` ;
- `ConsentManager` ;
- `MedicalRecordRegistry` ;
- encodeur/décodeur ABI dédié ;
- gestion des événements/logs dans `Receipt` ;
- chaîne de compilation Solidity ;
- test d'intégration de trois contrats médicaux.

`Receipt` indique explicitement que les logs ne sont pas encore exploités.
C'est un point à décider avant d'implémenter des événements Solidity.

### 1.3 Fichiers stables à ne pas modifier

D8/PHASE 4 ne doit pas modifier :

- `src/blockchain/` ;
- `src/crypto/` ;
- `src/node/validator.py` ;
- `src/node/consensus.py` ;
- `src/node/mempool.py` ;
- `src/node/socket_p2p.py` ;
- `Node._accept_block()`.

Les contrats restent en aval de l'exécuteur EVM. Le consensus PoA et les
signatures ML-DSA ne changent pas.

---

## 2. Règles de confidentialité

### 2.1 Ce qui est interdit dans les contrats

Ne jamais inscrire dans un bloc ou dans le stockage EVM :

- nom ou prénom ;
- numéro de sécurité sociale ;
- date de naissance ;
- diagnostic ;
- prescription ;
- résultat d'examen ;
- adresse ou téléphone ;
- contenu du dossier médical ;
- clé AES ou donnée permettant de déchiffrer le contenu.

Même chiffrée, une donnée médicale complète n'a pas sa place dans la
chaîne : elle serait publique, répliquée et durable.

### 2.2 Ce qui peut être inscrit dans la chaîne

- `patientIdHash` : identifiant pseudonymisé de 32 octets ;
- adresse blockchain du contrôleur ou du bénéficiaire ;
- identifiant de permission ;
- portée de permission ;
- expiration et révocation ;
- `recordId` ;
- CID ou référence IPFS ;
- hash du contenu chiffré ;
- timestamps de création et de révocation ;
- statut logique du dossier.

La pré-image de `patientIdHash` ne doit pas être déductible par simple
hachage d'un identifiant public connu. La construction de l'identifiant
pseudonymisé devra donc être documentée séparément.

---

## 3. Architecture fonctionnelle proposée

### 3.1 `PatientRegistry`

Responsabilité unique : associer un identifiant pseudonymisé à un
contrôleur blockchain et à un statut.

Données minimales proposées :

```text
patientIdHash -> controllerAddress, active, createdAt
```

Opérations proposées :

```text
registerPatient(patientIdHash)
deactivatePatient(patientIdHash)
isRegistered(patientIdHash)
getController(patientIdHash)
```

Règles :

- l'adresse qui enregistre devient le contrôleur ;
- un identifiant ne peut pas être enregistré deux fois ;
- la désactivation ne supprime pas l'historique ;
- aucune donnée d'identité réelle n'est acceptée par l'interface.

### 3.2 `ConsentManager`

Responsabilité unique : enregistrer et révoquer une permission entre un
patient et un bénéficiaire.

Clé logique proposée :

```text
(patientIdHash, beneficiaryAddress, scopeHash)
```

Données minimales :

```text
beneficiaryAddress, grantedAt, expiresAt, revoked
```

Opérations proposées :

```text
grantConsent(patientIdHash, beneficiaryAddress, scopeHash, expiresAt)
revokeConsent(patientIdHash, beneficiaryAddress, scopeHash)
hasConsent(patientIdHash, beneficiaryAddress, scopeHash)
```

Règles :

- seul le contrôleur du patient peut accorder ou révoquer ;
- une permission expirée vaut refus ;
- une permission révoquée ne redevient pas active sans nouvelle décision ;
- la permission porte sur une portée abstraite, jamais sur le contenu médical.

### 3.3 `MedicalRecordRegistry`

Responsabilité unique : enregistrer une référence vers un contenu médical
chiffré conservé hors chaîne.

Données minimales proposées :

```text
recordId -> patientIdHash, cid, encryptedContentHash, registeredBy,
            createdAt, revoked
```

Opérations proposées :

```text
registerRecord(recordId, patientIdHash, cid, encryptedContentHash)
revokeRecord(recordId)
getRecord(recordId)
isRecordActive(recordId)
```

Règles :

- `cid` référence le contenu chiffré dans IPFS ;
- `encryptedContentHash` permet de vérifier que le contenu téléchargé
  correspond à celui enregistré ;
- l'enregistrement exige que le patient soit connu ;
- l'enregistrement exige une permission valide lorsque l'appelant n'est
  pas le contrôleur ;
- révoquer une référence ne supprime pas l'historique blockchain ;
- le contrat ne déchiffre jamais le contenu.

---

## 4. Choix technique recommandé

### 4.1 Source des contrats

Pour se rapprocher d'une blockchain réelle, les contrats devraient être
écrits en Solidity et compilés avec un compilateur épinglé. Le bytecode
compilé serait ensuite déployé via `Transaction.data` et exécuté par le
moteur EVM déjà présent.

Le compilateur ne doit pas être ajouté aux VMs avant validation de la
procédure hors ligne. Les VMs n'ont pas besoin de compiler elles-mêmes les
contrats si le bytecode déterministe et la source Solidity sont transmis
ensemble.

Alternative rejetée par défaut : écrire tous les contrats en bytecode EVM
à la main. Cette solution est utile pour les tests du moteur, mais elle est
moins maintenable et moins représentative d'un développement de contrats
réel.

### 4.2 ABI

Les appels Solidity passeront dans `Transaction.data`. Il faudra donc
ajouter, après validation de l'architecture :

- un ABI minimal déterministe pour les fonctions utilisées ; ou
- des helpers Python d'encodage/décodage limités aux types réellement
  employés.

`web3` et `eth-account` ne doivent pas être ajoutés : les transactions
restent signées par ML-DSA et non par ECDSA.

### 4.3 Événements

Les événements seraient utiles pour l'audit : enregistrement d'un patient,
accord de consentement, révocation, enregistrement d'un CID.

Mais `Receipt` ne transporte actuellement ni logs ni bloom filter. Il faut
choisir entre :

1. première version sans événements, avec lecture d'état uniquement ;
2. ajout justifié d'une structure de logs dans `ExecutionOutcome` et
   `Receipt`, puis tests de persistance et de déterminisme.

Pour une intégration médicale réellement exploitable, l'option 2 est la
cible, mais elle doit être analysée et testée séparément avant de toucher
`Receipt`.

---

## 5. Flux bout en bout cible

```text
1. Patient ou opérateur crée un identifiant pseudonymisé
2. PatientRegistry enregistre cet identifiant
3. ConsentManager accorde une permission limitée
4. Dossier médical local préparé
5. Dossier chiffré avec AES-256-GCM
6. Contenu chiffré envoyé à IPFS
7. CID + hash du contenu enregistrés dans MedicalRecordRegistry
8. Un bénéficiaire vérifie la permission
9. Le bénéficiaire récupère le CID
10. Le contenu IPFS est vérifié puis déchiffré hors chaîne
```

La blockchain ne porte que les étapes 2, 3 et 7 à 9 sous forme de
transactions et de références.

---

## 6. Tests à préparer avant les VMs

Les tests doivent d'abord être locaux et déterministes :

1. déploiement des trois contrats ;
2. adresse de contrat déterministe ;
3. enregistrement d'un patient pseudonymisé ;
4. double enregistrement refusé ;
5. permission accordée par le contrôleur ;
6. permission refusée à un appelant non autorisé ;
7. expiration d'une permission ;
8. révocation d'une permission ;
9. enregistrement d'un CID sans contenu médical ;
10. enregistrement refusé pour un patient inconnu ;
11. hash du contenu chiffré conservé sans pré-image médicale ;
12. transaction revertie : bloc toujours accepté ;
13. rejeu depuis `ChainStorage` : même `state_root` ;
14. deux exécutions indépendantes : même `state_root` ;
15. aucun secret AES ni contenu médical dans les blocs ou le stockage.

Les trois VMs ne seront sollicitées qu'après le passage de ces tests en
local. Le déploiement inter-VM vérifiera ensuite que les mêmes bytecodes,
transactions et racines d'état donnent les mêmes résultats.

---

## 7. Fichiers potentiels — à confirmer avant création

Aucun de ces fichiers n'est créé par cette analyse. Proposition à valider :

```text
contracts/PatientRegistry.sol
contracts/ConsentManager.sol
contracts/MedicalRecordRegistry.sol
contracts/abi/...
contracts/artifacts/...
tests/unit/contracts/...
tests/integration/test_medical_contracts.py
```

La liste définitive dépendra du choix du compilateur, de l'ABI et des
événements. Aucun fichier de `src/blockchain/` ou de consensus ne doit être
ajouté pour ces contrats.

---

## 8. Prochaine décision avant le code

Décisions à valider :

1. Solidity compilé avec compilateur épinglé : recommandé ;
2. `patientIdHash` de 32 octets comme identifiant public pseudonymisé ;
3. CID + hash du contenu chiffré, jamais le contenu ;
4. permission définie par `(patient, bénéficiaire, portée, expiration)` ;
5. événements Solidity avec extension justifiée de `Receipt` : cible à
   confirmer.

**Aucune modification de code de production n'est appliquée par ce
 document.**
