# Blockchain expérimentale distribuée post-quantique

Projet de recherche sur une blockchain permissionnée à trois validateurs pour la gestion de références de dossiers médicaux synthétiques chiffrés.

> **Dépôt privé recommandé.** Les tests utilisent uniquement des données synthétiques. Les clés secrètes de validateurs, les répertoires `data/`, les environnements Python et les sauvegardes locales sont exclus par `.gitignore`.

## Architecture en une vue

- **3 VMs blockchain** :
  - `node1` — `192.168.168.101`
  - `node2` — `192.168.168.102`
  - `node3` — `192.168.168.103`
- **Blockchain P2P** : TCP `9001`, topologie en triangle complet.
- **Consensus** : PoA round-robin.
- **Signatures** : ML-DSA-44.
- **Confidentialité hors chaîne** : ML-KEM-768 + AES-256-GCM.
- **IPFS** : un fournisseur Kubo co-localisé sur chaque VM ; P2P `4001`, API loopback `127.0.0.1:5001`.
- **EVM** : exécution locale et contrats de registre patient, consentement et références de dossiers.

## Documentation principale

Le document à lire en premier pour comprendre l’ensemble du projet et préparer l’article scientifique est :

[`docs/00_ARCHITECTURE_COMPLETE_PROJET.md`](docs/00_ARCHITECTURE_COMPLETE_PROJET.md)

L’index de toute la documentation est disponible ici :

[`docs/00_INDEX_DOCUMENTATION_PROJET.md`](docs/00_INDEX_DOCUMENTATION_PROJET.md)

La documentation est organisée par phase :

```text
docs/01_PHASE1_FONDATIONS/
docs/02_PHASE2_RESEAU_3_NOEUDS/
docs/03_PHASE3_CONSENSUS_CONVERGENCE/
docs/04_PHASE4_CONTRATS_MEDICAUX/
docs/05_PHASE5_RELAIS_TRANSACTIONNEL/
docs/06_PHASE6_LIVENESS_POA/
docs/07_PHASE7_IPFS_DISTRIBUE/
docs/08_PHASE8_BENCHMARKS/
```

## Résultats expérimentaux

Le dossier consolidé de la Phase 8 se trouve ici :

[`results/phase8-dossier-complet-2026-09-16/`](results/phase8-dossier-complet-2026-09-16/)

Son index et son manifeste SHA-256 sont disponibles dans ce dossier.

## Sécurité avant publication

Ne jamais publier :

- les clés secrètes de validateurs ;
- les fichiers `.env`, certificats ou tokens ;
- les répertoires `data/` contenant l’état local d’une chaîne ;
- des données médicales réelles ;
- une configuration locale contenant des secrets.

Les fichiers de configuration versionnés dans `config/nodes/` sont des gabarits ; les valeurs locales doivent rester hors du dépôt si elles contiennent des informations sensibles.
