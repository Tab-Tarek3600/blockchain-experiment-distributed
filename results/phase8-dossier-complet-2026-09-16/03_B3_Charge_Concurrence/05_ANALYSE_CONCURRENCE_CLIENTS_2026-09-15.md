# Analyse B3-N — concurrence par clients logiques

**Date :** 15 septembre 2026  
**Série :** `b3-client-01-1p0-20260915`, `b3-client-02-1p0-20260915`, `b3-client-04-1p0-20260915`, `b3-client-08-1p0-20260915`  
**Scénario :** flux logiques → node1 → diffusion P2P → node2/node3

## 1. Périmètre

La série fait varier le nombre de connexions clientes logiques sur node1,
mais garde constants le taux total offert (`1 tx/s`), la durée (`60 s`) et le
payload (`0 octet`, synthétique). Il ne s'agit pas d'une comparaison de quatre
machines clientes distinctes. Node1 reste le seul ingress dans tous les runs.

Les quatre résumés JSON reçus ont été archivés depuis les fichiers attachés :

- `results/raw_data/b3-client-01-1p0-20260915-summary.json`
- `results/raw_data/b3-client-02-1p0-20260915-summary.json`
- `results/raw_data/b3-client-04-1p0-20260915-summary.json`
- `results/raw_data/b3-client-08-1p0-20260915-summary.json`

Le tableau machine complet est dans
`results/raw_data/b3-client-concurrency-20260915-comparison.json`.

## 2. Résultats principaux

| Clients logiques | Soumises | Incluses sur les 3 nœuds | Succès | TPS commis | Node1 soumission → commit p50 | p95 | max | Hauteur tip |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 60 | 60 | 100 % | 1,0 | 296,18 ms | 391,74 ms | 440,35 ms | 72 |
| 2 | 60 | 60 | 100 % | 1,0 | 364,07 ms | 763,11 ms | 922,29 ms | 117 |
| 4 | 60 | 60 | 100 % | 1,0 | 729,07 ms | 1 206,47 ms | 1 562,64 ms | 150 |
| 8 | 60 | 60 | 100 % | 1,0 | 1 028,45 ms | 1 941,10 ms | 2 008,37 ms | 182 |

Pour les quatre runs :

- aucun rejet explicite n'est observé sur node1 ;
- aucun doublon n'est observé sur node1, node2 ou node3 ;
- les 60 transactions sont présentes sur les trois chaînes ;
- les trois nœuds convergent sur le préfixe observé ;
- `state_root` reste identique à la valeur contrôlée dans les résumés ;
- la latence numérique de convergence inter-VM reste `not_measured`.

## 3. Acceptation locale → commit

Ces durées sont calculées localement à chaque VM. Elles ne doivent pas être
présentées comme une latence end-to-end inter-VM.

| Clients | node1 p50 | node2 p50 | node3 p50 |
|---:|---:|---:|---:|
| 1 | 263,77 ms | 177,25 ms | 166,69 ms |
| 2 | 281,66 ms | 203,66 ms | 212,45 ms |
| 4 | 495,75 ms | 328,38 ms | 306,43 ms |
| 8 | 674,89 ms | 374,21 ms | 360,83 ms |

## 4. Interprétation

À taux total offert constant de `1 tx/s`, le débit commis reste à `1 tx/s` et
la complétude reste de 100 % jusqu'à 8 clients logiques dans cette série. En
revanche, la latence node1 augmente de manière monotone avec la concurrence :
le p50 passe de `296,18 ms` à 1 client à `1 028,45 ms` à 8 clients, tandis que
le p95 passe de `391,74 ms` à `1 941,10 ms`.

Ce résultat est compatible avec une augmentation de la file ou du coût de
planification/traitement lorsque plusieurs flux concurrents alimentent le même
node1, sans baisse du débit à cette charge offerte. Il s'agit d'une observation
exploratoire sur quatre runs, pas d'une limite universelle de l'architecture.

## 5. Limites conservées

- la série mesure des clients logiques exécutés sur node1, et non des machines
  clientes indépendantes ;
- les timestamps des VMs ne sont pas synchronisés ; les mesures distantes ne
  sont donc pas comparées numériquement comme des latences réseau ;
- les métriques CPU, mémoire, réseau et disque ne sont pas collectées dans
  B3-N ;
- la série n'inclut pas de répétitions statistiques indépendantes ;
- les runs ont été séquentiels sur la chaîne persistante, sans suppression de
  clés, de configurations ou de données existantes.

## 6. Conclusion recommandée

> À charge totale constante de 1 transaction par seconde, l'augmentation du
> nombre de clients logiques concurrents de 1 à 8, tous connectés à node1,
> conserve dans cette série une complétude de 100 %, un débit commis de
> 1 transaction par seconde et la convergence des trois copies. La latence
> locale node1 soumission → commit augmente toutefois de 296,18 ms de médiane
> avec 1 client à 1 028,45 ms avec 8 clients, et de 391,74 ms à 1 941,10 ms au
> p95. Le résultat montre un coût de concurrence observable à charge fixe, mais
> ne constitue ni une mesure avec plusieurs machines clientes, ni une mesure de
> capacité maximale, ni une mesure de convergence inter-VM synchronisée.
