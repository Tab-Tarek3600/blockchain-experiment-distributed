# Analyse B5 — crash et reprise de node3

**Run ID :** `b5-secondary-crash-20260915`  
**Date :** 15 septembre 2026  
**Statut :** **PASS fonctionnel avec réserve instrumentale**  
**Scénario observé :** arrêt de node3, redémarrage, rattrapage et convergence

## 1. Résultat principal

L’analyse produite depuis la machine de développement donne :

```text
submitted                         : 12
included_on_all_three             : 12
success_rate_all_three            : 100 %
committed TPS over submission T2 : 0,2 tx/s
converged_to_min_tip              : true
```

Les 12 transactions synthétiques soumises par node1 ont finalement été
présentes sur les trois chaînes. Aucune transaction n’est manquante et aucun
doublon n’est signalé.

Le résultat est donc **positif pour la reprise et l’intégrité de la chaîne**
dans ce scénario exploratoire. Il ne constitue pas une mesure complète d’un
failover, car le timestamp exact du `kill -9`, le nombre de timeouts et le
proposant actif au moment précis de l’arrêt ne sont pas tous instrumentés dans
le résumé fourni.

## 2. Paramètres et périmètre

| Paramètre | Valeur |
|---|---:|
| Nœud arrêté | node3 |
| Ingress | node1 uniquement |
| Taux offert | 0,2 tx/s |
| Durée de soumission | 60 s |
| Transactions soumises | 12 |
| Payload | 0 octet, données synthétiques contrôlées |
| Drain | 300 s |
| Perturbation réseau volontaire | aucune ; seul le crash de node3 |
| Méthode d’arrêt | processus node3 arrêté puis redémarré |

Le chemin expérimental reste `client/médecin → node1 → diffusion P2P`. Aucune
requête directe aux trois nœuds n’a été utilisée comme ingress.

## 3. Preuve de crash et de reprise dans le journal de node3

L’extrait de journal fourni montre la séquence suivante :

1. node3 démarre à `14:17:55` à la hauteur 0 et se connecte à node1 et node2 ;
2. avant l’arrêt, node3 accepte et commite les transactions jusqu’à la
   hauteur 7 ;
3. node3 redémarre à `14:19:27` avec une chaîne locale à la hauteur 7 ;
4. après le redémarrage, il reçoit/commite la suite jusqu’à la hauteur 11 ;
5. à `14:19:32`, il indique `height=11`, `mempool=0` et deux pairs connectés.

Le bloc de hauteur 8 contient deux transactions ; les blocs 1–7 et 9–11
contiennent chacun une transaction. Les 12 transactions sont donc réparties
dans 11 blocs de benchmark.

Le dernier événement avant le redémarrage observé dans l’extrait est le statut
`height=7` à `14:18:46`, et le redémarrage apparaît à `14:19:27`, soit un
intervalle observé d’environ 41 secondes. Cet intervalle ne doit pas être
publié comme un temps exact de panne : il inclut le délai entre le crash, sa
détection et la commande de redémarrage. Un fichier marqueur contenant l’heure
exacte du `kill` serait nécessaire pour mesurer séparément la durée d’arrêt.

Le journal montre ensuite un démarrage supplémentaire à `14:20:44` à la hauteur
11. Il ne faut pas l’interpréter comme une nouvelle panne sans le marqueur
correspondant ; il peut s’agir d’un redémarrage/arrêt de collecte.

## 4. Intégrité finale

Les trois nœuds terminent à la même hauteur et avec les mêmes valeurs :

| Nœud | Hauteur | Hash final | Racine d’état |
|---|---:|---|---|
| node1 | 11 | `700746abc669dec92a11fe3ac360b183dfe822a90e753559d11155829969cd94` | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` |
| node2 | 11 | `700746abc669dec92a11fe3ac360b183dfe822a90e753559d11155829969cd94` | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` |
| node3 | 11 | `700746abc669dec92a11fe3ac360b183dfe822a90e753559d11155829969cd94` | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` |

Contrôles du résumé :

- toutes les transactions soumises sont présentes sur les trois nœuds ;
- aucun doublon de transaction ;
- aucun fichier de bloc invalide ;
- préfixe commun jusqu’à la hauteur 11 ;
- mempool final observé vide dans le journal de node3.

Cette convergence est une convergence de contenu après reprise. Elle ne doit
pas être décrite comme une finalité BFT ou comme une preuve de tolérance aux
pannes Byzantine.

## 5. Acceptation et latence

Les événements d’acceptation locaux ne sont pas identiques entre les nœuds,
ce qui est attendu après un crash :

| Nœud | Acceptations observées | Rejets observés | Interprétation |
|---|---:|---:|---|
| node1 | 12 | 0 | journal complet côté ingress |
| node2 | 12 | 0 | journal complet côté pair resté actif |
| node3 | 7 | 0 | événements avant l’arrêt ; les transactions restantes sont retrouvées/commitées après reprise |

Il ne faut pas interpréter les 5 événements d’acceptation absents de node3
comme 5 rejets. Le résumé de la chaîne montre au contraire que les 12
transactions ont finalement été incluses sur node3.

### Latence observée depuis node1

Pour les 12 transactions, la latence entre la soumission et le commit observé
sur node1 est :

| Mesure | Valeur |
|---|---:|
| Minimum | 18,41 ms |
| Médiane (p50) | 218,35 ms |
| p95 | 5 018,29 ms |
| Maximum | 5 094,84 ms |

La queue de latence autour de 5 secondes est compatible avec une perturbation
liée au crash et/ou à un changement de tour, mais le journal fourni ne permet
pas d’attribuer cette cause avec certitude. Cette queue doit rester dans le
résultat et constitue précisément l’effet de panne à analyser.

Les durées locales acceptation → commit sont disponibles pour node1 et node2,
mais elles incluent elles aussi des valeurs proches de 5 s :

| Nœud | Observations locales | p50 | p95 | Maximum |
|---|---:|---:|---:|---:|
| node1 | 12 | 212,33 ms | 5 017,30 ms | 5 094,24 ms |
| node2 | 12 | 135,73 ms | 5 021,43 ms | 5 099,56 ms |
| node3 | 7 | 184,78 ms | 219,82 ms | 247,54 ms |

Les valeurs de node3 ne portent que sur les sept événements enregistrés avant
le crash ; elles ne représentent donc pas la latence de reprise pour les 12
transactions. Comme pour B4, la latence numérique de convergence inter-VM est
`not_measured` sans synchronisation indépendante des horloges.

## 6. Conclusion scientifique

Formulation recommandée :

> Dans un scénario de crash d’un validateur, node3 a été arrêté puis redémarré
> pendant une charge synthétique de 0,2 transaction par seconde. Les 12
> transactions soumises via node1 ont finalement été incluses sur les trois
> nœuds. Après redémarrage à la hauteur 7, node3 a rattrapé la chaîne jusqu’à
> la hauteur 11 et les trois nœuds ont convergé vers le même hash de bloc et la
> même racine d’état. La campagne met en évidence une queue de latence allant
> jusqu’à environ 5,1 s, mais ne fournit pas encore un horodatage indépendant
> permettant de séparer précisément la durée du crash, le timeout de round et
> le temps de rattrapage.

La campagne B5 peut être classée **réussie pour l’intégrité et la reprise
fonctionnelle**, avec une réserve sur la mesure précise du temps de failover.
Le résultat doit être nommé « crash/reprise de node3 » tant que les journaux
node1/node2 ne prouvent pas que node3 était exactement le proposant au moment
de l’arrêt. Il ne faut pas utiliser le terme « panne secondaire » sans cette
vérification.

## 7. Fichiers associés

- Résumé machine : `results/raw_data/b5-secondary-crash-20260915-summary.json`
- Note d’analyse : `results/raw_data/b5-secondary-crash-20260915-analysis-note.md`
- Fiche de commandes B5 : `results/raw_data/phase8-b5-run-sheet-2026-09-15.md`
