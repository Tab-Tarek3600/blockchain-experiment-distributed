# Étape 4d — Diagnostic des échecs sur les VMs

Bonne nouvelle d'abord : **aucun de ces échecs n'est un bug de code.**
Ce sont trois problèmes de **fichiers pas à jour** sur les VMs.

---

## Ce que disent les captures

| VM | Résultat | Nature |
|---|---|---|
| node1 | 7 failed, 573 passed | anciens fichiers de tests |
| node2 | 24 failed, 13 passed | `consensus.py` pas copié |
| node3 | idem node2 | `consensus.py` pas copié |

Et un indice décisif : **573 + 7 = 580 tests sur node1**, alors que
j'en ai 385. Les VMs ont donc des fichiers que je n'ai pas.

---

## Problème 1 — node2 et node3 : `consensus.py` n'a pas été copié

**Symptôme** (24 fois) :

```
TypeError: Consensus.build_candidate_block() got an unexpected
           keyword argument 'state_root'
```

**Cause.** `node.py` (neuf, copié) appelle `build_candidate_block(...,
state_root=...)`, mais `consensus.py` (ancien, pas copié) ne connaît
pas encore ce paramètre. Les deux fichiers ne sont pas de la même
génération.

Chez moi, `consensus.py` accepte bien `state_root` (ligne 123). Le
fichier est donc correct — il n'est simplement **jamais arrivé** sur
node2 et node3.

**Pourquoi node1 n'a pas ce problème** : node1 est la machine
d'origine, ses fichiers `src/` sont déjà à jour. Cela confirme que
c'est bien un défaut de copie, pas un défaut de code.

---

## Problème 2 — les 3 VMs : `test_executor.py` est l'ancienne version

**Symptôme** (6 échecs, tous du même type) :

```
test_bloc_depassant_le_plafond_est_refuse ....... DID NOT RAISE
test_le_refus_intervient_avant_toute_execution .. assert 500 == 0
test_le_plafond_porte_sur_le_gas_annonce_non_consomme  DID NOT RAISE
test_bloc_hostile_...est_ecarte_sans_calcul ..... refus trop lent (5.93s)
```

**Cause.** Ces tests appartiennent à l'**ancienne** version, celle qui
vérifiait le gas *annoncé*. Nous avons justement corrigé ce
comportement (correctif A) : le plafond porte désormais sur le gas
*consommé*. Ces tests échouent donc **parce que le correctif
fonctionne**.

Vérification faite chez moi : ces trois noms de tests **n'existent
plus**. Ils ont été remplacés.

`refus trop lent (5.93s)` est particulièrement parlant : l'ancien test
exigeait un refus en moins d'1 s (rejet a priori). Le nouveau
comportement exécute le bloc jusqu'à épuisement du pool — c'est voulu,
et le nouveau test tolère 30 s.

| Ancien test (sur les VMs) | Remplacé chez moi par |
|---|---|
| `..._intervient_avant_toute_execution` | `test_une_transaction_trop_grosse_pour_le_solde_restant_est_refusee` |
| `..._ecarte_sans_calcul` | `test_bloc_hostile_en_boucle_infinie_est_borne` |
| `..._porte_sur_le_gas_annonce_non_consomme` | `test_le_plafond_porte_sur_le_gas_consomme_non_annonce` |

---

## Problème 3 — un fichier que je n'ai pas

```
FAILED tests/unit/blockchain/test_block_serialization.py::
       test_to_dict_contains_expected_keys
AssertionError: assert {'height', 'p...actions', ...}
                    == {'height', 'p...lidator', ...}
```

**Ce fichier n'existe pas dans mon espace de travail.** Mon
`tests/unit/blockchain/` ne contient qu'un `__init__.py` vide.

C'est cohérent avec l'écart de décompte : **580 tests sur les VMs
contre 385 chez moi**, soit ~195 tests que je n'ai jamais vus.

L'échec lui-même est attendu : ce test compare la liste des clés d'un
bloc sérialisé, et nous avons **ajouté `state_root`** au bloc en D3.
C'est la rupture de format assumée. Le test doit être mis à jour pour
inclure la nouvelle clé.

**Je ne peux pas le corriger sans le voir.** Il me le faut.

---

## Ce que cela dit de l'étape 4b

La copie a été **partielle**. `node.py` est passé, `consensus.py` non ;
`test_node.py` est passé, `test_executor.py` non — ou dans le mauvais
ordre.

C'est exactement ce que l'étape **4c** (contrôle `sha256sum`) devait
détecter **avant** de lancer les tests. Elle a été sautée, ou elle a
signalé des `FAILED` qui sont passés inaperçus.

---

## Correction, dans l'ordre

### A. Refaire la copie proprement sur node2 et node3

Le fichier vraiment critique est `consensus.py` :

```bash
cd ~/blockchain-experiment-distributed
P=blockchain-experiment-distributed

scp src/node/consensus.py ismail@192.168.168.102:$P/src/node/consensus.py
scp src/node/consensus.py ismail@192.168.168.103:$P/src/node/consensus.py
```

### B. Renvoyer `test_executor.py` sur les 3 VMs

Sur node1 il est ancien aussi. Depuis la machine qui a la bonne
version :

```bash
scp tests/unit/evm/test_executor.py ismail@192.168.168.102:$P/tests/unit/evm/test_executor.py
scp tests/unit/evm/test_executor.py ismail@192.168.168.103:$P/tests/unit/evm/test_executor.py
```

Pour node1, remplacer le fichier localement par celui du manifeste.

### C. Faire le contrôle 4c, cette fois sans le sauter

Sur **chaque** VM :

```bash
cd ~/blockchain-experiment-distributed
sha256sum -c scripts/setup/MANIFEST-phase3.sha256
```

**20 lignes `OK` attendues.** S'il reste un seul `FAILED`, ne pas
lancer les tests : recopier le fichier concerné d'abord.

Références de contrôle :

```
88ca5a938db2710884120965efd7e52359577ff64c5ffc980f4f2af72031c34a  src/evm/executor.py
3149630cd0b34c93b52ad7811fa5c29384c399d17b0380f7002a008f2d0cadd5  src/node/consensus.py
f122f506b2fd8062a539d8e06bda64ffdf2b8e72ed70911a900d78a404fa99d9  tests/unit/evm/test_executor.py
6728979509a5abeb3e7a92b231db0b6698a06e8a37d5bd46ce3a5e6cf6641988  tests/unit/node/test_node.py
```

### D. M'envoyer le fichier manquant

```bash
cat tests/unit/blockchain/test_block_serialization.py
```

Copiez-moi la sortie. Et pour mesurer l'écart complet :

```bash
ls -1 tests/unit/blockchain/ tests/unit/crypto/
```

---

## Point positif

**573 tests passent déjà sur node1**, et py-evm y fonctionne (sinon
aucun test EVM n'aurait pu s'exécuter). Le blocage que je redoutais en
4a n'existe pas : l'environnement des VMs est sain.
