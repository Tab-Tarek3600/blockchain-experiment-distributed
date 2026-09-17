# Analyse de clôture B8-C — IPFS distribué

**Date de campagne :** 16 septembre 2026  
**Run ID :** `b8c-ipfs-20260916`  
**Périmètre :** IPFS hors chaîne sur node1, node2 et node3  
**Verdict IPFS :** **PASS**  
**TPS blockchain :** non mesuré et non déduit

## 1. Artefacts examinés

- `b8c-precheck-node1.json`, `b8c-precheck-node2.json`, `b8c-precheck-node3.json`
- `b8c-seed-node1.json` et `b8c-seed-node1.log`
- `b8c-ipfs-20260916-node1.json`
- `b8c-ipfs-20260916-node2.json`
- `b8c-ipfs-20260916-node3.json`
- `b8c-ipfs-20260916-summary.json`
- les trois logs d'exécution IPFS
- les trois sorties `b8c-blockchain-readonly-node*.txt`
- l'inventaire en lecture seule `phase8-b8c-blockchain-history-inventory-2026-09-16.md`

Les trois JSON fournisseurs indiquent `ok: true`, zéro erreur, 30 succès sur
30 pour chaque opération et `all_integrity_ok: true`.

## 2. Pré-vérifications

| Élément | Résultat |
|---|---|
| API Kubo node1/node2/node3 | OK |
| Adresse API | `127.0.0.1:5001` sur les trois VMs |
| Port P2P | `0.0.0.0:4001` sur les trois VMs |
| Version Kubo | `0.43.0` sur les trois VMs |
| Identités IPFS | distinctes sur node1, node2 et node3 |
| Processus Kubo | présent sur les trois VMs, 7 threads relevés |
| OOM visible dans `dmesg` sur 24 h | aucune ligne OOM relevée |
| `memory.events` cgroup | non disponible dans les pré-vérifications |
| Espace disque | 49–50 % utilisé, environ 6,4–6,7 GiB disponibles |

L'absence de `memory.events` doit être conservée comme une limite de mesure :
les relevés ne constituent pas une preuve exhaustive de l'absence d'un compteur
OOM cgroup, mais aucun OOM n'a été visible dans la sortie noyau collectée.

## 3. Jeu synthétique et intégrité

Deux ciphertexts synthétiques de 128 octets ont été ajoutés par node1. Aucun
plaintext médical n'a été utilisé.

| Version | CID | SHA-256 | Taille |
|---|---|---|---:|
| v1 | `bafkreihwpoaggern5b26htrvldoxwhmphgde5yjzbl6d3yv6sfxjza47ca` | `f67b8063122de875e3ce3558dd7b1d8f39864ee1390afc3de2be916e9c839f10` | 128 octets |
| v2 | `bafkreidnrskdhumwzmd6qwhv67mwahu2v7nior22ylnj4hpxmteqwz45f4` | `6d8c9433d196cb07e858f5f7d9601e9aafda87475ac2da9e1df764c90b679d2f` | 128 octets |

Résultats :

- `CID_v1 != CID_v2` : OK ;
- `SHA256_v1 != SHA256_v2` : OK ;
- même CID récupéré sur les trois fournisseurs : OK ;
- même SHA-256 sur les trois fournisseurs : OK ;
- taille et octets récupérés conformes : OK ;
- pin et présence vérifiés sur les trois fournisseurs : OK.

## 4. Latence d'ajout — node1

Le seed a relevé une durée pour chaque ajout, sans prétendre fournir un
percentile statistique d'ajout :

| Version | Ajout | Cat de vérification | Pin initial |
|---|---:|---:|---:|
| v1 | 31,397 ms | 2,799 ms | 5,665 ms |
| v2 | 3,534 ms | 0,883 ms | 2,923 ms |

La durée v1 inclut vraisemblablement le coût initial du dépôt/daemon. Ces
valeurs sont des observations de seed, pas une série de 30 ajouts.

## 5. Réplication

Le premier `cat` exécuté sur chaque VM après le seed est conservé sous
`replication_fetch`. Sur node2 et node3, il peut inclure la récupération Bitswap.

| Fournisseur | v1 | v2 |
|---|---:|---:|
| node1 | 0,913 ms | 0,654 ms |
| node2 | 29,870 ms | 4,592 ms |
| node3 | 11,076 ms | 2,760 ms |

Les deux versions ont donc été récupérées avec succès sur les trois
fournisseurs. Ces durées sont mesurées avec l'horloge monotone locale de chaque
VM ; elles ne constituent pas une latence inter-VM obtenue par comparaison
d'horodatages.

## 6. Mesures locales Kubo — p50 / p95 en millisecondes

Chaque cellule contient `p50 / p95`. Chaque opération comporte 30 échantillons
et les résultats sont séparés par fournisseur et par version.

| VM | Version | `cat_local` | `has_block_stat` | `pin_add` | `pin_ls` |
|---|---|---:|---:|---:|---:|
| node1 | v1 | 0,738 / 1,395 | 0,510 / 0,681 | 3,046 / 4,714 | 0,545 / 1,112 |
| node1 | v2 | 0,472 / 0,584 | 0,475 / 0,562 | 3,218 / 4,660 | 0,510 / 0,874 |
| node2 | v1 | 0,762 / 1,666 | 0,588 / 0,961 | 3,218 / 4,448 | 0,502 / 1,033 |
| node2 | v2 | 0,581 / 0,737 | 0,547 / 1,205 | 2,885 / 3,933 | 0,487 / 0,614 |
| node3 | v1 | 0,679 / 1,076 | 0,531 / 0,685 | 2,868 / 3,285 | 0,501 / 0,672 |
| node3 | v2 | 0,542 / 0,733 | 0,481 / 0,659 | 2,939 / 4,142 | 0,516 / 0,687 |

Pour les 24 séries mesurées :

- 30 échantillons par série ;
- 30 succès par série ;
- zéro échec ;
- zéro erreur enregistrée.

Les valeurs sont des latences d'API Kubo loopback. Elles ne doivent pas être
additionnées au TPS ou à la latence de la blockchain.

## 7. Ressources Kubo

RSS Kubo avant/après la campagne :

| VM | RSS avant | RSS après | Variation |
|---|---:|---:|---:|
| node1 | 68 212 kB | 77 316 kB | +9 104 kB |
| node2 | 67 996 kB | 74 600 kB | +6 604 kB |
| node3 | 68 932 kB | 78 216 kB | +9 284 kB |

Les processus Kubo sont restés présents pendant la mesure. Aucun processus n'a
été démarré ou arrêté par le script B8-C. L'occupation disque reste stable à
49–50 % dans les relevés reçus.

## 8. Lecture blockchain en lecture seule — cohérence et portée

Les trois nœuds présentent :

| VM | Hauteur | `state_root` |
|---|---:|---|
| node1 | 242 | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` |
| node2 | 242 | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` |
| node3 | 242 | `56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421` |

Le contrat indiqué est identique :
`0x368108079fe315817cde85b3ab02bd70d7024c0f`.

L'inventaire des blocs 0 à 6 est également identique sur les trois nœuds :
les blocs 1 à 6 contiennent chacun une transaction avec `data_len=0`. Il n'y
a donc pas de transaction `registerRecord` Phase 7 dans la chaîne actuellement
chargée. L'échec de `read_phase7_records.py` avec `EXIT=1` et `transaction ...
absente du bloc 5` est cohérent avec cette chaîne et ne constitue pas un échec
de B8-C-IPFS.

`read_phase7_records.py` est un vérificateur historique spécifique à Phase 7,
et non un critère d'acceptation de B8-C-IPFS. B8-C n'a soumis aucune
transaction blockchain ; son contrôle blockchain en lecture seule porte sur la
cohérence hauteur/racine entre les trois nœuds. L'inventaire détaillé est
archivé dans `phase8-b8c-blockchain-history-inventory-2026-09-16.md`.

La preuve historique Phase 7 du 13 septembre reste archivée séparément dans
`phase7-blockchain-v1-v2-2026-09-13.txt`. Elle ne doit pas être interprétée
comme une nouvelle transaction de B8-C.

Aucune transaction, réinitialisation ou modification persistante n'a été
réalisée pendant ces contrôles.

## 9. Conclusion

B8-C est validé pour son périmètre IPFS :

- les trois APIs Kubo loopback sont opérationnelles ;
- les trois identités IPFS sont distinctes ;
- deux ciphertexts synthétiques ont été ajoutés ;
- les CID et SHA-256 sont cohérents sur les trois fournisseurs ;
- la réplication Bitswap a réussi ;
- pinning et présence ont réussi sur les trois fournisseurs ;
- les 24 séries de 30 échantillons ont réussi sans échec ;
- les mesures de ressources ont été archivées ;
- aucune latence IPFS n'est présentée comme TPS blockchain.

**Verdict final : `B8-C-IPFS PASS`.**

Le contrôle blockchain B8-C est également PASS pour son périmètre de lecture
seule : les trois nœuds sont convergents à la hauteur 242, avec la même
`state_root`, et aucune transaction blockchain n'a été soumise par la
campagne. Le lecteur `read_phase7_records.py` n'est pas applicable à cette
chaîne, qui ne contient pas les transactions historiques `registerRecord` de
Phase 7.

La disponibilité de `memory.events` reste une limite de mesure facultative,
et non une réserve sur le verdict d'acceptation IPFS : aucun OOM n'a été
observé dans les journaux noyau collectés.
