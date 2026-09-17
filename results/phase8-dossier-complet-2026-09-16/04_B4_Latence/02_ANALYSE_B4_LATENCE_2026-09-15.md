# Analyse B4 — latence d’inclusion, commit et convergence

**Run ID :** `b4-rate-1p0-20260915`  
**Date :** 15 septembre 2026  
**Statut :** **PASS pour le point expérimental B4 à 1 tx/s**  
**Nature :** essai contrôlé exploratoire, un seul run

## 1. Source et périmètre

L’analyse utilise le résultat JSON joint par l’expérimentateur sous le nom
`((.venv) ) ismail@node3~blockchain-.txt`. Malgré son extension `.txt`, son
contenu est un résumé JSON cohérent du run `b4-rate-1p0-20260915`.

Paramètres du run :

| Paramètre | Valeur |
|---|---:|
| Clients logiques | 1 |
| Taux offert | 1 tx/s |
| Durée de mesure | 60 s |
| Transactions soumises | 60 |
| Payload | 0 octet, données synthétiques contrôlées |
| Ingress | node1 uniquement |
| Chemin | client/médecin → node1 → diffusion P2P |
| Nœuds observés | node1, node2, node3 |
| Perturbation réseau | aucune |
| Drain demandé | 300 s |

Aucune donnée médicale réelle n’est utilisée dans ce run.

## 2. Verdict principal

Le run est valide pour mesurer le comportement du réseau à **1 tx/s** dans les
conditions fixées :

| Indicateur | Résultat |
|---|---:|
| Transactions soumises | 60 |
| Incluses sur node1 | 60 |
| Incluses sur node2 | 60 |
| Incluses sur node3 | 60 |
| Incluses sur les trois nœuds | 60 |
| Transactions manquantes | 0 |
| Doublons | 0 sur chaque nœud |
| Rejets explicites observés sur node1 | 0 |
| Taux de succès défini par inclusion sur les trois chaînes | **100 %** |
| TPS commis sur la fenêtre de soumission | **1,00 tx/s** |

Le résultat démontre donc qu’à ce point de charge, les 60 transactions
synthétiques ont été acceptées/observées et persistées sur les trois copies de
la chaîne. Il ne démontre pas que 1 tx/s est la capacité maximale et ne doit
pas être extrapolé à une charge supérieure sans nouvelle campagne.

## 3. Intégrité et convergence du contenu

Les contrôles du résumé donnent :

- `all_submitted_present_on_all_three = true` ;
- `no_benchmark_transaction_duplicate_on_any_node = true` ;
- `three_node_chain_converged_to_min_tip = true` ;
- `load_files_valid = true` ;
- hauteur finale commune : `56` ;
- nombre de blocs persistés : `57` par nœud, genesis compris ;
- préfixe commun : hauteur `56` ;
- même `block_hash` final sur les trois nœuds :
  `fed7b6421e35e0d2c327c9d5ac40fba0e8e1a1be17b7bb5ce42dc15516a9b185` ;
- même `state_root` final sur les trois nœuds :
  `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421`.

Les 60 transactions de benchmark apparaissent aux mêmes hauteurs sur les trois
nœuds. Le bloc de hauteur 38 contient cinq transactions ; les autres blocs de
benchmark contiennent normalement une transaction. Il faut donc distinguer la
hauteur des blocs du nombre de transactions : une hauteur finale de 56 ne
signifie pas 56 transactions.

Cette convergence est une convergence de contenu observée par le protocole
PoA. Elle ne constitue pas un certificat de finalité BFT explicite, qui n’est
pas fourni par l’implémentation actuelle.

## 4. Latences mesurées

### 4.1 Inclusion/commit observé depuis node1

Pour les 60 transactions, le résumé mesure le temps entre `t_submit_wall_ns`
du manifeste et l’événement `BENCHMARK_COMMIT` observé sur node1 :

| Mesure | Latence |
|---|---:|
| Nombre d’observations | 60 |
| Minimum | 38,98 ms |
| Médiane (p50) | 260,47 ms |
| p95 | 393,17 ms |
| Maximum | 5 505,79 ms |

La médiane et le p95 indiquent une inclusion généralement sub-seconde dans ce
run. Le maximum à environ 5,5 s est une valeur extrême réelle du fichier et ne
doit pas être supprimée. Elle doit être conservée dans les résultats et
investiguée dans une campagne ultérieure (tour/timeout, charge système ou
ordonnancement), sans lui attribuer une cause qui n’est pas directement
mesurée ici.

Cette mesure est appelée **latence d’inclusion/commit observée sur node1**. Le
résumé utilise le même événement `BENCHMARK_COMMIT` pour les deux champs ; il
ne faut donc pas prétendre disposer d’une mesure séparée de la réponse HTTP
client.

### 4.2 Durée locale acceptation → commit par nœud

Le résumé fournit aussi une durée calculée avec deux événements du même nœud.
Ces valeurs sont utiles pour caractériser le traitement local, mais ne sont
pas des latences end-to-end et ne permettent pas de classer la rapidité réseau
entre les VMs :

| Nœud | Observations | p50 | p95 | Maximum |
|---|---:|---:|---:|---:|
| node1 | 60 | 235,26 ms | 356,19 ms | 490,34 ms |
| node2 | 60 | 176,13 ms | 304,97 ms | 412,08 ms |
| node3 | 60 | 180,26 ms | 258,39 ms | 323,31 ms |

Les horodatages muraux des différentes VMs ne sont pas suffisamment
synchronisés pour calculer une latence numérique de convergence node1 → node2
→ node3. Le résumé le marque correctement `convergence.status =
not_measured`. Cette réserve doit être conservée dans l’article.

Le champ `node1_local_file_observation`, dont les valeurs augmentent jusqu’à
près de 59 s, correspond à l’observation locale du fichier et non à une
latence de commit réseau. Il ne doit pas être publié comme latence blockchain.

## 5. Interprétation scientifique à retenir

La formulation défendable est la suivante :

> Sous une charge offerte de 1 transaction par seconde, avec un seul client et
> node1 comme unique point d’entrée, les 60 transactions synthétiques du run
> B4 ont été incluses sur les trois nœuds, sans transaction manquante ni
> doublon. Le débit commis sur la fenêtre de mesure est de 1,00 tx/s. La
> latence d’inclusion/commit observée sur node1 présente une médiane de
> 260,47 ms et un p95 de 393,17 ms, avec une valeur maximale de 5,51 s. Les
> trois chaînes convergent vers le même hash de bloc et la même racine d’état à
> la hauteur 56. La latence numérique de convergence inter-VM n’est pas
> publiée, car les horloges des VMs n’ont pas fait l’objet d’une synchronisation
> indépendante.

Ce résultat clôt le **point B4 à 1 tx/s** comme baseline de latence et de
convergence de contenu. Il ne clôt ni la capacité maximale, ni la tolérance aux
pannes, ni la finalité BFT.

## 6. Limites et suite

1. Un seul run a été analysé ; le résultat doit être qualifié d’exploratoire.
2. La définition de succès est la présence de la transaction sur les trois
   chaînes, pas un statut de reçu EVM séparé.
3. La latence de convergence inter-VM reste non mesurée numériquement.
4. ML-KEM/AES-GCM n’est pas mesuré ici et ne doit pas être ajouté au TPS
   blockchain ; il s’agit d’un benchmark de confidentialité hors chaîne.
5. La prochaine campagne retenue est **B5 crash/reprise**, en commençant par
   l’arrêt contrôlé d’un nœud secondaire (node3), puis sa reprise et son
   rattrapage. Le scénario est un crash-only ; il ne doit pas être présenté
   comme une attaque Byzantine.

## 7. Fichiers associés

- Résumé machine : `results/raw_data/b4-rate-1p0-20260915-summary.json`
- Présente note d’analyse : `results/raw_data/b4-rate-1p0-20260915-analysis-note.md`
- Fiche B4 : `results/raw_data/phase8-b4-run-sheet-2026-09-15.md`
- Runbook général : `results/raw_data/phase8-accelerated-runbook-2026-09-15.md`
