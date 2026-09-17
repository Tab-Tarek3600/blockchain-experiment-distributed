# PHASE 4 — Spécification des contrats médicaux

**Statut : spécification validée comme base de travail — aucun contrat ni
code Python de production ajouté.**

Décisions prises pour ouvrir l'implémentation :

- contrats écrits en **Solidity** ;
- compilateur épinglé, bytecode compilé déterministe ;
- identifiant patient public limité à un `bytes32` pseudonymisé ;
- CID et hash du contenu chiffré uniquement ;
- événements Solidity inclus dès cette phase ;
- aucune donnée médicale, clé AES ou contenu IPFS dans la chaîne.

La chaîne reste signée en ML-DSA. Solidity ne signe pas les transactions :
le bytecode est appelé par `Transaction.data`, dont l'enveloppe reste celle
du projet.

---

## 1. Interfaces proposées

Les signatures ci-dessous sont la cible fonctionnelle. Elles seront
encodées dans l'ABI après choix et transport du compilateur.

### 1.1 PatientRegistry

```solidity
registerPatient(bytes32 patientId)
deactivatePatient(bytes32 patientId)
isRegistered(bytes32 patientId) view returns (bool)
isActive(bytes32 patientId) view returns (bool)
controllerOf(bytes32 patientId) view returns (address)
isController(bytes32 patientId, address candidate) view returns (bool)
```

Stockage logique :

```text
patientId -> controller, active, registeredAt
```

Règles :

- l'appelant devient le contrôleur lors de l'enregistrement ;
- un `patientId` déjà enregistré est refusé ;
- seul le contrôleur peut désactiver ;
- la désactivation conserve l'historique ;
- `patientId` ne contient aucune identité en clair.

Événements :

```solidity
event PatientRegistered(
    bytes32 indexed patientId,
    address indexed controller,
    uint256 registeredAt
);
event PatientDeactivated(
    bytes32 indexed patientId,
    address indexed controller,
    uint256 deactivatedAt
);
```

### 1.2 ConsentManager

Le contrat reçoit l'adresse `PatientRegistry` au déploiement. Pour éviter
`tx.origin`, la vérification de contrôle se fait explicitement :
`msg.sender` est passé comme candidat à `PatientRegistry.isController()`.

```solidity
grantConsent(
    bytes32 patientId,
    address beneficiary,
    bytes32 scope,
    uint256 expiresAt
)
revokeConsent(
    bytes32 patientId,
    address beneficiary,
    bytes32 scope
)
hasValidConsent(
    bytes32 patientId,
    address beneficiary,
    bytes32 scope
) view returns (bool)
getConsent(
    bytes32 patientId,
    address beneficiary,
    bytes32 scope
) view returns (bool granted, uint256 expiresAt, uint256 grantedAt)
```

Clé logique :

```text
(patientId, beneficiary, scope)
```

Données :

```text
expiresAt, granted, revoked, grantedAt
```

Règles :

- seul le contrôleur du patient peut accorder ou révoquer ;
- `expiresAt == 0` signifie sans expiration explicite ;
- une permission expirée est invalide ;
- une révocation est définitive pour cette instance de consentement ;
- une nouvelle autorisation doit être une nouvelle opération explicite.

Événements :

```solidity
event ConsentGranted(
    bytes32 indexed patientId,
    address indexed beneficiary,
    bytes32 indexed scope,
    uint256 expiresAt
);
event ConsentRevoked(
    bytes32 indexed patientId,
    address indexed beneficiary,
    bytes32 indexed scope
);
```

### 1.3 MedicalRecordRegistry

Le contrat reçoit les adresses `PatientRegistry` et `ConsentManager` au
déploiement.

```solidity
registerRecord(
    bytes32 recordId,
    bytes32 patientId,
    bytes calldata cid,
    bytes32 encryptedContentHash,
    bytes32 scope
)
revokeRecord(bytes32 recordId)
isRecordActive(bytes32 recordId) view returns (bool)
getRecord(bytes32 recordId) view returns (...)
```

Stockage logique :

```text
recordId -> patientId, cid, encryptedContentHash,
            registeredBy, createdAt, active, scope
```

Règles :

- `recordId` ne peut pas être enregistré deux fois ;
- `patientId` doit être enregistré et actif ;
- le contrôleur peut enregistrer directement ;
- un autre appelant doit posséder un consentement valide pour `scope` ;
- seul le contrôleur peut révoquer une référence, y compris après
  désactivation du patient ;
- `cid` est une référence non vide limitée à 256 octets et pointe vers le
  contenu déjà chiffré dans IPFS ;
- `encryptedContentHash` vérifie l'intégrité du contenu téléchargé ;
- la révocation désactive la référence sans effacer l'historique ;
- le contrat ne lit ni ne déchiffre le contenu IPFS.

Événements :

```solidity
event RecordRegistered(
    bytes32 indexed recordId,
    bytes32 indexed patientId,
    address indexed registeredBy,
    bytes32 encryptedContentHash,
    bytes32 scope
);
event RecordRevoked(
    bytes32 indexed recordId,
    address indexed revokedBy
);
```

---

## 2. Événements et reçus

Les événements sont retenus dès la PHASE 4 pour permettre un audit sans
rejouer tout l'état.

Le changement devra rester confiné à la couche EVM :

```text
py-evm computation
        ↓
src/evm/state.py : conversion en types natifs
        ↓
ExecutionOutcome.logs
        ↓
src/evm/executor.py
        ↓
Receipt.logs
```

Structure publique proposée :

```text
EVMLog(
    address: bytes20,
    topics: tuple[bytes32, ...],
    data: bytes
)
```

Dans le wheel py-evm présent dans le dépôt (`0.12.1b1`), l'API interne
vérifiée est `Computation.get_log_entries()`, qui renvoie :

```text
tuple[(address: bytes, topics: tuple[int, ...], data: bytes), ...]
```

L'adaptateur de `state.py` devra donc convertir chaque topic entier en mot
EVM big-endian de 32 octets et valider l'adresse canonique de 20 octets.
La dépendance réellement installée devra encore être comparée au commit
épinglé de `requirements.txt` avant le premier patch de production.

Contraintes :

- aucun objet py-evm ne sort de `state.py` ;
- les logs sont immuables comme `Receipt` ;
- `to_dict()`/`from_dict()` doivent être déterministes ;
- un revert ne conserve aucun log produit par la transaction revertie ;
- les logs d'une transaction réussie restent dans son reçu ;
- un bloc conserve un reçu par transaction, dans l'ordre du bloc.

---

## 3. Compilation et artefacts

La source Solidity doit être conservée avec les artefacts nécessaires :

```text
source Solidity
+ version exacte de solc
+ ABI
+ init bytecode
+ runtime bytecode
+ hash des artefacts
```

Le compilateur ne doit pas être requis par les VMs pour exécuter un contrat.
Les VMs reçoivent le bytecode déjà compilé et validé localement.

Version retenue pour la vérification hors ligne :

```text
solc 0.8.24
EVM target : Shanghai
pragma solidity 0.8.24;
```

La documentation officielle de Solidity 0.8.24 confirme le paramètre
`evmVersion: "shanghai"` et recommande l'interface JSON standard pour une
compilation automatisée. Le binaire exact reste à fournir ou à vérifier
hors ligne : l'absence de `solc` sur la machine de travail a été constatée
et aucun téléchargement n'a été lancé.

Configuration de compilation cible :

```json
{
  "optimizer": {"enabled": true, "runs": 200},
  "evmVersion": "shanghai",
  "metadata": {"bytecodeHash": "none"},
  "viaIR": false
}
```

Sorties minimales : ABI, init bytecode, runtime bytecode et metadata de
compilation. Les contrats doivent être compilés avec des options
strictement déterministes :

- même version de solc ;
- mêmes sources ;
- mêmes options d'optimisation ;
- même `evmVersion` ;
- metadata maîtrisée ;
- hash des artefacts comparé avant déploiement.

---

## 4. Séquence de déploiement déterministe

Le déploiement s'effectuera dans cet ordre :

```text
1. PatientRegistry
2. ConsentManager(PatientRegistry.address)
3. MedicalRecordRegistry(
       PatientRegistry.address,
       ConsentManager.address
   )
```

Les adresses de contrats dérivent du compte et du nonce de déploiement.
Le même compte de test, les mêmes nonces et les mêmes initcodes doivent
être utilisés lors du rejeu sur les trois nœuds.

Les adresses effectivement créées seront récupérées dans les reçus de
transactions de déploiement, jamais saisies arbitrairement dans la
configuration.

---

## 5. Tests locaux obligatoires

### Compilation et artefacts

- compilation avec la version exacte de solc ;
- hash identique des artefacts ;
- ABI cohérente avec le bytecode ;
- aucun contenu médical dans les sources de test ou les artefacts.

### PatientRegistry

- enregistrement valide ;
- double enregistrement rejeté ;
- lecture de l'état ;
- désactivation par le contrôleur ;
- désactivation par un tiers rejetée ;
- événement émis uniquement en cas de succès.

### ConsentManager

- consentement valide ;
- contrôle du patient ;
- bénéficiaire incorrect rejeté ;
- expiration ;
- révocation ;
- consultation après révocation ;
- événements `ConsentGranted` et `ConsentRevoked`.

### MedicalRecordRegistry

- patient inexistant rejeté ;
- enregistrement par le contrôleur ;
- enregistrement par bénéficiaire autorisé ;
- enregistrement par bénéficiaire non autorisé rejeté ;
- CID et hash conservés exactement ;
- révocation ;
- aucune donnée médicale stockée.

### Consensus et rejeu

- une transaction revertie reste dans un bloc valide ;
- même suite de déploiements/appels ⇒ même `state_root` ;
- rejeu depuis `ChainStorage` ⇒ même `state_root` ;
- mêmes logs et mêmes reçus sur deux exécuteurs indépendants.

Les VMs ne seront utilisées qu'après passage de tous ces tests en local.

---

## 6. Fichiers à créer après validation technique

Proposition, non encore créée :

```text
contracts/PatientRegistry.sol
contracts/ConsentManager.sol
contracts/MedicalRecordRegistry.sol
contracts/artifacts/...
src/evm/logs.py
src/evm/abi.py
tests/unit/evm/test_logs.py
tests/unit/contracts/...
tests/integration/test_medical_contracts.py
```

La liste finale dépendra de la vérification de l'API des logs py-evm et du
mode de compilation hors ligne. Aucun fichier de consensus ou de stockage
PHASE 1/2 ne doit être modifié.

**Cette spécification précède l'implémentation.**
