# Documentation du projet — index général

Cette arborescence regroupe les documents de conception, d'installation, de développement, de déploiement et de validation du projet blockchain distribuée.

Le document de présentation globale, recommandé pour comprendre le système et préparer l'article scientifique, est :

- [`00_ARCHITECTURE_COMPLETE_PROJET.md`](00_ARCHITECTURE_COMPLETE_PROJET.md)

## Organisation retenue

Chaque phase dispose de son propre dossier. Les fichiers suivent une numérotation de lecture et un nom explicite :

```text
docs/
├── 00_INDEX_DOCUMENTATION_PROJET.md
├── 00_ARCHITECTURE_COMPLETE_PROJET.md
├── README.md
├── 01_PHASE1_FONDATIONS/
├── 02_PHASE2_RESEAU_3_NOEUDS/
├── 03_PHASE3_CONSENSUS_CONVERGENCE/
├── 04_PHASE4_CONTRATS_MEDICAUX/
├── 05_PHASE5_RELAIS_TRANSACTIONNEL/
├── 06_PHASE6_LIVENESS_POA/
├── 07_PHASE7_IPFS_DISTRIBUE/
└── 08_PHASE8_BENCHMARKS/
```

## Index des phases

| Dossier | Sujet | Contenu principal |
|---|---|---|
| `01_PHASE1_FONDATIONS` | Fondations et environnement | Installation reproductible de liboqs et de l'environnement cryptographique sur les trois machines. |
| `02_PHASE2_RESEAU_3_NOEUDS` | Réseau réel à trois nœuds | Déploiement des trois VMs et transport TCP réel entre les nœuds. |
| `03_PHASE3_CONSENSUS_CONVERGENCE` | Consensus, transmission et convergence | Diagnostic des VMs, lancement, convergence, `state_root`, contrôles D3/D5/D6/D8 et mise à jour de `block.py`. |
| `04_PHASE4_CONTRATS_MEDICAUX` | Contrats médicaux | Spécification, déploiement et procédure de déploiement sur les trois nœuds. |
| `05_PHASE5_RELAIS_TRANSACTIONNEL` | Relais transactionnel | Production de blocs à la demande et relais par un nœud d'entrée. |
| `06_PHASE6_LIVENESS_POA` | Liveness PoA | Timeout, changement de round et reprise de production. |
| `07_PHASE7_IPFS_DISTRIBUE` | IPFS distribué | Références de dossiers chiffrés et réplication IPFS co-localisée. |
| `08_PHASE8_BENCHMARKS` | Tests et benchmarks | Plan expérimental et état des résultats Phase 8 disponibles au 15 septembre 2026. |

## Ordre de lecture conseillé

1. `01_PHASE1_FONDATIONS/00_LIRE_EN_PREMIER.md`
2. `02_PHASE2_RESEAU_3_NOEUDS/00_LIRE_EN_PREMIER.md`
3. `03_PHASE3_CONSENSUS_CONVERGENCE/00_LIRE_EN_PREMIER.md`
4. `04_PHASE4_CONTRATS_MEDICAUX/00_LIRE_EN_PREMIER.md`
5. `05_PHASE5_RELAIS_TRANSACTIONNEL/00_LIRE_EN_PREMIER.md`
6. `06_PHASE6_LIVENESS_POA/00_LIRE_EN_PREMIER.md`
7. `07_PHASE7_IPFS_DISTRIBUE/00_LIRE_EN_PREMIER.md`
8. `08_PHASE8_BENCHMARKS/00_LIRE_EN_PREMIER.md`

## Différence entre `docs/` et `results/`

- `docs/` contient la documentation de référence du projet : procédures, décisions d'architecture, analyses et plans de test.
- `results/` contient les preuves, sorties brutes, résumés d'exécution et manifestes d'intégrité.
- Le dossier complet de la Phase 8 est disponible séparément ici :
  `../results/phase8-dossier-complet-2026-09-16/`
- Son index est :
  `../results/phase8-dossier-complet-2026-09-16/00_INDEX_DOSSIER_COMPLET_PHASE8.md`

## Règles de nommage appliquées

- préfixe numérique pour l'ordre de lecture ;
- numéro de phase explicite ;
- sujet fonctionnel en majuscules et séparé par `_` ;
- date conservée lorsque le document décrit un état daté ;
- aucun document supprimé : les fichiers existants ont été déplacés et renommés uniquement pour clarifier l'organisation.
