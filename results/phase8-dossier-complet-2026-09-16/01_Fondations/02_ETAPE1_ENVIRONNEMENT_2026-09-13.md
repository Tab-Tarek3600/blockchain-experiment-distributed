# Phase 8 — Étape 1 : vérification de l’environnement expérimental

**Date :** 13 septembre 2026
**Statut :** résultats des trois nœuds intégrés — étape clôturée avec réserve méthodologique
**Objectif :** vérifier que l’environnement des trois nœuds est reproductible avant les autres benchmarks.

---

## 1. Périmètre de l’étape

Cette étape doit confirmer, pour node1, node2 et node3 :

- identité de la machine ;
- date et horloge ;
- version du noyau ;
- CPU, mémoire et virtualisation ;
- version Python ;
- présence de liboqs et de ML-DSA-44 ;
- version du code ;
- port P2P TCP `9001` ;
- configuration PoA ;
- hauteur, hash de tête et `state_root` initiaux ;
- état du mempool ;
- taille des données blockchain et IPFS ;
- absence de règle `tc-netem` avant le benchmark.

Les tests ont été exécutés en lecture seule. Aucune clé, configuration générée,
CID ou donnée de chaîne n’a été supprimé ou modifié.

---

## 2. Architecture attendue

| Nœud | Adresse | Rôle | Environnement |
|---|---|---|---|
| node1 | `192.168.168.101` | ingress et validateur | VM |
| node2 | `192.168.168.102` | validateur | VM |
| node3 | `192.168.168.103` | validateur | VM |

**Correction apportée le 13 septembre 2026 :** les trois nœuds sont des VMs
sous VMware. Node1 n’est pas la machine physique ; il constitue le point
d’entrée logique du scénario client/médecin → node1, en plus de son rôle de
validateur. Toute comparaison « physique contre VM » est donc exclue de cette
campagne et devra être retirée ou reformulée dans l’étape 14.

Paramètres communs attendus :

```text
P2P                  : TCP/9001
Consensus            : PoA round-robin
block_interval       : 5.0 s
round_timeout        : 5.0 s
Entrée du scénario   : client/médecin → node1
```

---

## 3. Vérification de la configuration du projet

La configuration observée dans les trois environnements réels est :

| Nœud | Identité observée | Adresse d’écoute | Port | Intervalle bloc | Timeout round |
|---|---|---:|---:|---:|---:|
| node1 | `Node1` | `192.168.168.101` | 9001 | 5.0 s | à confirmer explicitement |
| node2 | `Node2` | `192.168.168.102` | 9001 | 5.0 s | à confirmer explicitement |
| node3 | `Node3` | `192.168.168.103` | 9001 | 5.0 s | à confirmer explicitement |

Les fichiers de configuration ont des empreintes différentes parce que chaque
nœud porte son identité, son adresse et ses paramètres locaux. Les empreintes
du code commun (`Makefile`, `src/crypto`, `src/blockchain` et `src/node`) sont
identiques sur les trois nœuds.

Répertoires de données configurés :

```text
node1 : ./data/node1
node2 : ./data/node2
node3 : ./data/node3
```

La cohérence de cette configuration est confirmée localement dans le dépôt.
Elle ne remplace pas la vérification des trois machines réelles.

---

## 4. Résultat de l’exécution dans le workspace

Le workspace d’exécution est un environnement sandbox séparé des trois nœuds du
projet. Les résultats suivants sont donc des informations de diagnostic du
sandbox et ne doivent pas être utilisés comme caractéristiques de node1, node2
ou node3.

```text
hostname       : e2b.local
système        : Linux 6.1.158+ x86_64
CPU            : 2 CPU logiques visibles
hyperviseur    : KVM
mémoire        : 1.9 GiB
swap           : 0 B
Python         : 3.13.14
```

La commande locale `make check-oqs` a échoué avec :

```text
ModuleNotFoundError: No module named 'oqs'
```

Cette erreur est attendue dans le sandbox et ne permet pas de conclure sur les
installations `.venv` des trois nœuds. Le test cryptographique sera donc validé
sur les machines du projet, pas dans ce sandbox.

---

## 5. Résultats réellement obtenus sur les trois nœuds

Les commandes ont été exécutées directement sur node1, node2 et node3 le
13 septembre 2026. Les résultats sont résumés ci-dessous et restent traçables
dans les sorties complètes fournies dans la conversation.

### 5.1 Identité, système et ressources

| Nœud | Adresse | Python | CPU visible | Mémoire | Système/hyperviseur |
|---|---|---:|---:|---:|---|
| node1 | `192.168.168.101` | 3.12.13 | 2 | 1,6 GiB | Ubuntu / VMware |
| node2 | `192.168.168.102` | 3.12.13 | 2 | 1,6 GiB | Ubuntu / VMware |
| node3 | `192.168.168.103` | 3.12.13 | 2 | 1,6 GiB | Ubuntu / VMware |

Le processeur observé est le même sur les trois systèmes :

```text
13th Gen Intel(R) Core(TM) i7-1355U
```

Le noyau est `7.0.0-31-generic` sur node1 et node2, et
`7.0.0-29-generic` sur node3.

**Correction d’architecture :** la sortie `lscpu` identifie VMware sur les
trois nœuds et l’utilisateur confirme que node1, node2 et node3 sont tous des
VMs. Node1 reste le point d’entrée logique du scénario et un validateur, mais
n’est pas une machine physique. La comparaison physique/VM prévue à l’étape 14
n’est donc pas réalisable avec cette infrastructure et ne devra pas être
présentée comme un résultat expérimental.

### 5.2 Logiciels et code

Les trois nœuds utilisent :

```text
Python       : 3.12.13
liboqs       : 0.16.0
ML-DSA-44    : disponible sur les trois nœuds
```

`make check-oqs` réussit sur node1, node2 et node3. Le message
`liboqs-python faulthandler is disabled` est informatif et ne constitue pas un
échec.

Les empreintes SHA-256 du code commun sont identiques sur les trois nœuds,
notamment pour `Makefile`, `src/crypto`, `src/blockchain` et `src/node`. Les
fichiers `node.yaml` possèdent des empreintes différentes, ce qui est normal
pour des configurations propres aux nœuds.

### 5.3 Connectivité IP

Les trois nœuds répondent aux requêtes ICMP avec **0 % de perte**.

| Source | Destination | RTT moyen observé |
|---|---|---:|
| node1 | node2 | 2,213 ms |
| node1 | node3 | 1,925 ms |
| node2 | node1 | 0,887 ms |
| node2 | node3 | 1,797 ms |
| node3 | node1 | 1,571 ms |
| node3 | node2 | 1,399 ms |

Les valeurs loopback sont inférieures à 0,1 ms. Ces mesures sont des RTT ICMP
d’orientation ; elles ne remplacent pas les mesures TCP du benchmark blockchain.

### 5.4 Port P2P TCP/9001

Après démarrage des trois nœuds, le port `9001` est bien en écoute sur les trois
machines :

| Nœud | Adresse d’écoute | Processus | PID | Résultat |
|---|---|---|---:|---|
| node1 | `192.168.168.101:9001` | `python3` | 7482 | LISTEN |
| node2 | `192.168.168.102:9001` | `python3` | 8344 | LISTEN |
| node3 | `192.168.168.103:9001` | `python3` | 6424 | LISTEN |

Le transport P2P possède donc un point d’écoute actif sur les trois nœuds. La
configuration effective confirme également que chaque nœud possède les deux
autres nœuds comme pairs sur le port `9001`.

### 5.5 Synchronisation des horloges

Les trois machines indiquent :

```text
NTPSynchronized=no
chrony       : Not synchronised
```

L’étape 1 n’est donc pas entièrement validée pour les mesures comparant des
horodatages pris directement sur plusieurs machines. Pour les premiers
benchmarks, les durées end-to-end seront calculées depuis l’horloge du
client/générateur. Avant les mesures de propagation et de convergence, il
faudra soit synchroniser les horloges, soit mesurer explicitement leur écart et
utiliser des accusés de réception corrélés.

### 5.6 État `tc-netem`

Aucune règle `netem` n’est active. Les interfaces utilisent :

```text
lo     : noqueue
ens33  : pfifo_fast
```

La baseline réseau est donc propre, sans délai, perte ou jitter artificiellement
ajouté.

### 5.7 État initial des chaînes

Les trois nœuds possèdent sept blocs locaux, de la hauteur 0 à la hauteur 6,
et environ 124 KiB de données blockchain par nœud.

Le dernier bloc est identique sur les trois nœuds :

```text
height        : 6
round         : 0
transactions  : 1
block_hash    : 0x6069eb026a917d2a179a431e2a13f836a57ce2d811107462820810e5c86ed7d1
state_root    : 0x7c1f055464d160b1c1fb978e9f4eb527a362418b579ff7a80f5e4e6450591b16
timestamp     : 1789309438
```

Ce résultat confirme la cohérence initiale des trois copies au moment du
contrôle. Il s’agit d’un état de départ, pas encore d’un résultat de performance.

### 5.8 Paramètres effectifs de configuration

Les trois nœuds chargent effectivement les mêmes paramètres de consensus et de
mempool :

```text
block_interval_seconds : 5.0
round_timeout_seconds  : 5.0
mempool_max_size       : 1000
validator_count        : 3
```

La topologie effective est :

```text
node1 → node2:9001, node3:9001
node2 → node1:9001, node3:9001
node3 → node1:9001, node2:9001
```

La liste des validateurs autorisés est identique sur les trois nœuds :

```text
f0aee1a1c916d0584a2805de88f2544099cc3e26
017daee614c5368327267144292313480807c020
140db41bc9e14639e54dea0135eeca843b75634f
```

---

## 6. Décision méthodologique sur les horloges

Les trois nœuds indiquent `NTPSynchronized=no` et `chrony: Not synchronised`.
Aucune modification système n’est effectuée dans cette phase afin de ne pas
changer l’environnement expérimental sans le documenter.

Pour les benchmarks suivants :

- les latences end-to-end seront calculées depuis l’horloge monotone du
  générateur de charge ;
- les événements distants seront corrélés par `tx_id`, `block_hash`, hauteur et
  accusés de réception ;
- les temps de propagation entre deux horloges de nœuds ne seront pas calculés
  directement à partir de timestamps locaux non synchronisés ;
- la limite de synchronisation sera rappelée dans la section expérimentale.

Cette décision permet de poursuivre les tests sans présenter une différence
d’horloges comme une latence réseau. Une synchronisation NTP/chrony pourra être
ajoutée dans une campagne ultérieure, mais elle n’est pas nécessaire pour
clôturer la vérification de l’environnement logiciel et réseau.

---

## 7. Critères de validation de l’étape 1

| Critère | Résultat |
|---|---|
| Trois machines accessibles | VALIDÉ |
| IP node1/node2/node3 | VALIDÉ |
| Python 3.12.13 | VALIDÉ |
| liboqs 0.16.0 | VALIDÉ |
| ML-DSA-44 disponible | VALIDÉ |
| Code commun identique | VALIDÉ |
| Ping entre les nœuds | VALIDÉ, 0 % perte |
| Configuration `tc-netem` propre | VALIDÉE |
| Hauteur initiale identique | VALIDÉE, hauteur 6 |
| `block_hash` initial identique | VALIDÉ |
| `state_root` initial identique | VALIDÉ |
| Port TCP/9001 pendant l’exécution | VALIDÉ, LISTEN sur les trois nœuds |
| `round_timeout_seconds` effectif | VALIDÉ, 5.0 s sur les trois nœuds |
| Synchronisation NTP | NON synchronisée, limitation documentée |
| Type d’environnement | VALIDÉ, les trois nœuds sont des VMs VMware |
| Données IPFS et ressources Kubo | À compléter si nécessaire |

---

## 8. État de l’étape 1

```text
Environnement logiciel       : VALIDÉ
Cohérence du code            : VALIDÉE
Connectivité IP              : VALIDÉE
État initial blockchain      : VALIDÉ
Baseline tc-netem            : VALIDÉE
Port P2P en fonctionnement   : VALIDÉ sur les trois nœuds
Horloges synchronisées       : NON, méthode de mesure définie
Étape 1                      : VALIDÉE avec réserve méthodologique
```

L’étape 1 est clôturée avec une réserve méthodologique : les horloges ne sont
pas synchronisées, mais la méthode de mesure pour les étapes suivantes est
explicitement définie et cette limite sera rapportée dans l’article.

Une correction d’architecture est également enregistrée : les trois nœuds sont
des VMs VMware ; node1 n’est pas une machine physique. Les analyses
physique/VM ne sont donc pas applicables à cette campagne.

L’étape 2 peut commencer.
