# Contrôle direct des commits — B3 à 3 tx/s

**Run :** `b3-rate-3p0-20260915`  
**Contrôle exécuté :** 15 septembre 2026  
**Source :** journaux node1, node2 et node3 fournis après récupération des VMs  
**Méthode :** comptage des lignes `BENCHMARK_COMMIT` et addition directe de leur champ `tx_count`

## Résultat

| Nœud | Événements `BENCHMARK_COMMIT` | Somme `tx_count` | `BENCHMARK_ACCEPT` | `BENCHMARK_REJECT` | Identifiants dans les commits | Identifiants uniques |
|---|---:|---:|---:|---:|---:|---:|
| node1 | 116 | 121 | 121 | 0 | 121 | 121 |
| node2 | 116 | 121 | 121 | 0 | 121 | 121 |
| node3 | 116 | 121 | 121 | 0 | 121 | 121 |

**Statut de réconciliation : `PASS`.** La somme explicite `tx_count=121` est
obtenue sur les trois journaux et correspond à `included_on_all_three=121`.
Les événements de commit restent des événements de blocs : il y en a 116,
contre 121 transactions incluses.

Les blocs multi-transactions observés sont les hauteurs `17`, `54`, `93`, `105`
et `113`, chacun avec `tx_count=2`. Les 111 autres blocs de la hauteur 1 à 116
portent chacun une transaction, ce qui donne `111 + 5×2 = 121`.

Aucune ligne `BENCHMARK_COMMIT` n'est restée non analysée. Les 121 identifiants
présents dans les commits sont uniques dans chaque journal.

## Artefacts archivés

- `results/raw_data/b3-rate-3p0-20260915-node1.log`
- `results/raw_data/b3-rate-3p0-20260915-node2.log`
- `results/raw_data/b3-rate-3p0-20260915-node3.log`
- `results/raw_data/b3-rate-3p0-20260915-commit-audit.json`

Le JSON contient les tailles, empreintes SHA-256, provenance des pièces jointes
et les résultats par nœud. Les fichiers de journal sont des captures terminales
issues de la commande `cat`; la ligne initiale de commande n'est pas un événement
nœud et n'est pas comptée.

## Conclusion opérationnelle

Le contrôle restant avant de changer de test est satisfait. Le run B3 à 3 tx/s
est donc réconcilié sur les trois copies. Aucun nouveau benchmark ni redémarrage
de nœud n'a été effectué pendant ce contrôle. B4 peut maintenant être préparé
à charge maîtrisée, de préférence `1` ou `2 tx/s`, avec node1 comme seul ingress.
