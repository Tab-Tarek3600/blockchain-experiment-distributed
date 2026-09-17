# Phase 8 — Étape 3 : benchmark ML-KEM-768 + AES-256-GCM

**Date de préparation et d’exécution :** 13 septembre 2026  
**Statut :** VALIDÉE sur node1, node2 et node3 avec réserve de variabilité CPU  
**Périmètre :** confidentialité hors chaîne avant stockage IPFS  
**Algorithmes :** ML-KEM-768 via liboqs `0.16.0` et AES-256-GCM via
PyCryptodome `3.23.0`

---

## 1. Objectif

Mesurer séparément, sur chacune des trois VMs :

1. la génération de paire de clés ML-KEM-768 ;
2. l’encapsulation d’un secret partagé ;
3. la décapsulation avec la clé secrète correspondante ;
4. la dérivation de la clé AES-256 par SHA-256, comme dans la phase 7 ;
5. le chiffrement AES-256-GCM d’un payload synthétique de 1 KiB ;
6. le déchiffrement et la vérification AES-256-GCM ;
7. les tailles des clés, du ciphertext KEM, du secret partagé et de l’enveloppe ;
8. le rejet avec une mauvaise clé et avec un ciphertext modifié.

Cette étape mesure la **confidentialité hors chaîne**. Elle ne mesure ni IPFS,
ni le consensus, ni la propagation P2P, ni le débit blockchain. Le coût ML-KEM
et AES-GCM ne sera donc pas ajouté artificiellement au TPS blockchain.

---

## 2. Architecture corrigée

Les trois nœuds sont des VMs VMware :

| Nœud | Adresse | Rôle | Environnement |
|---|---|---|---|
| node1 | `192.168.168.101` | point d’entrée logique et validateur | VM VMware |
| node2 | `192.168.168.102` | validateur | VM VMware |
| node3 | `192.168.168.103` | validateur | VM VMware |

Le scénario de confidentialité est local et contrôlé. Il ne contacte ni la
blockchain ni IPFS et ne lit aucune donnée médicale réelle.

---

## 3. Protocole arrêté avant mesure

### 3.1 Conditions

- exécuter le benchmark séparément sur node1, node2 et node3 ;
- si possible, arrêter temporairement le processus blockchain avec `Ctrl-C` afin
  d’éviter une interférence CPU ;
- ne supprimer ni clés de validateurs, ni configuration, ni données blockchain ;
- ne pas exécuter `make clean-data` ;
- ne transmettre aucun fichier du répertoire `keys/` ;
- utiliser uniquement le payload synthétique généré par le programme ;
- conserver les valeurs de référence en mémoire uniquement.

Le programme génère une paire ML-KEM temporaire en mémoire. Il ne réutilise pas
les clés secrètes des validateurs et n’écrit aucune clé sur disque.

### 3.2 Mesures

Pour chaque opération :

- 100 opérations de warm-up ;
- 1 000 opérations mesurées par répétition ;
- 5 répétitions ;
- chronométrage avec `time.perf_counter_ns()` ;
- minimum, moyenne, médiane/p50, p95, p99, p25, p75, IQR et throughput depuis
  la médiane.

Les opérations ML-KEM utilisent le wrapper `src.crypto.ml_kem.MLKEM`. La création
du contexte `liboqs.KeyEncapsulation` réalisée par ce wrapper est incluse dans
les durées de `keygen`, `encapsulate` et `decapsulate`.

Pour AES-GCM, le chiffrement inclut la génération du nonce aléatoire de 12
octets, comme dans le chemin de la phase 7. Le déchiffrement utilise un vecteur
de contrôle valide et vérifie le plaintext récupéré.

### 3.3 Opérations mesurées

```text
keygen
encapsulate
decapsulate
derive_aes256_key_sha256
aes_gcm_encrypt_1KiB
aes_gcm_decrypt_1KiB
```

Les contrôles négatifs suivants sont réalisés hors fenêtre de mesure :

```text
mauvaise clé AES-GCM       → rejet d'authentification
ciphertext modifié         → rejet d'authentification
```

---

## 4. Commandes à exécuter sur les VMs réelles

Exécuter les commandes une VM à la fois. Remplacer `node1` par `node2`, puis
`node3`, dans `--node-label` et dans le nom du fichier de sortie.

### 4.1 Contrôle des dépendances sur node1

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH="$HOME/_oqs"
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"

make check-oqs

python3 -c 'import oqs; print("liboqs", oqs.oqs_version()); print("ML-KEM-768", "ML-KEM-768" in oqs.get_enabled_kem_mechanisms())'
python3 -c 'from Crypto.Cipher import AES; print("AES-GCM: OK")'
```

Le contrôle `make check-oqs` vérifie principalement ML-DSA-44 ; la deuxième
commande doit explicitement afficher `ML-KEM-768 True`.

### 4.2 Exécution sur node1

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH="$HOME/_oqs"
export LD_LIBRARY_PATH="$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}"

python3 scripts/experiments/benchmark_mlkem768_aesgcm.py \
  --node-label node1 \
  --iterations 1000 \
  --warmup 100 \
  --repetitions 5 \
  --json-output results/raw_data/mlkem768-aesgcm-node1-2026-09-13.json
```

### 4.3 Exécution sur node2 et node3

Sur node2 :

```bash
python3 scripts/experiments/benchmark_mlkem768_aesgcm.py \
  --node-label node2 \
  --iterations 1000 \
  --warmup 100 \
  --repetitions 5 \
  --json-output results/raw_data/mlkem768-aesgcm-node2-2026-09-13.json
```

Sur node3 :

```bash
python3 scripts/experiments/benchmark_mlkem768_aesgcm.py \
  --node-label node3 \
  --iterations 1000 \
  --warmup 100 \
  --repetitions 5 \
  --json-output results/raw_data/mlkem768-aesgcm-node3-2026-09-13.json
```

Si le dépôt n’est pas dans `~/blockchain-experiment-distributed`, exécuter les
commandes depuis le chemin réel du dépôt.

### 4.4 Contrôle et transmission

Après chaque exécution :

```bash
cat results/raw_data/mlkem768-aesgcm-node1-2026-09-13.json
```

Remplacer `node1` par `node2` et `node3`. Transmettre les trois sorties JSON dans
la conversation. Elles ne contiennent aucune clé secrète ni plaintext médical.

---

## 5. Valeurs de taille attendues avant mesure

Les valeurs FIPS 203 et les paramètres AES-GCM servent de référence. Les
valeurs réellement produites seront prises dans les fichiers JSON.

| Élément | Taille attendue |
|---|---:|
| clé publique ML-KEM-768 | 1 184 octets |
| clé secrète ML-KEM-768 | 2 400 octets |
| ciphertext ML-KEM-768 | 1 088 octets |
| secret partagé ML-KEM | 32 octets |
| clé AES-256 dérivée | 32 octets |
| nonce AES-GCM | 12 octets |
| tag AES-GCM | 16 octets |
| ciphertext AES-GCM pour 1 KiB | 1 024 octets |

Pour le format d’enveloppe de la phase 7, chaque champ est précédé d’une
longueur de 4 octets. Avec une version `v1` et un plaintext de 1 KiB, la taille
sérialisée attendue sera calculée et rapportée par le programme.

---

## 6. Résultats réels à intégrer

Cette section sera complétée après réception des trois fichiers JSON.

### 6.1 Versions et conditions

| Nœud | Hostname | Collecte UTC | Python | liboqs | Warm-up | Itérations × répétitions | Contrôles |
|---|---|---|---|---|---:|---:|---|
| node1 | `node1` | `19:08:15` | 3.12.13 | 0.16.0 | 100 | 1000 × 5 | VALIDÉS |
| node2 | `node2` | `19:08:46` | 3.12.13 | 0.16.0 | 100 | 1000 × 5 | VALIDÉS |
| node3 | `node3` | `19:09:39` | 3.12.13 | 0.16.0 | 100 | 1000 × 5 | VALIDÉS |

Les trois exécutions ont été réalisées le 13 septembre 2026 avec deux CPU
visibles par VM et le même protocole. Les sorties JSON brutes sont conservées
dans :

```text
results/raw_data/mlkem768-aesgcm-node1-2026-09-13.json
results/raw_data/mlkem768-aesgcm-node2-2026-09-13.json
results/raw_data/mlkem768-aesgcm-node3-2026-09-13.json
```

### 6.2 Tailles mesurées

| Nœud | Clé publique | Clé secrète comptée | Ciphertext KEM | Secret partagé | Envelope 1 KiB |
|---|---:|---:|---:|---:|---:|
| node1 | 1 184 o | 2 400 o | 1 088 o | 32 o | 2 162 o |
| node2 | 1 184 o | 2 400 o | 1 088 o | 32 o | 2 162 o |
| node3 | 1 184 o | 2 400 o | 1 088 o | 32 o | 2 162 o |

La taille de la clé AES-256 dérivée est de 32 octets. Le nonce GCM est de
12 octets, le tag d’authentification de 16 octets et le ciphertext AES conserve
les 1 024 octets du plaintext.

### 6.3 Latences et throughput

Les valeurs seront reportées en microsecondes et opérations par seconde. Ce
throughput est local à la couche de confidentialité hors chaîne.

| Nœud | Opération | p50 (µs) | p95 (µs) | p99 (µs) | IQR (µs) | ops/s depuis p50 |
|---|---|---:|---:|---:|---:|---:|
| node1 | keygen | 16,677 | 20,147 | 28,975 | 0,776 | 59 965 |
| node1 | encapsulate | 16,666 | 20,334 | 26,881 | 0,535 | 60 002 |
| node1 | decapsulate | 15,307 | 18,501 | 25,559 | 0,568 | 65 330 |
| node1 | derive AES-256 | 0,324 | 0,351 | 0,404 | 0,011 | 3 086 420 |
| node1 | AES-GCM encrypt 1 KiB | 24,878 | 31,892 | 52,726 | 1,768 | 40 196 |
| node1 | AES-GCM decrypt 1 KiB | 31,329 | 41,699 | 94,515 | 2,232 | 31 919 |
| node2 | keygen | 33,469 | 45,936 | 61,801 | 3,184 | 29 878 |
| node2 | encapsulate | 16,695 | 19,863 | 27,067 | 0,415 | 59 898 |
| node2 | decapsulate | 15,470 | 20,142 | 32,587 | 0,752 | 64 643 |
| node2 | derive AES-256 | 0,321 | 0,348 | 0,442 | 0,020 | 3 115 265 |
| node2 | AES-GCM encrypt 1 KiB | 27,471 | 50,908 | 69,685 | 13,002 | 36 403 |
| node2 | AES-GCM decrypt 1 KiB | 31,854 | 47,565 | 59,943 | 3,204 | 31 393 |
| node3 | keygen | 19,003 | 37,579 | 52,046 | 16,679 | 52 625 |
| node3 | encapsulate | 36,056 | 48,464 | 81,453 | 5,277 | 27 735 |
| node3 | decapsulate | 16,283 | 34,688 | 45,832 | 4,885 | 61 414 |
| node3 | derive AES-256 | 0,359 | 0,390 | 0,426 | 0,026 | 2 785 515 |
| node3 | AES-GCM encrypt 1 KiB | 24,333 | 30,647 | 42,301 | 1,476 | 41 096 |
| node3 | AES-GCM decrypt 1 KiB | 31,362 | 62,651 | 80,827 | 8,614 | 31 886 |

### 6.4 Contrôles de confidentialité

| Contrôle | node1 | node2 | node3 |
|---|---|---|---|
| Secret partagé encapsulation/décapsulation identique | VALIDÉ | VALIDÉ | VALIDÉ |
| Round-trip AES-GCM valide | VALIDÉ | VALIDÉ | VALIDÉ |
| Mauvaise clé rejetée | VALIDÉ | VALIDÉ | VALIDÉ |
| Ciphertext modifié rejeté | VALIDÉ | VALIDÉ | VALIDÉ |

Les quatre contrôles de sécurité sont positifs sur les trois VMs.

---

### 6.5 Observations expérimentales

- Les tailles produites sont identiques sur les trois VMs et conformes aux
  valeurs attendues pour ML-KEM-768 et AES-256-GCM.
- Les contrôles d’accord du secret partagé, de round-trip AES-GCM, de rejet de
  mauvaise clé et de rejet de ciphertext modifié sont tous validés sur les
  trois nœuds.
- Les médianes ML-KEM sont généralement de l’ordre de 15–17 µs pour la
  décapsulation et l’encapsulation sur node1/node2. Node3 présente une
  médiane d’encapsulation plus élevée de 36,056 µs.
- La génération de clés présente une variabilité inter-VM : 16,677 µs sur
  node1, 33,469 µs sur node2 et 19,003 µs sur node3 en médiane. Node2 atteint
  un p99 de 61,801 µs et node3 un IQR de 16,679 µs. Ces différences seront
  décrites comme une variabilité entre VMs, sans attribution causale au
  matériel ou à l’hyperviseur.
- La dérivation SHA-256 de la clé AES-256 est très faible devant ML-KEM et
  AES-GCM : médianes comprises entre 0,321 et 0,359 µs.
- Le chiffrement AES-GCM de 1 KiB présente une médiane de 24,333–27,471 µs et
  le déchiffrement une médiane de 31,329–31,854 µs. Le déchiffrement est donc
  légèrement plus coûteux dans cette mesure.
- L’enveloppe sérialisée de style phase 7 mesure 2 162 octets pour un plaintext
  de 1 024 octets. Cette taille inclut le ciphertext KEM de 1 088 octets, le
  nonce, le tag, la version et les préfixes de longueur.
- Le chiffrement AES-GCM inclut la génération du nonce aléatoire dans sa durée.
  Les valeurs `ops/s` restent le throughput de confidentialité local et ne
  constituent pas un TPS blockchain.

## 7. Interprétation prévue pour l’article

- ML-KEM-768 sera présenté comme une primitive d’établissement de secret, et
  non comme un chiffrement complet ;
- AES-256-GCM protège le payload avec authentification intégrée ;
- le ciphertext KEM, le nonce, le tag et le ciphertext applicatif constituent
  l’enveloppe hors chaîne ;
- les versions de documents restent distinctes : un nouveau document chiffré
  produit une nouvelle enveloppe et un nouveau CID IPFS ;
- la blockchain conserve uniquement les références d’intégrité et les CID selon
  le modèle du projet ;
- le coût ML-KEM/AES-GCM ne sera pas additionné aux TPS blockchain si ces
  opérations ne sont pas exécutées dans le chemin de chaque transaction ;
- aucune donnée médicale réelle ne sera utilisée.

**État de l’étape 3 :** VALIDÉE avec réserve méthodologique sur la variabilité
observée entre VMs pour `keygen`, `encapsulate` et certaines séries AES-GCM.
Les mesures réelles de node1, node2 et node3 sont intégrées et les fichiers
JSON bruts sont conservés dans `results/raw_data/`.
