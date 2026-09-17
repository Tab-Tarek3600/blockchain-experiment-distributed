# Dossier complet — Phase 8

**Date de consolidation :** 16 septembre 2026  
**Périmètre :** Phase 8 complète, des fondations jusqu'à B8-C  
**Sous-phases incluses :** fondations, B2, B3/B3-N, B4, B5, B6, B7, B8-A, B8-B et B8-C  
**Répertoire source :** `results/raw_data/`  
**Répertoire consolidé :** `results/phase8-dossier-complet-2026-09-16/`

## 1. Vue d'ensemble

Ce dossier rassemble les procédures, interprétations, résultats JSON, journaux,
audits et preuves disponibles pour **toute la Phase 8**, et pas uniquement pour
B8.

Les fichiers ont été copiés et renommés avec une convention explicite. Les
originaux restent conservés dans `results/raw_data/`.

## 2. Statut et interprétation par étape

### Fondations Phase 8

Les étapes d'environnement, ML-DSA-44, ML-KEM-768/AES-GCM et la baseline B2
sont regroupées dans `01_Fondations/`. Les résultats cryptographiques et les
procédures d'environnement sont conservés avec leurs fichiers JSON bruts.

### B2 — baseline de débit

La première passe retient `2 tx/s` comme zone de saturation observée dans la
configuration expérimentale : les répétitions disponibles donnent `119/120`
transactions incluses sur les trois nœuds à ce taux. Cette conclusion ne doit
pas être présentée comme une capacité maximale universelle.

### B3 — charge et concurrence

- À `3 tx/s` avec un client logique : 180 transactions offertes, 121 incluses
  sur les trois nœuds, soit `67,2222 %` et environ `2,0167 tx/s` committées sur
  la fenêtre ; 59 transactions restent non observées/non incluses, pas
  explicitement rejetées.
- En concurrence B3-N à taux total constant de `1 tx/s` : 1, 2, 4 et 8 clients
  logiques conservent 60/60 transactions incluses sur les trois nœuds, tandis
  que la latence locale node1 augmente avec la concurrence.

### B4 — latence à 1 tx/s

**PASS pour le point expérimental B4.** Les 60 transactions sont incluses sur
les trois nœuds, sans doublon, avec un débit commis de `1 tx/s`. La médiane
soumission→commit observée sur node1 est de `260,47 ms`, le p95 de
`393,17 ms`, avec un maximum réel de `5 505,79 ms`. La latence numérique de
convergence inter-VM reste non mesurée faute de synchronisation indépendante
des horloges.

### B5 — crash et reprise

**PASS fonctionnel avec réserve instrumentale.** Après arrêt puis redémarrage
de node3, les 12 transactions sont finalement présentes sur les trois nœuds et
les chaînes convergent. La mesure exacte du failover n'est pas isolée, car le
marqueur temporel précis du `kill -9` n'est pas disponible.

### B6 — délai réseau contrôlé

**Résultat fonctionnel positif.** Avec `50 ms ± 10 ms`, sans perte de paquets et
à `0,2 tx/s`, les 12 transactions sont incluses sur les trois nœuds. Le
netem a été supprimé et vérifié après le test sur les trois VMs.

### B7 — profil de ressources

À `1 tx/s` pendant 60 secondes, les 60 transactions sont incluses sur les trois
nœuds. Le processus blockchain est fortement CPU-bound, autour de `99,8 %`
de CPU par nœud, avec environ `49 MiB` de RSS par processus. La mémoire globale
reste stable, le swap n'est pas utilisé et l'attente I/O est nulle. Il s'agit
d'un profil de ressources de trois VMs sous charge contrôlée, pas d'une capacité
maximale.

### B8-A — EVM locale

**PASS / exécuté et interprété.** 180 mesures locales couvrent six opérations
avec données synthétiques. Les opérations autorisées réussissent ;
`unauthorizedRegister` échoue comme attendu. La chaîne persistante n'est pas
modifiée et aucune VM n'est contactée. Ces mesures ne sont ni HTTP, ni API, ni
TPS blockchain distribué.

### B8-B — ingress TCP

Le chemin TCP avait déjà été testé dans les campagnes précédentes. Aucun run
`b8b-tcp-*` n'a été lancé comme nouvelle campagne dans cette clôture. La fiche
de décision est conservée dans `09_B8B_TCP/`.

### B8-C — IPFS distribué

**PASS / exécuté et interprété.** Les trois fournisseurs co-localisés sur
node1, node2 et node3 ont réussi les opérations de seed, réplication,
récupération, pinning et présence. Les deux ciphertexts synthétiques ont 128
octets ; CID et SHA-256 sont cohérents sur les trois nœuds. Les 24 séries de
30 mesures représentent 720 opérations, toutes réussies.

Le contrôle blockchain B8-C est une lecture de cohérence : hauteur `242` et
même `state_root` sur les trois nœuds, sans transaction soumise par B8-C. Le
lecteur historique `read_phase7_records.py` n'est pas applicable à la chaîne
actuelle, qui ne contient pas les anciennes transactions `registerRecord` de
Phase 7. Cette distinction est documentée dans les analyses B8-C.

## 3. Organisation du dossier

```text
00_INDEX_DOSSIER_COMPLET_PHASE8.md

01_Fondations/
├── environnement et runbook général ;
├── étapes ML-DSA-44 et ML-KEM-768/AES-GCM ;
├── baseline B2 ;
└── résultats JSON cryptographiques par nœud.

02_B2_Baseline/
├── analyses et procédures B2 ;
├── exécutions pilotes ;
└── résumés JSON et chaîne finale.

03_B3_Charge_Concurrence/
├── procédures B3/B3-N ;
├── analyses 3 tx/s et concurrence ;
├── comparaisons JSON ;
├── audits de commits ;
└── journaux des trois nœuds.

04_B4_Latence/
05_B5_Crash_Reprise/
06_B6_Reseau/
07_B7_Ressources/

08_B8A_EVM/
├── analyse ;
├── procédure ;
└── journal de résultats.

09_B8B_TCP/
└── décision de non-relance.

10_B8C_IPFS/
├── analyses et procédures ;
├── résultats JSON et journaux bruts ;
└── diagnostics séparés des résultats validés.

99_MANIFEST_SHA256.txt
```

## 4. Règles d'interprétation à conserver

- Une transaction soumise n'est pas automatiquement une transaction incluse.
- Une hauteur de bloc n'est pas un nombre de transactions.
- Les latences locales et les latences inter-VM doivent rester séparées.
- Une convergence de contenu observée ne constitue pas un certificat de
  finalité BFT.
- Les résultats à 0 octet de payload ne doivent pas être publiés comme un
  goodput en octets.
- Les tests cryptographiques et IPFS utilisent des données synthétiques ;
  aucune donnée médicale réelle n'est incluse.
- B8-B n'a pas été relancé conformément à la décision de périmètre.
- Aucune clé de validateur, configuration ou donnée persistante n'a été
  supprimée dans le cadre de cette consolidation.

## 5. Limites documentées

- La synchronisation indépendante des horloges des VMs n'est pas établie ; les
  latences numériques de convergence inter-VM ne sont donc pas publiées.
- B5 mesure une reprise fonctionnelle, mais pas un temps de failover précisément
  instrumenté.
- `memory.events` n'était pas disponible dans les pré-vérifications B8-C ;
  aucun OOM n'a cependant été observé dans les journaux noyau collectés.
- Le JSON brut B8-A mentionné dans l'analyse (`b8a-evm-contracts-20260916.json`)
  n'était pas présent dans le workspace partagé lors de la consolidation. Le
  journal et l'analyse disponibles sont inclus ; aucun fichier absent n'a été
  recréé artificiellement.

## 6. Fichiers à ouvrir en premier

1. `02_B2_Baseline/01_ANALYSE_RESULTATS_B2_2026-09-14.md`
2. `03_B3_Charge_Concurrence/04_ANALYSE_SURCHARGE_3TPS_2026-09-15.md`
3. `04_B4_Latence/02_ANALYSE_B4_LATENCE_2026-09-15.md`
4. `05_B5_Crash_Reprise/02_ANALYSE_B5_CRASH_REPRISE_2026-09-15.md`
5. `06_B6_Reseau/02_ANALYSE_B6_DELAY_50MS_2026-09-15.md`
6. `07_B7_Ressources/02_ANALYSE_B7_RESSOURCES_2026-09-15.md`
7. `08_B8A_EVM/01_ANALYSE_B8A_EVM_2026-09-16.md`
8. `10_B8C_IPFS/01_Analyses_et_procedures/01_ANALYSE_FINALE_B8C_IPFS_2026-09-16.md`

## 7. Traçabilité

Les documents de ce dossier sont des copies organisées des artefacts présents
dans `results/raw_data/`. Les fichiers sources n'ont pas été supprimés ni
modifiés.
