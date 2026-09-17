# PHASE 3 — D6 : verification du state_root cote receveur (POINT 2)

> **Mise à jour du 15 septembre 2026.** Les paragraphes d'analyse initiale
> ci-dessous sont conservés comme historique. Le code D6 a depuis été écrit,
> testé et utilisé sur les trois VMs dans le run B3
> `b3-rate-3p0-20260915`.

**Statut actuel :** code D6 terminé ; validation opérationnelle des blocs
valides confirmée sur node1, node2 et node3. Le run B3 converge à la hauteur
116 avec le même `block_hash` et le même `state_root` sur les trois nœuds. Les
contrôles dédiés de bloc hostile décrits à l'étape 4f restent des contrôles de
validation séparés et ne doivent pas être déduits du seul benchmark B3.

Ce document décrit également l'analyse qui a précédé la modification de
`src/node/node.py` (`_accept_block`) et de l'exécuteur. Il ne représente plus
un état « aucun code écrit ».

Contexte que vous avez pose : ce projet vise une **blockchain reelle**,
pas une maquette. L'analyse ci-dessous est ecrite dans cet esprit : elle
signale aussi ce qui manque pour meriter ce mot, meme quand cela sort du
strict point 2.

---

## 1. L'etat actuel, dit sans complaisance

Depuis D5, le producteur inscrit une vraie racine. Mais **aucun noeud ne
la verifie**. Concretement, aujourd'hui :

- un validateur autorise peut annoncer `state_root = 0xdeadbeef...`,
  signer, diffuser : les deux autres noeuds **acceptent le bloc** ;
- un validateur peut inclure une transaction et annoncer la racine
  d'avant : accepte ;
- deux noeuds peuvent avoir des etats EVM totalement divergents tout en
  ayant la **meme chaine de blocs**, sans que rien ne le signale.

Autrement dit, le `state_root` est aujourd'hui **un commentaire signe**.
Il a la forme d'une garantie sans en etre une. C'est precisement ce que
le point 2 doit corriger.

Formule a retenir : tant que le receveur ne rejoue pas, la chaine
garantit *qui a parle*, jamais *ce qui est vrai*.

---

## 2. Mesures reelles (faites aujourd'hui, pas estimees)

| Operation | Cout mesure |
|---|---|
| Verification ML-DSA d'une signature | **0,038 ms** |
| Signature ML-DSA | 0,094 ms |
| Rejeu d'un bloc vide | 0,042 ms |
| Rejeu d'un bloc d'une transaction | **1,03 ms** |

Conclusion directe : **rejouer un bloc coute a peu pres autant que
verifier une signature ML-DSA.** Le rejeu n'est pas l'operation couteuse
qu'on imagine. L'argument « c'est trop cher a la reception » ne tient
pas ici, et il ne faut donc pas s'en servir pour justifier un
raccourci.

---

## 3. Faille decouverte pendant l'analyse (hors point 2, mais grave)

En verifiant l'ordonnancement, j'ai teste si le gas cumule d'un bloc
etait plafonne. **Il ne l'est pas.**

    BLOCK_GAS_LIMIT       : 30 000 000
    gas consomme par bloc : 42 000 000
    DEPASSEMENT ACCEPTE ? : True

`BLOCK_GAS_LIMIT` sert uniquement de contexte d'execution py-evm ; rien
ne compare `BlockExecutionResult.gas_used` a cette borne. Or
`MAX_TRANSACTIONS = 10 000` dans `block.py`.

Consequence mesuree, avec le bytecode `5b600056` (boucle infinie) et
`gas_limit = 1 000 000` par transaction :

    300 tx en boucle infinie : 80,46 s  (268 ms/tx)
    extrapolation a 10 000 tx : ~2 682 s, soit ~45 minutes

**Un seul bloc, structurellement valide et correctement signe par un
validateur autorise, immobiliserait chaque noeud du reseau pendant
environ 45 minutes.** Et avec la verification du point 2, ce cout serait
paye par les trois noeuds au lieu d'un seul.

C'est un DoS trivial. Il existe deja aujourd'hui pour le producteur ; le
point 2 l'etend aux receveurs. **Il faut donc traiter le plafond de gas
en meme temps que la verification, pas apres.** Sinon j'introduis
sciemment un vecteur d'attaque.

Sur une vraie blockchain, cette borne est un invariant de consensus, pas
une optimisation.

---

## 4. Ou placer la verification : le vrai choix

### Contrainte de depart

Vous avez interdit de modifier `_accept_block`. Or c'est le seul chemin
d'entree d'un bloc. Il faut donc regarder les options honnetement.

### Option A — dans `validator.validate_block_for_acceptance`

Ajouter un parametre `state_replayer` et rejouer a l'etape 6.

- **Contre** : `validator.py` deviendrait dependant de `src/evm/`, donc
  de py-evm, pour ce qui est aujourd'hui un module de validation
  cryptographique pur. Son docstring revendique de n'avoir besoin
  d'aucun contexte lourd.
- **Contre** : le rejeu **modifie l'etat**. Une fonction nommee
  `validate_...` qui ecrit serait un piege durable.
- **Rejetee.**

### Option B — nouvelle etape dans `_accept_block`, entre 2 et 3

L'ordre deviendrait :

    1. validate_block_for_acceptance   (structure, chainage, ML-DSA)
    2. consensus.is_expected_proposer  (tour)
    2bis. VERIFICATION DU state_root   (rejeu)          <-- nouveau
    3. blockchain.add_block
    4. mempool.remove_transactions
    5. p2p.broadcast_block

- **Pour** : place logiquement correcte. On ne persiste jamais un bloc
  dont l'etat n'a pas ete verifie, et on ne rediffuse jamais un bloc
  invalide.
- **Pour** : l'ordre fail-fast est respecte — la verification arrive
  apres les controles bon marche (signature 0,038 ms), donc un bloc mal
  signe ne declenche aucun rejeu.
- **Contre** : cela modifie `_accept_block`, que vous avez gele.

### Option C — verifier apres l'ajout, puis revenir en arriere

Rejeter apres coup si la racine diverge.

- **Rejetee** : `ChainStorage` n'a aucun mecanisme de retrait, et le
  bloc aurait deja ete rediffuse aux pairs. On propagerait un bloc
  invalide avant de s'apercevoir qu'il l'est.

### Recommandation

**Option B.** C'est le seul emplacement correct. Je vous demande donc
une levee ponctuelle et delimitee du gel sur `_accept_block` : une
etape inseree, aucune des cinq existantes deplacee ni modifiee.

Sans cette levee, le point 2 ne peut pas etre fait proprement, et je
prefere le dire plutot que de bricoler ailleurs.

---

## 5. Conception proposee

### 5.1 Le mecanisme

Dans `_accept_block`, apres le controle du tour :

1. `self._state_replayer.sync_to(block.height - 1)` — se placer sur
   l'etat du parent ;
2. `attendue = self._state_replayer.root_after(block.transactions,
   block_number=block.height, timestamp=block.timestamp,
   coinbase=block.validator)` — essai a blanc, sans engager l'etat ;
3. si `attendue != block.state_root` : **rejet** (`NodeError`) ;
4. sinon, apres `add_block` reussi, `sync_to(block.height)` pour
   engager reellement l'etat.

Le point 4 est important : l'etat ne doit avancer **qu'apres** que le
bloc soit reellement dans la chaine. Si `add_block` echoue, l'etat ne
doit pas refleter un bloc absent.

### 5.2 Le plafond de gas (§3)

Dans le meme mouvement, refuser tout bloc dont le gas cumule depasse
`BLOCK_GAS_LIMIT`. Deux emplacements possibles :

- **(a)** dans `executor.execute_block`, s'arreter des le depassement ;
- **(b)** dans `_accept_block`, comparer `result.gas_used` a la borne.

`(a)` est preferable : le producteur cesse alors de fabriquer des blocs
invalides, et le receveur cesse d'executer des le depassement au lieu de
tout executer avant de constater. Cela demande cependant que
`root_after` expose le `gas_used`, donc un ajustement de son type de
retour — aujourd'hui `bytes`.

**Point a trancher (Q2 ci-dessous).**

### 5.3 Le cas du bloc de genese

Le genese porte `EMPTY_STATE_ROOT` et n'est jamais recu par ce chemin
(il est construit localement depuis la config). Rien a faire, mais a
verifier par un test.

---

## 6. Ce que cette etape apporterait reellement

Une fois faite, et **seulement** une fois faite :

- un validateur ne peut plus annoncer un etat qu'il n'a pas produit ;
- une divergence d'etat entre les 3 VMs devient **impossible sans
  detection** — le bloc fautif est rejete a la reception ;
- le `state_root` cesse d'etre declaratif et devient verifie.

C'est ce qui separe une chaine « qui fonctionne entre gens de bonne
volonte » d'une chaine qui tient face a un participant defaillant ou
malveillant. Compte tenu de votre objectif, c'est le minimum.

---

## 7. Ce qui manquera encore apres (honnetete sur la portee)

Pour ne pas laisser croire a une garantie qui n'existerait pas, voici ce
qui restera hors perimetre meme apres le point 2 :

1. **Pas de racine des recus** (`receipts_root`). Les recus sont
   calcules puis jetes. Deux noeuds pourraient produire des recus
   differents sans que rien ne le detecte — la racine d'etat couvre
   l'etat final, pas le detail des executions.
2. **`gas_used` du bloc n'est pas inscrit** dans `Block`. L'ajouter
   serait une seconde rupture de format.
3. **Pas de detection de fork ni de reorganisation.** `StateReplayer`
   refuse explicitement de reculer. En PoA a 3 noeuds avec un
   round-robin strict, il n'y a pas de fork attendu — mais « pas
   attendu » n'est pas « impossible ».
4. **Un validateur autorise peut toujours censurer** des transactions
   (ne pas les inclure). Aucun mecanisme ne le detecte. C'est inherent
   au PoA.
5. **Pas de limite de taille serialisee du bloc** en octets, seulement
   un nombre de transactions et `MAX_MESSAGE_BYTES = 8 MiB` au
   transport.

Les points 1 et 2 meriteraient d'etre traites en PHASE 3 si vous visez
le realisme. Le point 5 est un durcissement reseau a envisager.

---

## 8. Ampleur du changement propose

| Fichier | Nature | Ampleur |
|---|---|---|
| `src/node/node.py` (`_accept_block`) | **1 etape inseree** | ~20 l. |
| `src/evm/executor.py` | plafond de gas | ~10 l. |
| `src/evm/replay.py` | `root_after` expose le gas | ~5 l. |
| `tests/unit/node/test_node.py` | ajouts | ~6 tests |
| `tests/unit/evm/test_replay.py` | ajouts | ~3 tests |
| Tests existants | **aucune modification attendue** | 0 |

Critere de fin : suite complete verte (357 aujourd'hui), un bloc a
racine falsifiee **rejete**, un bloc depassant le plafond de gas
**rejete**, et les 3 VMs convergeant toujours.

---

## 9. Questions a trancher

**Q1 — Levez-vous le gel sur `_accept_block` pour cette unique etape
inseree ?** Sans cela, le point 2 n'a pas d'emplacement correct. Aucune
des 5 etapes existantes ne serait deplacee ni modifiee.

**Q2 — Traite-t-on le plafond de gas maintenant ?** Je recommande oui,
dans `execute_block` (option (a)). Faire la verification sans le plafond
transformerait un DoS visant un noeud en DoS visant les trois.

**Q3 — Que faire d'un bloc rejete pour racine invalide ?** Aujourd'hui
`_accept_block` leve `NodeError` et le bloc est ignore. Pour une chaine
« reelle », il faudrait au minimum un `logger.error` distinctif : une
racine fausse signee par un validateur autorise n'est pas une erreur
banale, c'est soit un bug de consensus, soit une attaque. Je recommande
un message explicite et distinct des autres rejets.

**Q4 — Ajoute-t-on `receipts_root` maintenant ou plus tard ?** Cela
impliquerait un troisieme champ dans `Block`, donc une nouvelle rupture
de format. Je recommande **plus tard**, en une seule rupture groupee
avec `gas_used` si vous decidez de viser le realisme complet — pour ne
pas vider `data/nodeN/blocks/` trois fois.

---

## 10. Ordre d'execution si vous validez

1. Plafond de gas dans `executor.py` + tests ; suite complete verte.
2. `root_after` expose le gas ; suite complete verte.
3. Etape inseree dans `_accept_block` + tests de rejet ; suite verte.
4. Verification inter-VMs.

A chaque etape : `py_compile` -> tests du module -> suite complete.

---

## 11. Étape 3/4 — résultat d'exécution

Pipeline `_accept_block` en place :

```
validate_block_for_acceptance
  -> is_expected_proposer
  -> _verify_state_root      (NOUVEAU : rejeu sur vue jetable)
  -> add_block
  -> _commit_state           (NOUVEAU : engagement après persistance)
  -> mempool.remove_transactions
  -> broadcast_block
```

### Suite complète

`pytest tests/unit/ tests/integration/ -q` → **380 passed en 101,46 s**.

### Changement de sémantique assumé (et non un correctif de complaisance)

`test_l_etat_rattrape_les_blocs_des_autres_validateurs` échouait sur
`assert applied_height == 0`. Cette assertion encodait la sémantique
**paresseuse de D5** : un nœud qui recevait un bloc n'avançait pas son
état, il attendait son propre tour de proposition.

D6 supprime volontairement cette paresse : **vérifier un bloc impose de
le rejouer**, donc l'état est à jour dès l'acceptation. L'assertion a
été mise à jour (`0 -> 1`, puis `1 -> 2` après `propose_block`), ce qui
préserve l'intention du test (le rattrapage fonctionne) tout en
vérifiant désormais que le bloc h=2 s'appuie sur l'état h=1.

`_commit_state` n'a **pas** été affaibli pour faire passer le test.

### Couverture ajoutée : plafond de gas côté receveur

`test_un_bloc_depassant_le_plafond_de_gas_est_rejete` comble le trou
signalé : 31 transactions à 1 000 000 de gas annoncé (31 M > 30 M).
Journal effectivement produit, refus **avant toute exécution** :

```
ERROR src.evm.executor: block rejected: announced gas 31000000
      exceeds limit 30000000 at transaction 31/31
ERROR src.node.node: BLOCK REJECTED: cannot verify state at height 1 ...
```

Après refus : `height == 0` et `applied_height == 0` (aucune trace).

### Test flaky supplémentaire identifié (préexistant, non lié à D6)

`test_three_nodes_tcp.py::test_transaction_is_removed_from_all_mempools_after_inclusion`
a échoué **une fois** en suite combinée (`Bad file descriptor` sur une
socket node3), puis **3/3 en isolation** et **la suite combinée entière
repassée à 380/380**. Cause : la fixture `network` est de portée
**module**, les connexions TCP sont donc partagées entre tests et une
socket morte se propage. C'est le **deuxième** flaky du même fichier,
avec `test_node_started_later_still_connects`.

---

## 12. Point 1 tranché — gas annoncé vs gas consommé

### Ce que fait réellement Ethereum (vérifié, pas supposé)

Le flux de go-ethereum n'est ni « annoncé » ni « consommé » : c'est un
**pool réapprovisionné**.

```
buyGas()   -> GasPool.SubGas(tx.Gas)              // débit du gas ANNONCÉ
... exécution ...
AddGas(initialGas - blockGasUsed)                 // RESTITUTION de l'inutilisé
```

Validité du bloc : `gasUsed <= gasLimit` sur le gas **consommé**.

Ma pré-passe reproduit le débit mais **omet la restitution**. C'est
exactement là qu'est l'erreur.

### Mesures

| Scénario | Gas annoncé | Gas consommé | Ma règle | Ethereum |
|---|---|---|---|---|
| 1 000 transferts, `gas_limit=100 000` | 100 M | 21 M (70 % du plafond) | **REJETÉ** | **accepté** |
| 30 tx boucle infinie, `gas_limit=1 M` | 30 M | 30 M | accepté, 8,28 s | accepté, 8,28 s |
| 10 000 tx boucle infinie | 10 000 M | — | rejeté en 0,0016 s | **invalide à la tx 30, borné à 7,93 s** |

### Conclusion : ma règle est trop stricte, et c'est un vrai défaut

Le premier cas est le verdict. Annoncer large « au cas où » est le
comportement **normal** d'un portefeuille — c'est ce que fait
`estimateGas` avec une marge. Ma règle **rejette un bloc parfaitement
honnête** qui n'utilise que 70 % du plafond, et le rejette *chez tous
les receveurs*. Sur une vraie chaîne, cela plafonne le débit réel à
~300 transferts par bloc au lieu de ~1 400 : une perte de capacité de
plus de 4x, causée par une transaction qui n'a rien fait de mal.

Le troisième cas démontre que la sévérité supplémentaire **n'achète
rien** : le modèle du pool écarte le bloc hostile après 7,93 s de
travail borné, sans jamais approcher les 45 minutes. La protection
anti-DoS ne dépend pas du refus a priori, elle dépend du fait que
**le gas consommé est borné par le plafond** — ce qui est vrai par
construction dès que l'on arrête d'exécuter quand le pool est vide.

### Décision

`_check_block_gas_limit` (pré-passe sur le gas annoncé) est
**remplacée** par un **pool de gas décrémenté pendant l'exécution** :

1. avant chaque transaction, refuser le bloc si `gas_limit` de la
   transaction dépasse le gas restant dans le pool ;
2. après exécution, ne retirer du pool que le gas **réellement
   consommé**.

On conserve ainsi les trois propriétés voulues : arrêt anticipé sur
bloc hostile, travail borné par `BLOCK_GAS_LIMIT`, et **aucun faux
rejet** de bloc honnête. C'est également la sémantique littérale de
votre consigne : « arrêt dès que `BLOCK_GAS_LIMIT` est dépassé ».

Déterminisme préservé : le pool est une soustraction d'entiers sur la
séquence ordonnée du bloc ; les trois nœuds concluent identiquement.

---

## 13. Point 1 — correctif appliqué

### Ce qui a changé

**`src/evm/executor.py`** — `_check_block_gas_limit` (pré-passe) est
**supprimée**. Le plafond est désormais appliqué dans la boucle de
`execute_block` :

```python
restant = BLOCK_GAS_LIMIT - gas_total
if transaction.gas_limit > restant:
    raise BlockGasLimitExceeded(...)      # SubGas : on ne démarre pas
recu = self.execute_transaction(...)
gas_total += recu.gas_used                # AddGas : restitution implicite
```

Le pool ne se vide que du gas **consommé** ; le refus porte sur le gas
**annoncé** de la prochaine transaction comparé au **solde restant**.

**`src/node/node.py`** — nouvelle méthode `_select_within_gas_limit`,
appelée par `propose_block` avant le calcul de la racine. Le producteur
applique la **même** règle que le receveur, au pire cas (`gas_limit`) :
il est donc conservateur — il peut sous-remplir un bloc, jamais en
produire un invalide. Les transactions écartées sont **différées**, pas
perdues.

Placée dans `node.py` et non `consensus.py` : ce dernier ne doit pas
dépendre de `src.evm`, pour la même raison qui fait passer `state_root`
en paramètre.

### Vérification demandée : restitution sur transactions successives

`test_le_gas_inutilise_est_rendu_au_pool` — **le test qui aurait
révélé le bug initial**. 100 transactions dans un même bloc, annonçant
1 000 000 chacune (100 M annoncés, > plafond) mais n'en consommant que
21 000 : le bloc **passe**, `gas_used == 2 100 000`.

Complété par :
- `test_la_restitution_s_accumule_sur_de_nombreuses_transactions` —
  1 400 transferts, cumul vérifié transaction par transaction ;
- `test_restitution_partielle_puis_epuisement` — les deux régimes dans
  un seul bloc (transferts bon marché, puis boucles infinies) ;
- `test_une_transaction_trop_grosse_pour_le_solde_restant_est_refusee` ;
- `test_le_plafond_porte_sur_le_gas_consomme_non_annonce` — remplace le
  test homonyme qui affirmait exactement l'inverse.

### Cohérence producteur/receveur (les deux corrections ensemble)

- `test_le_producteur_ne_fabrique_pas_de_bloc_hors_plafond` — 40 tx à
  1 M dans le mempool ; le bloc produit tient dans le plafond **et est
  accepté par un pair**.
- `test_les_transactions_ecartees_restent_dans_le_mempool`.

### Mesures après correctif

| Scénario | Avant (pré-passe) | Après (pool) |
|---|---|---|
| 400 transferts, marge 100 k | **REJETÉ** | **accepté**, 8,4 M de gas, 0,07 s |
| 10 000 tx boucle infinie | rejeté 0,0016 s | **refusé à la tx 31, 8,20 s** |

Le travail reste borné (`only 0 remains in the block pool`) et les
blocs honnêtes ne sont plus rejetés.

### Suite

`pytest tests/unit/ tests/integration/ -q` → **385 passed en 130,25 s**.
