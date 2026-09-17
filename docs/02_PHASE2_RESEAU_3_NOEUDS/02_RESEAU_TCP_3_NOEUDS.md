# PHASE 2 — Réseau TCP réel à 3 nœuds

Machine physique (`node1`) + VM1 (`node2`) + VM2 (`node3`), une seule
base de code, communication par sockets TCP.

---

## 1. Fichiers créés

| Fichier | Rôle |
|---|---|
| `src/node/socket_p2p.py` | `SocketP2P(P2PTransport)` : transport TCP réel (framing, handshake, anti-boucle, lifecycle) |
| `src/node/main.py` | Point d'entrée `python -m src.node.main --config …` |
| `tests/unit/node/test_socket_p2p.py` | 40 tests du transport (sockets réelles, dont 2 processus séparés) |
| `tests/integration/test_three_nodes_tcp.py` | 14 tests d'intégration 3 nœuds en triangle TCP |
| `tests/integration/__init__.py` | Package de tests |
| `config/node1.yaml`, `node2.yaml`, `node3.yaml` | Gabarits de configuration commentés |
| `docs/02_PHASE2_RESEAU_3_NOEUDS/02_RESEAU_TCP_3_NOEUDS.md` | Ce document |

## 2. Fichiers modifiés

| Fichier | Modification | Justification |
|---|---|---|
| `src/node/node.py` | **Ajout seul** de 3 accesseurs lecture seule : `genesis_hash`, `tip_hash`, `is_my_turn(height)` | `main.py` devait sinon lire `node._blockchain` / `node._consensus`. Aucune logique existante touchée ; `_accept_block` et le pipeline sont inchangés. |
| `pytest.ini` | Déclaration du marqueur `integration` | Évite un warning et permet `pytest -m "not integration"`. |

Sauvegarde : `src/node/node.py.bak-20260812-193557`.

**Non modifiés** : `src/blockchain/` (aucun besoin — `to_dict`/`from_dict`
existaient déjà), `p2p.py`, `validator.py`, `consensus.py`, `mempool.py`,
`config.py`, la crypto ML-DSA.

---

## 3. Architecture finale

```
        MACHINE PHYSIQUE                VM1                        VM2
      ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
      │      node1       │      │      node2       │      │      node3       │
      │  192.168.1.101   │      │  192.168.1.102   │      │  192.168.1.103   │
      │    TCP :5000     │      │    TCP :5000     │      │    TCP :5000     │
      ├──────────────────┤      ├──────────────────┤      ├──────────────────┤
      │ Blockchain (disk)│      │ Blockchain (disk)│      │ Blockchain (disk)│
      │ Mempool          │      │ Mempool          │      │ Mempool          │
      │ Consensus PoA    │      │ Consensus PoA    │      │ Consensus PoA    │
      │ Validator ML-DSA │      │ Validator ML-DSA │      │ Validator ML-DSA │
      ├──────────────────┤      ├──────────────────┤      ├──────────────────┤
      │    SocketP2P     │◄────►│    SocketP2P     │◄────►│    SocketP2P     │
      └────────┬─────────┘      └──────────────────┘      └─────────┬────────┘
               │                                                     │
               └──────────────────── TCP ────────────────────────────┘
                          (triangle complet, 3 liens)
```

Empilement logiciel, identique sur les trois machines :

```
   main.py            charge le YAML, câble, boucle de production
      │
      ├── NodeConfig.from_file()      source unique de vérité
      │
      ├── SocketP2P(host, port, peers)  ──► sockets TCP
      │        implémente P2PTransport
      │
      └── Node.from_config(config, p2p=transport)
               dépend de l'ABC P2PTransport, jamais de TCP
```

`Node` ignore totalement l'existence des sockets : `NullP2P`,
`InMemoryP2P` et `SocketP2P` restent interchangeables.

### Format de trame

```
 ┌────────────────────┬──────────────────────────────┐
 │ longueur (4 o, BE) │  JSON UTF-8 (N octets)       │
 └────────────────────┴──────────────────────────────┘
```

Messages : `hello` (node_id + adresse d'écoute), `tx`, `block`.
Charges utiles produites par `Transaction.to_dict()` / `Block.to_dict()`.

---

## 4. Configuration

Générer les clés **sur chaque machine**, puis les configs **sur une
seule** (voir `scripts/README-etape2.md`) :

```bash
# sur chaque machine
python3 scripts/gen_validator_key.py --key-dir keys/nodeN

# sur une seule machine, avec les 3 adresses collectées
python3 scripts/make_configs.py --nodes nodes.json --out config/
# puis copier config/nodeN.yaml sur la machine N
```

Champs **obligatoirement identiques** sur les 3 machines :
`authorized_validators` (même ordre), `genesis_validator_public_key`,
`genesis_timestamp`, `block_interval_seconds`.

> **Ordre PoA** : le genesis occupe la hauteur 0, donc le premier bloc
> produit (h=1) revient à `authorized_validators[1]` = **node2**, pas
> node1.

---

## 5. Lancer les 3 nœuds

Sur chaque machine, depuis la racine du dépôt :

```bash
# MACHINE PHYSIQUE
python3 -m src.node.main --config config/node1.yaml

# VM1
python3 -m src.node.main --config config/node2.yaml

# VM2
python3 -m src.node.main --config config/node3.yaml
```

L'ordre de démarrage est indifférent : la composition est réessayée
toutes les 2 s. Arrêt propre par `Ctrl+C`.

Options : `--log-level DEBUG`, `--send-tx` (injecte une transaction
signée), `--no-propose` (écoute seule), `--tx-value N`.

---

## 6. Tester la propagation N1→N2, N2→N3, N3→N1

Chaque nœud lancé avec `--send-tx` émet une transaction signée. Pour
tester les trois chemins :

```bash
# 1) N1 -> N2 et N3 : seul node1 émet
#    machine physique
python3 -m src.node.main --config config/node1.yaml --send-tx --tx-value 111
#    VM1 et VM2 (écoute seule, pour isoler l'origine)
python3 -m src.node.main --config config/node2.yaml --no-propose
python3 -m src.node.main --config config/node3.yaml --no-propose
```

Attendu dans les logs de VM1 et VM2 : la transaction apparaît, puis
`status: … mempool=1`.

```bash
# 2) N2 -> N3 et N1
python3 -m src.node.main --config config/node2.yaml --send-tx --tx-value 222

# 3) N3 -> N1 et N2
python3 -m src.node.main --config config/node3.yaml --send-tx --tx-value 333
```

Pour la propagation des **blocs**, relancer les trois sans
`--no-propose` : chaque nœud propose à son tour et les trois hauteurs
doivent progresser ensemble.

Vérification côté réseau, avant même de lancer les nœuds :

```bash
# depuis la machine physique, tester que VM1 est joignable
nc -vz 192.168.1.102 5000
# et l'inverse depuis VM1
nc -vz 192.168.1.101 5000
```

---

## 7. Procédure de test réelle

1. **Réseau** — les 3 machines se pinguent ; les VMs sont en **bridge**
   (le NAT par défaut rend la VM injoignable depuis l'hôte).
2. **Pare-feu** — ouvrir le port 5000 sur les trois machines :
   ```bash
   sudo ufw allow 5000/tcp      # Debian/Ubuntu
   sudo firewall-cmd --add-port=5000/tcp --permanent && sudo firewall-cmd --reload
   ```
3. **Code** — même commit sur les 3 machines.
4. **Clés** — `gen_validator_key.py` sur chaque machine ; les 3 adresses
   doivent être différentes ; aucune clé secrète ne circule.
5. **Configs** — générées en une fois, puis distribuées.
6. **Démarrage** — les 3 nœuds ; vérifier `connected peers` = les deux
   autres, et surtout **`genesis hash` identique sur les trois**.
7. **Transactions** — relancer avec `--send-tx` ; vérifier l'arrivée
   chez les deux autres.
8. **Blocs** — vérifier la rotation h=1→node2, h=2→node3, h=3→node1 et
   des hauteurs qui progressent ensemble.
9. **Arrêt d'un nœud** — `Ctrl+C` sur VM2 ; les deux autres continuent.
   Le redémarrage rejoint le réseau (sans rattrapage d'historique :
   hors périmètre).

### Diagnostic

| Symptôme | Cause probable |
|---|---|
| `connected peers : none` | pare-feu, VM en NAT, ou mauvaise IP dans `peers` |
| `cannot listen on … : Address already in use` | port déjà pris |
| genesis hash différent | un des 4 champs partagés diffère |
| `NodeError: … not in authorized_validators` | l'adresse locale n'est pas dans la liste |
| Bloc refusé chez les pairs | horloges désynchronisées, ou tour PoA mal compris |

---

## 8. Checklist de vérification

| # | Point | Vérifié |
|---|---|---|
| 1 | Chaque nœud a des clés ML-DSA **différentes** | ✅ 3 adresses distinctes (test `test_the_three_nodes_have_distinct_addresses`) |
| 2 | Les 3 nœuds ont le **même genesis** | ✅ `7990d908…` identique sur les 3 processus réels |
| 3 | Les 3 ont les **mêmes validators** dans le même ordre | ✅ imposé par la config, vérifié par `NodeConfig` |
| 4 | Communication en **TCP réel** | ✅ sockets réelles ; validé entre 3 processus OS distincts |
| 5 | Les **transactions circulent** | ✅ 3 tx émises par 3 processus → toutes trois dans le bloc h=1 (`txs=3`) |
| 6 | Les **blocs circulent** | ✅ tip final identique `6dbe2db7…`, hauteur 10 partout |
| 7 | Le **PoA fonctionne** | ✅ rotation h=1→node2, h=2→node3, h=3→node1 ; proposeur hors tour rejeté |
| 8 | **Pas de boucle** de broadcast | ✅ dédup `tx_id`/`block_hash` ; test d'écho ; réseau silencieux après convergence |
| 9 | Tests unitaires **toujours verts** | ✅ 49/49 préexistants ; 103/103 au total |
| 10 | Validation **physique ↔ VM** | ⚠️ **à faire par vous** : non testable en sandbox |

---

## 9. Niveaux de validation

| Niveau | Statut |
|---|---|
| IN-PROCESS (threads, sockets réelles) | ✅ 40 tests |
| MULTI-PROCESS (même machine) | ✅ 3 processus `main.py`, 40 s, 0 déconnexion |
| ENTRE VMs / PHYSIQUE ↔ VM | ❌ **non validé** — impossible depuis la sandbox |

Les deux premiers niveaux ne prouvent **rien** sur le routage, le
pare-feu ou le mode réseau des VMs. Seule la procédure §7 le fera.

---

## 10. Deux défauts trouvés par le test réel

Les tests unitaires passaient dans les deux cas ; seuls les logs des
processus réels les ont révélés.

**a) Double fermeture lors d'une composition mutuelle.** La règle « le
premier lien établi gagne » est locale : chaque côté pouvait fermer un
lien *différent*, supprimant les deux. Corrigé par un départage
déterministe — le lien sortant du nœud au `node_id` le plus petit est
conservé, règle que les deux extrémités évaluent identiquement.

**b) Reconnexion en boucle (17 déconnexions en 25 s).** La détection
« ce pair est-il déjà connecté ? » comparait `getpeername()`, qui pour
un lien entrant rend le **port éphémère** du client, jamais son port
d'écoute : le lien entrant était invisible et le nœud recomposait sans
cesse. Corrigé en faisant annoncer l'adresse d'écoute dans le `HELLO`,
plus un garde `_dialing` pour la fenêtre du handshake.

Après correction : 2 liens par nœud, 0 déconnexion en 40 s.

---

## 11. Hors périmètre (assumé)

Peer discovery, NAT traversal, TLS/chiffrement, gossip avancé, fork
choice, synchronisation d'historique, RPC/REST, Docker.

Conséquence directe de l'absence de synchronisation : un nœud
redémarré ne rattrape pas les blocs manqués.
