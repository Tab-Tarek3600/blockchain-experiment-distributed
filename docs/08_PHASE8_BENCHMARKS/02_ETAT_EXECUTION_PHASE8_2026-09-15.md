# Phase 8 — état d'exécution des étapes au 15 septembre 2026

Ce document synthétise les résultats réellement disponibles. Il distingue les
étapes validées, les réserves méthodologiques et les tests qui restent à faire.
Les valeurs ne doivent pas être remplacées par des estimations.

## 1. Matrice de statut

| Étape | Objet | Statut | Résultat ou réserve |
|---|---|---|---|
| B0 | environnement et reproductibilité | **Validé avec réserve** | Trois VMs VMware accessibles, code et configuration cohérents, port 9001 actif ; horloges non synchronisées |
| B1-DSA | ML-DSA-44 | **Validé avec réserve** | Tailles et latences mesurées sur les trois VMs ; variabilité CPU inter-VM documentée |
| B1-KEM | ML-KEM-768 + AES-256-GCM | **Validé avec réserve** | Contrôles de confidentialité positifs ; mesure hors chaîne, non incluse dans le TPS blockchain |
| B2 | baseline blockchain | **Première passe validée** | De 0,1 à 1 tx/s sans perte observée ; à 2 tx/s, 119/120 incluses sur deux essais indépendants |
| B3-3 | surcharge à 3 tx/s, 1 client | **Exécuté et analysé** | 121/180 incluses sur les trois nœuds ; 0 rejet explicite ; convergence du tip h116 |
| B3-N | concurrence par nombre de clients | **Exécuté et analysé** | Série à 1, 2, 4 et 8 clients logiques, taux total constant à 1 tx/s : 60/60 incluses sur les trois nœuds dans chaque run ; p50 node1 296,18 → 364,07 → 729,07 → 1 028,45 ms ; convergence inter-VM numérique non mesurée |
| B4 | latence inclusion/commit/convergence | **Exécuté et analysé** | `b4-rate-1p0-20260915` : 60/60 incluses sur les trois nœuds à 1 tx/s ; p50 node1 260,47 ms, p95 393,17 ms ; convergence numérique inter-VM non mesurée |
| B5 | crash et reprise | **Exécuté et analysé avec réserve** | node3 arrêté puis redémarré ; 12/12 incluses sur les trois nœuds ; rattrapage jusqu’à h11 ; mesure précise du failover partielle |
| B6 | délai/perte réseau | **Exécuté, analysé et clôturé** | `b6-delay50ms-20260915` : 12/12 acceptées et incluses à 0,2 tx/s sous `50 ms ± 10 ms`, sans perte ajoutée ; node1 p50 300,73 ms, p95 438,50 ms ; `tc-netem` supprimé et vérifié sur les trois VMs, puis nœuds arrêtés |
| B7 | profil des trois VMs | **Exécuté et analysé** | `b7-profile-1p0-20260915` : 60/60 incluses sur les trois nœuds, 0 rejet explicite, convergence et zéro doublon ; processus Python ~99,8 % CPU et ~49 MiB RSS par VM ; nœuds arrêtés et port `9001` fermé après le run ; aucune comparaison physique/VM possible |
| B8 | EVM/API/IPFS par couche | **Partiel** | Fonctionnalité contrats/IPFS démontrée ; campagne de performance par couche à compléter |

## 2. Résultat de B3 à 3 tx/s

Run : `b3-rate-3p0-20260915`

```text
clients logiques             : 1
fenêtre de soumission        : 60 s
taux offert                  : 3 tx/s
transactions théoriques     : 180
transactions soumises       : 180
acceptations node1           : 121
rejets explicites node1     : 0
incluses sur les 3 nœuds    : 121
non observées/non incluses  : 59
taux de succès               : 67.2222 %
TPS commis sur T2            : 2.0166666667 tx/s
hauteur finale               : 116 sur node1/node2/node3
convergence contenu          : oui
```

Le générateur définit `submitted` après une écriture `sendall()` vers node1 ;
il n'attend pas un accusé applicatif individuel. Les 59 transactions sans
`BENCHMARK_ACCEPT` et sans `BENCHMARK_REJECT` sont donc **non observées/non
commises**, et non explicitement rejetées.

La hauteur `116` est une hauteur de bloc. Les lignes `BENCHMARK_COMMIT`
correspondent à 116 blocs ; l'analyse des blocs compte 121 transactions
incluses. Le bloc h113 contient notamment deux transactions.

Le contrôle direct des journaux a maintenant été exécuté et archivé :

```text
                 commit_events   sum_tx_count   accepts   rejects
node1                    116            121        121         0
node2                    116            121        121         0
node3                    116            121        121         0
```

Ainsi, la somme explicite des champs `tx_count` vaut `121` sur les trois
journaux et réconcilie `included_on_all_three=121`. Les blocs multi-transactions
sont h17, h54, h93, h105 et h113, chacun avec `tx_count=2`. Les trois nœuds ont
le même hash de bloc et la même racine d'état au tip observé, puis node2 et node3
indiquent `mempool=0`. La preuve détaillée est dans
`results/raw_data/b3-rate-3p0-20260915-commit-audit.md` et le résultat machine
dans `results/raw_data/b3-rate-3p0-20260915-commit-audit.json`.

## 3. Résultat B7 — profil de ressources

Le run `b7-profile-1p0-20260915` a été exécuté avec un client logique à `1 tx/s`
pendant `60 s`, un payload synthétique nul et node1 comme seul ingress. Le
manifeste et le résumé JSON sont valides. Les `60/60` transactions sont
présentes sur node1, node2 et node3, sans rejet explicite, erreur de charge ni
doublon ; la convergence des trois chaînes est indiquée comme positive dans le
résumé.

La collecte de ressources couvre `120` échantillons `vmstat` par VM et `120`
échantillons par groupe `pidstat` (CPU, RSS et disque). Le processus Python
consomme en moyenne environ `99,8 %` CPU et `49 MiB` RSS sur chaque VM. La
mémoire globale reste stable, le swap reste nul et l'attente I/O est nulle.
Les deltas réseau observés sur la fenêtre sont de `17 644 B` sur node1,
`16 910 B` sur node2 et `17 024 B` sur node3, sans erreur ni perte. `du -sh`
reste à `3,5M` par nœud, ce qui ne permet pas de mesurer une petite croissance
à cette résolution ; les 182 blocs existants n'ont pas été supprimés.

La note d'analyse est `results/raw_data/b7-profile-1p0-20260915-analysis-note.md`.
La latence numérique de convergence inter-VM n'est pas déduite et le résultat
ne constitue pas une capacité maximale ni une comparaison physique/VM.

## 4. Documents de preuve

- Fiche opérationnelle B7 :
  `results/raw_data/phase8-b7-resource-profile-run-sheet-2026-09-15.md`
- Note d'analyse B7 :
  `results/raw_data/b7-profile-1p0-20260915-analysis-note.md`
- Manifeste B7 :
  `results/raw_data/b7-profile-1p0-20260915-node1-manifest.json`
- Résumé machine B7 :
  `results/raw_data/b7-profile-1p0-20260915-summary.json`

- Protocole et résultat B3 :
  `results/raw_data/phase8-b3-run-sheet-2026-09-14.md`
- Note d'analyse détaillée :
  `results/raw_data/b3-rate-3p0-20260915-analysis-note.md`
- Manifeste :
  `results/raw_data/b3-rate-3p0-20260915-node1-manifest.json`
- Résumé machine :
  `results/raw_data/b3-rate-3p0-20260915-summary.json`
- Protocole général : `docs/08_PHASE8_BENCHMARKS/01_PLAN_TESTS_BENCHMARKS.md`

## 5. Prochaine étape recommandée

### 5.1 Contrôle immédiat avant de changer de test — effectué

Le contrôle a été exécuté sur les journaux réellement récupérés pour le run
`b3-rate-3p0-20260915`, puis archivé depuis la machine de développement. Il
additionne directement le champ `tx_count` de chaque ligne
`BENCHMARK_COMMIT`.

```text
                 commit_events   sum_tx_count   accepts   rejects
node1                    116            121        121         0
node2                    116            121        121         0
node3                    116            121        121         0
```

Résultat : **PASS**. Les trois sommes `sum_tx_count=121` concordent avec
`included_on_all_three=121`. Les 116 événements sont bien des blocs ; ils ne
doivent pas être comptés comme 116 transactions. Le contrôle est détaillé dans
`results/raw_data/b3-rate-3p0-20260915-commit-audit.md` et
`results/raw_data/b3-rate-3p0-20260915-commit-audit.json`.

### 4.2 B4 — latence d'inclusion, commit local et convergence

Le run `b4-rate-1p0-20260915` a été exécuté puis analysé depuis la machine de
développement. Avec un client à `1 tx/s` pendant `60 s`, payload synthétique nul
et drain de `300 s`, les `60/60` transactions ont été incluses sur les trois
nœuds. La médiane d'inclusion/commit observée sur node1 est de `260,47 ms`, le
p95 de `393,17 ms` et le maximum de `5,51 s`. Il n'y a eu ni transaction
manquante ni doublon.

Les trois chaînes ont convergé à la hauteur `56`, avec le même `block_hash` et
le même `state_root`. La latence numérique de convergence inter-VM reste
`not_measured`, car les horloges des VMs n'ont pas fait l'objet d'une
synchronisation indépendante. La note complète est dans
`results/raw_data/b4-rate-1p0-20260915-analysis-note.md` et le résumé machine
dans `results/raw_data/b4-rate-1p0-20260915-summary.json`.

Le run B5 `b5-secondary-crash-20260915` a maintenant été exécuté et analysé.
Node3 a été arrêté puis redémarré ; les 12 transactions ont finalement été
incluses sur les trois nœuds et les chaînes ont convergé à la hauteur 11. Le
résultat est fonctionnellement positif, mais le timestamp exact du crash et le
proposant actif au moment de l’arrêt ne sont pas entièrement instrumentés. La
note est `results/raw_data/b5-secondary-crash-20260915-analysis-note.md`.

Le run B6 `b6-delay50ms-20260915` a été exécuté puis analysé depuis la machine
de développement. Avec un client à `0,2 tx/s` pendant `60 s`, un délai
`50 ms ± 10 ms` et aucune perte ajoutée, les `12/12` transactions ont été
acceptées et incluses sur les trois nœuds, sans doublon observé. La latence
locale node1 soumission → commit est de `300,73 ms` en médiane, `438,50 ms` au
p95 et `470,72 ms` au maximum. Les trois tips convergent à la hauteur `12` vers
le même `block_hash` et le même `state_root`. Les mesures acceptation → commit
sur chaque VM restent locales et ne sont pas des latences end-to-end
inter-VM. Le résultat est fonctionnellement positif pour ce point exploratoire ;
la note et le résumé sont
`results/raw_data/b6-delay50ms-20260915-analysis-note.md` et
`results/raw_data/b6-delay50ms-20260915-summary.json`.

La clôture opérationnelle de B6 est maintenant acquise : les trois sorties
post-run `tc qdisc show` ont été archivées, aucune ne contient `qdisc netem`, et
la qdisc par défaut observée est `fq_codel` sur `ens33`. Les trois nœuds ont
ensuite été arrêtés. La latence numérique de convergence inter-VM n'est pas
publiée sans synchronisation indépendante des horloges. Le point B3-N concurrence a ensuite été exécuté à taux total constant
`1 tx/s`, avec `1`, `2`, `4` et `8` clients logiques sur node1. Les quatre runs
ont inclus `60/60` transactions sur les trois nœuds, sans doublon ni rejet
explicite ; la latence node1 p50 augmente de `296,18 ms` à `1 028,45 ms` et le
p95 de `391,74 ms` à `1 941,10 ms`. Cette hausse est observée sur une série
exploratoire de clients logiques, sans constituer une mesure multi-machines ni
une latence de convergence inter-VM. La note est
`results/raw_data/b3-client-concurrency-20260915-analysis-note.md` et le
comparatif machine est `results/raw_data/b3-client-concurrency-20260915-comparison.json`.
