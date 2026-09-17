# B2 pilote r02 — résultat d'exécution

**Date du run :** 13 septembre 2026  
**Source :** sortie console fournie après exécution sur les trois VMs  
**Statut :** pilote réussi pour l'inclusion et la convergence ; les empreintes
finales ont maintenant été fournies dans le résumé JSON

## Conditions observées

- Entrée du benchmark : node1 uniquement (`192.168.168.101:9001`).
- Diffusion : chemin P2P normal vers node2 et node3.
- Payload : transactions synthétiques, `payload-size=0`.
- Taux demandé : `0.2 tx/s`.
- Durée T2 observée : `30.000115 s`.
- Transactions pré-signées et soumises : `6`.
- Aucune perturbation réseau ni appel IPFS dans ce pilote.

## Résultats fournis par l'analyseur

| Indicateur | Valeur |
|---|---:|
| Transactions soumises | 6 |
| Transactions présentes sur les trois chaînes | 6 |
| Taux de présence sur les trois chaînes | 1.0 |
| TPS commis sur la fenêtre de soumission | 0.1999992357562537 tx/s |
| Convergence au tip minimal | `true` |
| Transactions observées localement par le générateur node1 | 0 |

Le débit commis est donc cohérent avec `6 / 30.000115`, sans utiliser ni
extrapoler les microbenchmarks ML-KEM/AES-GCM.

Les fichiers copiés portent les hauteurs `0` à `6` sur chacun des trois nœuds,
d'après la sortie `scp`; le tip final observé est donc la hauteur `6`, sous
réserve de l'absence d'autres fichiers non affichés dans la commande.

## Interprétation par catégorie

- **Soumises :** 6, directement mesurées dans le manifeste.
- **Acceptées par node1 :** non accusées directement par le protocole TCP du
  client. Les 6 sont toutefois une borne inférieure déduite de leur inclusion
  sur node1.
- **Incluses dans un bloc :** 6 sur node1, node2 et node3, selon le résultat
  `included_on_all_three=6`.
- **Commises :** 6 sur les trois copies persistées.
- **Réussies/échouées :** 6 commises ; aucune transaction benchmark non commise
  n'est signalée. Cette notion de succès signifie ici présence sur les trois
  chaînes, pas un statut d'exécution EVM séparé par receipt.
- **Backlog benchmark :** 0 transaction benchmark manquante sur les trois
  chaînes. La taille finale complète du mempool n'a pas été capturée.
- **TPS commis :** `0.1999992357562537 tx/s`.
- **Goodput transactionnel :** identique au TPS commis, soit
  `0.1999992357562537 tx/s`, si le goodput est défini comme transactions
  benchmark commises avec succès sur les trois nœuds.
- **Goodput de payload applicatif :** `0 B/s`, car `payload-size=0`. Cela ne
  compte pas les octets de protocole, de signature ou de stockage.
- **Latence d'inclusion :** non disponible pour ce run, car le générateur a
  terminé avec `local_observed=0`.
- **Latence de convergence :** non calculée. Les timestamps `commit_wall_ns`
  sont locaux aux VMs et les horloges ne sont pas synchronisées ; la
  convergence est validée ici par hauteur, `block_hash` et `state_root`, pas par
  soustraction de timestamps inter-VM.
- **Hauteur finale :** `6` sur node1, node2 et node3 ; chaque chaîne contient
  7 blocs, genesis inclus.
- **`block_hash` final à la hauteur 6 :** identique sur les trois nœuds :
  `276601ce46dd6e39161dda1b2285bd6d67b06507a34095f7efc1002022814945`.
- **`state_root` final à la hauteur 6 :** identique sur les trois nœuds :
  `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421`.
- **Convergence par hauteur :** les `block_hash` et `state_root` concordent à
  toutes les hauteurs 0 à 6. À la hauteur 0, le `block_hash` commun est
  `3ff93ff7c581582d53d9218d0368e4a35cc4c6828c0a6a683b54986f1c8fa590`.
- Les valeurs détaillées des blocs benchmark sont conservées dans le résumé
  JSON fourni ; aucune empreinte n'est déduite des seuls noms de fichiers.

## Point à corriger avant les répétitions

Le résultat `local_observed=0` n'invalide pas le comptage postérieur sur les
blocs copiés, mais il empêche de calculer les latences d'inclusion pour cette
répétition. Avant la campagne longue, synchroniser la version étendue de
`analyze_b2_baseline.py`, exécuter explicitement avec :

```bash
--data-dir "$PWD/data/node1"
```

et vérifier que le manifeste contient des entrées dans
`node1_local_observations`.

La version étendue de l'analyseur ajoute également les sections explicites
`acceptance`, `success_failure`, `backlog`, `latencies` et `final_chain`.

## Archive attendue

À conserver dans `results/raw_data/` :

```text
b2-pilot-r02-2026-09-13-node1-manifest.json
b2-pilot-r02-2026-09-13-summary.json
b2-pilot-r02-2026-09-13-execution.md
```

Aucune clé secrète, donnée médicale réelle ou configuration générée ne doit
être ajoutée à cette archive.
