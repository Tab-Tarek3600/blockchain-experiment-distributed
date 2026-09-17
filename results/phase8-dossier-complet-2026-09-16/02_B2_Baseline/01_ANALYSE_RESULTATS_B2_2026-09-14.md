# B2 officielle — résultats de la première passe

**Date :** 14 septembre 2026  
**Scénario :** client/médecin synthétique → node1 → diffusion P2P → node2/node3  
**Conditions :** trois VMs, aucune perturbation `tc-netem`, aucun appel IPFS,
`--payload-size 0`, données synthétiques contrôlées.

## Décision opérationnelle

La répétition confirmatoire à `2 tx/s` reproduit exactement le résultat de la
première observation : `119/120` transactions sont incluses sur les trois
nœuds, avec convergence vers le tip minimal. La zone de saturation observée
est donc retenue à `2 tx/s` dans le mode contraint expérimental.

Cette conclusion ne signifie pas qu'une capacité maximale universelle de
`2 tx/s` est démontrée. Elle signifie que, dans la configuration actuelle et
avec le protocole de mesure retenu, deux essais indépendants à `2 tx/s` donnent
une perte de complétude d'une transaction sur 120 pendant la fenêtre et le
drain observés.

Le run à `5 tx/s` n'est pas lancé dans cette première passe : il n'est plus
nécessaire pour décider si `2 tx/s` constitue la zone de saturation observée.
Une charge supérieure pourra être étudiée dans B3 comme scénario de surcharge,
avec comptage explicite du backlog et des transactions non commises.

## Résultats retenus

| Run | Taux offert | Soumises | Incluses sur les 3 nœuds | Taux de succès | TPS commis |
|---|---:|---:|---:|---:|---:|
| r01 retry | 0,1 tx/s | 6 | 6 | 100 % | 0,0999998213 |
| r02 | 0,2 tx/s | 12 | 12 | 100 % | 0,1999989488 |
| r03 | 0,5 tx/s | 30 | 30 | 100 % | 0,4999990645 |
| r04 | 1 tx/s | 60 | 60 | 100 % | 0,9999980701 |
| r05 | 2 tx/s | 120 | 119 | 99,1667 % | 1,9833297340 |
| r05 rep02 | 2 tx/s | 120 | 119 | 99,1667 % | 1,9833291937 |

Les quatre premiers taux sont sans perte observée dans la première passe. Les
résultats détaillés du r05 original établissent en outre : zéro doublon sur
chaque copie, même préfixe de chaîne, même état final sur les trois nœuds et
aucun rejet explicite observé par node1 ; la transaction restante est donc
classée **non observée/non commise**, et non comme rejetée.

Pour la répétition `r05 rep02`, ce fichier conserve uniquement les champs du
résultat compact fourni après exécution. Les valeurs détaillées non présentes
dans cette sortie — acceptation node1, taille finale du mempool, hauteur,
`block_hash`, `state_root`, latences et liste des transactions — ne sont pas
reconstituées ici. Elles doivent rester celles des artefacts bruts copiés
depuis les VMs lorsqu'ils seront archivés.

## Goodput et latence

Les essais B2 utilisent `--payload-size 0` : le goodput en octets est donc nul.
Le TPS ci-dessus est exclusivement un débit de transactions commises. Les
latences détaillées publiées pour le r05 original restent celles observées sur
ses 119 transactions :

- node1 soumission→commit : p50 `262,372888 ms`, p95 `398,127479 ms`, max
  `1400,003797 ms` ;
- node1 acceptation→commit : p50 `236,503903 ms`, p95 `344,616031 ms`, max
  `380,779192 ms` ;
- node2 acceptation→commit : p50 `172,664963 ms`, p95 `291,813017 ms`, max
  `315,662961 ms` ;
- node3 acceptation→commit : p50 `170,708635 ms`, p95 `281,428817 ms`, max
  `315,232797 ms`.

La convergence temporelle inter-VM reste `not_measured`, car la synchronisation
indépendante des horloges n'est pas déclarée. `converged_to_min_tip=true`
signifie ici convergence de contenu observée, pas mesure temporelle de
finalité BFT.

## Portée de la clôture

Cette note clôture la **première passe opérationnelle B2** et autorise le
passage à B3. Elle ne doit pas être présentée comme cinq répétitions
statistiques par taux : cette campagne complète reste une extension possible si
l'analyse statistique l'exige. Aucun résultat ML-KEM/AES-GCM n'est intégré aux
TPS blockchain.

Le fichier compact de la répétition est conservé sous :

```text
results/raw_data/b2-official-r05-rep2-retry-2p0-20260914-summary.json
```

## Passage à B3 — mise à jour du 15 septembre 2026

Le point B3 à `3 tx/s` avec un client logique a ensuite été exécuté sous le
run `b3-rate-3p0-20260915`. Il confirme une surcharge plus nette que la zone
B2 à `2 tx/s` : `180` transactions offertes, `121` incluses sur les trois
nœuds, soit `67,2222 %` de présence et `2,0167 tx/s` committées sur la fenêtre
de soumission. Les `59` transactions restantes ne sont pas classées comme
rejets, car aucun `BENCHMARK_REJECT` n'a été enregistré.

Les trois nœuds ont convergé sur la hauteur `116`, avec le même `block_hash` et
le même `state_root`. Cette observation valide le contenu des transactions
incluses ; elle ne transforme pas le point B3 en capacité soutenue à 3 tx/s avec
100 % de succès.

La note détaillée du point B3 est :

```text
results/raw_data/b3-rate-3p0-20260915-analysis-note.md
```

Le prochain test recommandé est B4 à charge maîtrisée (`1` ou `2 tx/s`) pour
mesurer l'inclusion et la convergence sans augmenter immédiatement la charge
au-delà du point de surcharge déjà observé.
