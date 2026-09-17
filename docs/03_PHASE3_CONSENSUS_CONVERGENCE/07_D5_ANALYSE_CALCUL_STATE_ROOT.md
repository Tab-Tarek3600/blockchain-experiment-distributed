# PHASE 3 — D5 : brancher le calcul reel du state_root (POINT 1, producteur)

Etat : **ANALYSE — AUCUN CODE ECRIT**. En attente d'accord.

Sauvegarde prealable : `~/_backups/PHASE3-avant-D5-20260823-143203.tar.gz` (158 fichiers).

---

## 1. Ou en est-on exactement

`Block.state_root` existe (D3), il est couvert par `signing_hash` et
`block_hash`. Mais **personne ne calcule sa valeur** :

    $ grep -rn "state_root" --include=*.py src/ tests/ \
        | grep -v "src/evm/|src/blockchain/block.py|tests/unit/evm/"
    (aucun resultat)

Autrement dit : `src/evm/` sait produire une racine
(`EVMExecutor.execute_block(...).state_root`), `src/blockchain/block.py`
sait la transporter et la signer, et **rien ne relie les deux**. Tous les
blocs produits aujourd'hui portent `EMPTY_STATE_ROOT`.

Le point 1 consiste a poser ce fil, cote producteur uniquement.

---

## 2. Le vrai probleme n'est pas le calcul, c'est *qui detient l'etat*

Le calcul lui-meme est une ligne : `execute_block(...).state_root`.

La difficulte est ailleurs. En PoA round-robin a 3 noeuds,
`validators[h % 3]`, chaque noeud ne propose **qu'un bloc sur trois**.
Pour calculer la racine du bloc `h`, il lui faut l'etat resultant des
blocs `1..h-1` — donc **y compris les deux blocs proposes par les
autres**. Un noeud ne peut pas se contenter d'appliquer ses propres
blocs.

Or la decision D4 (la votre) dit :

> l'etat EVM est maintenu par rejeu depuis `ChainStorage`, **aucun hook
> dans `_accept_block`**.

Ces deux faits se combinent en une seule contrainte : l'etat doit pouvoir
**rattraper son retard a la demande**, en relisant la chaine, sans que
personne ne le notifie qu'un bloc est arrive.

C'est le coeur de la conception ci-dessous. Le reste est de la plomberie.

---

## 3. Mesures reelles (faites ici, aujourd'hui, pas des estimations)

py-evm avait disparu du bac a sable entre deux sessions ; je l'ai
reinstalle (pin `ffce74fa`, `rlp==4.1.0`) pour pouvoir mesurer.

| Scenario                          | Cout mesure      | Extrapolation 10 000 blocs |
|-----------------------------------|------------------|----------------------------|
| Rejeu d'un bloc **vide**          | **0,042 ms**     | 0,4 s                      |
| Rejeu d'un bloc **1 transaction** | **1,03 ms**      | 10,3 s                     |

Methode : `EVMState()` + `EVMExecutor`, 300 blocs vides puis 200 blocs
d'un transfert chacun, chronometre `perf_counter`.

Trois conclusions chiffrees :

1. **Rattraper 2 blocs de retard coute ~2 ms.** C'est le cas nominal
   (les deux blocs proposes par les autres noeuds depuis mon dernier
   tour). Negligeable devant l'intervalle de 5 s.
2. **Rejouer toute la chaine au demarrage coute 0,4 a 10 s pour 10 000
   blocs.** Acceptable au lancement d'un noeud, pas a chaque bloc.
3. Donc : **rejeu integral au demarrage, rejeu incrementiel ensuite.**
   Rejouer toute la chaine a chaque proposition serait tenable
   aujourd'hui (h=55) et intenable a h=5000 — a rejeter tout de suite,
   pas quand ca cassera.

---

## 4. Les trois conceptions envisagees

### Option A — `Consensus` recoit un `EVMExecutor`

`build_candidate_block` prend un executor en parametre et calcule la
racine lui-meme.

- **Contre** : `Consensus` deviendrait dependant de `src/evm/`, donc de
  py-evm. Aujourd'hui `consensus.py` n'importe que `Block`, `Blockchain`,
  `MLDSA`, `Mempool`, et son docstring revendique explicitement d'etre
  testable sans `NodeConfig`. Un noeud sans py-evm ne pourrait plus
  demarrer. **Rejetee.**

### Option B — `Consensus` recoit la racine deja calculee

`build_candidate_block(..., state_root: bytes = EMPTY_STATE_ROOT)`. Le
calcul est fait par l'appelant (`Node.propose_block`), qui detient deja
tout le contexte.

- **Pour** : `consensus.py` reste ignorant de l'EVM — il transporte une
  valeur opaque de 32 octets, exactement comme il transporte deja
  `local_public_key`. La modification y est **minimale** : un parametre
  facultatif et son passage a `Block.create()`.
- **Pour** : symetrique du reste de l'architecture — `Node` cable les
  composants, `Consensus` applique la regle de tour.
- **Contre** : `Node` grossit un peu.

### Option C — un composant dedie, `EVMStateManager`, detenu par `Node`

Option B **plus** un objet qui encapsule « l'etat + jusqu'ou il est a
jour », avec le rattrapage par rejeu.

C'est l'option B augmentee du seul element qui manque pour respecter D4.

---

## 5. Conception retenue (proposition) : B + C

### 5.1 Nouveau fichier `src/evm/replay.py`

Un seul objet, une seule responsabilite : **maintenir un `EVMState` a
jour avec `ChainStorage`, par rejeu**.

    class StateReplayer:
        def __init__(self, storage: ChainStorage) -> None: ...

        @property
        def applied_height(self) -> int:      # -1 = rien applique
        @property
        def state_root(self) -> bytes:        # racine apres applied_height

        def sync_to(self, height: int) -> bytes:
            """Rejoue les blocs manquants jusqu'a `height` inclus.
            Retourne la racine obtenue. Ne rejoue que ce qui manque."""

        def root_after(self, transactions, *, block_number, timestamp,
                       coinbase) -> bytes:
            """Racine qu'on obtiendrait en ajoutant ce bloc, SANS
            engager l'etat de facon definitive (snapshot/revert)."""

Pourquoi un fichier separe plutot que dans `executor.py` : `executor.py`
execute *un* bloc et ne connait ni `ChainStorage` ni la notion de
« retard ». Melanger les deux rendrait l'executor dependant du stockage.

Pourquoi `root_after` ne s'appuie pas sur `commit()` seul : si le bloc
candidat est ensuite refuse (validation, course avec un pair), l'etat
aurait avance d'un bloc qui n'existe pas — divergence silencieuse avec
les deux autres noeuds. On utilise donc `snapshot()` / `revert()`, deja
presents dans `EVMState` et deja testes.

**Point a trancher (voir §7, Q2)** : la genese. `sync_to` doit-elle
partir de la hauteur 0 ou 1 ? Le bloc de genese porte
`state_root == EMPTY_STATE_ROOT` et ne contient aucune transaction ;
le rejouer est un no-op. Je propose de le rejouer quand meme, pour que
`applied_height` corresponde exactement a `blockchain.height` et eviter
un decalage de 1 permanent dans le raisonnement.

### 5.2 `src/node/consensus.py` — modification minimale

Un parametre facultatif :

    def build_candidate_block(
        self, blockchain, mempool, local_public_key, local_secret_key,
        timestamp, ml_dsa=None, max_transactions=None,
        state_root: bytes = EMPTY_STATE_ROOT,     # <-- ajout
    ) -> Block:
        ...
        block = Block.create(
            ...,
            state_root=state_root,                # <-- ajout
        )

Deux lignes utiles. `EMPTY_STATE_ROOT` serait importe depuis
`src.blockchain.block` (la constante en dur de D3), **pas** depuis
`src.evm.state` : `consensus.py` ne doit pas tirer py-evm. La valeur par
defaut preserve le comportement actuel pour tout appelant qui ne fournit
rien — les 29 tests existants qui passent par `propose_block` ne voient
aucune difference tant que `Node` ne fournit pas la racine.

### 5.3 `src/node/node.py` — cablage

Dans `propose_block`, avant l'appel :

1. `self._replayer.sync_to(self._blockchain.height)` — rattrapage des
   blocs des autres (cout mesure ~2 ms) ;
2. `root = self._replayer.root_after(txs, ...)` sur les transactions du
   mempool qui iront dans le bloc ;
3. passage de `root` a `build_candidate_block`.

Difficulte reelle : au point 2 il faut **les memes transactions, dans le
meme ordre** que celles qui entreront dans le bloc. `Mempool.get_pending`
est deterministe (tri par `sender, nonce, tx_id`), mais appeler
`get_pending` deux fois — une fois pour la racine, une fois dans
`build_candidate_block` — laisse la porte ouverte a une transaction
arrivee entre les deux, donc a une racine qui ne correspond pas au bloc.
Il faut selectionner les transactions **une seule fois** et les passer
aux deux etapes. Cela implique soit un parametre `transactions=` explicite
sur `build_candidate_block`, soit un decoupage en deux temps. C'est le
point de conception le plus delicat du lot, et la question Q3 ci-dessous.

`_accept_block` n'est **pas** touche, conformement a la contrainte. Le
rattrapage se fait paresseusement, au moment ou on en a besoin.

### 5.4 Ou l'etat est-il construit ?

Dans `Node.from_config`, a cote de `ChainStorage`. Question ouverte Q1 :
faut-il rejouer toute la chaine **au demarrage** (0,4 a 10 s pour 10 000
blocs, mais un demarrage predictible) ou paresseusement au premier
`propose_block` (demarrage instantane, premiere proposition plus lente) ?
Je penche pour le rejeu au demarrage : un noeud qui met 3 s a demarrer
est preferable a un noeud qui rate son tour de proposition.

---

## 6. Ce que ce point 1 ne fait PAS

A dire clairement, pour ne pas laisser croire a une fonctionnalite qui
n'existerait pas :

- **Aucune verification cote receveur.** Un pair malveillant ou bogue
  peut annoncer n'importe quel `state_root` : il sera accepte. C'est le
  point 2, qui touche `validator.py`, et qui fera l'objet de sa propre
  analyse.
- **Les recus (`Receipt`) sont calcules puis jetes.** Rien ne les
  persiste ni ne les expose. Ce sera un travail ulterieur.
- **`gas_used` du bloc n'est pas inscrit** : `Block` n'a pas ce champ, et
  je ne propose pas de l'ajouter (ce serait un second changement de
  format, donc une seconde rupture des blocs existants).
- **Tant que le point 2 n'est pas fait, la chaine n'a pas de garantie
  d'etat.** Le `state_root` devient un champ *renseigne*, pas encore un
  champ *verifie*.

---

## 7. Questions a trancher avant que je code

**Q1 — Rejeu au demarrage ou paresseux ?**
Je recommande : au demarrage, dans `from_config`. Demarrage plus lent
mais previsible ; pas de risque de rater son tour.

**Q2 — `sync_to` inclut-elle le bloc de genese ?**
Je recommande : oui (no-op), pour que `applied_height == blockchain.height`.

**Q3 — Comment garantir que la racine porte sur exactement les
transactions du bloc ?**
Je recommande d'ajouter un parametre `transactions: Optional[Sequence]`
a `build_candidate_block` : si fourni, il est utilise tel quel au lieu
d'interroger le mempool. `Node` selectionne alors une seule fois, calcule
la racine sur cette liste, et passe la meme liste. C'est un second
parametre facultatif sur `consensus.py` — a valider, puisque ce fichier
est protege.

**Q4 — Un noeud sans py-evm doit-il encore pouvoir demarrer ?**
Aujourd'hui oui, et `block.py` a ete concu pour (constante dupliquee).
Si `Node.from_config` importe `src/evm/replay.py`, ce ne sera plus vrai.
Faut-il un import paresseux et un mode degrade (`state_root` vide), ou
py-evm devient-il une dependance dure du noeud ? Je recommande la
dependance dure : un mode degrade produirait des blocs a racine vide
indistinguables des vrais, donc des divergences muettes.

---

## 8. Ampleur du changement propose

| Fichier | Nature | Ampleur estimee |
|---|---|---|
| `src/evm/replay.py` | **creation** | ~120 l. |
| `src/node/consensus.py` | 1 a 2 parametres facultatifs + passage | ~6 l. |
| `src/node/node.py` | construction + 3 lignes dans `propose_block` | ~15 l. |
| `tests/unit/evm/test_replay.py` | **creation** | ~15 tests |
| Tests existants | **aucune modification attendue** | 0 |

Critere de fin : `pytest tests/unit/ tests/integration/` reste
integralement au vert (328 passed aujourd'hui, + les nouveaux), et deux
noeuds partant du meme genesis et rejouant la meme chaine obtiennent la
**meme** racine.

---

## 9. Ordre d'execution si vous validez

1. `src/evm/replay.py` + ses tests, **isolement** (aucun autre fichier
   touche) ; suite complete verte.
2. `consensus.py` : le ou les parametres facultatifs ; suite complete
   verte, comportement inchange par defaut.
3. `node.py` : le cablage ; suite complete verte.
4. Verification inter-VMs.

A chaque etape : `py_compile` -> tests du module -> suite complete.

---

# ETAPE 1 — REALISEE

Statut : `src/evm/replay.py` **ecrit et teste**. Aucun fichier existant
modifie. Les etapes 2 (`consensus.py`) et 3 (`node.py`) restent en
attente d'accord sur Q3.

## Correction apportee a l'analyse : §5.1 etait FAUX

L'analyse proposait `snapshot()` / `revert()` autour de `execute_block`
pour l'essai a blanc. **Verifie, cela ne fonctionne pas** :

    eth_utils.exceptions.ValidationError: No checkpoint 5 was found

Cause : `execute_block` se termine par `commit()`, qui appelle
`persist()` et invalide les points de restauration. Le `revert()`
consecutif echoue. C'est exactement le piege deja consigne dans les
notes de session a propos de `_apply`.

Solution retenue, mesuree et fonctionnelle : `at_root()`. On execute le
bloc candidat sur une **vue jetable** partageant la meme base de
donnees. Verification faite :

    racine simulee  : 44d67d3301ef6458
    racine reelle   : 44d67d3301ef6458      -> identiques
    etat principal inchange : True, nonce toujours a 0

Le point est documente dans la docstring de `root_after` pour que
personne ne « retablisse » un jour le snapshot/revert.

## Ce qui a ete livre

| Fichier | Etat | Taille |
|---|---|---|
| `src/evm/replay.py` | **cree** | 210 l. |
| `tests/unit/evm/test_replay.py` | **cree** | 24 tests |
| tout le reste | **intact** | — |

API de `StateReplayer` :

    StateReplayer(storage, state=None)
    .applied_height -> int          (-1 = NOTHING_APPLIED)
    .state_root     -> bytes
    .state          -> EVMState
    .sync_to(height) -> bytes       rattrapage incrementiel
    .root_after(txs, *, block_number, timestamp, coinbase) -> bytes

## Resultats

- `tests/unit/evm/test_replay.py` : **24 passed** en 0,64 s.
- Suite complete : **352 passed en 102 s** (328 avant + 24 nouveaux).
  Aucune regression, aucun test existant modifie.
- Convergence verifiee hors tests, sur 10 blocs : un noeud ayant suivi
  la chaine en direct et un noeud redemarre a froid obtiennent la
  **meme** racine `8801fe044251fd41e001...`.

## Choix appliques

- **Q1** — rejeu au demarrage : `sync_to` est concu pour, mais l'appel
  se fera a l'etape 3 dans `node.py`.
- **Q2** — la genese compte : `applied_height == 0` apres `sync_to(0)`,
  aligne sur `Blockchain.height`. Teste.
- **Reculer est refuse** (`StateError`) : cette chaine n'a pas de
  reorganisation, mieux vaut signaler que rendre une racine muette.
- Un echec en cours de rattrapage laisse le rejoueur coherent : ce qui
  etait applique le reste. Teste.

## Environnement (bac a sable)

py-evm et `oqs` avaient disparu entre les sessions. Reinstalles :
`pip install git+...py-evm@ffce74fa`, `rlp==4.1.0`,
`liboqs-python==0.16.0`, puis recreation des liens
`liboqs.so` / `liboqs.so.6` dans `~/_oqs/lib` (**jamais** de rebuild).
Sans rapport avec le code livre.

---

# ETAPES 2 ET 3 — REALISEES

Le POINT 1 (producteur) est **termine**. Un bloc contenant une
transaction inscrit desormais la racine reelle de l'etat, et cette
racine est couverte par la signature ML-DSA.

## Preuve de fonctionnement

    genesis racine vide ? True
    bloc 1 (vide)  : 56e81f171bcc55a6ff83  | vide ? True
    bloc 2 (1 tx)  : ab2f60f896eb3dbd5e10  | vide ? False
    signature couvre la racine : True

Un bloc vide conserve `EMPTY_STATE_ROOT` : c'est correct, rien n'a ete
ecrit dans l'etat.

## Etape 2 — `src/node/consensus.py`

Diff : **33 ajouts, 4 suppressions**, dont l'essentiel est de la
documentation. Deux parametres facultatifs :

    state_root: bytes = EMPTY_STATE_ROOT,
    transactions: Optional[Sequence[Transaction]] = None,

`EMPTY_STATE_ROOT` est importe de `src.blockchain.block`, **pas** de
`src.evm.state` : `consensus.py` ne doit pas dependre de py-evm pour ce
qui reste une regle d'ordonnancement. Les valeurs par defaut preservent
integralement le comportement anterieur.

## Etape 3 — `src/node/node.py`

- `__init__` accepte `state_replayer` (injectable pour les tests) et en
  construit un sinon, depuis `config.data_dir`.
- **Rejeu au demarrage** (Q1) : `sync_to(blockchain.height)` dans
  `__init__`.
- `propose_block` : rattrapage, puis selection **unique** des
  transactions, puis `root_after`, puis passage des deux au consensus.
- `_accept_block` **n'est pas touche**, conformement a la contrainte.

Reponse a Q4 appliquee : le replayer n'est jamais absent. Un `Node`
sans etat produirait des racines vides indiscernables de blocs
legitimement vides — la divergence resterait muette. py-evm devient
donc une dependance dure du noeud.

## Q3 — la fenetre de course, fermee

`propose_block` appelle `get_pending()` **une seule fois** et passe la
meme liste au calcul de la racine et a la construction du bloc. Sans
cela, une transaction arrivee entre les deux lectures aurait produit un
bloc dont la racine annoncee ne correspond pas au contenu : une cause de
fork qu'aucun test n'aurait detectee.

## Resultats

| Suite | Avant | Apres |
|---|---|---|
| `tests/unit/node/test_node.py` | 22 | **27** |
| Suite complete | 328 | **357 passed / 106 s** |

Les 29 tests existants passant par `propose_block` sont inchanges.
Aucun test existant modifie ; seuls 5 tests ont ete ajoutes a la fin de
`test_node.py`, plus 24 dans `test_replay.py`.

## Ce qui reste faux a ce stade

**Le receveur ne verifie toujours rien.** Un pair peut annoncer
n'importe quelle racine : elle sera acceptee. C'est le POINT 2, qui
touche `validator.py` et fera l'objet de son analyse propre.
