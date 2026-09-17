# Phase 8 — Plan détaillé des tests et benchmarks de performance

## Document de travail pour l’article scientifique final

**Projet :** blockchain permissionnée post-quantique pour dossiers médicaux
**Architecture étudiée :** 3 nœuds, consensus PoA round-robin, ML-DSA-44,
ML-KEM-768, py-evm, Flask/Gunicorn et IPFS distribué co-localisé
**Date de rédaction initiale :** 13 septembre 2026  
**Mise à jour des résultats :** 15 septembre 2026  
**Statut :** protocole expérimental avec résultats B0, B1, B2, B3, B3-N, B4, B5 et B6 intégrés ; B6 est clôturé après preuve de nettoyage `tc-netem`, B7–B8 restent à exécuter

---

## Résumé exécutif

Une évaluation sérieuse d’une blockchain ne peut pas être réduite à une seule
valeur de TPS. La performance observée dépend simultanément de la charge
soumise, du type de transaction, de la taille des messages, du nombre de
validateurs, du protocole de consensus, de la latence réseau, de la cryptographie,
de la persistance et de la manière dont la fin d’une transaction est définie.

La littérature sur les blockchains privées retient généralement quatre axes :
**débit**, **latence**, **scalabilité** et **tolérance aux pannes**. BLOCKBENCH
propose en outre de séparer les couches consensus, modèle de données et
exécution afin d’identifier les goulots d’étranglement plutôt que de produire
uniquement une mesure globale ([BLOCKBENCH](https://ar5iv.labs.arxiv.org/html/1703.04057)).
Hyperledger Caliper distingue de son côté les statistiques de transactions et
la consommation de ressources ; ses moniteurs collectent notamment CPU, mémoire,
trafic réseau et E/S disque ([documentation des moniteurs Caliper](https://hyperledger-caliper.github.io/caliper/0.6.0/concepts/caliper-monitors/)).

Pour notre projet, le plan recommandé est donc composé de :

1. un **contrôle de reproductibilité et de configuration** ;
2. des **microbenchmarks cryptographiques** ML-DSA-44 et ML-KEM-768 ;
3. un **benchmark blockchain de référence** sur le scénario
   `client/médecin → node1 → diffusion P2P` ;
4. une campagne de **charge et de saturation** ;
5. une mesure séparée de la **latence d’inclusion, de commit et de convergence** ;
6. des tests de **dégradation réseau** ;
7. un test de **crash/reprise d’un validateur** ;
8. un profil comparatif des **trois VMs VMware** (la comparaison machine physique contre VMs n’est pas réalisable dans l’environnement actuel) ;
9. des microbenchmarks **py-evm/contrats** ;
10. une mesure séparée de la couche **Flask/Gunicorn** ;
11. un benchmark complémentaire du **stockage IPFS**.

Les mesures doivent distinguer les transactions **soumises**, **acceptées par le
nœud d’entrée**, **incluses dans un bloc**, **validées localement** et
**observées par les trois nœuds**. La chaîne de comptage à conserver dans tous
les tableaux est donc :

```text
API request rate
≠ transactions soumises
≠ transactions acceptées
≠ transactions incluses dans un bloc
≠ transactions finalisées/convergées
```

Sans cette distinction, un système peut sembler avoir un débit élevé simplement
parce que le client envoie beaucoup de requêtes, alors que la blockchain les
accumule dans le mempool ou les rejette.

## État d'exécution au 15 septembre 2026

| Étape | Résultat actuel | Réserve |
|---|---|---|
| B0 — environnement | Validé sur les trois VMs | Horloges non synchronisées ; latence inter-VM numérique à ne pas déduire directement |
| B1 — ML-DSA-44 | Validé sur les trois VMs | Microbenchmark local, pas un TPS blockchain |
| B1 — ML-KEM-768 + AES-GCM | Validé sur les trois VMs | Confidentialité hors chaîne, pas un TPS blockchain |
| B2 — baseline | Première passe validée jusqu'à 2 tx/s | À 2 tx/s : 119/120 incluses sur deux essais ; saturation observée, pas capacité universelle |
| B3 — 3 tx/s, 1 client | Exécuté le 15/09/2026 | 121/180 incluses sur les trois nœuds ; 59 non observées, aucun rejet explicite |
| B3-N — concurrence logique | **Exécuté et analysé** | À taux total constant de 1 tx/s, 1/2/4/8 clients : 60/60 incluses sur les trois nœuds dans chaque run ; p50 node1 296,18 → 1 028,45 ms ; p95 391,74 → 1 941,10 ms ; pas une campagne multi-machines |
| B4 — latence/convergence | Exécuté et analysé | `b4-rate-1p0-20260915` : 60/60 incluses sur les trois nœuds à 1 tx/s ; p50 node1 260,47 ms, p95 393,17 ms ; convergence numérique inter-VM non mesurée |
| B5 — crash/reprise | Exécuté et analysé avec réserve | node3 arrêté puis redémarré ; 12/12 incluses sur les trois nœuds ; rattrapage jusqu’à h11 ; mesure précise du failover partielle |
| B6 — réseau dégradé | **Exécuté, analysé et clôturé** | `b6-delay50ms-20260915` : 12/12 acceptées et incluses à 0,2 tx/s sous `50 ms ± 10 ms`, sans perte ajoutée ; node1 p50 300,73 ms, p95 438,50 ms ; `qdisc netem` supprimé et absent sur les trois VMs, puis nœuds arrêtés |
| B7 — profil des trois VMs | **Exécuté et analysé** | `b7-profile-1p0-20260915` : 60/60 incluses sur les trois nœuds, zéro rejet explicite et zéro doublon ; processus Python ~99,8 % CPU, RSS ~49 MiB, swap nul ; les trois nœuds sont des VMs VMware, sans comparaison physique/VM |
| B8 — EVM/API/IPFS performance | Fonctionnalité IPFS et contrats déjà démontrée ; performance par couche à compléter | Ne pas mélanger ces mesures avec le TPS blockchain |

### Résultat B3 retenu

Le run `b3-rate-3p0-20260915` a offert `3 tx/s` pendant `60 s` avec un seul
client logique, soit `180` transactions préconstruites et envoyées vers node1.
Les journaux et les blocs analysés depuis la machine de développement donnent :

```text
submitted                         : 180
BENCHMARK_ACCEPT node1            : 121
BENCHMARK_REJECT node1            : 0
included_on_all_three             : 121
missing/non-observed              : 59
success_rate_all_three            : 121/180 = 67.2222 %
committed TPS over submission T2  : 121/60 = 2.0166666667 tx/s
final height on node1/node2/node3 : 116
content convergence               : yes
local_observation_complete        : false
```

La hauteur `116` représente des blocs et non des transactions. Les événements
`BENCHMARK_COMMIT` concernent 116 blocs ; l'analyse des blocs compte 121
transactions incluses, avec notamment un bloc h113 contenant deux transactions.
Le contrôle direct des journaux a confirmé la somme des champs `tx_count` :
`116` événements et `sum_tx_count=121` sur node1, node2 et node3, sans ligne de
commit non analysée. Les trois nœuds ont convergé vers le même tip observé (même
`block_hash` et même `state_root`) et node2/node3 ont ensuite un mempool vide.
La preuve est archivée dans
`results/raw_data/b3-rate-3p0-20260915-commit-audit.md`.

Les `180` représentent une charge offerte par le générateur, pas 180
acceptations applicatives. Le générateur incrémente `submitted` après une écriture
TCP `sendall()` et ne reçoit pas d'accusé individuel pour chaque transaction.
Les `59` transactions sans événement `BENCHMARK_ACCEPT` ou
`BENCHMARK_REJECT` sont donc classées **non observées/non commises**, et non
rejetées. `Connection reset by peer` est compatible avec la fermeture de la
connexion, mais ne permet pas de déterminer le sort de chacune des 59 requêtes.

Le détail reproductible de ce run est dans
`results/raw_data/b3-rate-3p0-20260915-analysis-note.md` et la fiche de protocole
mise à jour dans `results/raw_data/phase8-b3-run-sheet-2026-09-14.md`.

Ce résultat clôt le **point B3 à 3 tx/s** comme une surcharge observée ; il ne
clôt pas la matrice B3 complète et ne constitue pas une capacité maximale
universelle de la blockchain.

---

# 1. Périmètre expérimental et architecture sous test

## 1.1 Architecture retenue

| Couche | Implémentation du projet | Conséquence pour le benchmark |
|---|---|---|
| Réseau blockchain | 3 nœuds TCP en triangle complet | Mesurer les liens pair-à-pair et la convergence sur les 3 copies |
| Adresses | node1 `192.168.168.101`, node2 `192.168.168.102`, node3 `192.168.168.103` | Conserver une topologie et des IP fixes dans les journaux |
| Port P2P | `9001` | Ne pas confondre ce trafic avec l’API applicative |
| Consensus | PoA round-robin à validateurs autorisés | Mesurer les tours, timeouts et changements de proposer |
| Production | à la demande lorsque le mempool contient des transactions ; blocs vides optionnels pour benchmark | Désactiver les blocs vides pour le benchmark transactionnel principal |
| Intervalle de bloc | `5 s` dans la configuration actuelle | Ce paramètre impose une borne importante à la latence et au débit par blocs |
| Timeout de round | `5 s` dans la configuration actuelle | Mesurer séparément le coût d’un changement de proposant |
| Authentification | signatures ML-DSA-44 | Le coût de signature/vérification est dans le chemin blockchain |
| Confidentialité | ML-KEM-768 puis chiffrement symétrique côté application | ML-KEM doit être mesuré séparément s’il n’est pas exécuté pour chaque bloc |
| Exécution | py-evm via l’exécuteur EVM du projet | Mesurer l’exécution de contrat séparément du réseau |
| Contrats | registres patient, consentement et dossier médical | Utiliser des identifiants et CID synthétiques contrôlés |
| API | Flask/Gunicorn lorsqu’elle est déployée | Séparer les métriques HTTP des métriques blockchain |
| Stockage hors chaîne | 3 Kubo/IPFS co-localisés avec les nœuds | Mesurer IPFS comme couche complémentaire, pas comme TPS blockchain |
| Données | aucune donnée médicale réelle | Toutes les charges doivent être synthétiques et reproductibles |

## 1.2 Ce qui est déjà démontré

La phase précédente a principalement produit des preuves de **fonctionnalité,
d’intégrité et de convergence** :

- V1 et V2 ont des CID et des transactions distincts ;
- le même compte client a enregistré V1 et V2 ;
- les trois nœuds convergent à la hauteur 6 sur le même `state_root` ;
- `registerRecord()` sans consentement est rejeté sur les trois nœuds avec
  `UnauthorizedRecordRegistration` ;
- la confidentialité contrôlée est validée avec ML-KEM-768 et AES-256-GCM ;
- les récupérations IPFS et les empreintes des ciphertexts ont déjà été
  vérifiées sur les trois fournisseurs.

Ces résultats ne sont pas encore un benchmark de performance. Ils constituent
l’état fonctionnel de référence à préserver avant toute campagne de charge.
Aucun benchmark ne doit exécuter `make clean-data`, modifier les CID historiques,
supprimer les clés de validateurs ou remplacer le scénario d’entrée par des
requêtes directes aux trois nœuds.

## 1.3 Point méthodologique essentiel : définir la finalité

Dans cette implémentation, il faut éviter d’écrire sans précision que la
transaction possède une « finalité instantanée ». Le protocole produit et
signe un bloc, puis chaque nœud l’accepte et le persiste. Il n’existe pas, dans
les éléments actuellement observés, de certificat de quorum séparé comparable
à un protocole BFT avec preuve de finalité explicite.

L’article doit donc utiliser trois notions mesurables :

1. **latence d’inclusion** : temps entre l’émission client et l’inclusion de la
   transaction dans le premier bloc accepté ;
2. **latence de commit local** : temps entre l’émission et la persistance du
   bloc sur le nœud observé ;
3. **latence de convergence** : temps entre l’émission et l’observation du même
   bloc, du même `block_hash` et du même `state_root` sur les trois nœuds.

La troisième mesure est la définition expérimentale la plus défendable pour la
« finalisation applicative » de ce projet. Elle doit être nommée ainsi dans
l’article plutôt que d’être confondue avec une finalité théorique plus forte.

---

# 2. Tests et benchmarks généralement utilisés

## 2.1 Contrôle fonctionnel et intégrité

Avant de mesurer la vitesse, un benchmark blockchain doit vérifier que les
résultats sont valides :

- chaque transaction réussie apparaît dans un bloc ;
- les transactions échouées sont comptées et ne sont pas présentées comme
  réussies ;
- tous les nœuds obtiennent la même hauteur, le même hash de bloc et le même
  `state_root` ;
- aucune transaction n’est perdue, dupliquée ou exécutée dans un ordre différent ;
- les règles d’autorisation produisent le même résultat partout ;
- le stockage IPFS renvoie des octets dont le hash correspond à la référence.

**Métriques :** taux de succès, taux d’échec, nombre de doublons, transactions
manquantes, divergence de hauteur, divergence de hash, divergence de
`state_root`, nombre de reverts par type.

Ce test est un prérequis, pas un résultat de performance. Une campagne avec un
bon TPS mais un `state_root` divergent est invalide.

## 2.2 Débit transactionnel

Le débit est le nombre de transactions effectivement **commises** par seconde,
et non le nombre de requêtes envoyées par le générateur :

```text
TPS_committed = nombre de transactions incluses et validées
                 / durée de mesure
```

Il faut aussi publier le débit utile :

```text
Goodput = transactions réussies et commises / durée de mesure
```

Deux valeurs sont souvent nécessaires :

- **offered rate** : taux d’émission demandé par le client ;
- **achieved rate** : taux effectivement commis par la blockchain.

La courbe intéressante est celle qui montre le point où augmenter le taux
émis n’augmente plus le débit commis mais augmente la file d’attente et la
latence.

## 2.3 Latence transactionnelle

La latence doit être définie avec deux bornes explicites :

```text
latence HTTP/API       = t_réponse_API - t_requête_API
latence end-to-end     = t_commit_observé - t_soumission_client
```

Pour une blockchain distribuée, il faut au minimum mesurer :

- soumission → réception par node1 ;
- soumission → inclusion dans le premier bloc ;
- soumission → commit sur node1 ;
- soumission → commit sur node2 ;
- soumission → commit sur node3 ;
- soumission → convergence des trois nœuds.

La moyenne seule est insuffisante. Il faut publier médiane, p95 et p99, car
les timeouts de round et les retransmissions apparaissent dans la queue de
distribution.

## 2.4 Temps de production et de finalisation des blocs

Ce test observe la chaîne elle-même plutôt que chaque requête :

- intervalle entre deux blocs ;
- nombre de transactions par bloc ;
- temps de proposition ;
- temps de validation d’un bloc reçu ;
- temps de propagation du bloc ;
- nombre de tours de consensus utilisés ;
- nombre de timeouts ;
- temps de rattrapage après retard d’un nœud.

Le débit théorique dépend notamment du nombre moyen de transactions par bloc
et de l’intervalle entre blocs :

```text
TPS ≈ transactions_moyennes_par_bloc / intervalle_moyen_de_bloc
```

Cette approximation ne remplace pas la mesure end-to-end ; elle sert à
expliquer les résultats. Avec un intervalle configuré à 5 secondes, une charge
qui envoie une seule transaction par bloc ne doit pas être comparée à une
architecture qui produit plusieurs blocs par seconde sans normalisation.

## 2.5 Scalabilité

La scalabilité n’est pas une seule expérience. Elle peut être étudiée selon
plusieurs dimensions :

1. nombre de clients concurrents ;
2. taux d’arrivée des transactions ;
3. taille de la transaction et du payload ;
4. nombre de transactions par bloc ;
5. nombre de nœuds validateurs ;
6. nombre de fournisseurs IPFS ;
7. nombre de workers API ;
8. taille de l’état et de la chaîne.

La définition expérimentale est la variation du débit, de la latence et de la
consommation de ressources lorsque l’on augmente une seule dimension en gardant
les autres constantes.

Dans notre projet, la scalabilité **par clients et par charge** est directement
réalisable. La scalabilité par nombre de validateurs est limitée à 1, 2 et 3
nœuds et nécessite des déploiements distincts avec une configuration PoA et un
genesis cohérents. Il ne faut pas présenter un test à 1 nœud comme une
scalabilité horizontale de la même chaîne à 3 nœuds sans préciser qu’il s’agit
d’une configuration de comparaison.

## 2.6 Tolérance aux pannes et reprise

Les scénarios généralement utilisés sont :

- arrêt brutal d’un nœud ;
- arrêt du proposant attendu ;
- redémarrage d’un nœud en retard ;
- délai réseau ;
- perte de paquets ;
- partition réseau ;
- messages corrompus ou contradictoires ;
- comportement byzantin d’un validateur.

BLOCKBENCH mesure notamment l’évolution du débit et de la latence pendant une
panne et distingue crash, délai réseau et réponses aléatoires. Cette structure
est adaptée à notre analyse, mais le niveau de panne doit être limité à ce que
le code supporte réellement.

Pour notre PoA, les tests directement défendables sont :

- crash d’un validateur ;
- crash du proposant courant ;
- reprise et synchronisation du nœud arrêté ;
- délai ou perte réseau contrôlée.

Un test d’un nœud malveillant qui signe intentionnellement des blocs
contradictoires ne doit pas être présenté comme réalisé si cette campagne n’a
pas été implémentée et si le protocole courant ne fournit pas une tolérance
byzantine complète.

## 2.7 Consommation de ressources

Il faut observer les ressources du processus blockchain et, lorsque c’est
possible, celles de l’ensemble de la machine :

- CPU moyen, médian et pic ;
- mémoire RSS moyenne et pic ;
- mémoire disponible ;
- swap ;
- débit réseau entrant et sortant ;
- nombre de connexions TCP ;
- lecture et écriture disque ;
- taille du répertoire de chaîne ;
- taille de l’état EVM ;
- temps CPU par transaction ;
- nombre de transactions par GiB ou par seconde de trafic.

Caliper documente la collecte de CPU, mémoire, réseau et disque pour le
processus testé. Dans notre expérience, on peut reproduire ce principe avec
`pidstat`, `psutil`, `/proc`, `ss`, `ip -s link` et `du`, sans introduire une
infrastructure de monitoring lourde.

## 2.8 Overhead cryptographique post-quantique

Le benchmark cryptographique doit isoler :

### ML-DSA-44

- génération de paire de clés ;
- signature d’une transaction ;
- vérification d’une transaction ;
- signature d’un bloc ;
- vérification d’un bloc ;
- taille de clé publique, clé secrète et signature ;
- impact du nombre de signatures vérifiées par bloc.

FIPS 204 spécifie ML-DSA comme algorithme de signature post-quantique. Pour
ML-DSA-44, les tailles normalisées sont 2 560 octets pour la clé secrète,
1 312 octets pour la clé publique et 2 420 octets pour la signature
([NIST FIPS 204](https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.204.pdf)). Les
valeurs réellement produites par `liboqs-python` doivent être mesurées et
rapportées, même lorsqu’elles correspondent aux valeurs de la norme.

### ML-KEM-768

- génération de paire de clés ;
- encapsulation ;
- décapsulation ;
- taille de clé publique, clé secrète et ciphertext KEM ;
- taille finale de l’enveloppe chiffrée ;
- échec d’authentification avec une mauvaise clé ;
- coût AES-GCM et dérivation de clé, si utilisés.

FIPS 203 définit ML-KEM comme une primitive d’établissement de secret partagé,
et non comme un chiffrement complet ; le secret partagé doit être utilisé avec
un chiffrement symétrique pour protéger et authentifier les données
([NIST FIPS 203](https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.203.pdf)). Pour
ML-KEM-768, les valeurs normalisées sont 1 184 octets pour la clé publique,
2 400 octets pour la clé secrète, 1 088 octets pour le ciphertext KEM et 32
octets pour le secret partagé.

**Attention d’interprétation :** ML-DSA est dans le chemin de validation des
transactions/blocs du projet. ML-KEM sert principalement à la confidentialité
hors chaîne. Si ML-KEM n’est pas appelé pour chaque transaction blockchain, son
coût ne doit pas être ajouté artificiellement au TPS du consensus. Il doit
être présenté comme overhead de la couche de confidentialité.

## 2.9 Performance de l’exécution EVM

Les opérations de contrat doivent être mesurées séparément :

- `registerRecord()` valide ;
- `getRecord()` en lecture ;
- `revokeRecord()` valide ;
- tentative sans consentement ;
- record inexistant ;
- CID trop long ;
- tentative de doublon.

Pour chaque appel :

- temps d’exécution py-evm ;
- `receipt.status` ;
- `gas_used` ;
- taille de calldata ;
- taille de la sortie ;
- nombre et taille des logs ;
- variation du `state_root` pour une écriture ;
- absence de variation du `state_root` pour une lecture ou un revert.

La documentation py-evm expose l’application d’une transaction à un état et la
production d’un reçu ; cela permet de distinguer le coût de l’exécution EVM du
coût de consensus et du coût réseau ([API py-evm](https://py-evm.readthedocs.io/en/latest/api/api.abc.html)).

## 2.10 Performance Flask/Gunicorn

La couche HTTP doit faire l’objet d’un benchmark indépendant :

- requête de soumission au nœud d’entrée ;
- requête de lecture de métadonnées ;
- requête de lecture IPFS ;
- taux de requêtes HTTP par seconde ;
- latence HTTP p50/p95/p99 ;
- codes HTTP 2xx, 4xx et 5xx ;
- requêtes en timeout ;
- nombre de workers Gunicorn ;
- files d’attente et connexions ;
- CPU et mémoire par worker.

Gunicorn peut exposer des statistiques de requêtes et un histogramme de durée
via son logger StatsD, ce qui est utile pour séparer la latence de l’API de la
latence de commit blockchain ([documentation Gunicorn](https://docs.gunicorn.org/_/downloads/en/20.x/pdf/)).

Le débit HTTP ne doit jamais être présenté comme le TPS blockchain. Une API
peut répondre rapidement à une requête d’acceptation alors que la transaction
n’est pas encore incluse dans un bloc.

## 2.11 Benchmark IPFS complémentaire

Même si IPFS n’est pas la blockchain, il faut mesurer la partie pertinente du
scénario médical :

- temps d’ajout d’un ciphertext ;
- taille du ciphertext ;
- temps de pin ;
- disponibilité sur chacun des trois fournisseurs ;
- temps de récupération local ;
- temps de récupération après réplication ;
- taux d’échec de récupération ;
- taille du repository ;
- mémoire et CPU de Kubo ;
- délai de réplication entre fournisseurs.

Les valeurs déjà obtenues pour les récupérations loopback v1/v2 doivent rester
identifiées comme des **latences API IPFS locales**, et non comme une mesure
pure de transfert Bitswap inter-VM.

---

# 3. Métriques à collecter et moment de la mesure

## 3.1 Chronologie commune d’un essai

Chaque essai doit être découpé en cinq périodes :

```text
T0  préparation et vérification de l'état
T1  warm-up non mesuré
T2  fenêtre de mesure
T3  drain : attendre les transactions encore en file
T4  vérification post-test et archivage
```

La nomenclature temporelle canonique par transaction est :

```text
t_submit       : envoi par le générateur vers node1
t_receive      : réception et validation par node1
t_propose      : inclusion dans le bloc proposé
t_commit_local : acceptation et persistance locale
t_commit_remote: observation du même bloc par node2 et node3
t_stable       : absence de divergence pendant la fenêtre de stabilité définie
```

`t_stable` doit être défini avant la campagne, par exemple comme l’observation
du même `block_hash`, de la même hauteur et du même `state_root` sur les trois
nœuds pendant au moins un intervalle de bloc supplémentaire. Cette définition
mesure une convergence expérimentale ; elle ne crée pas un certificat de
finalité BFT qui n’existe pas dans l’implémentation actuelle.

### T0 — préparation

À mesurer avant la charge :

- version du code et hash des fichiers ;
- versions Python, py-evm, liboqs, liboqs-python, Flask et Gunicorn ;
- nombre de cœurs, fréquence CPU, RAM, type de virtualisation ;
- configuration PoA, intervalle et timeout ;
- hauteur, hash de tête et `state_root` de départ ;
- état du mempool ;
- taille des répertoires `data/nodeN` et du repository IPFS ;
- horloge système et dérive entre machines ;
- état des interfaces et routes réseau.

### T1 — warm-up

Le warm-up permet de charger Python, liboqs, py-evm, caches de fichiers et
workers Gunicorn. Les échantillons de cette période ne doivent pas être
mélangés aux résultats mesurés. Sa durée recommandée est de 30 à 60 secondes,
ou d’au moins deux intervalles de bloc pour ce projet.

### T2 — fenêtre mesurée

Pendant cette période, enregistrer chaque transaction avec un identifiant
unique et les horodatages suivants :

```text
run_id
scenario
client_id
transaction_id
nonce
t_submit_client
 t_ingress_node1
 t_mempool_node1
 t_proposal
 t_block_accept_node1
 t_block_accept_node2
 t_block_accept_node3
 t_converged
 block_height
 block_hash
 state_root
 proposal_round
 receipt_status
 gas_used
 error_code
```

Les espaces dans `t_ingress_node1` et `t_mempool_node1` sont uniquement
visuels dans cette documentation : les noms de colonnes doivent être écrits
sans espace dans le fichier CSV/JSONL.

### T3 — drain

Après l’arrêt des émissions, il faut attendre :

- que le mempool soit vide ;
- que les transactions restantes soient commises ou déclarées échouées ;
- que les trois nœuds atteignent la même hauteur ;
- que les hashes de blocs et `state_root` correspondent.

Les transactions émises mais non encore commises à la fin de T2 ne doivent pas
être supprimées silencieusement. Elles sont comptées dans le backlog et leur
latence est mesurée jusqu’à T3.

### T4 — vérification

Archiver :

- nombre de transactions soumises, reçues, commises et échouées ;
- liste des transactions manquantes ;
- divergences éventuelles de chaîne ;
- logs de chaque nœud ;
- échantillons de ressources ;
- configuration `tc` si une dégradation réseau a été appliquée ;
- hash du fichier de résultat.

## 3.2 Tableau des métriques principales

| Métrique | Définition | Moment et source |
|---|---|---|
| Taux d’émission | transactions demandées par seconde | horloge du générateur pendant T2 |
| TPS soumis | transactions envoyées / durée | générateur client |
| TPS accepté | transactions acceptées par node1 / durée | réponse d’ingress/mempool |
| TPS commis | transactions présentes dans des blocs valides / durée | lecture des blocs après T3 |
| Goodput | transactions commises avec `status=1` / durée | reçus et blocs |
| Taux d’échec | transactions `status=0` ou non commises / soumises | reçus, logs, drain |
| Latence API | réponse HTTP − requête HTTP | client Flask/Gunicorn |
| Latence inclusion | premier bloc contenant la tx − soumission | client + lecture bloc |
| Latence commit local | acceptation/persistance nodeN − soumission | logs nodeN ou endpoint de suivi |
| Latence convergence | dernier des 3 commits − soumission | trois nœuds |
| P50/P95/P99 | percentiles des latences | post-traitement par scénario |
| Intervalle bloc | timestamp bloc i − bloc i−1 | chaîne persistée |
| Transactions/bloc | nombre de tx du bloc | bloc |
| Taille bloc | octets sérialisés ou JSON | stockage/réseau |
| Round | numéro de proposition utilisé | en-tête du bloc |
| Timeout | changement de round après expiration | logs PoA |
| Propagation | acceptation distante − acceptation source | logs synchronisés ou accusé |
| CPU | moyenne, pic, CPU-secondes | `pidstat`, `psutil`, `/proc` |
| RSS | moyenne et pic du processus | `psutil` ou `/proc` |
| Réseau | octets et paquets reçus/envoyés | `ip -s link`, `/proc/net/dev` |
| Disque | octets lus/écrits et croissance data | `pidstat -d`, `du`, stockage |
| EVM | durée, gas, status, logs | reçu et chronométrage executor |
| Crypto | durée keygen/sign/verify/encap/decap | microbenchmark `perf_counter_ns` |
| Intégrité | hauteur, hash, `state_root` par nœud | T0 et T4 |

## 3.3 Horloges et synchronisation

Les horodatages pris dans un seul générateur peuvent utiliser
`time.perf_counter_ns()` et fournir une excellente durée locale. En revanche,
les horloges monotoniques de deux machines ne sont pas directement comparables.

Deux méthodes sont acceptables :

1. synchroniser les horloges avec NTP/chrony, mesurer l’écart résiduel et
   l’indiquer dans la méthode ;
2. faire remonter les événements distants au client avec un accusé de réception,
   puis calculer la durée depuis l’horloge du client.

Pour un article scientifique, la seconde méthode est préférable pour la
latence de convergence. Les journaux distants peuvent en plus être conservés
pour l’audit, mais les différences d’horloge ne doivent pas être présentées
comme des latences réseau sans correction.

---

# 4. Tests compatibles avec l’architecture du projet

## 4.1 Matrice de décision

| Test | Compatibilité | Priorité | Remarque |
|---|---:|---:|---|
| Reproductibilité de l’environnement | Oui | P0 | Indispensable avant toute valeur numérique |
| Vérification de convergence | Oui | P0 | Déjà démontrée fonctionnellement ; à répéter après charge |
| Microbenchmark ML-DSA-44 | Oui | P0 | Directement pertinent pour PoA et validation |
| Microbenchmark ML-KEM-768 | Oui | P0 | Pertinent pour la confidentialité hors chaîne |
| Baseline 3 nœuds | Oui | P0 | Mesure principale de l’article |
| Charge par taux d’arrivée | Oui | P0 | Révèle le point de saturation |
| Charge par concurrence | Oui | P1 | Mesure la file et la latence sous clients multiples |
| Latence réseau | Oui | P1 | `tc netem`, avec privilèges et nettoyage contrôlé |
| Perte de paquets | Oui | P1 | Scénarios faibles et documentés |
| Crash du proposant | Oui | P0 | Directement lié au timeout PoA |
| Reprise d’un nœud | Oui | P0 | Vérifier synchronisation et intégrité |
| Partition byzantine | Non comme résultat actuel | P2 | Nécessite une extension et une définition de sécurité |
| Scalabilité 1/2/3 nœuds | Partielle | P1 | Déploiements distincts et genesis cohérent |
| Scalabilité >3 nœuds | Non prioritaire | P3 | Hors capacité et hors architecture retenue |
| Profil comparatif des trois VMs | Oui | P1 | CPU, mémoire et variabilité à documenter ; comparaison physique/VM exclue |
| Exécution py-evm | Oui | P1 | Mesure de couche, pas TPS réseau seul |
| Flask/Gunicorn | Conditionnelle | P1 | Seulement si l’API déployée est stabilisée |
| IPFS local/réplication | Oui | P1 | Couche complémentaire au benchmark blockchain |
| Énergie réelle | Non actuellement | P3 | Nécessite wattmètre ou métrique hyperviseur fiable |
| Comparaison avec Ethereum public | Non recommandée | P3 | Sémantique, paramètres et menaces différents |

## 4.2 Tests à retenir pour l’article

Le noyau minimal mais convaincant est :

```text
B0  environnement et intégrité
B1  ML-DSA-44 / ML-KEM-768
B2  baseline 3 nœuds sans perturbation
B3  charge croissante et saturation
B4  latence d'inclusion et convergence
B5  crash/reprise d'un validateur
B6  réseau dégradé
B7  profil comparatif des trois VMs
B8  exécution EVM et couche API/IPFS en complément
```

Les tests B0 à B7 suffisent à répondre à la question « la solution fonctionne-t-
elle et à quel coût dans son environnement expérimental ? ». B8 permet de
relier la blockchain au scénario applicatif médical sans confondre les couches.

---

# 5. Mise en œuvre concrète des tests retenus

## 5.1 B0 — Reproductibilité et baseline de configuration

### Préparation

Sur chaque nœud, conserver les clés existantes et exécuter uniquement des
commandes de lecture :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
make check-oqs
python3 --version
python3 -c 'import oqs; print(oqs.oqs_version())'
sha256sum src/crypto/*.py src/blockchain/*.py src/node/*.py
lscpu
free -h
ip -s link
ss -ltnp
```

Conserver les sorties avec le nom du nœud. Ne pas inclure les fichiers de clés
secrètes dans les résultats.

### Mesures

- versions et hash du code ;
- type de machine : physique ou VM ;
- vCPU/cœurs, RAM, fréquence et hyperviseur ;
- état initial de la chaîne ;
- configuration PoA ;
- latence ICMP et TCP entre les trois IP ;
- absence de processus concurrents importants.

### Présentation

Une table « Experimental setup » doit précéder tous les graphiques. Les
résultats de performance sans cette table ne sont pas reproductibles.

## 5.2 B1 — Microbenchmark PQC

### Protocole

Pour chaque nœud et chaque opération :

1. générer les clés hors fenêtre mesurée lorsque l’on mesure une opération
   répétitive ;
2. exécuter 100 itérations de warm-up ;
3. exécuter au moins 1 000 opérations mesurées, ou suffisamment pour dépasser
   une seconde ;
4. mesurer avec `time.perf_counter_ns()` ;
5. répéter 5 fois la série complète ;
6. publier médiane, p95, p99 et écart interquartile.

Opérations ML-DSA-44 :

```text
keygen
sign(message de 32 octets)
sign(message de 1 KiB)
verify(message de 32 octets)
verify(message de 1 KiB)
```

Opérations ML-KEM-768 :

```text
keygen
encapsulate
 decapsulate
```

Le message `decapsulate` est le ciphertext produit par l’encapsulation avec la
clé publique correspondante. Vérifier également qu’une mauvaise clé produit
un secret différent et que l’authentification AES-GCM échoue.

### Mesures

- temps par opération en microsecondes ;
- opérations par seconde ;
- taille des clés, signatures et ciphertexts ;
- CPU et RSS pendant la série ;
- différence physique/VM ;
- ratio p99/p50, révélateur de variabilité.

### Présentation

- tableau des tailles normalisées ;
- barres groupées keygen/sign/verify et encap/decap ;
- boxplots ou violons des latences ;
- tableau séparé par nœud ;
- phrase claire indiquant quelles opérations sont dans le chemin blockchain.

## 5.3 B2 — Baseline blockchain à 3 nœuds

### Conditions contrôlées

- trois nœuds actifs ;
- scénario client/médecin → node1 ;
- diffusion P2P normale vers node2 et node3 ;
- aucune règle `tc netem` ;
- mempool initialement vide ;
- pas de production de blocs vides ;
- charge de transactions synthétiques valides ;
- code, paramètres et clés de validation inchangés ;
- IPFS non inclus dans la première mesure, afin d’isoler la blockchain.

Le générateur doit produire des transactions avec :

- nonce unique ;
- identifiants de dossier synthétiques distincts ;
- payloads de taille contrôlée ;
- signature ML-DSA valide ;
- émission uniquement vers node1.

L’option actuelle `--send-tx` sert à la vérification manuelle d’une transaction,
pas à une campagne de débit. Une campagne de performance doit utiliser un
générateur contrôlé capable d’émettre une séquence de transactions et
d’enregistrer les identifiants et timestamps. Ce générateur peut être un script
de benchmark indépendant ; il ne doit pas devenir un orchestrateur qui modifie
les VMs ou copie les clés.

### Charges recommandées

Commencer par une charge faible, puis augmenter progressivement :

```text
0,1 tx/s
0,2 tx/s
0,5 tx/s
1 tx/s
2 tx/s
5 tx/s
10 tx/s si la file reste maîtrisée
```

Ces valeurs ne sont pas des résultats attendus ; ce sont des points de départ.
La charge maximale doit être arrêtée ou marquée dès que la file croît sans
borne, que les timeouts apparaissent ou que le taux de succès baisse.

Pour chaque point :

- 30–60 s de warm-up ;
- 60–120 s de mesure ;
- drain jusqu’à vidage du mempool ;
- au moins 5 répétitions indépendantes ;
- même séquence de tailles et de types de transactions.

### Mesures à extraire

```text
send_rate
accepted_rate
committed_tps
goodput
success_rate
failure_rate
latency_p50
latency_p95
latency_p99
backlog_max
blocks_created
transactions_per_block
CPU/RSS par nœud
network bytes par nœud
state_root final
```

### Présentation

Figure principale : taux offert en abscisse, débit commis en ordonnée, une
courbe par scénario.

Figure secondaire : taux offert en abscisse, latence p50/p95/p99 en ordonnée.

Tableau : médiane et intervalle de confiance à 95 % par charge.

Une annotation verticale doit indiquer le point de saturation observé. Il faut
rapporter les transactions rejetées et non seulement la courbe du débit.

## 5.4 B3 — Charge, saturation et scalabilité par clients

### Variante A : taux d’arrivée contrôlé

Le générateur émet à un taux fixe. Les valeurs augmentent jusqu’à ce que :

- le débit commis plafonne ;
- la latence p95 augmente fortement ;
- le mempool se remplisse ;
- le taux de timeout ou d’échec apparaisse.

### Variante B : concurrence contrôlée

Maintenir 1, 2, 4, 8 puis 16 clients logiques, mais toujours en envoyant via
node1 pour respecter le scénario expérimental. Chaque client possède une plage
de nonces et d’identifiants indépendante.

### Variante C : taille de payload

Utiliser des payloads de taille synthétique fixe :

```text
0 octet de data
128 octets
1 KiB
4 KiB
16 KiB
```

Le contenu médical ne doit jamais être utilisé. Pour le registre de dossiers,
le CID reste un pointeur et les données volumineuses restent hors chaîne.

### Présentation

- courbe débit contre nombre de clients ;
- courbe latence contre nombre de clients ;
- courbe mémoire et trafic contre taille de transaction ;
- tableau indiquant le nombre de transactions réellement commises ;
- discussion du point où le goulot devient consensus, signature, EVM, disque
  ou réseau.

### Résultat exécuté — B3 à 3 tx/s

Le premier point B3 a été exécuté le 15 septembre 2026 avec `1` client logique,
`60 s` de mesure, `payload-size=0` et `drain-timeout=300 s`. Le générateur a
offert `180` transactions, dont `121` ont été observées comme acceptées par
node1 et incluses sur les trois copies. Aucun rejet explicite n'a été journalisé.

```text
submitted                         : 180
accepted node1                    : 121
rejected node1                    : 0
included on all three             : 121
success rate                      : 67.2222 %
committed TPS over T2              : 2.0167 tx/s
final height                      : 116 on node1/node2/node3
converged block_hash/state_root   : yes
```

Ce résultat confirme une surcharge à 3 tx/s dans le mode expérimental contraint,
mais il ne signifie pas que 3 tx/s sont soutenues avec 100 % de complétude. Les
`59` transactions restantes n'ont ni événement d'acceptation ni événement de
rejet et sont classées non observées/non commises. Le `submitted` du générateur
correspond à une écriture TCP et non à un accusé applicatif individuel.

La hauteur 116 compte des blocs et non des transactions. Les lignes de commit
comptent 116 blocs. Le contrôle direct des journaux donne
`sum(tx_count)=121` sur chacun des trois nœuds, ce qui réconcilie explicitement
les 121 transactions incluses ; les blocs h17, h54, h93, h105 et h113 portent
chacun deux transactions. Les latences numériques inter-VM de convergence
restent non mesurées sans synchronisation ou correction indépendante des
horloges. Le détail du contrôle est archivé dans
`results/raw_data/b3-rate-3p0-20260915-commit-audit.md`.

Le point B4 à `1 tx/s` a maintenant été exécuté et analysé. Le run
`b4-rate-1p0-20260915` (1 client, 60 s, payload synthétique nul, drain de
300 s) a inclus `60/60` transactions sur les trois nœuds, sans doublon ni rejet
explicite. La latence observée sur node1 est de 260,47 ms en médiane et
393,17 ms au p95, avec un maximum de 5,51 s. Les trois chaînes convergent vers
la même hauteur, le même `block_hash` et le même `state_root`; la latence
numérique inter-VM reste `not_measured` à cause des horloges non synchronisées.
La note détaillée est `results/raw_data/b4-rate-1p0-20260915-analysis-note.md`.
Le run B5 `b5-secondary-crash-20260915` a été exécuté et analysé : node3 a été
arrêté puis redémarré, les `12/12` transactions ont finalement été incluses sur
les trois nœuds et les chaînes ont convergé à la hauteur `11`. La queue de
latence atteint environ `5,1 s`, mais la durée exacte du failover reste
partiellement instrumentée. La note est
`results/raw_data/b5-secondary-crash-20260915-analysis-note.md`.
Le run B6 `b6-delay50ms-20260915` a maintenant été exécuté puis analysé depuis
la machine de développement. À `0,2 tx/s` pendant `60 s`, avec `tc-netem delay
50ms 10ms` et sans perte de paquets, `12/12` transactions ont été acceptées et
incluses sur les trois nœuds, sans doublon observé. La latence locale node1
soumission → commit est de `300,73 ms` en médiane, `438,50 ms` au p95 et
`470,72 ms` au maximum. Les tips convergent à la hauteur `12` vers le même hash
et la même racine d'état. Les mesures acceptation → commit des trois VMs sont
locales et ne constituent pas des latences end-to-end inter-VM. Ce résultat est
fonctionnellement positif pour ce point exploratoire, sans constituer une
capacité maximale ni une mesure de perte.
La note détaillée est `results/raw_data/b6-delay50ms-20260915-analysis-note.md`
et le résumé est `results/raw_data/b6-delay50ms-20260915-summary.json`.

La clôture opérationnelle est acquise : les vérifications post-run ont été
archivées dans `results/raw_data/b6-delay50ms-20260915-qdisc-cleanup.txt`.
Les trois sorties indiquent `fq_codel` sur `ens33` et aucune ne contient
`qdisc netem`; les nœuds ont ensuite été arrêtés. La latence numérique de
convergence inter-VM reste `not_measured` sans synchronisation indépendante des
horloges.

Le point B3-N a aussi été exécuté avec un taux total constant de `1 tx/s` et
`1`, `2`, `4` puis `8` clients logiques, tous connectés à node1. Chaque run a
inclus `60/60` transactions sur les trois nœuds, sans doublon ni rejet
explicite. La médiane node1 augmente de `296,18 ms` à `1 028,45 ms` et le p95
de `391,74 ms` à `1 941,10 ms`. Cette série mesure des flux logiques sur node1,
pas des machines clientes distinctes. Les résultats sont archivés dans
`results/raw_data/b3-client-concurrency-20260915-analysis-note.md` et
`results/raw_data/b3-client-concurrency-20260915-comparison.json`.

Le point B7 `b7-profile-1p0-20260915` a ensuite été exécuté avec un client à
`1 tx/s`, `60 s` de soumission, payload synthétique nul et collecte de ressources
pendant `120 s`. Les `60/60` transactions sont présentes sur les trois nœuds,
sans erreur, rejet explicite ni doublon. Les trois VMs montrent environ `99,8 %`
de CPU pour le processus Python et environ `49 MiB` de RSS, avec swap nul,
attente I/O nulle et trafic observé inférieur à `18 KiB` par VM sur la fenêtre.
La note est `results/raw_data/b7-profile-1p0-20260915-analysis-note.md`.

## 5.5 B4 — Latence d’inclusion, commit et convergence

### Instrumentation

Pour chaque transaction `tx_id`, corréler :

1. timestamp d’émission du client ;
2. réception par node1 ;
3. première présence dans un bloc ;
4. acceptation du bloc par node1 ;
5. acceptation du même bloc par node2 ;
6. acceptation du même bloc par node3 ;
7. confirmation de hauteur/hash/`state_root` identiques.

Un bloc n’est pas considéré comme convergent uniquement parce que les trois
nœuds ont la même hauteur. Il faut vérifier au minimum le même hash de bloc et
le même `state_root`.

### Métriques

```text
L_inclusion = t_first_block - t_submit
L_node1     = t_accept_node1 - t_submit
L_node2     = t_accept_node2 - t_submit
L_node3     = t_accept_node3 - t_submit
L_converge  = max(t_accept_node1, t_accept_node2, t_accept_node3) - t_submit
```

### Présentation

- CDF de `L_inclusion` et `L_converge` ;
- boxplot par nœud ;
- timeline d’un échantillon avec émission, proposition et acceptation ;
- tableau des rounds et timeouts ;
- corrélation entre latence et nombre de transactions par bloc.

## 5.6 B5 — Crash d’un proposant et reprise

### Scénario 1 : crash du proposant

1. démarrer les trois nœuds ;
2. injecter une charge faible via node1 ;
3. identifier le proposer attendu pour la prochaine hauteur ;
4. arrêter ce processus avant sa proposition ;
5. observer le passage au round suivant ;
6. laisser le nœud suivant proposer ;
7. redémarrer le nœud arrêté ;
8. observer son rattrapage.

L’arrêt doit être effectué par PID, jamais avec un `pkill -f` trop large.

### Scénario 2 : crash d’un nœud secondaire

Répéter en arrêtant un nœud qui n’est pas le proposant courant. Cela mesure
l’effet sur la latence des deux nœuds restants et la capacité de resynchroniser
le nœud arrêté.

### Mesures

- hauteur au moment de la panne ;
- hauteur au redémarrage ;
- temps jusqu’à la prochaine proposition ;
- nombre de timeouts ;
- transactions commises avant, pendant et après la panne ;
- backlog ;
- temps de rattrapage ;
- divergences de `block_hash` ou `state_root` ;
- nombre de transactions dupliquées ou manquantes.

Avec la configuration actuelle, le timeout de round est d’environ 5 secondes.
Il faut donc s’attendre à un ordre de grandeur lié à ce paramètre, sans le
présenter comme une constante universelle du consensus PoA.

### Présentation

- timeline annotée de la panne et de la reprise ;
- tableau baseline / panne / reprise ;
- courbe hauteur de chaîne contre temps pour les trois nœuds ;
- barres du temps de rattrapage ;
- encadré « crash-only, not Byzantine ».

## 5.7 B6 — Latence, perte et limitation réseau

Linux `tc netem` permet d’émuler délai, jitter, perte, corruption, duplication,
réordonnancement et limitation de débit ([manuel `tc-netem`](https://man7.org/linux/man-pages/man8/tc-netem.8.html)).

### Scénarios raisonnables

| Scénario | Paramètre indicatif |
|---|---|
| baseline | aucun `netem` |
| délai faible | 10 ms |
| délai moyen | 50 ms |
| délai élevé | 100 ms |
| jitter | 50 ms ± 10 ms |
| perte faible | 0,1 % |
| perte moyenne | 1 % |
| perte forte | 5 % |
| limitation | 5 ou 10 Mbit/s |

Une seule perturbation doit être activée à la fois dans la campagne principale.
Les scénarios combinés doivent être présentés comme exploratoires.

Exemple à exécuter avec prudence sur l’interface choisie :

```bash
sudo tc qdisc add dev <interface> root netem delay 50ms 10ms
# exécuter un seul scénario
sudo tc qdisc del dev <interface> root
```

La commande peut affecter SSH et d’autres flux ; elle doit être préparée dans
une session de secours. Il faut vérifier l’état avant et après :

```bash
tc qdisc show dev <interface>
```

### Mesures

- RTT et jitter ;
- débit commis ;
- latence p50/p95/p99 ;
- timeouts et changements de round ;
- nombre de retransmissions TCP ;
- trafic par nœud ;
- taux de convergence ;
- transactions manquantes.

### Présentation

Heatmap délai/perte → latence p95 et goodput ; courbe de dégradation du débit ;
tableau du taux de succès et du nombre de timeouts.

## 5.8 B7 — Profil comparatif des trois VMs VMware

Les contrôles réels de l’étape 1 montrent que node1, node2 et node3 sont tous
des VMs sous VMware. Cette campagne ne contient donc aucune machine physique et
ne permet pas d’attribuer une différence à la virtualisation par comparaison
contrôlée.

### Protocole

- documenter le vCPU, la mémoire, le noyau et l’hyperviseur de chaque VM ;
- garder la même version de code et les mêmes paramètres ;
- exécuter la même charge via node1 ;
- utiliser le round-robin pour associer les mesures au proposer réel ;
- mesurer node1, node2 et node3 séparément ;
- rapporter les différences comme variabilité entre VMs, sans conclusion
  physique/VM.

### Mesures normalisées

```text
CPU moyen et pic
RSS moyen et pic
CPU-secondes / transaction commise
octets réseau / transaction
écritures disque / transaction
latence de validation locale
latence de convergence
```

### Présentation

- tableau complet des ressources visibles de chaque VM ;
- barres groupées node1/node2/node3 pour p50/p95, CPU et mémoire ;
- nuage latence contre CPU ;
- normalisation par vCPU et par transaction ;
- paragraphe de limites indiquant qu’il s’agit d’une comparaison de
  déploiements virtualisés, non d’une attribution causale à la virtualisation.

## 5.9 Résultat B7 — profil des trois VMs

Le run `b7-profile-1p0-20260915` a été exécuté à `1 tx/s` pendant `60 s` avec
un client logique, un payload synthétique nul et node1 comme seul ingress. Le
manifeste et le résumé JSON sont valides. Les `60` transactions soumises sont
présentes sur les trois chaînes (`included_on_all_three=60`), avec un taux de
succès observé de `100 %`, zéro rejet explicite, zéro erreur de charge et zéro
doublon. Le résumé indique également la convergence des trois chaînes vers le
tip commun observé.

Les collecteurs ont produit `120` échantillons `vmstat` par nœud et trois
blocs de `120` échantillons `pidstat` par nœud. Les moyennes du processus
blockchain sont proches entre VMs : `99,81–99,88 %` CPU et `50 284–50 480 KiB`
de RSS, soit environ `49 MiB`. La mémoire système et le swap restent stables,
avec `wa=0`. Les deltas réseau sur `ens33` sont de `7 740–7 944 B` en réception
et `9 170–9 700 B` en émission par VM, sans erreurs ni pertes. `pidstat -d`
affiche `0,00 kB/s` pour le processus, tandis que `vmstat` montre une activité
bloc système faible (`bi` environ `3,4 KiB/s`, `bo` inférieur à `0,8 KiB/s`).
La taille arrondie `du -sh data/nodeN` reste `3,5M` avant et après ; cette
résolution ne permet pas de conclure à une absence d'octets écrits.

Ce résultat est un profil de trois VMs VMware sous une charge contrôlée. Il ne
constitue ni une capacité maximale, ni une comparaison avec une machine
physique, ni une mesure numérique de la convergence inter-VM. Les blocs
existants, notamment les 182 blocs de la chaîne avant B7, sont conservés. La
note détaillée est `results/raw_data/b7-profile-1p0-20260915-analysis-note.md`.

## 5.10 B8 — Contrats, py-evm et API/IPFS

### Exécution EVM

Chronométrer l’appel autour de `EVMExecutor.execute_transaction()` dans une
copie d’état contrôlée. Pour chaque opération, vérifier l’état avant/après.

Les tests d’écriture doivent utiliser de nouveaux identifiants synthétiques.
Les tests de lecture peuvent relire V1/V2 déjà confirmées en mode view, sans
produire de transaction.

### API Flask/Gunicorn

Si l’API est disponible dans le déploiement final :

- envoyer des requêtes uniquement à l’endpoint node1 ;
- séparer requête d’acceptation et requête de confirmation ;
- tester 1, 2, 4, 8 workers dans des campagnes distinctes ;
- mesurer RPS, latence, erreurs, CPU et mémoire ;
- corréler un identifiant HTTP à `tx_id`.

Le dépôt actuel doit être vérifié avant de déclarer cette partie réalisée : la
présence de Flask/Gunicorn dans les dépendances ne suffit pas à démontrer qu’un
endpoint applicatif est instrumenté et déployé.

### IPFS

Réaliser au besoin une campagne distincte :

```text
ajouter un ciphertext synthétique
calculer son hash
pinner sur le fournisseur local
vérifier la présence sur les trois fournisseurs
récupérer le contenu
comparer les octets et le hash
```

Présenter les résultats sous forme de latence de récupération, taille,
ressources Kubo et délai de réplication. Ne pas intégrer la latence IPFS dans le
TPS blockchain sauf si l’objectif est explicitement un benchmark end-to-end de
l’application médicale.

---

# 6. Plan de campagne recommandé

## 6.1 Campagne minimale

| Campagne | Points | Répétitions | Sortie principale |
|---|---:|---:|---|
| B0 environnement | 3 nœuds | 1 | table de configuration |
| B1 ML-DSA/ML-KEM | opérations cryptographiques | 5 séries | latence et tailles |
| B2 baseline | 4–6 taux d’arrivée | 5 | TPS, latence, succès |
| B3 concurrence | 1–16 clients | 5 | saturation et backlog |
| B4 convergence | mêmes essais B2 | 5 | inclusion et convergence |
| B5 crash/reprise | 2–3 scénarios | 3 à 5 | failover et rattrapage |
| B6 réseau | 4–6 perturbations | 3 à 5 | dégradation |
| B7 trois VMs | mêmes points B2 | 5 | comparaison de ressources entre VMs |
| B8 EVM/API/IPFS | opérations ciblées | 5 | décomposition par couche |

Le nombre exact de répétitions doit être annoncé avant la campagne. Les essais
échoués ne doivent pas être supprimés ; ils doivent être classés comme échec,
timeout, arrêt infrastructurel ou erreur de protocole.

## 6.2 Convention de nommage des résultats

```text
results/raw_data/bench-<scenario>-<node>-<run>-<date>.jsonl
results/raw_data/bench-<scenario>-<node>-<run>-<date>.log
results/processed_data/bench-summary-<date>.csv
results/figures/fig-<numero>-<description>.png
```

Chaque résultat doit contenir un manifeste :

```text
run_id
commit/source hash
configuration hash
date et fuseau horaire
node hardware
scenario
warmup duration
measurement duration
offered rate
number submitted
number committed
number failed
number timed out
```

Les fichiers doivent être synthétiques et ne doivent contenir aucune clé
secrète, plaintext médical ou configuration privée non nécessaire à la
reproduction.

---

# 7. Présentation des résultats dans l’article

## 7.1 Table de configuration

À placer dans la section « Experimental setup » :

| Élément | Valeur à rapporter |
|---|---|
| Nœuds | 3 |
| Topologie | triangle TCP |
| P2P | port 9001 |
| Consensus | PoA round-robin |
| Signatures | ML-DSA-44 |
| KEM | ML-KEM-768 |
| Exécution | py-evm |
| Intervalle de bloc | 5 s |
| Timeout de round | 5 s |
| Ingress | node1 |
| Stockage | blockchain local + IPFS co-localisé |
| Données | synthétiques |

## 7.2 Table de baseline

| Offered rate | Committed TPS | Goodput | Success rate | p50 | p95 | p99 | CPU node1 | RSS node1 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| à compléter | à compléter | à compléter | à compléter | à compléter | à compléter | à compléter | à compléter | à compléter |

Ne remplir cette table qu’avec des données effectivement mesurées. Les valeurs
fonctionnelles de la phase 7 — hauteur, `state_root`, CID, erreurs de revert —
ne doivent pas être réutilisées comme valeurs TPS ou latence.

## 7.3 Graphiques recommandés

### Figure 1 — Architecture et points de mesure

Diagramme indiquant :

```text
client/médecin
     │ t_submit
     ▼
Flask/Gunicorn node1
     │ t_ingress / t_accept
     ▼
mempool node1
     │ diffusion tx
     ▼
PoA / proposer
     │ t_propose
     ▼
bloc signé ML-DSA
     │ t_accept node1/node2/node3
     ▼
état py-evm + state_root convergent
```

IPFS doit apparaître à côté de la chaîne, avec le CID dans la transaction et le
ciphertext hors chaîne.

### Figure 2 — Débit sous charge

- abscisse : taux offert ;
- ordonnée : TPS commis ;
- ligne diagonale éventuelle : débit idéal ;
- marqueur : point de saturation ;
- bande : intervalle de confiance.

### Figure 3 — Latence

CDF ou boxplots pour p50, p95 et p99 de :

- inclusion ;
- commit node1 ;
- commit node2 ;
- commit node3 ;
- convergence.

### Figure 4 — Ressources

Courbes temporelles CPU, RSS, réseau et disque pour les trois nœuds, alignées
sur le début et la fin de T2.

### Figure 5 — Crash/reprise

Timeline hauteur/round par nœud avec annotation :

```text
crash → timeout → nouveau proposer → commit → redémarrage → catch-up
```

### Figure 6 — Dégradation réseau

Heatmap des paramètres `delay/loss` avec couleur représentant la latence p95,
le goodput ou le taux de succès.

### Figure 7 — Overhead PQC

Barres séparées pour ML-DSA et ML-KEM, en microsecondes et en octets. Ne pas
additionner les deux coûts si ML-KEM n’est pas exécuté dans chaque transaction.

### Figure 8 — Physique contre VM

Barres ou boxplots des mêmes métriques sous la même charge, accompagnés d’un
tableau matériel détaillé.

## 7.4 Statistiques

Pour chaque scénario :

- n de répétitions ;
- moyenne et écart-type pour comparaison générale ;
- médiane et IQR pour robustesse aux valeurs extrêmes ;
- p95 et p99 pour les queues de latence ;
- intervalle de confiance à 95 %, idéalement par bootstrap si le nombre de
  répétitions le permet ;
- taux d’échec et nombre absolu d’échecs ;
- charge réellement mesurée, pas seulement la charge demandée.

Les valeurs extrêmes ne doivent pas être supprimées après observation parce
qu’elles sont défavorables. La règle de filtrage, si elle existe, doit être
fixée avant l’analyse et justifiée par un incident documenté.

---

# 8. Limites et interprétation scientifique

## 8.1 Petite taille du réseau

Trois validateurs suffisent pour démontrer le fonctionnement du scénario P2P et
la convergence du PoA étudié, mais ne permettent pas d’extrapoler à un réseau
industriel de dizaines ou centaines de validateurs.

## 8.2 PoA et tolérance aux pannes

Le test de crash d’un validateur mesure la reprise prévue par le round-robin et
le timeout. Il ne prouve pas une tolérance générale aux comportements
byzantins, aux signatures contradictoires ou aux partitions arbitraires.

## 8.3 Configuration à 5 secondes

L’intervalle de bloc et le timeout sont des paramètres expérimentaux. Les
latences observées reflètent leur valeur actuelle. Toute comparaison doit
indiquer ces paramètres.

## 8.4 ML-KEM hors chemin consensus

La mesure ML-KEM-768 démontre le coût de la confidentialité hors chaîne. Elle
ne doit pas être utilisée pour affirmer que la validation PoA coûte ce temps si
la transaction blockchain n’exécute pas réellement ML-KEM.

## 8.5 Profil des trois VMs VMware

Les trois nœuds observés sont des VMs VMware. La campagne peut comparer leurs
ressources visibles, leur variabilité et leurs coûts sous charge, mais elle ne
contient aucune machine physique et ne constitue pas une preuve causale isolée
de l’effet de la virtualisation.

## 8.6 API et blockchain

La latence Flask/Gunicorn, la latence IPFS et la latence blockchain sont trois
latences différentes. Une figure end-to-end peut les additionner, mais les
résultats par couche doivent rester disponibles.

## 8.7 Absence de données médicales réelles

C’est une décision méthodologique et éthique. La charge doit reproduire la
taille et la structure nécessaires sans contenir d’identité, de diagnostic,
d’image, de prescription ou de document réel.

---

# 9. Structure proposée pour l’article scientifique

## 9.1 Méthodologie expérimentale

1. architecture 3 nœuds et scénario client/médecin → node1 ;
2. configuration PoA et paramètres de bloc ;
3. cryptographie ML-DSA-44 / ML-KEM-768 ;
4. py-evm, contrats et état ;
5. IPFS distribué co-localisé ;
6. ressources visibles des trois VMs VMware ;
7. génération de charge et synchronisation des horloges ;
8. définition de committed TPS et de la finalité applicative ;
9. répétitions et analyse statistique.

## 9.2 Résultats

1. validation de l’intégrité et convergence ;
2. coût cryptographique PQC ;
3. baseline débit/latence ;
4. saturation et scalabilité par charge ;
5. finalisation et convergence ;
6. panne et reprise ;
7. perturbations réseau ;
8. comparaison entre les trois VMs ;
9. couche EVM/API/IPFS.

## 9.3 Discussion

- goulot d’étranglement observé ;
- compromis sécurité post-quantique / taille / coût ;
- rôle de l’intervalle de bloc et du timeout ;
- intérêt du stockage hors chaîne ;
- limites de la topologie à trois nœuds ;
- portée du mode contraint expérimental ;
- travail futur : instrumentation Prometheus, plus de nœuds, consensus BFT,
  réseau chiffré, charge clinique synthétique plus large.

## 9.4 Formulation recommandée

> Nous évaluons une blockchain permissionnée post-quantique à trois nœuds dans
> un mode expérimental contraint. Les dossiers médicaux restent hors chaîne et
> seuls leurs pointeurs CID et leurs empreintes sont inscrits dans la
> blockchain. Les performances sont mesurées selon le débit de transactions
> effectivement commises, la latence d’inclusion et de convergence, la
> consommation de ressources, l’overhead cryptographique, la dégradation
> réseau et la reprise après crash d’un validateur. Le terme finalité est
> utilisé au sens de convergence observée des trois copies, et non comme
> l’existence d’un certificat de quorum qui ne fait pas partie de cette
> version du protocole.

---

# 10. Conclusion opérationnelle

Les tests les plus pertinents et réalisables avec l’architecture actuelle sont
ceux qui évaluent le comportement réel des trois nœuds dans le scénario retenu,
sans prétendre à une scalabilité industrielle non mesurée :

```text
reproductibilité
→ overhead ML-DSA/ML-KEM
→ baseline 3 nœuds
→ charge et saturation
→ inclusion/commit/convergence
→ crash/reprise
→ délai/perte réseau
→ comparaison entre les trois VMs
→ EVM, API et IPFS par couche
```

Le résultat final de l’article doit présenter simultanément :

1. la performance utile ;
2. la distribution des latences ;
3. les ressources consommées ;
4. la conservation de l’intégrité ;
5. la reprise après incident ;
6. les limites de l’environnement expérimental.

Un seul chiffre de TPS ne permettrait pas de démontrer ces propriétés. La
valeur scientifique du travail vient de la mise en relation entre blockchain,
PQC, consensus PoA, stockage IPFS distribué, contraintes matérielles et
scénario client/médecin réaliste.

---

# Références et ressources méthodologiques

1. Dinh, T. T. A. et al., **BLOCKBENCH: A Framework for Analyzing Private
   Blockchains**, arXiv:1703.04057, 2017.
   [Version HTML](https://ar5iv.labs.arxiv.org/html/1703.04057)
2. Hyperledger Caliper, **Resource and Transaction Monitors**, documentation
   0.6.0.
   [Documentation](https://hyperledger-caliper.github.io/caliper/0.6.0/concepts/caliper-monitors/)
3. NIST, **FIPS 203: Module-Lattice-Based Key-Encapsulation Mechanism
   Standard**, 13 août 2024.
   [PDF officiel](https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.203.pdf)
4. NIST, **FIPS 204: Module-Lattice-Based Digital Signature Standard**, 13
   août 2024.
   [PDF officiel](https://nvlpubs.nist.gov/nistpubs/fips/nist.fips.204.pdf)
5. Linux man-pages, **tc-netem(8) — Network Emulator**.
   [Manuel](https://man7.org/linux/man-pages/man8/tc-netem.8.html)
6. Gunicorn, **Documentation — StatsD logger and request metrics**.
   [Documentation PDF](https://docs.gunicorn.org/_/downloads/en/20.x/pdf/)
7. py-evm, **State and transaction execution APIs**.
   [Documentation API](https://py-evm.readthedocs.io/en/latest/api/api.abc.html)
8. Hyperledger Foundation, **Benchmarking Hyperledger Fabric 2.5 Performance**,
   2023. Le document rappelle que les résultats dépendent fortement du
   workload, du générateur de charge, du chemin d’API et de la configuration.
   [Article](https://www.lfdecentralizedtrust.org/blog/2023/02/16/benchmarking-hyperledger-fabric-2-5-performance)
9. Dinh, T. T. A. et al., **Gromit: Benchmarking the Performance and
   Scalability of Blockchain Systems**, arXiv:2208.11254.
   [Article](https://arxiv.org/abs/2208.11254)

Ces références servent de base méthodologique. Les valeurs expérimentales
présentées dans l’article final doivent provenir des journaux et fichiers de
résultats produits par cette architecture précise, et non être reprises des
benchmarks d’autres plateformes.
�autres plateformes.
