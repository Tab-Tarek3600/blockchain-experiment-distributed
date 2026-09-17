# B3 — charge à 3 tx/s, un client logique

**Run :** `b3-rate-3p0-20260915`  
**Date d'exécution :** 15 septembre 2026  
**Scénario :** client logique → node1 → diffusion P2P → node2/node3  
**Entrée :** node1 uniquement  
**Clients logiques :** 1  
**Durée T2 :** 60 s  
**Taux offert demandé :** 3 tx/s  
**Payload :** 0 octet, transactions synthétiques contrôlées  
**Perturbation réseau :** aucune règle `tc-netem`  
**IPFS :** non inclus dans cette mesure

## 1. Artefacts utilisés

- Manifeste : `results/raw_data/b3-rate-3p0-20260915-node1-manifest.json`
- Résumé d'analyse : `results/raw_data/b3-rate-3p0-20260915-summary.json`
- Journaux node1, node2 et node3 collectés pour le run ;
- Répertoires de blocs copiés sur la machine de développement puis analysés
  localement avec `scripts/experiments/analyze_b2_baseline.py`.

L'analyse a été exécutée depuis le dépôt de développement. Aucun post-traitement
n'a été exécuté sur node1 et aucun nœud n'a été contacté par l'analyseur.

## 2. Résultats principaux

| Mesure | Résultat |
|---|---:|
| Transactions préconstruites | 180 |
| Transactions soumises par le générateur | 180 |
| `BENCHMARK_ACCEPT` node1 | 121 |
| `BENCHMARK_REJECT` node1 | 0 |
| Transactions incluses sur node1 | 121 |
| Transactions incluses sur node2 | 121 |
| Transactions incluses sur node3 | 121 |
| Transactions incluses sur les trois nœuds | 121 |
| Transactions non observées/incluses | 59 |
| Taux de succès sur les trois copies | 67,2222 % |
| Débit commis sur la fenêtre de soumission | 2,0166666667 tx/s |
| Doublons de transactions | 0 |
| Convergence vers la hauteur minimale | Oui |
| Hauteur finale observée | 116 |
| `local_observation_complete` | `false` |
| Erreurs du générateur | `[]` |

Le résumé machine produit par l'analyseur est :

```text
submitted                              : 180
included_on_all_three                  : 121
success_rate_all_three                 : 0.6722222222222223
committed_tps_all_three_over_submission_window : 2.0166666666666666
converged_to_min_tip                   : true
```

## 3. Convergence et hauteur

Les trois chaînes atteignent la hauteur `116`. La hauteur est une hauteur de
bloc, pas un nombre de transactions. Les lignes `BENCHMARK_COMMIT` correspondent
à 116 événements de blocs ; l'analyse des blocs compte 121 transactions
incluses. Au moins un bloc contient plusieurs transactions, notamment le bloc
h113 avec `tx_count=2`.

Le contrôle direct des journaux a été exécuté et archivé. Il donne, pour chaque
nœud :

```text
                 commit_events   sum_tx_count   accepts   rejects
node1                    116            121        121         0
node2                    116            121        121         0
node3                    116            121        121         0
```

Aucune ligne `BENCHMARK_COMMIT` n'est restée non analysée et les 121 identifiants
présents dans les commits sont uniques sur chaque nœud. Les blocs multi-
transactions sont h17, h54, h93, h105 et h113, chacun avec `tx_count=2`.

La somme explicite `sum_tx_count=121` réconcilie donc
`included_on_all_three=121`. Le résumé de l'analyse et le contrôle direct
mesurent la même quantité de transactions incluses, mais le contrôle conserve
séparément le nombre d'événements de commit (`116`), qui est le nombre de blocs.
La preuve complète est dans `b3-rate-3p0-20260915-commit-audit.md` et le
résultat machine dans `b3-rate-3p0-20260915-commit-audit.json`.

La comparaison du tip commun observé dans les journaux donne :

```text
height     : 116
block_hash : b3368dd94842f401d81b55887db68adb489c43eb655823568a90cfd343ad4176
state_root : 56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
tx_count   : 1
```

Le même `block_hash`, le même `state_root` et le même identifiant de transaction
ont été observés sur node1, node2 et node3 pour ce tip. Les statuts ultérieurs
montrent également `height=116` et `mempool=0` sur node2 et node3.

**Conclusion de convergence :** les 121 transactions qui ont été observées et
incluses sont cohérentes sur les trois nœuds. Le résultat ne montre pas de fork
ou de divergence de chaîne pour ce run.

## 4. Pourquoi 180 ne donne pas 180 transactions incluses

Le générateur calcule la charge offerte ainsi :

```text
3 tx/s × 60 s = 180 transactions préconstruites
```

Dans `benchmark_b3_clients.py`, une transaction est ajoutée au compteur
`submitted` après l'appel local `sendall()` sur la connexion TCP vers node1. Le
client n'attend pas un accusé de réception applicatif individuel pour chaque
transaction. Ainsi, `submitted` signifie **offerte/écrite par le générateur** ;
ce compteur ne prouve pas l'acceptation par le mempool, l'inclusion dans un
bloc ou la convergence sur les trois nœuds.

Les journaux fournissent ensuite 121 événements `BENCHMARK_ACCEPT` et aucun
`BENCHMARK_REJECT`. Les 59 transactions restantes ne disposent donc d'aucun
verdict blockchain explicite. Elles sont classées :

```text
non observées / non acceptées localement / non incluses
```

et non :

```text
rejetées
```

La réinitialisation de la connexion client à la fin de la fenêtre peut être
compatible avec la disparition des dernières requêtes, mais `Connection reset
by peer` ne suffit pas à déterminer à lui seul si chacune des 59 transactions a
été reçue, partiellement lue, ou jamais traitée par node1.

## 5. Interprétation des métriques

Le taux de succès publié est :

```text
121 / 180 = 0,6722222222 = 67,2222 %
```

Le débit commis publié par l'analyseur est calculé sur la fenêtre de soumission,
et non sur le temps total de drain :

```text
121 / 60 s = 2,0166666667 tx/s
```

Il s'agit d'un **débit commis observé dans cette configuration**, avec un client
logique et un payload nul. Ce n'est pas une capacité maximale universelle du
protocole et ce n'est pas un débit HTTP.

ML-KEM/AES-GCM n'est pas inclus dans cette valeur. Ces primitives ont été
mesurées séparément comme confidentialité hors chaîne. ML-DSA, en revanche,
reste dans le chemin de signature/vérification des transactions et des blocs.

## 6. Classement du run

Le run est retenu comme :

> **B3 — surcharge observée à 3 tx/s, avec convergence des 121 transactions
> effectivement incluses et complétude de soumission non atteinte pour les 59
> autres transactions.**

Il ne faut pas le présenter comme une validation de 180 transactions réussies,
ni comme une preuve de rejet de 59 transactions.

## 7. Limites à conserver dans l'article

- Les trois VMs sont virtualisées sous VMware ; node1 est le point d'entrée
  logique, pas une machine physique.
- Le temps de convergence inter-VM n'est pas publié comme latence numérique
  tant que les horloges des VMs ne sont pas synchronisées ou corrigées par une
  méthode d'accusé de réception.
- La finalité doit être appelée convergence applicative observée ; le réseau ne
  produit pas de certificat BFT explicite.
- Le run utilise un seul client logique ; il ne mesure pas encore la
  scalabilité par nombre de clients.
- Les 59 transactions non observées doivent rester dans le dénominateur du
  taux de succès, mais ne doivent pas être classées comme rejets explicites.

## 8. Décision pour la suite

Le point `3 tx/s` est documenté et exploitable comme point de surcharge B3. Le
prochain travail ne consiste pas à relancer immédiatement une charge supérieure
sans conserver les artefacts :

1. archiver ce manifeste, ce résumé, les journaux et les blocs associés ;
2. conserver la provenance du `data_dir` et des journaux pour chaque run ;
3. passer au test B4 de latence d'inclusion/commit/convergence à une charge
   maîtrisée, de préférence `1 tx/s` ou `2 tx/s` ;
4. ne lancer le point B3 à `5 tx/s` qu'après cette étape, avec le même contrôle
   de collecte et la même classification des transactions manquantes.
