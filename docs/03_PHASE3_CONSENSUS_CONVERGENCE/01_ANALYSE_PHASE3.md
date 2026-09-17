# PHASE 3 — EVM : analyse préalable

**Aucun code de production n'a été écrit.** Ce document résulte de
l'inspection du dépôt et de trois prototypes jetables exécutés dans un
venv isolé (`/tmp/evmtest`), hors du projet. Les résultats cités sont
des exécutions réelles, pas des suppositions.

Prérequis validé : la PHASE 2 est terminée, les 10 critères sont
satisfaits, `pytest tests/ -q` passe. La PHASE 3 peut donc s'ouvrir.

---

## A. Ce qui est réellement terminé

| Brique | État | Ce que la PHASE 3 peut en attendre |
|---|---|---|
| `Transaction` | ✅ | `sender`/`recipient` sur **20 octets** — déjà au format adresse EVM. Champs `value`, `gas_limit`, `gas_price`, `data` déjà présents et validés. |
| `Block` | ✅ | `frozen`, `to_dict`/`from_dict` stables, transactions ordonnées en tuple. |
| `Blockchain` + `ChainStorage` | ✅ | Chaîne rejouable depuis le disque : `get_block(h)` pour tout `h`. |
| `Node._accept_block` | ✅ | Point d'entrée unique et déterministe de tout bloc dans la chaîne. |
| Consensus PoA | ✅ | Ordre des blocs déterministe et identique sur les 3 nœuds. |
| ML-DSA | ✅ | Signature de bloc et de transaction vérifiées à l'acceptation. |
| Réseau 3 VMs | ✅ | Propagation et convergence prouvées (h=55, md5 identiques). |
| `src/evm/` | vide | Répertoire réservé, un `.gitkeep`, **aucun import nulle part**. |

Trois propriétés de la PHASE 1 sont des cadeaux pour l'EVM, et il faut
en avoir conscience avant de concevoir quoi que ce soit :

1. **Les adresses font déjà 20 octets.** `public_key_to_address()`
   tronque le SHA-256 de la clé publique ML-DSA aux 20 derniers octets.
   C'est exactement la largeur d'une adresse EVM. Aucune conversion,
   aucun mapping à maintenir.
2. **`Transaction` porte déjà tous les champs EVM utiles.** Ils sont
   validés structurellement mais **actuellement ignorés** : rien ne lit
   `value`, `gas_limit`, `gas_price` ni `data` aujourd'hui.
3. **L'ordre des transactions est déjà déterministe** : tuple figé dans
   un bloc figé, dans une chaîne au consensus déterministe.

---

## B. Ce qui est réellement absent

Rien de la PHASE 3 n'existe. Précisément :

- **Aucun modèle de compte.** Pas de balance, pas de nonce persistant,
  pas de code, pas de stockage. `Transaction.value` ne déplace rien :
  une transaction est aujourd'hui une donnée signée et rien de plus.
- **Aucune exécution.** Aucun opcode n'est interprété.
- **Aucune base d'état** ni racine d'état.
- **Aucun reçu** (`Receipt`), donc aucun moyen de savoir si une
  transaction a réussi, combien de gas elle a consommé, ni ce qu'elle a
  renvoyé.
- **Aucune dépendance EVM installée** : `requirements.txt` interdit
  explicitement `py-evm` avant cette phase.
- **Aucun compilateur Solidity** dans la chaîne d'outils.

Il manque aussi, et c'est le point structurant, **un engagement
cryptographique sur l'état** : `Block` n'a pas de champ `state_root`, et
`src/blockchain/` est déclaré stable. Voir la décision D3.

---

## C. Problèmes et risques identifiés

### C1 — Le `state_root` n'a nulle part où aller *(bloquant, décision requise)*

Sans racine d'état dans l'en-tête du bloc, deux nœuds peuvent accepter
exactement la même chaîne tout en calculant des états **divergents**,
sans que personne ne le détecte. Le consensus porterait sur l'ordre des
transactions, jamais sur le résultat de leur exécution.

Ajouter le champ impose de toucher `Block` — donc `to_bytes`,
`signing_hash`, `to_dict`/`from_dict`, le genesis et la sérialisation
réseau. C'est précisément ce que vos consignes interdisent sans
discussion préalable. **Trois options en D3.**

### C2 — Rester en Python 3.12 *(résolu — contrainte à respecter)*

**Le `requirements.txt` du dépôt fait autorité** ; il épingle py-evm sur
le commit `ffce74fa` (= version 0.12.1-beta.1, sur `main`, 2025-09-08).
Ce commit est immuable, contrairement à une beta PyPI republiable.

L'environnement est **déjà installé sur les VMs**. Aucun kit hors ligne
n'est nécessaire.

Contrainte à ne pas franchir : **`pandas==2.2.0` n'a pas de wheel
cp313.**

| version | cp312 | cp313 |
|---|---|---|
| pandas 2.2.0 → 2.2.2 | oui | **non** |
| pandas 2.2.3 | oui | oui |

Sur un Python 3.13, `pip` compile pandas depuis les sources : très long
et gourmand en mémoire. Une tentative dans ce sandbox (2 Go) a saturé la
RAM et dû être interrompue. Sur une VM modeste, le résultat serait le
même.

**Conclusion : rester en Python 3.12 sur les trois VMs.** Pour passer à
3.13, il faudrait d'abord monter pandas à 2.2.3.

### C3 — Le gas n'a personne pour le payer

Toutes les balances valent zéro. Si l'on facture le gas, aucune
transaction ne passe. Il faut soit une allocation genesis, soit
accepter `gas_price = 0`. Voir D5.

### C4 — Une exécution qui échoue ne doit pas rejeter le bloc

Si un nœud rejetait un bloc parce qu'une transaction a échoué à
l'exécution, la moindre divergence d'implémentation provoquerait un
fork. Une transaction qui `revert` est un **fait**, pas une erreur de
consensus : elle reste dans le bloc, avec un reçu en échec. Cette règle
doit être posée explicitement dans le code, pas déduite.

### C5 — `py-evm` est en bêta permanente

Version épinglée : commit **`ffce74fa`** (= 0.12.1-beta.1). Épingler un
SHA plutôt qu'une beta PyPI est le bon réflexe : une beta peut être
republiée sous le même numéro, pas un commit. L'API n'est pas figée et les
`Computation` ont des pièges (`comp.error` lève une `AttributeError` ;
il faut `is_success` / `is_error`). D'où la couche d'isolation en D2 :
un seul module du projet doit connaître `eth.*`.

### C6 — Solidity absent, et hors ligne

Compiler `PatientRegistry.sol` (PHASE 4) demandera `solc` ou `py-solc-x`
— qui télécharge son binaire. Sur des VMs sans DNS, il faudra
transporter le binaire `solc` à la main. **La PHASE 3 n'en a pas besoin :
elle se valide entièrement avec du bytecode écrit à la main.**

---

## D. Architecture proposée

### D0 — Faisabilité prouvée

La question déterminante était : *peut-on utiliser le moteur
d'exécution de py-evm sans sa couche transaction, qui impose RLP et des
signatures ECDSA ?* Si la réponse était non, py-evm était inutilisable
ici, puisque nos transactions sont signées en ML-DSA.

**La réponse est oui.** Prototype exécuté :

```
StateClass: ShanghaiState
deploy success: True
deployed code: 602a60005260206000f3
contract addr: 2222222222222222222222222222222222222222
call success: True
returned: 42
gas used: 18
```

En pilotant `State` + `Message` + `computation_class` directement, on
contourne entièrement `eth.rlp.transactions`. **Aucune clé ECDSA n'entre
dans le système. La signature reste 100 % ML-DSA.**

Trois propriétés supplémentaires ont été vérifiées :

```
--- session 2 : nouvel objet State, meme backend + meme root ---
slot0 relu: 7
SLOAD renvoie: 7
--- determinisme : meme sequence => meme root ---
root reproduit: 4ca3dcca78999b419eb82cc5 | identique: True
--- revert : OOG ne doit rien ecrire ---
is_error: True | slot0 apres echec: 0
```

Persistance du stockage, **déterminisme de la racine d'état** (deux
exécutions indépendantes de la même séquence donnent le même root — la
condition sine qua non d'un consensus sur l'état), et atomicité du
revert.

### D1 — Position dans l'architecture

```
                  Node._accept_block()   ← INTOUCHABLE
                          │
      1. validate_block_for_acceptance   (ML-DSA)
      2. is_expected_proposer            (PoA)
      3. blockchain.add_block            (persistance)
      4. mempool.remove_transactions
      5. p2p.broadcast_block
                          │
                          ▼
              ┌───────────────────────┐
              │   src/evm/executor    │  ← NOUVEAU, en aval
              │   EVMExecutor         │
              └───────────┬───────────┘
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   src/evm/state     src/evm/receipt    src/evm/addresses
   WorldState         Receipt           dérivation contrat
        │
        ▼
   py-evm : ShanghaiState + AccountDB + trie
```

**L'EVM est strictement en aval du consensus.** Elle ne peut pas
influencer l'acceptation d'un bloc. `src/blockchain/` reste intact,
`src/crypto/` reste intact, la validation ML-DSA reste intacte.

### D2 — Règle d'isolation

`import eth.*` n'est autorisé **que** dans `src/evm/state.py`. Tout le
reste du projet manipule `WorldState`, `Receipt` et `EVMExecutor`. Si
py-evm casse son API en 0.13, un seul fichier est à reprendre.

### D3 — Où va le `state_root` ? *(à décider)*

| Option | Modification | Détection d'une divergence | Verdict |
|---|---|---|---|
| **1. Hors chaîne** | aucune | manuelle : comparer les roots entre VMs | recommandé pour la PHASE 3 |
| **2. Champ `Block.state_root`** | `block.py`, genesis, sérialisation, tests | automatique, au consensus | correct, mais casse la PHASE 1 |
| **3. Transaction système** | conventions dans `data` | automatique, mais bricolée | rejeté |

**Recommandation : option 1 pour la PHASE 3.** Elle apporte l'exécution
et l'état sans toucher une ligne de `src/blockchain/`. Le nœud
journalise sa racine à chaque bloc :

```
INFO [evm] block h=12 executed: 3 tx, 2 ok, 1 reverted, state_root=4ca3dcca...
```

Comparer trois logs suffit à prouver la convergence de l'état, comme les
`md5sum` ont prouvé celle de la chaîne en PHASE 2. On rebasculera vers
l'option 2 au moment voulu, en pleine connaissance de son coût.

### D4 — Où l'exécution est-elle déclenchée ? *(à décider)*

`_accept_block` est intouchable, mais l'état doit suivre la chaîne.

- **D4-a — Rejeu à la demande.** `EVMExecutor` lit la chaîne depuis
  `ChainStorage` et calcule l'état jusqu'à la hauteur *h*. **Zéro
  modification de `node.py`.** L'état est reconstruit au démarrage puis
  maintenu par appels explicites. Le plus propre en termes de couplage.
- **D4-b — Hook optionnel.** `Node` reçoit un `executor=None` ; une
  **étape 6** est ajoutée à `_accept_block`, après le broadcast :
  ```python
  if self._executor is not None:
      self._executor.apply_block(block)   # ne lève jamais
  ```
  Trois lignes, en fin de pipeline, sans effet sur l'acceptation. Mais
  cela modifie une fonction que vous avez déclarée figée. **Je ne le
  ferai pas sans votre accord explicite.**

**Recommandation : D4-a d'abord**, testable seul, puis D4-b si le rejeu
devient trop lent.

### D5 — Modèle économique

| Question | Proposition |
|---|---|
| Fork EVM | **Shanghai** — post-Merge, sans blobs (Cancun) ni nouveautés instables (Prague). |
| `chain_id` | `1337` (réseau privé), fixé en configuration. |
| `gas_price = 0` | **accepté** : réseau permissionné, pas de marché des frais. |
| `gas_price > 0` | débité du `sender`, crédité au `block.validator`. |
| Balance insuffisante | reçu en échec, bloc valide. |
| `nonce` | doit égaler le nonce du compte, sinon reçu en échec. |
| Déploiement | `recipient == b"\x00" * 20` ⇒ `data` est l'initcode. |
| Adresse de contrat | dérivée de `keccak(sender ‖ nonce)` — py-evm exige un `create_address` explicite. |
| Gas limite de bloc | constante `BLOCK_GAS_LIMIT` côté executor, hors consensus. |
| Allocation genesis | facultative, via `evm_genesis_alloc` dans le YAML, **identique sur les 3 VMs**. |

---

## E. Fichiers à créer et à modifier

### À créer

| Fichier | Responsabilité | Taille estimée |
|---|---|---|
| `src/evm/__init__.py` | exports publics | ~15 l. |
| `src/evm/state.py` | `WorldState` : **seul** point de contact avec py-evm. Balances, nonces, code, stockage, `state_root`, snapshot/revert. | ~200 l. |
| `src/evm/executor.py` | `EVMExecutor` : `apply_transaction()`, `apply_block()`, `replay_from_chain()`. Traduit `Transaction` → `Message`. | ~250 l. |
| `src/evm/receipt.py` | `Receipt` frozen : `tx_id`, `status`, `gas_used`, `output`, `contract_address`, `error`. | ~80 l. |
| `src/evm/addresses.py` | dérivation d'adresse de contrat, `ZERO_ADDRESS`, aides de conversion. | ~50 l. |
| `src/evm/errors.py` | `EVMError` et sous-classes. | ~30 l. |

### À modifier

| Fichier | Modification | Risque |
|---|---|---|
| `requirements.txt` | **déjà à jour** (py-evm épinglé sur `ffce74fa`) | néant |
| `src/node/config.py` | *facultatif* : `evm_genesis_alloc` | faible |
| `src/node/node.py` | **uniquement si D4-b est retenu** — 3 lignes | à valider par vous |

### À ne pas toucher

`src/blockchain/` (sauf décision D3-2 explicite), `src/crypto/`,
`validator.py`, `consensus.py`, `mempool.py`, `socket_p2p.py`, `p2p.py`,
`main.py`.

---

## F. Tests prévus

| Fichier | Contenu | Nb estimé |
|---|---|---|
| `tests/unit/evm/test_addresses.py` | dérivation, déterminisme, `ZERO_ADDRESS`, longueur 20 | ~8 |
| `tests/unit/evm/test_receipt.py` | immutabilité, sérialisation, succès/échec | ~10 |
| `tests/unit/evm/test_state.py` | balance, nonce, code, stockage, `state_root` déterministe, snapshot/revert, persistance | ~25 |
| `tests/unit/evm/test_executor.py` | transfert de valeur, déploiement, appel, revert, OOG, nonce erroné, solde insuffisant, gas facturé au validateur, `apply_block` | ~35 |
| `tests/integration/test_evm_replay.py` | rejeu d'une chaîne persistée ⇒ même `state_root` | ~5 |
| `tests/integration/test_evm_determinism.py` | deux exécuteurs indépendants, mêmes blocs ⇒ même root | ~4 |

Environ **85 tests** ; cible ≈ **235** dans le sandbox, ≈ **435** dans
votre dépôt.

Contraintes maintenues : docstrings en français, séparateurs
`# --- section ---`, imports absolus `from src.…`, aucun `conftest.py`,
bytecode écrit à la main (jamais de `solc` en PHASE 3), exécution en
mémoire.

---

## G. Critères de validation de la PHASE 3

| # | Critère | Vérification |
|---|---|---|
| 1 | Aucune régression | `pytest tests/ -q` : les 148 tests actuels passent toujours |
| 2 | py-evm cloisonné | `grep -rn "import eth" src/ \| grep -v "src/evm/state.py"` ⇒ vide |
| 3 | Chaîne intacte | `git diff --stat src/blockchain/` ⇒ vide |
| 4 | ML-DSA intacte | aucune clé ECDSA nulle part ; signatures inchangées |
| 5 | Transfert de valeur | balance débitée/créditée, nonce incrémenté |
| 6 | Déploiement | code déployé lisible via `get_code()`, adresse déterministe |
| 7 | Appel de contrat | `SSTORE` puis `SLOAD` renvoient la valeur écrite |
| 8 | Revert atomique | échec ⇒ aucune écriture, gas consommé, bloc toujours valide |
| 9 | Déterminisme | deux exécuteurs, mêmes blocs ⇒ **`state_root` identique** |
| 10 | Rejeu | état reconstruit depuis le disque ⇒ même root qu'en direct |
| 11 | Isolation du consensus | une tx qui revert ne fait jamais rejeter un bloc |
| 12 | Convergence 3 VMs | même `state_root` journalisé sur les 3 nœuds à hauteur égale |

Les critères 1 à 11 se valident **en local**. Seul le 12 exige les VMs
— on ne les mobilise qu'une fois le reste vert.

---

## Décisions attendues avant d'écrire la moindre ligne

1. **D3** — `state_root` hors chaîne (recommandé) ou champ dans `Block` ?
2. **D4** — rejeu à la demande (recommandé) ou hook dans `_accept_block` ?
3. **C2** — quelle version de Python sur les trois VMs ?
