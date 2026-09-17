# B8-C — inventaire blockchain en lecture seule

**Date :** 16 septembre 2026  
**Périmètre :** node1, node2, node3  
**Mode :** lecture seule, aucune transaction soumise

Les trois nœuds ont retourné la même hauteur (`242`), la même racine d'état
et le même inventaire des blocs 0 à 6. La transcription ci-dessous est celle
fournie pour node1 ; node2 et node3 ont été indiqués comme identiques.

```text
node=node1
height=242

BLOCK height=0 tx_count=0 state_root=56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
BLOCK height=1 tx_count=1 state_root=56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
  TX id=4c73960960a0d22d93f05f67175f594ba85d1abbeba869f15b850dca403e71dc selector= data_len=0
BLOCK height=2 tx_count=1 state_root=56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
  TX id=ad3ae981815a60e7ebf6c3a02a0dcf5edb32c9d71f641eb05400934529278a27 selector= data_len=0
BLOCK height=3 tx_count=1 state_root=56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
  TX id=cbe8c9de2b19e66735ba5890993190bdfb950bd928a5d82dea55f392bba09c1c selector= data_len=0
BLOCK height=4 tx_count=1 state_root=56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
  TX id=60dc9d9d72b27d547a270dd4d7c56b5ec1e75d35bc887179080aacb0c5c3ded0 selector= data_len=0
BLOCK height=5 tx_count=1 state_root=56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
  TX id=d468ba142c320edcdbbbfac729bb4e2be10bc46cd7f33e33aef8b2c8f1d98ca8 selector= data_len=0
BLOCK height=6 tx_count=1 state_root=56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421
  TX id=5931e1acd1f395387e22f7f2d2838b48ccc1940d07aa91cfb59cecdac7b26e02 selector= data_len=0
```

## Interprétation

Les transactions présentes aux hauteurs 1 à 6 ont `data_len=0`. Elles ne sont
pas les transactions `registerRecord` Phase 7 attendues par
`read_phase7_records.py`. La transaction v1 historique attendue n'existe donc
pas dans la chaîne actuellement chargée ; l'arrêt `EXIT=1` du lecteur Phase 7
est cohérent avec cet inventaire.

Cette chaîne est néanmoins convergente entre les trois nœuds pour le contrôle
B8-C : même hauteur, même `state_root` et aucune transaction blockchain
soumise par B8-C.

`read_phase7_records.py` est un lecteur historique spécifique aux dossiers
Phase 7 ; il ne constitue pas un critère d'acceptation de la campagne
B8-C-IPFS. La preuve historique Phase 7 antérieure reste archivée séparément
dans `phase7-blockchain-v1-v2-2026-09-13.txt` et ne doit pas être présentée
comme une nouvelle transaction B8-C.
