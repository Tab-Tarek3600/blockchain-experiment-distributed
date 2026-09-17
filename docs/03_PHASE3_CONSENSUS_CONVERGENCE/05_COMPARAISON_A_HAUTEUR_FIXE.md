# 4f — contrôle 1 corrigé : comparer à hauteur FIXE

## Pourquoi la première version ne pouvait pas marcher

La commande du contrôle 1 lisait `get_latest_block()`, c'est-à-dire le
**sommet** de chaque chaîne. Or les trois nœuds ont été arrêtés à trois
instants différents, donc ils ont trois sommets différents (45, 46, 47).
Comparer trois sommets distincts ne prouve rien : ils *doivent* différer.

Ce qu'il faut comparer, c'est **le même numéro de bloc sur les trois
machines**. C'est là que l'accord se voit.

La hauteur commune est celle du nœud le plus en retard : **45**.

---

## Contrôle 1 corrigé

Les nœuds peuvent rester arrêtés : on lit le disque, pas le réseau.

Sur **chaque** VM, à la racine du projet :

```bash
cd ~/blockchain-experiment-distributed
PYTHONPATH=. python3 -c "
from src.blockchain.storage import ChainStorage

CHEMIN  = 'data/nodeN'     # <-- node1 / node2 / node3 selon la VM
HAUTEUR = 45               # <-- la MEME valeur sur les 3 machines

s = ChainStorage(CHEMIN)
b = s.load_block(HAUTEUR)
print('sommet local :', s.get_tip_height())
print('hauteur lue  :', b.height)
print('block_hash   :', b.block_hash.hex())
print('previous     :', b.previous_hash.hex())
print('state_root   :', b.state_root.hex())
print('validateur   :', b.validator.hex())
print('nb tx        :', len(b.transactions))
"
```

Deux champs seulement à modifier : `CHEMIN` et rien d'autre.
`HAUTEUR = 45` doit rester **identique** sur les trois VMs.

### Attendu

`sommet local` diffère (45, 46, 47) — c'est normal et sans importance.

`block_hash`, `previous_hash`, `state_root`, `validateur` et `nb tx`
doivent être **identiques, caractère pour caractère, sur les 3 VMs**.

C'est cela, et cela seul, le critère 5 : *les trois machines sont
d'accord sur le contenu et sur l'état*.

### Si `block_hash` est identique mais `state_root` diffère

Ce serait le seul cas réellement inquiétant : même bloc, états
divergents. Cause quasi certaine : versions de py-evm différentes.
Vérifier sur les 3 VMs :

```bash
pip show py-evm rlp | grep -E "Name|Version"
```

Attendu partout : py-evm `0.12.1b1`, rlp `4.1.0`.

---

## Contrôle 1 bis — la chaîne entière, en une empreinte

Plus rapide et plus probant que de comparer un bloc à l'œil : on
résume les 46 premiers blocs (0 à 45) en un seul hachage.

Sur **chaque** VM :

```bash
cd ~/blockchain-experiment-distributed
PYTHONPATH=. python3 -c "
import hashlib
from src.blockchain.storage import ChainStorage

CHEMIN  = 'data/nodeN'     # <-- node1 / node2 / node3
JUSQUA  = 45               # <-- identique sur les 3 machines

s = ChainStorage(CHEMIN)
h = hashlib.sha256()
for n in range(JUSQUA + 1):
    b = s.load_block(n)
    h.update(b.block_hash)
    h.update(b.state_root)
print('empreinte 0..%d : %s' % (JUSQUA, h.hexdigest()))
"
```

**Une seule ligne à comparer entre les trois machines.** Si les trois
empreintes sont égales, les 46 blocs et les 46 racines d'état sont
identiques partout : critère 5 rempli sans discussion possible.

---

## Rappel : pourquoi les hauteurs divergeaient

Ordre d'arrêt : node1, puis node2, puis node3.

| Hauteur | Proposeur imposé (`h % 3`) | Qui l'a reçu |
|---------|---------------------------|--------------|
| 45      | —                         | les 3        |
| 46      | `46 % 3 = 1` → node2      | node2, node3 (node1 déjà arrêté) |
| 47      | `47 % 3 = 2` → node3      | node3 seul (node2 déjà arrêté)   |

Sommets finaux : 45, 46, 47. La suite correspond **exactement** à
l'ordre des arrêts, ce qui confirme que le round-robin PoA et la
propagation fonctionnaient jusqu'à la dernière seconde.

Pour obtenir trois sommets égaux à l'avenir : arrêter les trois nœuds
**dans la même seconde**, ou bien les relancer tous les trois et
attendre que la synchronisation au handshake
(`_request_sync_from_peer`, `socket_p2p.py` l. 884) ait rattrapé les
retardataires — un nœud qui se reconnecte demande automatiquement à
ses pairs les blocs qui lui manquent.

---

## Reste à faire

Le **contrôle 2** (bloc hostile) du document
`04_LANCEMENT_3_NOEUDS_ET_CONVERGENCE.md` est inchangé et reste valable : il ne
dépend pas des hauteurs, il s'exécute hors chaîne sur un état neuf.
C'est lui qui couvre les critères 3, 4 et 6.
