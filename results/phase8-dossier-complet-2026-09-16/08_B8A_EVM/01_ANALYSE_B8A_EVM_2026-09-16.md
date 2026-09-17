# Analyse B8-A — exécution EVM locale des contrats médicaux

**Date :** 16 septembre 2026  
**Run ID :** `b8a-evm-contracts-20260916`  
**Statut :** exécuté et interprété  
**Source :** journal `results/raw_data/b8a-evm-contracts-20260916.log` fourni après exécution du benchmark  
**Données :** synthétiques uniquement

## 1. Objet et périmètre

B8-A mesure le coût d'exécution local des contrats Solidity dans `EVMState`,
avec `ContractHarness`, sans connexion aux VMs et sans déploiement sur la chaîne
persistante.

Le benchmark couvre six cas, avec 30 échantillons chacun :

- `registerPatient` ;
- `grantConsent` ;
- `registerRecord` ;
- `getRecord` ;
- `revokeRecord` ;
- `unauthorizedRegister`, qui doit échouer.

Le temps mesuré inclut l'appel de l'EVM locale et la mise à jour de l'état du
harness. Il n'inclut pas :

- l'API HTTP ;
- le réseau ou la propagation P2P ;
- le consensus PoA ;
- la persistance disque ;
- la signature ML-DSA réelle ;
- IPFS ;
- la concurrence entre clients ;
- une blockchain distribuée réelle.

Ces résultats ne doivent donc pas être présentés comme une latence HTTP, une
latence end-to-end ou un TPS de la blockchain.

## 2. Résultats de contrôle

Le journal confirme :

```text
artifacts_sha256 : OK
persistent_chain : NOT_MODIFIED
```

Cela signifie que :

1. `PatientRegistry.json`, `ConsentManager.json` et
   `MedicalRecordRegistry.json` correspondent aux sommes SHA-256 attendues ;
2. aucune chaîne persistante n'a été modifiée ;
3. les VMs n'ont pas été contactées ;
4. le benchmark a utilisé des identifiants, CID et hashes synthétiques.

Le benchmark a produit 180 mesures au total : 150 appels autorisés et 30 appels
non autorisés attendus en échec.

## 3. Résultats quantitatifs

Les latences sont exprimées en microsecondes d'exécution EVM locale.

| Opération | Résultat | p50 | p95 | `gas_used` p50 | Logs |
|---|---:|---:|---:|---:|---:|
| `registerPatient` | 30/30 réussis | 2 044,17 µs | 2 524,71 µs | 90 287 | 1 |
| `grantConsent` | 30/30 réussis | 3 262,56 µs | 3 696,40 µs | 79 657 | 1 |
| `registerRecord` | 30/30 réussis | 6 637,56 µs | 9 584,69 µs | 200 017 | 1 |
| `getRecord` | 30/30 réussis | 2 438,26 µs | 2 677,70 µs | 38 036 | 0 |
| `revokeRecord` | 30/30 réussis | 2 928,68 µs | 3 522,23 µs | 38 353 | 1 |
| `unauthorizedRegister` | 0/30 réussis, échec attendu | 3 576,75 µs | 5 046,76 µs | 40 937 | 0 |

### 3.1 Écritures autorisées

Les cinq opérations autorisées atteignent 100 % de succès :

- le statut attendu est `status=1` ;
- les événements attendus sont présents pour les écritures ;
- `getRecord` ne produit aucun événement, ce qui est attendu pour une lecture ;
- aucun message d'erreur n'est associé aux appels réussis.

`registerRecord` est l'opération la plus coûteuse dans ce périmètre :

- p50 de 6,64 ms ;
- p95 de 9,58 ms ;
- `gas_used` p50 de 200 017.

Cette différence est cohérente avec son rôle : vérification du patient, contrôle
du consentement, traitement du CID, du hash de contenu et de la portée, puis
écriture des métadonnées et émission d'un événement.

`registerPatient` est l'écriture la plus rapide parmi les opérations mesurées,
avec un p50 de 2,04 ms. `grantConsent` et `revokeRecord` restent dans une plage
intermédiaire.

### 3.2 Lecture `getRecord`

`getRecord` obtient un p50 de 2,44 ms et un p95 de 2,68 ms. Cette mesure est
utile pour comparer le chemin d'exécution EVM avec les autres appels, mais elle
ne représente pas une lecture RPC ou HTTP en production.

En particulier, elle ne comprend pas :

- la réception d'une requête client ;
- l'authentification au niveau API ;
- la sérialisation HTTP ;
- un accès réseau ;
- une éventuelle lecture IPFS du document hors chaîne.

### 3.3 Appel non autorisé

`unauthorizedRegister` échoue dans les 30 échantillons, avec :

- `success_rate = 0.0`, car l'échec est le résultat attendu ;
- `status=0` dans le reçu d'échec ;
- aucun log Solidity (`log_count = 0`) ;
- une erreur `Revert` pour chaque échantillon ;
- un coût non nul de 40 937 gas p50, ce qui est normal : une transaction qui
  revertit consomme le gas déjà exécuté.

Les 30 messages d'erreur sont différents uniquement parce que les identifiants
synthétiques `b8a-patient-0000` à `b8a-patient-0029` et les scopes associés sont
différents. Ils doivent être regroupés dans l'analyse comme une seule classe :
**rejet d'autorisation attendu**, et non comme 30 incidents indépendants.

L'absence de logs confirme qu'aucun événement `RecordRegistered` n'est produit
par une tentative non autorisée.

## 4. État et reproductibilité

Pour chaque mesure, le runner conserve dans le JSON :

- la racine d'état avant l'appel ;
- la racine d'état après l'appel ;
- le numéro de bloc local avant et après ;
- le statut ;
- le gas consommé ;
- les logs ;
- l'erreur éventuelle.

Ces informations permettent une analyse ultérieure de la déterminisme de
l'exécution et du rejeu EVM. Le journal texte ne montre que les résumés ; le
fichier JSON est la source de référence pour les racines d'état et les mesures
brutes :

```text
results/raw_data/b8a-evm-contracts-20260916.json
```

`gas_used` doit être interprété comme un coût d'exécution EVM dans cet
exécuteur. Aucun prix monétaire ni coût de gas de réseau public ne doit être
déduit de ces valeurs.

## 5. Limites expérimentales

B8-A ne permet pas encore de conclure sur :

- le débit maximal de la blockchain ;
- la latence de finalité ou de convergence entre les trois VMs ;
- la latence API ;
- les effets de la signature ML-DSA dans le chemin complet ;
- l'impact d'IPFS ;
- les performances sous charge concurrente ;
- les effets de la propagation P2P, du disque ou d'une perturbation réseau ;
- la capacité d'augmentation du nombre de validateurs.

La formulation correcte dans l'article est donc :

> B8-A mesure exclusivement l'exécution locale en mémoire de la couche EVM et
> des contrats médicaux, avec des données synthétiques. Les valeurs de
> latence, de gas et de logs ne constituent pas une mesure de performance
> réseau, API ou blockchain distribuée.

## 6. Vérification finale recommandée du JSON

Le journal confirme déjà les invariants principaux. Pour archiver une preuve
machine explicite des statuts et des logs, exécuter depuis la racine du dépôt :

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("results/raw_data/b8a-evm-contracts-20260916.json")
data = json.loads(path.read_text())

expected_status = {
    "registerPatient": 1,
    "grantConsent": 1,
    "registerRecord": 1,
    "getRecord": 1,
    "revokeRecord": 1,
    "unauthorizedRegister": 0,
}
expected_logs = {
    "registerPatient": 1,
    "grantConsent": 1,
    "registerRecord": 1,
    "getRecord": 0,
    "revokeRecord": 1,
    "unauthorizedRegister": 0,
}

assert data["persistent_chain_modified"] is False
assert data["remote_vms_contacted"] is False
assert data["synthetic_data_only"] is True

for case, expected in expected_status.items():
    rows = [row for row in data["measurements"] if row["case"] == case]
    assert len(rows) == 30, (case, len(rows))
    assert all(int(row["status"]) == expected for row in rows), case
    assert all(row["log_count"] == expected_logs[case] for row in rows), case

print("B8A_RESULT_OK")
print("status/logs/chain/data invariants validated")
PY
```

## 7. Ce qu'il faut faire ensuite

### Étape 1 — Archiver et figer B8-A

1. Conserver le JSON et le journal sans les modifier.
2. Exécuter la vérification finale ci-dessus.
3. Conserver ce document d'analyse dans `results/raw_data/`.
4. Ne pas relancer les VMs et ne pas déployer ces contrats sur la chaîne
   persistante pour B8-A.

### Étape 2 — B8-B : mesurer la couche API

La prochaine campagne doit mesurer séparément la couche HTTP/API, toujours avec
un jeu de données synthétiques contrôlées. Elle devra notamment relever :

- requêtes soumises, acceptées et rejetées ;
- latence HTTP p50/p95/p99 ;
- code HTTP et message d'erreur ;
- temps de construction et de signature de transaction ;
- temps d'acceptation locale par node1 ;
- délai de diffusion et de convergence observé sur node2 et node3 ;
- CPU, mémoire et réseau pendant la campagne.

Le scénario d'entrée doit rester :

```text
client/médecin → node1 → diffusion P2P → node2/node3
```

Il ne faut pas remplacer ce scénario par un envoi direct du client vers les
trois nœuds. Les mesures B8-B devront être présentées séparément des latences
B8-A.

### Étape 3 — B8-C : IPFS distribué co-localisé

Après B8-B, réaliser la couche IPFS distribuée conformément à l'architecture
retenue :

- un service IPFS co-localisé avec chacun des trois nœuds blockchain ;
- aucune VM IPFS supplémentaire ;
- dossiers de test contrôlés et synthétiques uniquement ;
- documents médicaux hors chaîne ;
- CID inscrit dans la transaction blockchain pour l'audit et l'intégrité ;
- chaque mise à jour crée un nouveau CID et une nouvelle version ;
- vérification de publication, récupération, pinning et réplication sur les
  trois fournisseurs ;
- tests de disponibilité avec un fournisseur temporairement indisponible.

Les commandes de déploiement devront rester simples (`ssh` et `scp`) et ne
pas introduire de script d'orchestration. Les clés secrètes des validateurs et
les configurations existantes ne doivent pas être supprimées.

### Étape 4 — Campagnes de charge et perturbation

Une fois B8-B et B8-C stabilisés, poursuivre avec :

1. variation du nombre de clients ;
2. concurrence ;
3. variation du débit d'arrivée ;
4. délai et perte réseau contrôlés ;
5. arrêt temporaire d'un service IPFS ;
6. comparaison des taux de succès, latences et convergences.

La scalabilité en validateurs restera limitée à trois nœuds dans l'architecture
actuelle. Les campagnes les plus pertinentes sont donc celles qui varient les
clients, la concurrence, le débit et les perturbations réseau.

## 8. Conclusion

B8-A valide le comportement fonctionnel et le coût local des cinq opérations
autorisées, ainsi que le rejet déterministe d'une tentative non autorisée sans
émission de log. Le résultat est exploitable comme **baseline EVM locale**.

La prochaine étape n'est pas de relancer B8-A, mais de mesurer séparément :

1. la chaîne complète côté API avec le scénario `client/médecin → node1` ;
2. la persistance et la réplication IPFS distribuées sur les trois nœuds
   co-localisés ;
3. les effets de la charge et des perturbations réseau.
