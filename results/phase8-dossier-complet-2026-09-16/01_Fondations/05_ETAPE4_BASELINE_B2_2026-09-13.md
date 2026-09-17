# Phase 8 — Étape 4 : baseline blockchain B2 à trois nœuds

**Date :** 13 septembre 2026  
**Statut :** pilote inter-VM r02 exécuté ; résultat conservé dans
`b2-pilot-r02-2026-09-13-execution.md` ; répétitions B2 longues non lancées  
**Périmètre :** débit de transactions synthétiques et convergence de la chaîne,
sans perturbation réseau, sur les trois VMs

---

## 1. Objectif

Mesurer le comportement de référence de la blockchain dans le scénario retenu :

```text
client/médecin synthétique → node1 → diffusion P2P → node2/node3
```

Le client de benchmark envoie uniquement vers node1. Il ne contacte jamais
node2 ou node3 directement. Les dossiers médicaux réels sont exclus ; le
payload est déterministe, synthétique et contrôlé.

Cette étape mesure la blockchain et le chemin ML-DSA des transactions/blocs.
Elle ne mesure pas ML-KEM/AES-GCM et n'intègre pas IPFS dans le TPS.

## 2. Outils préparés

```text
scripts/experiments/benchmark_b2_baseline.py
scripts/experiments/analyze_b2_baseline.py
```

Le générateur :

- pré-signe les transactions avant la fenêtre T2 ;
- ouvre une seule connexion TCP locale vers node1:9001 ;
- envoie des transactions à un taux contrôlé ;
- n'arrête ni ne démarre les nœuds ;
- ne modifie aucune configuration ;
- ne copie ni n'affiche de clé secrète ;
- observe optionnellement la persistance locale des transactions sur node1 ;
- écrit un manifeste JSON sans secret.

Le post-traitement :

- charge le manifeste node1 ;
- lit les répertoires de blocs copiés depuis les trois VMs ;
- compte les transactions du benchmark présentes sur chaque nœud ;
- détecte les doublons et transactions manquantes ;
- calcule le débit effectivement présent sur les trois copies ;
- compare, hauteur par hauteur, `block_hash` et `state_root`.

Le code de `src/node/node.py` journalise également un événement public
`BENCHMARK_COMMIT` avec `commit_wall_ns`, hauteur, hash de bloc, `state_root` et
identifiants de transactions. Ces timestamps sont locaux à chaque VM et ne
doivent pas être soustraits entre nœuds non synchronisés.

## 3. Conditions B2

- 3 nœuds actifs : node1 `192.168.168.101`, node2 `192.168.168.102`, node3
  `192.168.168.103` ;
- port P2P : `9001` ;
- consensus : PoA round-robin ;
- entrée : node1 uniquement ;
- diffusion : P2P normale ;
- aucune règle `tc netem` ;
- paramètres de bloc et clés de validation inchangés ;
- payload synthétique contrôlé ;
- IPFS hors de la première mesure ;
- ML-KEM/AES-GCM hors de la première mesure ;
- aucun plaintext médical réel.

Les trois nœuds doivent utiliser le même code, le même genesis et la même
configuration réseau. Les trois VMs restent décrites comme des VMs ; aucune
comparaison physique/VM n'est effectuée.

## 4. Préparation sûre sur les VMs

Ces commandes sont volontairement simples et indépendantes. Elles ne
suppriment ni les clés secrètes ni les configurations.

### 4.1 Mettre à jour le code

Depuis le dépôt de référence, copier uniquement les fichiers nécessaires avec
`scp` ou utiliser la procédure manuelle de synchronisation déjà documentée,
en excluant toujours :

```text
keys/
data/
config/nodes/
.venv/
```

Fichiers nouveaux/modifiés pour B2 :

```text
src/node/node.py
scripts/experiments/benchmark_b2_baseline.py
scripts/experiments/analyze_b2_baseline.py
```

Après copie, vérifier sur chaque VM :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
PYTHONPATH=. python3 -m py_compile src/node/node.py \
    scripts/experiments/benchmark_b2_baseline.py \
    scripts/experiments/analyze_b2_baseline.py
```

Le contrôle local du 13 septembre 2026 a confirmé la compilation syntaxique de
ces trois fichiers. L'analyseur a également été exercé avec un manifeste vide
et avec un fichier de bloc persistant corrompu : il signale l'erreur dans le
résumé au lieu d'arrêter toute l'analyse. Le générateur n'a pas été exécuté
sur le sandbox, qui ne fournit pas le binding `oqs` ; son exécution doit donc
être faite sur node1 avec l'environnement liboqs de la campagne.

### 4.2 Vérifier les préconditions, sans modification

Sur chaque VM :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
python3 --version
python3 -c 'import oqs; print(oqs.oqs_version())'
ss -ltnp | grep ':9001' || true
find data/nodeN/blocks -maxdepth 1 -type f -name '*.json' | sort | tail -3
```

Remplacer `N` par `1`, `2` ou `3`.

Pour une nouvelle répétition indépendante, arrêter d'abord les trois nœuds,
puis supprimer **uniquement les blocs de données du run précédent** :

```bash
rm -f data/node1/blocks/*.json
rm -f data/node2/blocks/*.json
rm -f data/node3/blocks/*.json
```

Cette opération ne touche ni `keys/`, ni `config/`, ni les paramètres générés.
Le genesis sera recréé à partir de la configuration conservée. Ne pas utiliser
`make clean-data` dans la campagne.

## 5. Démarrage manuel des trois nœuds

Dans un terminal distinct sur chaque VM, conserver le journal du nœud :

### node1

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}
make node1 2>&1 | tee /tmp/phase8-b2-node1.log
```

### node2

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}
make node2 2>&1 | tee /tmp/phase8-b2-node2.log
```

### node3

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}
make node3 2>&1 | tee /tmp/phase8-b2-node3.log
```

Avant la charge, vérifier dans les journaux :

```text
genesis hash identique sur les trois nœuds
connected peers : les deux autres nœuds
chain height identique au départ
```

## 6. Pilote B2 recommandé

Le premier essai est volontairement court. Il sert à valider le générateur et
la conservation de la chaîne avant la matrice complète.

Sur **node1 uniquement**, dans un quatrième terminal :

```bash
cd ~/blockchain-experiment-distributed
source .venv/bin/activate
export OQS_INSTALL_PATH=$HOME/_oqs
export LD_LIBRARY_PATH=$OQS_INSTALL_PATH/lib:${LD_LIBRARY_PATH:-}

PYTHONPATH=. python3 scripts/experiments/benchmark_b2_baseline.py \
  --config config/nodes/node1/node.yaml \
  --rate 0.2 \
  --duration 30 \
  --payload-size 0 \
  --data-dir "$PWD/data/node1" \
  --run-id b2-pilot-r02-2026-09-13 \
  --manifest-output results/raw_data/b2-pilot-r02-2026-09-13-node1-manifest.json
```

Le pilote soumet environ six transactions synthétiques. Le résultat attendu
n'est pas une valeur TPS prédéterminée ; il faut conserver la sortie réelle et
les éventuelles erreurs.

Pendant le pilote, vérifier que :

- le compteur `submitted` est positif ;
- node1 relaie la transaction ;
- un validateur produit les blocs ;
- la hauteur progresse sur les trois nœuds ;
- aucun nœud ne diverge ;
- le manifeste indique les transactions observées sur node1, si le drain est
  terminé dans le délai.

## 7. Arrêt et collecte simple

Après la fin du drain, arrêter proprement les trois processus avec `Ctrl+C`.
Ne pas utiliser `pkill -f`.

Depuis le dépôt local de référence, créer les répertoires de collecte :

```bash
mkdir -p /tmp/b2-pilot-r02/node{1,2,3}/blocks
```

Copier uniquement les blocs, les journaux de mesure et le manifeste nécessaires avec `scp` :

```bash
scp user@192.168.168.101:~/blockchain-experiment-distributed/results/raw_data/b2-pilot-r02-2026-09-13-node1-manifest.json \
  results/raw_data/
scp user@192.168.168.101:/tmp/phase8-b2-node1.log \
  /tmp/b2-pilot-r02/node1.log
scp user@192.168.168.102:/tmp/phase8-b2-node2.log \
  /tmp/b2-pilot-r02/node2.log
scp user@192.168.168.103:/tmp/phase8-b2-node3.log \
  /tmp/b2-pilot-r02/node3.log
scp user@192.168.168.101:~/blockchain-experiment-distributed/data/node1/blocks/*.json \
  /tmp/b2-pilot-r02/node1/blocks/
scp user@192.168.168.102:~/blockchain-experiment-distributed/data/node2/blocks/*.json \
  /tmp/b2-pilot-r02/node2/blocks/
scp user@192.168.168.103:~/blockchain-experiment-distributed/data/node3/blocks/*.json \
  /tmp/b2-pilot-r02/node3/blocks/
```

Adapter `user` et le chemin distant à l'installation réelle. Ne jamais copier
`keys/`, les configurations générées ou les données hors périmètre. Les
commandes ci-dessus placent directement les JSON dans les sous-répertoires
`blocks/` attendus par l'analyseur ; aucune commande `mv` n'est nécessaire.

## 8. Analyse du pilote

Depuis la racine du dépôt de référence :

```bash
PYTHONPATH=. python3 scripts/experiments/analyze_b2_baseline.py \
  --manifest results/raw_data/b2-pilot-r02-2026-09-13-node1-manifest.json \
  --node1-blocks /tmp/b2-pilot-r02/node1/blocks \
  --node2-blocks /tmp/b2-pilot-r02/node2/blocks \
  --node3-blocks /tmp/b2-pilot-r02/node3/blocks \
  --node1-log /tmp/b2-pilot-r02/node1.log \
  --node2-log /tmp/b2-pilot-r02/node2.log \
  --node3-log /tmp/b2-pilot-r02/node3.log \
  --output results/raw_data/b2-pilot-r02-2026-09-13-summary.json
```

Le résumé contient notamment :

```text
submitted
acceptance directe et borne inférieure d'acceptation node1
included_node1/node2/node3
included_on_all_three
success_failure et backlog
success_rate_all_three
committed_tps_all_three_over_submission_window
latence d'inclusion de bout en bout node1 via `BENCHMARK_COMMIT` et `t_submit_wall_ns`
latence locale acceptation→commit pour chaque nœud via ses propres événements `BENCHMARK_ACCEPT`/`BENCHMARK_COMMIT`, sans synchronisation inter-VM
latence de convergence inter-nœuds seulement avec journaux des trois nœuds et horloges explicitement synchronisées ; sinon marquée non mesurée
transactions_per_block
final_chain : hauteur, block_hash et state_root finaux par nœud
common_prefix_height
same block_hash et state_root
```

Le débit B2 retenu est le nombre de transactions du benchmark présentes sur
les trois copies, divisé par la durée de soumission T2. Le taux d'acceptation
au mempool n'est pas inventé si aucun accusé d'ingress n'est disponible.

## 9. Matrice après validation du pilote

Une fois le pilote validé, exécuter séparément les charges suivantes :

```text
0,1 tx/s
0,2 tx/s
0,5 tx/s
1 tx/s
2 tx/s
5 tx/s si le mempool reste maîtrisé
```

Pour la campagne complète :

- 30–60 s de warm-up séparé si nécessaire ;
- 60–120 s de mesure ;
- drain jusqu'à inclusion ou timeout explicite ;
- 5 répétitions par taux ;
- nouvelle chaîne de données pour chaque répétition indépendante ;
- même payload et mêmes paramètres hors taux d'arrivée ;
- conservation de tous les manifestes, y compris les échecs.

Le pilote B2 n'est pas encore un résultat scientifique final. Il valide le
chemin de mesure et permet de détecter un problème de transport, de nonce, de
mempool ou de convergence avant la campagne longue.

## 10. Critères de validation de l'étape 4

L'étape sera validée lorsque, pour chaque run retenu :

1. le manifeste JSON est syntaxiquement valide ;
2. les transactions sont synthétiques et sans secret ;
3. l'entrée est exclusivement node1 ;
4. les trois répertoires de blocs sont lisibles ;
5. les transactions de benchmark sont comptées sans doublon ;
6. les trois nœuds convergent au moins jusqu'à la hauteur minimale observée ;
7. les `block_hash` et `state_root` concordent sur le préfixe commun ;
8. le taux offert, le débit commis et les échecs sont distingués ;
9. aucune valeur ML-KEM/AES-GCM n'est incluse dans le TPS ;
11. les journaux et manifestes bruts sont archivés dans `results/raw_data/`.

**Statut actuel :** le pilote inter-VM r04 du 14 septembre 2026 est validé
pour le chemin de mesure, l'acceptation et la convergence. Il montre 6
transactions soumises, acceptées directement par node1, incluses sur chacun
des trois nœuds, sans rejet ni doublon. Le taux de succès est `1.0` et le TPS
commis sur la fenêtre de soumission est `0.19999870699502603 tx/s`.

La latence d'inclusion node1 est mesurée à partir des événements
`BENCHMARK_COMMIT` : minimum `60.005428 ms`, médiane `169.759788 ms`, p95
`283.361167 ms`, maximum `299.287065 ms`. L'observation locale par scan des
blocs est également non vide pour les 6 transactions. La convergence est
établie jusqu'à la hauteur 6 avec `block_hash` et `state_root` identiques sur
les trois nœuds, mais sa latence numérique inter-VM reste non mesurée, car les
horloges ne sont pas déclarées synchronisées.

La hauteur finale commune est 6, avec `block_hash`
`d2674288077ab8fd03909c81c69b46181a295baeb4747f925aca2cb62892ee4b` et
`state_root`
`56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421`.
Le résumé est archivé dans
`results/raw_data/b2-pilot-r04-2026-09-14-summary.json`. La campagne B2
officielle peut commencer sans ajouter `--clocks-synchronised`; la première
campagne doit conserver la latence de convergence comme non mesurée et ne doit
inclure ni IPFS ni perturbation réseau.
