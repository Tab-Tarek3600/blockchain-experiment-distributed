# B3 — charge, saturation et scalabilité par clients

**Phase :** 8 — étape opérationnelle suivante après B2  
**Date de préparation :** 14 septembre 2026 ; premier point exécuté le 15 septembre 2026  
**Statut :** point `3 tx/s`, 1 client logique, exécuté et analysé ; campagne B3 complète non terminée  
**Scénario invariant :** clients logiques → node1 → diffusion P2P → node2/node3

> La présente fiche conserve le protocole B3 et son résultat réel. Le point
> `b3-rate-3p0-20260915` est détaillé dans
> `results/raw_data/b3-rate-3p0-20260915-analysis-note.md`.

## 1. Décision de méthode

B2 a confirmé une zone de saturation observée autour de `2 tx/s` (`119/120`
sur deux essais indépendants). B3 caractérise cette zone et la surcharge sans
confondre :

- taux offert par les clients ;
- transactions réellement soumises ;
- transactions acceptées par node1 ;
- transactions incluses et commises sur les trois nœuds ;
- backlog et transactions non commises ;
- débit commis, goodput et latences.

Les clients B3 sont des **clients logiques concurrents** dans le générateur,
avec une connexion TCP indépendante par client, mais ils s'exécutent sur node1
et envoient tous vers node1. Ce test ne mesure pas une scalabilité avec plusieurs
machines clientes.

Le script B3 ne démarre ni n'arrête les VMs, ne modifie pas de configuration,
ne copie pas de clé et n'applique pas `tc-netem` :

```text
scripts/experiments/benchmark_b3_clients.py
```

Il réutilise le protocole de trame et les transactions synthétiques de B2. Les
plages de nonces sont disjointes entre clients pour éviter les conflits
artificiels du mempool.

## 2. Matrice B3 sous contrainte de ressources

Chaque essai est exécuté sur une chaîne de données fraîche, avec 60 secondes de
mesure et un drain maximal de 300 secondes.

### A — taux d'arrivée, un client logique

| Run | Clients | Taux total offert | Payload | État |
|---|---:|---:|---:|---|
| b3-rate-1p0 | 1 | 1 tx/s | 0 octet | à exécuter si nécessaire |
| b3-rate-2p0 | 1 | 2 tx/s | 0 octet | repère B2 déjà mesuré |
| b3-rate-3p0-20260915 | 1 | 3 tx/s | 0 octet | **exécuté** |
| b3-rate-5p0 | 1 | 5 tx/s | 0 octet | ne pas lancer avant analyse B4 |

Les points `1` et `2 tx/s` servent de repères B2 ; les points `3` et `5 tx/s`
explorent la surcharge dans B3. Le point à `3 tx/s` montre déjà une perte de
complétude : 121 transactions incluses sur 180 offertes. Il est donc classé
comme surcharge observée, et non comme une capacité réussie de 3 tx/s.

### B — concurrence de clients logiques

Fixer le taux total afin de ne faire varier qu'une dimension à la fois :

| Run | Clients | Taux total offert | Payload | État |
|---|---:|---:|---:|---|
| b3-client-01 | 1 | 1 tx/s | 0 octet | à exécuter après B4 |
| b3-client-02 | 2 | 1 tx/s | 0 octet | à exécuter après B4 |
| b3-client-04 | 4 | 1 tx/s | 0 octet | à exécuter après B4 |
| b3-client-08 | 8 | 1 tx/s | 0 octet | à exécuter après B4 |

Si cette série reste complète, répéter uniquement les points 1, 4 et 8 clients
à `2 tx/s` pour mesurer la concurrence dans la zone de saturation. Dans tous
les cas, le débit total offert reste explicite dans le manifeste.

Une série payload séparée pourra ensuite utiliser `128`, `1024` et `4096`
octets synthétiques à `1 tx/s` et 1 client. Elle ne doit pas être mélangée aux
résultats B2 `payload-size=0`.

## 3. Commande utilisée pour le point exécuté

Le générateur a été exécuté sur node1, avec node1 comme seul ingress :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}

PYTHONPATH=. python3 scripts/experiments/benchmark_b3_clients.py \
  --config config/nodes/node1/node.yaml \
  --rate 3.0 \
  --clients 1 \
  --duration 60 \
  --payload-size 0 \
  --drain-timeout 300 \
  --poll-interval 0.05 \
  --data-dir "$PWD/data/node1" \
  --run-id b3-rate-3p0-20260915 \
  --manifest-output results/raw_data/b3-rate-3p0-20260915-node1-manifest.json
```

Le générateur préconstruit et pré-signe les 180 transactions avant la fenêtre
T2. Le champ `submitted` est incrémenté après `sendall()` sur la connexion TCP ;
le script ne reçoit pas d'accusé applicatif individuel pour chaque transaction.
Cette définition est essentielle pour interpréter l'écart entre `submitted` et
`BENCHMARK_ACCEPT`.

## 4. Résultat du point `3 tx/s`

| Mesure | Résultat |
|---|---:|
| Préconstruites | 180 |
| Soumises | 180 |
| `BENCHMARK_ACCEPT` node1 | 121 |
| `BENCHMARK_REJECT` node1 | 0 |
| Incluses sur node1/node2/node3 | 121 / 121 / 121 |
| Incluses sur les trois nœuds | 121 |
| Non observées/non incluses | 59 |
| Taux de succès | 67,2222 % |
| Débit commis sur 60 s | 2,0166666667 tx/s |
| Doublons | 0 |
| Hauteur finale | 116 sur les trois nœuds |
| Convergence contenu | oui |
| Observation locale complète | non |
| Erreurs générateur | `[]` |

L'analyse a été effectuée depuis la machine de développement avec :

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py \
  --manifest results/raw_data/b3-rate-3p0-20260915-node1-manifest.json \
  --node1-blocks /tmp/b3-rate-3p0-20260915/node1/blocks \
  --node2-blocks /tmp/b3-rate-3p0-20260915/node2/blocks \
  --node3-blocks /tmp/b3-rate-3p0-20260915/node3/blocks \
  --node1-log /tmp/b3-rate-3p0-20260915/node1.log \
  --node2-log /tmp/b3-rate-3p0-20260915/node2.log \
  --node3-log /tmp/b3-rate-3p0-20260915/node3.log \
  --output results/raw_data/b3-rate-3p0-20260915-summary.json
```

Le résumé obtenu est :

```text
submitted                              : 180
included_on_all_three                  : 121
success_rate_all_three                 : 0.6722222222222223
committed_tps_all_three_over_submission_window : 2.0166666666666666
converged_to_min_tip                   : true
```

La hauteur `116` compte des blocs. Elle ne représente pas 116 transactions.
Les événements de commit concernent 116 blocs et l'analyse des blocs compte 121
transactions incluses ; le bloc h113 contient notamment `tx_count=2`.

Le contrôle direct des champs `tx_count` a maintenant été exécuté sur les
journaux archivés des trois nœuds :

```text
                 commit_events   sum_tx_count   accepts   rejects
node1                    116            121        121         0
node2                    116            121        121         0
node3                    116            121        121         0
```

Le statut de réconciliation est **PASS** : `sum_tx_count=121` sur les trois
journaux, en accord avec `included_on_all_three=121`. Les 116 événements de
commit sont des blocs, et non 116 transactions. Les blocs h17, h54, h93, h105
et h113 portent chacun deux transactions ; les 111 autres blocs portent chacun
une transaction. Le détail est archivé dans
`results/raw_data/b3-rate-3p0-20260915-commit-audit.md` et le résultat machine
dans `results/raw_data/b3-rate-3p0-20260915-commit-audit.json`.

Le tip commun observé dans les journaux est :

```text
height     : 116
block_hash : b3368dd94842f401d81b55887db68adb489c43eb655823568a90cfd343ad4176
state_root : 56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
tx_count   : 1
```

Le même hash de bloc et la même racine d'état ont été observés sur les trois
nœuds. Node2 et node3 indiquent ensuite `height=116` et `mempool=0`.

## 5. Interprétation et classement

Les 180 transactions sont la charge offerte :

```text
3 tx/s × 60 s = 180
```

Elles ne sont pas 180 preuves d'acceptation. Le générateur ne demande pas un
accusé applicatif individuel ; il comptabilise les écritures locales réussies
sur la connexion. Les 121 acceptations sont les seules observations directes
d'acceptation disponibles. Aucun rejet explicite n'a été journalisé.

Les 59 transactions restantes sont donc classées **non observées/non
commises**, et non rejetées. `Connection reset by peer` est compatible avec la
fermeture de la connexion client, mais ne suffit pas à attribuer formellement
un sort à chaque transaction manquante.

Le run est retenu comme :

> **B3 — surcharge observée à 3 tx/s, avec convergence des 121 transactions
> effectivement incluses et complétude non atteinte pour les 59 autres.**

Le détail des limites et des artefacts se trouve dans
`b3-rate-3p0-20260915-analysis-note.md`.

## 6. Critères de validation d'un run B3

Un run est exploitable seulement si :

- le nombre de clients logiques et le taux total offert figurent dans le
  manifeste ;
- `submitted` est distingué de `included_node1/node2/node3` ;
- les transactions sont synthétiques et sans secret ;
- node1 est le seul ingress ;
- les trois chaînes sont comparées sur leur préfixe commun ;
- le backlog est rapporté sans être confondu avec la taille finale du mempool ;
- les transactions non commises restent listées ou sont quantifiées ;
- payload et débit en octets restent séparés du TPS de transactions ;
- les latences p50/p95/max sont calculées uniquement à partir de timestamps
  comparables sur un même nœud, ou marquées `not_measured` entre VMs ;
- le résultat est archivé avant toute réinitialisation du run suivant.

Le run du 15 septembre satisfait ces critères pour l'analyse de contenu et de
convergence. Il ne fournit pas un verdict applicatif individuel pour les 59
transactions manquantes ; cette limite est explicitement conservée.

## 7. Collecte et conservation

Les artefacts doivent rester sur la machine de développement :

- manifeste JSON ;
- résumé JSON ;
- journaux des trois nœuds ;
- blocs des trois nœuds ;
- présente note d'analyse.

Ne pas supprimer les clés de validateurs, les configurations ou les artefacts
avant la clôture documentaire du run. Les tests suivants doivent utiliser un
nouveau `run_id` et une nouvelle zone temporaire de collecte.

## 8. Étape suivante

Le point à `3 tx/s` est clôturé comme point de surcharge B3. La suite
recommandée est :

1. documenter et archiver définitivement ce run ;
2. exécuter **B4 — latence d'inclusion, commit local et convergence de contenu**
   à une charge maîtrisée (`1` ou `2 tx/s`) ;
3. mesurer uniquement les temps numériques dont les horloges sont comparables,
   et laisser la latence inter-VM `not_measured` sinon ;
4. reprendre ensuite B3 par `5 tx/s` ou par concurrence de clients, seulement
   si la collecte reste corrélée et si les nœuds restent stables.
