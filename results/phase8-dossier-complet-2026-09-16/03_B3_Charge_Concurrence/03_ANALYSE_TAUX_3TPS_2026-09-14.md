# B3 rate 3,0 tx/s — note d'analyse

**Run :** `b3-rate-3p0-20260914`  
**Source :** `results/raw_data/b3-rate-3p0-20260914-summary.json`  
**Payload :** synthétique contrôlé, `payload-size=0`  
**Ingress :** node1 uniquement  
**Perturbations :** aucune règle `tc-netem`, aucun appel IPFS

## Mesures observées

- transactions soumises : `180` ;
- transactions présentes dans chaque copie : `121` ;
- transactions manquantes par rapport au manifeste : `59` ;
- taux de présence sur les trois copies : `121/180 = 67,2222 %` ;
- débit calculé par l'analyseur sur la fenêtre de 60 s :
  `2,0166666667 tx/s` ;
- doublons : `0` sur node1, node2 et node3 ;
- hauteur locale : `116` sur les trois nœuds ;
- préfixe commun : jusqu'à la hauteur `115` ;
- même `state_root` à la hauteur finale, mais pas le même `block_hash`.

Les latences `node1_inclusion` sont des observations de présence dans les
fichiers de blocs, et non des événements `BENCHMARK_COMMIT` : p50
`39696,895589 ms`, p95 `57696,778591 ms`, maximum `59684,455738 ms`.
Elles révèlent une file d'attente croissante sous la charge, mais ne mesurent
pas une convergence inter-VM.

## Non-validités et limites

Le run n'est pas un run B3 convergé exploitable comme succès final :

```text
node1 height 116 block_hash = ada7e99a...
node2 height 116 block_hash = 1c5628ee...
node3 height 116 block_hash = 1c5628ee...
```

`all_same_to_min_tip=false` et `common_prefix_height=115` indiquent une
divergence au dernier bloc observé, même si les trois `state_root` sont égaux.
Il faut comparer les transactions, le proposant, le round et le timestamp des
blocs de hauteur 116 avant d'attribuer la cause. Il peut s'agir de deux vues de
mempool différentes ayant produit deux propositions concurrentes, mais cette
cause n'est pas déduite sans les blocs et journaux bruts.

`accepted_by_node1_direct_observation=0` ne signifie pas que node1 a rejeté
180 transactions. Le compteur direct n'est pas mesuré : aucun événement
`BENCHMARK_ACCEPT` n'a été corrélé dans le journal fourni. La borne inférieure
est `121` transactions acceptées, car elles apparaissent dans les blocs de
node1. Les `59` restantes sont non commises/non observées ; elles ne doivent
pas être classées comme rejetées, et la taille finale du mempool est inconnue.

## Mise à jour après inspection des journaux et des artefacts de hauteur 116

### Correction importante après lecture du code source et du nouveau document

Le JSON n'est pas dans un mauvais schéma. `block_hash` et `tx_id` ne sont
volontairement pas stockés comme clés JSON : `Block.from_dict()` reconstruit le
bloc et les propriétés `block.block_hash` et `transaction.tx_id` les recalculent.
L'analyseur `analyze_b2_baseline.py` utilise précisément ce chemin de
reconstruction. La divergence observée dans les fichiers JSON est donc une
observation valide pour les fichiers copiés ; elle ne doit pas être écartée
comme un simple défaut de lecture des clés.

Le code établit aussi que `Node._accept_block_locked()` journalise
`BENCHMARK_COMMIT` après `Blockchain.add_block()`. `ChainStorage.append_block()`
persiste le bloc à la hauteur suivante sans écraser un fichier existant. Dans
un même processus utilisant le même `data_dir`, un commit journalisé à la
hauteur 116 et le fichier de hauteur 116 devraient donc correspondre.

Le nouveau document montre au contraire que le fichier JSON de hauteur 116
contient une transaction dont le nonce est `1789416305883`. Le générateur B2/B3
construit les nonces avec `time.time_ns() // 1_000_000` ; ce nonce correspond à
environ `2026-09-14T20:05:05.883Z`. Le `BENCHMARK_COMMIT` de hauteur 116 visible
dans le journal intervient vers `2026-09-14T19:59:35.038Z` et porte la
transaction `dd227950...`, pas la transaction du fichier JSON. Le fichier
persisté inspecté appartient donc à une autre période de charge ou à un autre
répertoire de données/processus que le journal utilisé.

La conclusion correcte n'est ni « fork prouvé dans le run B3 » ni « simple
schéma JSON incorrect », mais : **les journaux et les blocs fournis ne sont pas
corrélés au même état de stockage**. Il faut conserver les deux artefacts,
identifier le `data_dir` effectif du processus node1 et vérifier la provenance
exacte de chaque copie avant de recalculer les métriques.


Les journaux copiés apportent une information nouvelle et contredisent la
première synthèse fondée sur les blocs :

- node1, node2 et node3 contiennent chacun `120` événements
  `BENCHMARK_ACCEPT` ;
- chacun contient `0` `BENCHMARK_REJECT` ;
- chacun contient `116` événements `BENCHMARK_COMMIT` ;
- pour les hauteurs visibles `103..116`, les journaux montrent les mêmes
  `block_hash`, le même `state_root` et les mêmes `tx_ids` sur les trois
  nœuds ;
- à la hauteur 116, les journaux indiquent le hash commun
  `da0bffa7df95cd76229bf63d88c734d8bbc816fbd3222ecd76e8997f367d8bb5` et la
  transaction `dd227950c592387bfb7ac042e92ec00a65a7b3de50a51e6ae4342962c4517f02`.

En revanche, les fichiers JSON actuellement inspectés à la hauteur 116 ne
contiennent ni `block_hash` ni `tx_id` aux clés attendues. Ils montrent des
métadonnées différentes : node1 a `timestamp=1789416365`, `round=1` et le
validator `f0aee1a1c916d0584a2805de88f2544099cc3e26`, tandis que node2/node3 ont
`timestamp=1789416346`, `round=0` et le validator
`140db41bc9e14639e54dea0135eeca843b75634f`. Ces fichiers ne sont donc pas
corrélés de manière démontrée aux événements `BENCHMARK_COMMIT` du journal ;
le premier résultat de divergence ne doit pas être simplement supprimé, mais
requalifié comme **contradiction entre artefacts de journal et de stockage**.

La situation actuelle permet de confirmer l'instrumentation d'acceptation :
`120` acceptations observées par nœud, `0` rejet observé. Elle ne permet pas
de classer les `60` soumissions restantes comme rejetées. Elle permet aussi
de compter `116` événements de commit par nœud, mais la convergence du tip
persisté doit encore être vérifiée après identification du schéma JSON et de
la relation entre fichiers de blocs et journaux.

## Décision

Ne pas lancer `5 tx/s` ni la série multi-clients avant :

1. d'archiver le run sans supprimer les blocs ;
2. d'inspecter les trois blocs de hauteur 116 ;
3. de vérifier que les journaux copiés sont bien ceux des processus node1,
   node2 et node3 et contiennent `BENCHMARK_ACCEPT`/`BENCHMARK_COMMIT` ;
4. de corriger la collecte ou de refaire un run de contrôle à `3 tx/s` ;
5. de confirmer la convergence des trois chaînes.

Le run est donc classé **surcharge observée avec divergence de tip et
instrumentation d'acceptation incomplète**, pas comme preuve de capacité
convergée à `2,0167 tx/s`.
