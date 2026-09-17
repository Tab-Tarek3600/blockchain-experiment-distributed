# PHASE 5 — relais transactionnel et production à la demande

## Objectif expérimental

La version 2 doit améliorer le scénario de la version 1, sans le remplacer
par un envoi artificiel aux trois nœuds.

- **Version 1 :** le dossier médical de test est placé dans IPFS ; le CID est
  inscrit dans une transaction, puis cette transaction est envoyée selon le
  mécanisme de déploiement alors disponible.
- **Version 2 :** le client/médecin contacte un seul nœud d'entrée. Ce nœud
  valide la transaction, la place dans son mempool et la relaie immédiatement
  au réseau. Un validateur autorisé qui possède la transaction produit le
  bloc ; le bloc est ensuite diffusé et validé par les autres nœuds.

Le scénario de référence est donc :

```text
client/médecin
    │ transaction signée (dossier de test contrôlé / CID IPFS)
    ▼
node1 — nœud d'entrée
    │ validation + mempool + diffusion immédiate
    ▼
node2 ─────────────── node3
    │                  │
    └── validateur autorisé à la hauteur courante ──┘
                         │
                         ▼
             production, diffusion et validation du bloc
```

L'envoi direct du client vers node1, node2 et node3 reste uniquement un
contournement temporaire ou une condition de comparaison avec la version 1.
Il n'est pas le chemin applicatif final.

## Implémentation

### Relais dans `Node`

Le transport (`InMemoryP2P` ou `SocketP2P`) transmet les messages à ses
pairs ; il ne décide pas de la politique applicative de relais.

`src/node/node.py` applique le flux suivant :

```text
receive_transaction(tx)       # client ou API locale
    ├── validation et ajout au mempool
    ├── mémorisation du tx_id
    └── broadcast_transaction(tx)

_on_transaction_received(tx)  # pair P2P
    ├── validation et ajout au mempool
    ├── si nouveau tx_id : mémorisation
    └── diffusion vers les pairs
```

Une transaction rejetée (signature invalide, doublon, conflit de nonce ou
mempool plein) n'est pas relayée et ne consomme pas le cache de relais. Le
cache borné de 10 000 identifiants, protégé par verrou, empêche les boucles
sur une topologie en ligne ou en triangle. Le cache est un mécanisme
anti-boucle ; le mempool et la chaîne restent les sources de vérité pour
l'acceptation et l'inclusion.

### Production à la demande

`src/node/main.py` ne propose plus de blocs vides par défaut :

```text
mempool vide       → aucune proposition
mempool non vide   → le proposant de height + 1 peut proposer
```

L'option explicite `--produce-empty-blocks` conserve la cadence périodique
historique pour les benchmarks. Elle ne doit pas être utilisée pour mesurer
le chemin applicatif normal.

Le nœud d'entrée n'a pas besoin d'être le proposant. S'il reçoit la
transaction et n'est pas de tour, il la relaie ; node2 ou node3 peut produire
le bloc lorsque son tour arrive. Après acceptation, les transactions incluses
sont retirées des mempools et le bloc est diffusé par le proposant.

## Tests prévus et critères d'acceptation

Les tests doivent couvrir les deux niveaux suivants :

1. **Relais en mémoire :** une topologie `node1 ↔ node2 ↔ node3` doit faire
   parvenir une transaction reçue par node1 à node3, sans lien direct ; un
   doublon ne doit pas créer une nouvelle entrée ni une tempête de diffusion ;
   une transaction invalide ne doit atteindre aucun mempool.
2. **Réseau TCP :** le même chemin doit être vérifié avec trois transports
   `SocketP2P` et des nœuds complets, sur des ports locaux de test. Le test
   doit ensuite vérifier l'inclusion, la diffusion du bloc, l'égalité des
   hauteurs et la convergence des hash de chaîne et de l'état EVM.

Le scénario de validation final est accepté lorsque les assertions suivantes
sont toutes vraies :

```text
node1 reçoit la transaction
→ node2 puis node3 la reçoivent par relais
→ le validateur autorisé de la hauteur courante produit le bloc
→ le bloc est accepté par les autres nœuds
→ mempools purgés après inclusion
→ hauteurs, hash de bloc terminal et états EVM convergents
```

La présence de tests existants de triangle complet ne suffit pas à elle seule :
un triangle peut masquer l'absence de relais multi-sauts puisque l'émetteur
peut atteindre directement les trois nœuds.

### Validation exécutée

Le 8 septembre 2026, la suite complète a été exécutée dans l'environnement
de développement :

```text
pytest -q
407 passed in 147.81s
```

Elle inclut les tests unitaires du mode à la demande, les tests de transport
TCP et le scénario TCP en ligne `node1 ↔ node2 ↔ node3`. Une compilation
Python complémentaire avec `python -m compileall -q src tests` a également
réussi.

## Liveness et proposant indisponible

La règle de base reste fondée sur la hauteur et un tour de rôle déterministe.
La correction fonctionnelle de l'indisponibilité du proposant est décrite
dans `docs/06_PHASE6_LIVENESS_POA/01_TIMEOUT_ET_CHANGEMENT_DE_ROUND.md` : un timeout
configurable déclenche un changement de round à la même hauteur, le round
est inclus dans le bloc signé, et le validateur suivant peut reprendre la
production sans remplacer le relais applicatif `node1 -> P2P`.

Cette correction ne transforme pas l'envoi applicatif en diffusion directe
aux trois nœuds. La transaction entre toujours par le nœud d'entrée, puis le
relais explicite la rend disponible au validateur courant et à ses pairs.

## Déploiement inter-VM — procédure manuelle

Cibles finales :

| Nœud | Adresse | P2P |
|---|---:|---:|
| node1 | `192.168.168.101` | `9001` |
| node2 | `192.168.168.102` | `9001` |
| node3 | `192.168.168.103` | `9001` |

Avant un déploiement sur une blockchain neuve, supprimer **uniquement** les
fichiers de blocs sur les VMs :

```bash
ssh user@192.168.168.101 'rm -f data/node1/blocks/*'
ssh user@192.168.168.102 'rm -f data/node2/blocks/*'
ssh user@192.168.168.103 'rm -f data/node3/blocks/*'
```

Adapter le chemin distant à l'installation réelle. Ne jamais supprimer
`keys/nodeN` ni les configurations générées. Vérifier ensuite, avec des
commandes SSH simples, que les trois nœuds écoutent sur `9001`, que le
maillage est formé et que les genesis sont identiques. Ne lancer le client de
déploiement qu'après cette convergence.

Pour le déploiement des contrats, la clé de déploiement reste distincte des
clés secrètes des validateurs. Les contrats ne sont pas copiés dans les
répertoires des nœuds : ils sont inscrits par transactions et reconstruits
par rejeu EVM. La procédure détaillée de PHASE 4 et son client externe restent
la référence pour ce cas ; l'envoi direct aux trois cibles y est conservé
comme mécanisme de déploiement/comparaison, pas comme scénario client final.

Aucune donnée médicale réelle ne doit être utilisée. Les mesures IPFS,
blockchain et relais doivent employer des dossiers de test contrôlés et des
CID de test.

## Mesures pour l'article scientifique

Pour comparer V1 et V2, conserver au minimum :

- latence d'émission jusqu'à la réception par node3 ;
- latence d'inclusion dans le bloc ;
- latence de convergence des trois hauteurs et états ;
- nombre de messages et connexions utilisés ;
- taux de transactions incluses et transactions rejetées ;
- comportement avec nœud d'entrée non-proposant ;
- comportement lorsque le proposant attendu est indisponible ;
- comparaison avec l'envoi direct aux trois cibles, explicitement identifié
  comme baseline et non comme architecture finale.

Les résultats bruts doivent être séparés des données médicales et déposés
sous `results/raw_data/` ; aucun dossier réel ne doit entrer dans le dépôt ou
sur les VMs.
