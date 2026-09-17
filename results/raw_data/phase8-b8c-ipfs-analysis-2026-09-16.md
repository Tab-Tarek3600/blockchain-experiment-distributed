# Analyse B8-C — IPFS distribué

- Générée : `2026-09-16T17:32:52.088679+00:00`
- Données : ciphertexts synthétiques uniquement, 128 octets par version.
- Blockchain : aucune nouvelle transaction soumise par cette campagne.
- Les latences IPFS ne sont pas du TPS blockchain.

## Verdict

- CID identiques sur les fournisseurs : **OK**
- SHA-256 identiques : **OK**
- Intégrité de chaque fournisseur : **OK**
- Opérations mesurées sans échec : **OK**
- Verdict B8-C IPFS : **PASS**

## Mesures locales Kubo

| Fournisseur | Version | CID | cat p50/p95 ms | has p50/p95 ms | pin_add p50/p95 ms | pin_ls p50/p95 ms |
|---|---|---|---:|---:|---:|---:|
| node1 | v1 | `bafkreihwpoaggern5b26htrvldoxwhmphgde5yjzbl6d3yv6sfxjza47ca` | 0.7381865000000001 / 1.3949171999999996 | 0.5099835 / 0.68103335 | 3.0459025000000004 / 4.71351125 | 0.5450125 / 1.112430699999999 |
| node1 | v2 | `bafkreidnrskdhumwzmd6qwhv67mwahu2v7nior22ylnj4hpxmteqwz45f4` | 0.47234600000000004 / 0.5842579499999999 | 0.474726 / 0.5621736 | 3.2182315 / 4.660002099999998 | 0.5100370000000001 / 0.8738036499999998 |
| node2 | v1 | `bafkreihwpoaggern5b26htrvldoxwhmphgde5yjzbl6d3yv6sfxjza47ca` | 0.761653 / 1.66573355 | 0.587946 / 0.9610016 | 3.2180625000000003 / 4.44794755 | 0.501987 / 1.0334348999999994 |
| node2 | v2 | `bafkreidnrskdhumwzmd6qwhv67mwahu2v7nior22ylnj4hpxmteqwz45f4` | 0.5806119999999999 / 0.7371618 | 0.5470195 / 1.2054901999999994 | 2.884973 / 3.9333917499999997 | 0.486665 / 0.6144362 |
| node3 | v1 | `bafkreihwpoaggern5b26htrvldoxwhmphgde5yjzbl6d3yv6sfxjza47ca` | 0.6785205000000001 / 1.0763686499999996 | 0.5310545 / 0.6854209 | 2.8676845 / 3.2849143499999998 | 0.5008985 / 0.6722702 |
| node3 | v2 | `bafkreidnrskdhumwzmd6qwhv67mwahu2v7nior22ylnj4hpxmteqwz45f4` | 0.5415355 / 0.7329187499999996 | 0.4813615 / 0.6585028499999996 | 2.9391895 / 4.14249245 | 0.5163694999999999 / 0.6867902999999996 |

## Ressources et OOM

Les JSON fournisseurs conservent les relevés `VmRSS`, `VmSize`, `Threads`, les événements cgroup mémoire et les erreurs OOM visibles sans privilège. Aucun processus n'a été démarré ou arrêté par le script.

## Vérification blockchain

La lecture de `read_phase7_records.py` doit être archivée séparément. Elle vérifie les références historiques CID/hash sans inscrire les nouveaux CID B8-C. Ses sorties ne sont pas agrégées aux latences IPFS.

## Limite de mesure

`replication_fetch` est une mesure réalisée avec l'horloge monotone locale de la VM et peut inclure Bitswap. Aucun calcul de latence inter-VM n'est déduit de timestamps provenant d'horloges différentes.
