# Remplacer `block.py` sur les 3 VMs (D3 — `state_root`)

## Référence du fichier attendu

| Contrôle | Valeur |
|---|---|
| SHA-256 | `2dbe88df59b9e44e085310cf0cdeeb94bc57880b33a33f64aae9381b83b66b0a` |
| Taille | 12842 octets |
| Lignes | 344 |
| Fins de ligne | LF (Unix) — **pas** de CRLF, pas de BOM |

Si le SHA-256 ne correspond pas après copie, la cause la plus probable est la
clé USB Windows qui a converti les fins de ligne. Le `sed` de l'étape 3 le
corrige, et le hash redevient correct.

---

## Bonne nouvelle : `block.py` seul suffit

`block.py` **ne dépend pas** de py-evm ni de `src/evm/`. La constante
`EMPTY_STATE_ROOT` y est écrite en dur exprès. Vous pouvez donc mettre à jour
ce seul fichier : les 3 nœuds démarreront et se synchroniseront sans que
py-evm soit installé sur les VMs.

L'EVM (`src/evm/`) ne sera nécessaire que lorsqu'on branchera le calcul réel
du `state_root`.

---

## Procédure — à répéter **à l'identique sur node1, node2 et node3**

### 1. Arrêter le nœud

```bash
pgrep -af "src.node.main"
```

Puis tuer **par PID** (jamais `pkill -f` en aveugle) :

```bash
kill <PID>
```

### 2. Sauvegarder l'ancien fichier

```bash
cd ~/blockchain-medical        # adaptez au chemin réel du projet
cp src/blockchain/block.py ~/block.py.avant-D3-$(date +%Y%m%d)
```

### 3. Copier depuis la clé USB, puis normaliser les fins de ligne

```bash
# repérer le point de montage
lsblk
# exemple : /media/$USER/USB

cp /media/$USER/USB/block.py src/blockchain/block.py
sed -i 's/\r$//' src/blockchain/block.py
```

### 4. Vérifier — étape à ne pas sauter

```bash
sha256sum src/blockchain/block.py
```

Doit afficher **exactement** :

```
2dbe88df59b9e44e085310cf0cdeeb94bc57880b33a33f64aae9381b83b66b0a
```

Contrôle automatique (affiche OK ou STOP) :

```bash
echo "2dbe88df59b9e44e085310cf0cdeeb94bc57880b33a33f64aae9381b83b66b0a  src/blockchain/block.py" \
  | sha256sum -c - && echo "=== OK ===" || echo "=== STOP : fichier different ==="
```

Si c'est `STOP`, **ne démarrez pas le nœud** : restaurez la sauvegarde de
l'étape 2 et recopiez depuis la clé.

### 5. Compiler puis tester

```bash
python3 -m py_compile src/blockchain/block.py && echo "COMPILE OK"
PYTHONPATH=. python3 -m pytest tests/unit/ -q
```

### 6. Vider les anciens blocs

Obligatoire : les blocs d'avant D3 n'ont pas de champ `state_root` et seront
rejetés avec `BlockError: missing field in block dict: 'state_root'`.

```bash
rm -rf data/node1/blocks/*      # node1 — adaptez le numéro sur chaque VM
```

### 7. Redémarrer

```bash
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:$LD_LIBRARY_PATH
PYTHONPATH=. python3 -m src.node.main --config config/nodes/node1/node.yaml
```

`PYTHONPATH=.` est indispensable sur node2 et node3.

---

## Règle absolue

Les 3 VMs doivent être mises à jour **avant** qu'aucune ne redémarre.

Un nœud à jour et un nœud non à jour ne peuvent pas communiquer : le
`state_root` entre dans `signing_hash` et `block_hash`, donc les hachages
diffèrent et les blocs sont rejetés de part et d'autre.

Ordre conseillé : étapes 1→6 sur les trois machines, **puis** étape 7 sur les
trois.

---

## Vérifier la convergence après redémarrage

Les 3 nœuds doivent afficher le **même** `block_hash` de genesis. S'ils
diffèrent, le genesis n'est pas identique (clé publique ou timestamp) — ce
n'est pas un problème lié à D3.

Ensuite, la hauteur doit progresser de la même façon sur les trois.
