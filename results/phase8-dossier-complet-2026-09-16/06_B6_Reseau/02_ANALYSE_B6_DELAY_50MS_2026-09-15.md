# Analyse B6 — délai réseau contrôlé `50 ms ± 10 ms`

**Run ID :** `b6-delay50ms-20260915`  
**Date :** 15 septembre 2026  
**Statut analytique :** **résultat fonctionnel positif ; B6 clôturé opérationnellement après nettoyage vérifié de `tc-netem`**  
**Scénario :** délai `50 ms ± 10 ms`, sans perte de paquets

## 1. Source et portée

Cette note archive le JSON complet fourni depuis la machine de développement
après l'exécution de `scripts/experiments/analyze_b2_baseline.py`. Les deux
blocs JSON reçus étaient identiques ; ils sont traités comme une seule source.
Le JSON complet confirme les compteurs d'acceptation, les contrôles de doublons
et les latences locales détaillées. Les sorties post-run `ssh -tt` ont ensuite
été fournies et archivées dans
`results/raw_data/b6-delay50ms-20260915-qdisc-cleanup.txt`.

Le scénario conserve le chemin expérimental :

```text
client/médecin → node1 → diffusion P2P vers node2 et node3
```

Aucune donnée médicale réelle n'est utilisée.

## 2. Paramètres du run

| Paramètre | Valeur |
|---|---:|
| Clients logiques | 1 |
| Nœud d'entrée | node1 uniquement |
| Taux offert | 0,2 tx/s |
| Durée de soumission | 60 s |
| Transactions attendues/soumises | 12 |
| Payload | 0 octet, données synthétiques contrôlées |
| Délai réseau | `50 ms ± 10 ms` via `tc-netem` |
| Perte de paquets | aucune ajoutée dans ce run |
| Nœuds observés | node1, node2, node3 |
| Définition du TPS | transactions incluses sur les trois chaînes / fenêtre de soumission |

## 3. Résultat principal

La sortie d'analyse complète donne :

```text
run_id                         : b6-delay50ms-20260915
submitted                      : 12
accepted node1                 : 12
rejected node1                 : 0
accepted node2                 : 12
rejected node2                 : 0
accepted node3                 : 12
rejected node3                 : 0
included_on_all_three          : 12
success_rate_all_three         : 1.0 (100 %)
committed_tps                  : 0.2 tx/s
converged_to_min_tip           : true
benchmark duplicates           : 0 sur chaque nœud
```

Les 12 transactions soumises pendant la fenêtre de 60 secondes ont donc été
acceptées localement, retrouvées sur les trois copies persistées de la chaîne
et ne présentent aucun doublon selon les contrôles du JSON. Le point
expérimental n'a pas introduit de perte de paquets ; il isole le retard et sa
gigue configurés.

Ce résultat montre une conservation fonctionnelle de l'intégrité à **0,2 tx/s**
sous ce profil de délai pour ce run exploratoire. Il ne permet pas de conclure
sur la capacité maximale, le comportement sous perte, ni la latence de
convergence numérique entre VMs.

## 4. Intégrité et convergence finale

Les trois nœuds terminent avec les mêmes valeurs observées :

| Nœud | Hauteur | Hash du bloc final | Racine d'état | `transaction_count` affiché |
|---|---:|---|---|---:|
| node1 | 12 | `208956f7d2e3cbf3f4d3f7183aa15727d4a0894551c582fb5dc5ae51a8a33cb3` | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` | 1 |
| node2 | 12 | `208956f7d2e3cbf3f4d3f7183aa15727d4a0894551c582fb5dc5ae51a8a33cb3` | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` | 1 |
| node3 | 12 | `208956f7d2e3cbf3f4d3f7183aa15727d4a0894551c582fb5dc5ae51a8a33cb3` | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` | 1 |

La hauteur `12` est une hauteur de bloc ; elle ne doit pas être assimilée à
12 blocs contenant chacun une transaction. Le champ `transaction_count=1`
correspond au tip affiché dans le résumé et ne remplace pas le comptage global
des 12 transactions du benchmark.

La convergence de contenu est positive (`converged_to_min_tip=true`). Comme
pour B4 et B5, elle doit être décrite comme une convergence observée du PoA,
non comme un certificat de finalité BFT explicite.

### 4.1 Latences mesurées et limite d'interprétation

Le JSON complet fournit une mesure locale node1 calculée entre la soumission du
manifeste et l'événement `BENCHMARK_COMMIT` :

| Mesure | n | min (ms) | p50 (ms) | p95 (ms) | max (ms) |
|---|---:|---:|---:|---:|---:|
| soumission → commit/inclusion observé sur node1 | 12 | 118,99 | 300,73 | 438,50 | 470,72 |
| acceptation locale → commit node1 | 12 | 103,84 | 278,15 | 427,39 | 448,39 |
| acceptation locale → commit node2 | 12 | 90,89 | 216,85 | 302,33 | 333,62 |
| acceptation locale → commit node3 | 12 | 113,21 | 208,84 | 331,31 | 355,43 |

La première ligne est la latence d'inclusion/commit observable depuis node1
avec le timestamp du générateur ; elle ne doit pas être appelée latence de
convergence. Les trois lignes d'acceptation locale sont des durées calculées
avec des événements du même nœud et sont explicitement **non end-to-end**.
Elles ne permettent pas de comparer le temps de commit de node2 ou node3 à
node1, car les horloges des VMs ne sont pas indépendamment synchronisées.
La latence inter-VM de convergence reste donc `not_measured`.

Le champ `node1_local_file_observation` est également présent dans le JSON
(min `163,58 ms`, p50 `25,00 s`, p95 `50,00 s`, maximum `54,99 s`). Il est
conservé comme observation technique séparée, mais ne doit pas être publié
comme une latence blockchain end-to-end : ses échantillons suivent la cadence
d'observation du fichier local et non l'événement de commit distribué.

## 5. Ce qui est et n'est pas démontré

### Démontré par ce run

- le chemin d'entrée reste node1 seul puis diffusion P2P ;
- 12/12 transactions sont acceptées et présentes sur les trois nœuds ;
- aucun rejet direct et aucun doublon ne sont observés dans le JSON complet ;
- le taux de succès défini par inclusion sur les trois chaînes vaut 100 % ;
- le débit commis sur la fenêtre de soumission vaut 0,2 tx/s ;
- la latence locale node1 soumission → commit est mesurée : p50 300,73 ms,
  p95 438,50 ms, maximum 470,72 ms ;
- les trois tips observés ont le même hash et la même racine d'état ;
- aucune perte de paquets n'a été ajoutée dans ce scénario.

### Non démontré par la sortie fournie

- une latence de convergence inter-VM comparable entre node1, node2 et node3 ;
- une latence end-to-end distante pour node2 et node3 ;
- une campagne statistique avec répétitions ;
- le comportement sous perte de paquets ;
- une finalité BFT ou une tolérance Byzantine.

Ces absences ne remettent pas en cause le résultat fonctionnel résumé, mais elles
interdisent d'ajouter des valeurs non présentes dans les artefacts fournis.

## 6. Nettoyage de `tc-netem` — vérifié

Les trois commandes de suppression ont été exécutées avec `ssh -tt` après le
test. L'interface détectée est `ens33` sur chaque VM. Les sorties
`qdisc_after` sont les suivantes :

| Nœud | Interface | Qdisc après suppression | `qdisc netem` présent |
|---|---|---|---|
| node1 `192.168.168.101` | `ens33` | `fq_codel` | non |
| node2 `192.168.168.102` | `ens33` | `fq_codel` | non |
| node3 `192.168.168.103` | `ens33` | `fq_codel` | non |

Le critère de nettoyage est donc satisfait : aucune des trois sorties ne
contient `qdisc netem`. Selon la confirmation fournie, les trois nœuds ont été
arrêtés après le test et le nettoyage. La preuve est archivée dans
`results/raw_data/b6-delay50ms-20260915-qdisc-cleanup.txt`.

## 7. Conclusion scientifique recommandée

> Sous un délai réseau configuré à 50 ms avec une gigue de 10 ms, sans perte de
> paquets et à une charge offerte de 0,2 transaction par seconde, les 12
> transactions synthétiques soumises via node1 ont été acceptées et incluses sur
> les trois nœuds, sans doublon observé. La latence locale node1 entre la
> soumission et l'événement de commit présente une médiane de 300,73 ms, un p95
> de 438,50 ms et un maximum de 470,72 ms. Les trois copies observées convergent
> à la hauteur 12 vers le même hash de bloc et la même racine d'état. Ce résultat
> est un point fonctionnel exploratoire de robustesse au délai ; il ne constitue
> ni une mesure de capacité maximale, ni une mesure de perte, ni une preuve de
> finalité BFT. Les mesures locales d'acceptation → commit des VMs ne sont pas
> des latences end-to-end inter-VM. Le nettoyage opérationnel est vérifié :
> `tc qdisc show` n'affiche plus `qdisc netem` sur node1, node2 et node3 ; les
> nœuds ont ensuite été arrêtés.

## 8. Fichiers associés

- Résumé archivé : `results/raw_data/b6-delay50ms-20260915-summary.json`
- Note d'analyse : `results/raw_data/b6-delay50ms-20260915-analysis-note.md`
- Preuve du nettoyage `tc` : `results/raw_data/b6-delay50ms-20260915-qdisc-cleanup.txt`
- Fiche de commandes : `results/raw_data/phase8-b6-run-sheet-2026-09-15.md`
- Manifeste attendu : `results/raw_data/b6-delay50ms-20260915-node1-manifest.json`
- Journaux attendus : `results/raw_data/b6-delay50ms-20260915-node1.log`,
  `results/raw_data/b6-delay50ms-20260915-node2.log` et
  `results/raw_data/b6-delay50ms-20260915-node3.log`
