# D3 — Ajout de `state_root` à `Block` : APPLIQUÉ

**Statut : APPLIQUÉ le 2026-08-22 après accord (anciens blocs supprimés côté
utilisateur, les 3 nœuds repartent de zéro).**

- Sauvegarde : `/home/user/_backups/block.py.avantD3-20260822-223122`
- Archive PHASE 2 : `/home/user/_backups/PHASE2-avant-D3-20260822.tar.gz`
- Diff réel appliqué : **7 ajouts, 0 suppression, 1 fichier** — identique à la
  proposition relue ci-dessous.
- Tests : **328 passés** (310 unitaires + 18 intégration), **aucun test modifié**.
- Garde anti-divergence de la constante dupliquée :
  `test_state_root_vide_coherent_avec_block` — vérifié en le faisant échouer
  volontairement, puis restauré.

---

## 1. Ce que ça change

`state_root` devient un champ de `Block`, inclus dans `to_bytes()` **côté non signé**.
Conséquence directe : il entre dans `signing_hash` **et** dans `block_hash`.

Vérifié par exécution :

| Propriété | Résultat |
|---|---|
| `signing_hash` change si `state_root` change | ✅ |
| `block_hash` change si `state_root` change | ✅ |
| Signature ML-DSA valide sur un bloc honnête | ✅ |
| Signature **rejetée** si `state_root` falsifié après signature | ✅ |
| `to_dict()` → `from_dict()` redonne le même `block_hash` | ✅ |
| `state_root` du genesis = `EMPTY_STATE_ROOT` | ✅ |

Le dernier point du tableau est l'objectif réel de D3 : un validateur ne peut plus
annoncer un état qu'il n'a pas calculé, la racine étant couverte par sa signature.

## 2. Coût réel : 13 lignes, 6 sites

Contrairement à ce qui était prévu, **aucun test n'a besoin d'être modifié**.
La suite passe à **310/310** sur la copie patchée, sans y toucher.

La raison est le choix d'un **défaut** `state_root: bytes = EMPTY_STATE_ROOT` :
tout appelant existant (`genesis.py` l.61, `consensus.py` l.166, les 6 constructions
directes `Block(...)` dans `test_sync.py` / `test_socket_p2p.py`) continue de
fonctionner sans changement. Les sites listés dans l'analyse initiale comme
« à modifier » n'ont donc pas eu à l'être.

Les 6 sites touchés, tous dans `block.py` :

1. constante `EMPTY_STATE_ROOT`
2. champ de la dataclass
3. paramètre de `create()` + passage au constructeur
4. `to_bytes()` — **le seul changement à conséquence cryptographique**
5. `validate_structure()` — réutilise `_validate_hash_field` (32 octets)
6. `to_dict()` / `from_dict()`

## 3. Décision à trancher : la constante est dupliquée

`EMPTY_STATE_ROOT` est **écrite en dur** dans `block.py` plutôt qu'importée de
`src/evm/state.py`.

C'est délibéré : `src/blockchain/` ne doit dépendre ni de la couche EVM ni de
py-evm. Un `from src.evm.state import EMPTY_STATE_ROOT` ferait remonter py-evm
dans le cœur PHASE 1, et un nœud ne pourrait plus charger un bloc sans py-evm
installé.

Le prix est une valeur dupliquée en deux endroits. **À couvrir par un test**
d'égalité entre les deux constantes (dans `tests/unit/evm/`, qui a déjà le droit
d'importer les deux), pour qu'une divergence soit détectée à la seconde près
plutôt que sur trois VMs en production.

## 4. Rupture de compatibilité — le point bloquant

```
relecture d'un bloc PHASE 2 (JSON sans "state_root") : ROMPUE
  -> BlockError: missing field in block dict: 'state_root'
```

C'est **volontaire et souhaitable** : accepter un bloc sans `state_root` en lui
attribuant une valeur par défaut reviendrait à accepter un bloc dont l'état n'a
jamais été validé. Un rejet franc vaut mieux qu'une acceptation silencieuse.

Mais cela implique, sans exception :

- les 3 VMs sont mises à jour **ensemble** ;
- `data/` est **réinitialisé** sur les 3 (les blocs existants sont illisibles) ;
- le genesis est régénéré à l'identique sur les 3 ;
- **le tag PHASE 2 doit être figé AVANT**, sinon il n'y a plus de point de retour.

Ce dernier point est le seul vrai blocage. Le sandbox n'est pas un dépôt git
(`fatal: not a git repository`) : le tag ne peut être posé que de votre côté.

## 4 bis. Résultat après application

```
GENESIS
  state_root : 56e81f171bcc55a6ff8345e692c0f86e ...   (== EMPTY_STATE_ROOT)
  block_hash : e0e0eb796b579e4e3047aa3fb7535bc62a88b69213c2adead694a6c6f8988cf8

PROPRIETE D3 -- le state_root est couvert par la signature
  signature valide sur le bloc honnete    : True
  signature REJETEE si state_root modifie : True

PERSISTANCE
  roundtrip to_dict/from_dict identique   : True
```

Le `block_hash` du genesis ci-dessus dépend de la clé publique du validateur
genesis : ce n'est pas une valeur de référence à recopier, seulement la preuve
que la chaîne se construit. **Les 3 VMs doivent partager le même genesis**
(même clé publique, même timestamp) pour obtenir le même hash.

## 5. Ce que D3 ne fait pas encore

Ce patch ajoute le **champ** et le fait entrer dans la signature. Il ne branche
rien : personne ne calcule encore la valeur, et aucune validation ne vérifie que
le `state_root` annoncé correspond au rejeu. C'est l'étape suivante
(`consensus.build_candidate_block` côté producteur, validation côté receveur),
volontairement séparée pour que ce diff-ci reste vérifiable d'un coup d'œil.
