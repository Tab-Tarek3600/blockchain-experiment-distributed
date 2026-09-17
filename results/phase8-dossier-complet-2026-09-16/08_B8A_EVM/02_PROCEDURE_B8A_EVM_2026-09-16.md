# Fiche B8-A — performance d'exécution EVM des contrats

**Date :** 16 septembre 2026  
**Run ID :** `b8a-evm-contracts-20260916`  
**Statut :** préparée  
**Périmètre :** couche EVM/contrats uniquement, sans réseau distant et sans IPFS

## 1. Règles de sécurité expérimentale

- Ne pas démarrer les trois VMs pour B8-A.
- Ne pas modifier `data/node1`, `data/node2` ou `data/node3`.
- Ne pas supprimer les 182 blocs existants.
- Ne pas lire, copier ou supprimer les clés secrètes des validateurs.
- Ne pas déployer de contrat sur la chaîne persistante des VMs.
- Les essais utilisent `EVMState` en mémoire et des identifiants, CID et hashes
  synthétiques.
- Le benchmark mesure l'exécution EVM locale, pas le TPS blockchain, le réseau,
  le consensus, le disque ou la signature ML-DSA réelle.

## 2. Préparation locale

Depuis la machine de développement :

```bash
cd ~/Bureau/blockchain-experiment-distributed
source .venv/bin/activate
mkdir -p results/raw_data
```

Vérifier les artefacts Solidity et leurs sommes :

```bash
sha256sum -c contracts/artifacts/SHA256SUMS
```

Résultat attendu : trois lignes `OK` pour `PatientRegistry.json`,
`ConsentManager.json` et `MedicalRecordRegistry.json`.

Vérifier que le script est compilable :

```bash
python3 -m py_compile scripts/experiments/benchmark_b8_evm.py
```

## 3. Tests fonctionnels préalables

Tests unitaires des contrats et de l'exécuteur :

```bash
PYTHONPATH=. pytest -q \
  tests/unit/contracts/test_contracts.py \
  tests/unit/evm/test_executor.py \
  tests/unit/evm/test_receipt.py \
  tests/unit/evm/test_logs.py \
  --timeout=120
```

Le résultat attendu est `PASSED` pour tous les tests.

Test d'intégration local avec trois nœuds éphémères TCP :

```bash
PYTHONPATH=. pytest -q \
  tests/integration/test_medical_contracts.py \
  --timeout=120
```

Ce test utilise des ports, clés, états et répertoires temporaires. Il ne touche
pas les VMs ni les répertoires persistants `data/nodeN`.

Le scénario vérifie notamment :

- déploiement des trois contrats ;
- enregistrement d'un patient pseudonymisé ;
- consentement valide, expiration et révocation ;
- `registerRecord()` autorisé ;
- `registerRecord()` non autorisé avec revert attendu ;
- `getRecord()` ;
- `revokeRecord()` ;
- événements Solidity ;
- `gas_used` et statut du reçu ;
- reproduction du `state_root` par rejeu ;
- convergence des trois nœuds locaux ;
- redémarrage depuis le stockage temporaire.

## 4. Benchmark de performance EVM

Le script mesure 30 échantillons par opération. Chaque échantillon utilise un
nouvel `EVMState` en mémoire et un nouvel ensemble d'identifiants synthétiques.
Le déploiement et la préparation sont exclus du temps de l'opération mesurée.

```bash
PYTHONPATH=. python3 scripts/experiments/benchmark_b8_evm.py \
  --samples 30 \
  --output results/raw_data/b8a-evm-contracts-20260916.json \
  2>&1 | tee results/raw_data/b8a-evm-contracts-20260916.log
```

Les opérations mesurées sont :

```text
registerPatient
 grantConsent
registerRecord
getRecord
revokeRecord
unauthorizedRegister  # échec attendu
```

Pour chaque opération, le JSON conserve :

- durée locale en microsecondes ;
- statut du reçu ;
- `gas_used` ;
- nombre de logs ;
- message d'erreur éventuel ;
- hauteur locale du bloc ;
- racine d'état avant et après.

## 5. Vérifier le résultat machine

```bash
python3 -m json.tool \
  results/raw_data/b8a-evm-contracts-20260916.json >/dev/null \
  && echo "B8A_JSON_OK"
```

```bash
grep -E '^(case|registerPatient|grantConsent|registerRecord|getRecord|revokeRecord|unauthorizedRegister|artifacts_sha256|persistent_chain|output)' \
  results/raw_data/b8a-evm-contracts-20260916.log
```

Contrôler les invariants du résumé :

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("results/raw_data/b8a-evm-contracts-20260916.json")
data = json.loads(path.read_text())
expected_success = {
    "registerPatient": 1.0,
    "grantConsent": 1.0,
    "registerRecord": 1.0,
    "getRecord": 1.0,
    "revokeRecord": 1.0,
    "unauthorizedRegister": 0.0,
}
expected_logs = {
    "registerPatient": [1],
    "grantConsent": [1],
    "registerRecord": [1],
    "getRecord": [0],
    "revokeRecord": [1],
    "unauthorizedRegister": [0],
}

assert data["persistent_chain_modified"] is False
assert data["remote_vms_contacted"] is False
assert data["synthetic_data_only"] is True

for case, success_rate in expected_success.items():
    summary = data["summaries"][case]
    assert summary["samples"] == 30, (case, summary)
    assert summary["success_rate"] == success_rate, (case, summary)
    assert summary["log_count_values"] == expected_logs[case], (case, summary)
    assert summary["gas_used"]["p50"] >= 0, (case, summary)
    assert summary["elapsed_us"]["p50"] > 0, (case, summary)

print("B8A_RESULT_OK")
print("persistent_chain_modified=False")
print("remote_vms_contacted=False")
PY
```

## 6. Interprétation à publier

- `registerPatient`, `grantConsent`, `registerRecord` et `revokeRecord` sont
  des écritures EVM réussies et doivent avoir un reçu `status=1`.
- `getRecord` est mesuré ici sur le chemin transactionnel local de l'EVM ; sa
  durée ne doit pas être appelée latence API ni latence blockchain end-to-end.
- `unauthorizedRegister` doit échouer avec `status=0` et sans événement
  Solidity ; cet échec déterministe n'est pas un échec d'infrastructure.
- Le `gas_used` est le coût d'exécution local de la transaction dans cet
  exécuteur, pas un prix en monnaie réelle.
- Les durées excluent le réseau, la production PoA, la propagation P2P, la
  persistance disque et la signature ML-DSA réelle.

## 7. Artefacts attendus

```text
results/raw_data/b8a-evm-contracts-20260916.json
results/raw_data/b8a-evm-contracts-20260916.log
```

Après validation de ces résultats, B8-A sera marqué exécuté et analysé. B8-B
(API) et B8-C (IPFS distribué) resteront les sous-couches suivantes de B8.
