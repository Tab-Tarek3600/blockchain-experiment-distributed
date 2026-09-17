# PHASE 6 — Liveness PoA : timeout et changement de round

## Objectif

La production reste **à la demande** :

```text
mempool vide          -> aucun bloc
transaction en attente -> production si le proposant courant est disponible
```

L'indisponibilité du proposant ne bloque plus la hauteur. Après expiration
du timeout, les nœuds actifs passent ensemble au round suivant et le
validateur désigné peut produire le bloc à la même hauteur.

Le scénario applicatif reste inchangé :

```text
client/médecin -> node1 (entrée)
               -> relais P2P explicite
               -> proposant PoA du round courant
               -> diffusion, validation et convergence
```

Le relais n'est pas remplacé par un gossip automatique dans `SocketP2P`.

## Règle déterministe

Pour une hauteur `h` et un round `r`, le proposant attendu est :

```text
authorized_validators[(h + r) % len(authorized_validators)]
```

Le round initial est `0`. Un timeout incrémente le round de **la hauteur
courante**, sans créer de hauteur intermédiaire. Ainsi, avec trois
validateurs, si le proposant de `h=1, r=0` est arrêté :

```text
(h=1, r=0) -> validator[1]
timeout     -> (h=1, r=1) -> validator[2]
timeout     -> (h=1, r=2) -> validator[0]
```

Le validateur qui produit doit toujours être à la fois :

1. autorisé par `authorized_validators` ;
2. le proposant exact de la paire `(height, round)` ;
3. signataire ML-DSA du bloc.

## Authentification et anti-concurrence

`Block` possède désormais le champ entier non négatif `round`. Ce champ est
inclus dans `to_bytes()`, donc dans `signing_hash` et `block_hash`, puis est
transporté par `to_dict()/from_dict()`. Une modification du round invalide
la signature.

L'acceptation suit toujours un point unique (`Node._accept_block`) :

```text
structure + signatures
        -> proposant de (height, round)
        -> vérification state_root par rejeu EVM
        -> Blockchain.add_block()
        -> nettoyage du mempool + diffusion
```

Un bloc d'un validateur hors tour est rejeté. Un bloc d'une ancienne round
est rejeté par un nœud qui a déjà avancé. Une hauteur déjà acceptée reste
obsolète et n'est pas ajoutée une seconde fois : il n'existe pas de second
appel concurrent à `Blockchain.add_block()` pour la même hauteur.

Le round de proposition est un état local de liveness ; il est remis à zéro
pour la hauteur suivante. Le round effectivement utilisé est, lui, persistant
et vérifiable dans le bloc signé. Au redémarrage, un nœud reprend la hauteur
persistée et peut réarmer le timeout si des transactions sont présentes.

## Timeout configurable

La configuration partagée contient :

```yaml
block_interval_seconds: 5.0
round_timeout_seconds: 5.0
```

`round_timeout_seconds` doit être identique sur les trois nœuds du même
réseau et strictement positif. Dans un ancien YAML qui ne possède pas encore
ce champ, `NodeConfig` utilise `block_interval_seconds` comme valeur de
compatibilité. Le générateur `scripts/setup/make_configs.py` expose aussi :

```text
--round-timeout SECONDS
```

Le timer n'est armé que lorsqu'une transaction est dans le mempool. Il ne
produit donc pas de bloc vide dans le mode normal. La boucle de
`src.node.main` appelle `Node.advance_round_if_timed_out()` à chaque tour,
y compris sur un nœud configuré `--no-propose`, afin que celui-ci puisse
continuer à accepter le round de remplacement et relayer son résultat.

## Tests ajoutés

Le test unitaire `test_un_proposeur_indisponible_est_remplace_apres_timeout`
construit deux nœuds actifs sans le validateur du round 0, arme leur timeout
avec une horloge contrôlée, puis vérifie :

- passage de `round=0` à `round=1` à hauteur 1 ;
- production par le validateur suivant ;
- présence de `round=1` dans le bloc signé ;
- acceptation par l'autre nœud, même hauteur et même hash de tip ;
- suppression de la transaction des deux mempools.

Le test `test_aucun_timeout_n_est_arme_avec_un_mempool_vide` conserve
explicitement l'invariant de production à la demande.

Le test d'intégration TCP `test_tcp_failover_when_initial_proposer_is_offline`
arrête le proposant attendu du round 0, injecte la transaction par node1,
la relaie vers node3 par la connexion TCP restante, puis exécute la boucle
réelle de `src.node.main` sur les validateurs disponibles. Il vérifie qu'un
bloc `round=1` est produit à la même hauteur et accepté par node1 et node3,
avec le même hash de tip.

La suite complète doit être exécutée avant déploiement :

```bash
pytest -q
```

## Déploiement propre des trois VMs

Avant un nouveau déploiement de chaîne, supprimer uniquement les blocs
persistés :

```bash
ssh <user>@192.168.168.101 'rm -f data/node1/blocks/*'
ssh <user>@192.168.168.102 'rm -f data/node2/blocks/*'
ssh <user>@192.168.168.103 'rm -f data/node3/blocks/*'
```

Ne jamais supprimer `keys/node1`, `keys/node2`, `keys/node3` ni les
configurations générées. Démarrer les trois nœuds sur le port P2P `9001`,
attendre leur écoute et leur convergence, puis seulement lancer le client de
déploiement. Les transactions de déploiement gardent la clé de déploiement,
distincte des clés secrètes des validateurs, et sont envoyées au nœud d'entrée
selon le scénario applicatif documenté.
