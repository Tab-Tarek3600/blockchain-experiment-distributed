# Installation de l'environnement sur les 3 machines

Procédure à exécuter **à l'identique** sur `node1` (VM1), `node2` (VM2) et
`node3` (machine physique).

L'objectif est que les trois machines exécutent exactement le même
environnement. Une divergence de version de `liboqs` peut modifier le
comportement des signatures ML-DSA et provoquer des rejets de blocs
inter-nœuds difficiles à diagnostiquer.

---

## 0. Pourquoi cette page existe

`pip install liboqs-python` **ne suffit pas**.

`liboqs-python` est un simple binding `ctypes`. Il ne contient aucun code
cryptographique : il charge à l'exécution une bibliothèque native
`liboqs.so` qui doit déjà être installée sur le système. Si elle est
absente ou introuvable, l'erreur est :

```
ModuleNotFoundError: No module named 'oqs'
```

ou, une fois le paquet pip installé mais la bibliothèque native absente :

```
OSError: liboqs.so: cannot open shared object file
```

---

## 1. Prérequis système

| Élément | Version | Vérification |
|---|---|---|
| Python | 3.12+ | `python3 --version` |
| CMake | 3.16+ | `cmake --version` |
| Compilateur C | gcc ou clang | `gcc --version` |
| Ninja *(optionnel)* | — | accélère la compilation |
| Git | — | `git --version` |

Sur Debian / Ubuntu :

```bash
sudo apt update
sudo apt install -y cmake gcc ninja-build git python3-dev python3-pip
```

---

## 2. Compilation de liboqs (bibliothèque native)

Version cible : **0.16.0**, identique sur les trois machines.

```bash
git clone --branch 0.16.0 --depth 1 https://github.com/open-quantum-safe/liboqs.git
cd liboqs
mkdir build && cd build

cmake -GNinja \
      -DCMAKE_INSTALL_PREFIX="$HOME/_oqs" \
      -DBUILD_SHARED_LIBS=ON \
      -DOQS_BUILD_ONLY_LIB=ON \
      ..

ninja
ninja install
```

> **Mémoire :** la compilation complète est coûteuse. Sur une VM à faible
> RAM elle peut être tuée par le OOM killer aux alentours de 70–75 %.
> Dans ce cas, limiter le parallélisme : `ninja -j2`, voire `ninja -j1`.
> Prévoir au moins 2 Go de RAM, ou ajouter du swap.

Résultat attendu :

```
$HOME/_oqs/
├── include/oqs/...
└── lib/liboqs.so.0.16.0
```

---

## 3. Symlinks — étape indispensable

Le chargeur cherche `liboqs.so` et `liboqs.so.6`, **pas** le fichier
versionné complet. `ninja install` ne les crée pas toujours. À vérifier
systématiquement :

```bash
cd "$HOME/_oqs/lib"
ls -l

# Créer les liens manquants (sans écraser ceux qui existent) :
[ -e liboqs.so ]   || ln -s liboqs.so.0.16.0 liboqs.so
[ -e liboqs.so.6 ] || ln -s liboqs.so.0.16.0 liboqs.so.6
```

Attendu :

```
liboqs.so     -> liboqs.so.0.16.0
liboqs.so.6   -> liboqs.so.0.16.0
liboqs.so.0.16.0
```

**C'est la cause n°1 d'échec de `import oqs`.**

---

## 4. Dépendances Python

```bash
cd /chemin/vers/le/depot
pip install -r requirements.txt
```

---

## 5. Rendre liboqs trouvable

Le binding lit la variable **`OQS_INSTALL_PATH`** (chemin du préfixe
d'installation). C'est la méthode recommandée, plus fiable que
`LD_LIBRARY_PATH` seul.

Ajouter à `~/.bashrc` sur les trois machines :

```bash
export OQS_INSTALL_PATH="$HOME/_oqs"
export LD_LIBRARY_PATH="$HOME/_oqs/lib:$LD_LIBRARY_PATH"
```

Puis :

```bash
source ~/.bashrc
```

Alternative permanente, à l'échelle du système :

```bash
echo "$HOME/_oqs/lib" | sudo tee /etc/ld.so.conf.d/liboqs.conf
sudo ldconfig
```

---

## 6. Vérification

À exécuter sur **chacune** des trois machines. Les trois doivent produire
une sortie strictement identique.

```bash
python3 -c "
import oqs
print('liboqs      :', oqs.oqs_version())
print('ML-DSA-44   :', 'ML-DSA-44'  in oqs.get_enabled_sig_mechanisms())
print('ML-KEM-768  :', 'ML-KEM-768' in oqs.get_enabled_kem_mechanisms())
"
```

Sortie attendue :

```
liboqs      : 0.16.0
ML-DSA-44   : True
ML-KEM-768  : True
```

Puis la suite de tests, depuis la racine du dépôt :

```bash
python3 -m pytest tests/ -q
```

Attendu : **103 passed**, sur les trois machines.

Si le nombre diffère d'une machine à l'autre, **s'arrêter** : ne pas
poursuivre le déploiement tant que les trois environnements ne sont pas
identiques.

---

## 7. Diagnostic

| Symptôme | Cause | Correction |
|---|---|---|
| `ModuleNotFoundError: No module named 'oqs'` | paquet pip absent | `pip install -r requirements.txt` |
| `OSError: liboqs.so: cannot open shared object file` | symlinks manquants | étape 3 |
| `import oqs` OK en shell, échec sous pytest | environnement non exporté | `OQS_INSTALL_PATH` dans `~/.bashrc`, puis `source` |
| Compilation tuée vers 70 % | OOM | `ninja -j1`, ou ajouter du swap |
| `ML-DSA-44 : False` | liboqs trop ancien | recompiler en 0.16.0 |
| Version liboqs différente entre machines | installations divergentes | recompiler à l'identique — **bloquant** |

---

## 8. Note sur l'environnement de développement jetable

Sur un bac à sable dont le système de fichiers n'est pas intégralement
persistant, `liboqs-python` peut disparaître entre deux sessions alors que
`$HOME/_oqs/lib` subsiste. Dans ce cas, **ne pas recompiler liboqs** :

```bash
pip install liboqs-python==0.16.0
cd "$HOME/_oqs/lib"
[ -e liboqs.so ]   || ln -s liboqs.so.0.16.0 liboqs.so
[ -e liboqs.so.6 ] || ln -s liboqs.so.0.16.0 liboqs.so.6
```

Cela ne concerne pas les trois machines de déploiement, où l'installation
est permanente.
