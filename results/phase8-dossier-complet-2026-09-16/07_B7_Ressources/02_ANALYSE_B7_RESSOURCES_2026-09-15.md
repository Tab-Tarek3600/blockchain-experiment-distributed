# Analyse B7 — profil de ressources des trois VMs

**Run ID :** `b7-profile-1p0-20260915`  
**Date du run selon l'identifiant :** 15 septembre 2026  
**Date de réception de la sortie :** 16 septembre 2026  
**Scénario :** 1 client logique, 1 tx/s, 60 s, payload synthétique de 0 octet, ingress node1 uniquement  
**Collecte :** 120 s, échantillonnage à 1 s  
**Statut :** exécuté et analysé

## 1. Source et intégrité des résultats

Le manifeste et le résumé ont été validés par :

```text
MANIFESTE_JSON_OK
SUMMARY_JSON_OK
```

La sortie fournie pour le résumé indique :

```text
submitted                 : 60
included_node1            : 60
included_node2            : 60
included_node3            : 60
included_on_all_three     : 60
rejected_count            : 0
errors                    : []
success_rate_all_three     : 1.0
submitted_duration_s      : 60.0
```

Le résumé indique également :

```text
all_submitted_present_on_all_three       : true
no_benchmark_transaction_duplicate...   : true
three_node_chain_converged_to_min_tip   : true
```

Ainsi, le run comporte `60/60` transactions présentes sur les trois chaînes,
soit un taux de succès observé de `100 %` et un débit commis de `1 tx/s` sur la
fenêtre de soumission. Il n'y a eu ni rejet explicite, ni erreur de charge, ni
doublon observé.

## 2. Nombre d'échantillons

La commande de comptage retourne `720` lignes temporelles dans chaque fichier
`pidstat`. Ce n'est pas une anomalie : `pidstat -u -r -d` produit trois groupes
de mesures, CPU, mémoire/RSS et E/S disque, chacun contenant environ 120
échantillons.

| Nœud | Lignes pidstat | Groupes pidstat | Échantillons par groupe | vmstat |
|---|---:|---:|---:|---:|
| node1 | 720 | 3 | 120 | 120 |
| node2 | 720 | 3 | 120 | 120 |
| node3 | 720 | 3 | 120 | 120 |

Le critère d'échantillonnage B7 est donc satisfait : 120 secondes de mesure à
un intervalle d'une seconde sur les trois VMs.

## 3. CPU, RSS et E/S du processus blockchain

Les moyennes `pidstat` sont :

| Nœud | PID | %CPU moyen | %usr | %system | VSZ | RSS | %MEM | Lecture/écriture processus |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| node1 | 2163 | 99,81 % | 99,81 % | 0,00 % | 384 736 KiB | 50 432 KiB | 3,09 % | 0,00 / 0,00 kB/s |
| node2 | 2164 | 99,88 % | 99,82 % | 0,06 % | 384 736 KiB | 50 480 KiB | 3,09 % | 0,00 / 0,00 kB/s |
| node3 | 2163 | 99,87 % | 99,81 % | 0,06 % | 384 736 KiB | 50 284 KiB | 3,08 % | 0,00 / 0,00 kB/s |

Les RSS correspondent approximativement à `49,25 MiB`, `49,30 MiB` et `49,11
MiB`. Les trois processus consomment donc environ un cœur logique à pleine
charge pendant la collecte, avec une empreinte mémoire résidentielle proche de
49 MiB et très similaire entre les VMs.

Les valeurs `0,00 kB/s` de `pidstat -d` doivent être interprétées avec
prudence : elles signifient qu'aucune moyenne mesurable n'a été attribuée au
processus à la résolution affichée. Elles ne prouvent pas l'absence absolue de
toute E/S disque ; les valeurs système `vmstat bi/bo` ci-dessous montrent une
activité faible mais non nulle.

## 4. Ressources système avec `vmstat`

| Nœud | Échantillons | free moyen | bi moyen | bo moyen | us moyen | sy moyen | id moyen | wa moyen |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| node1 | 120 | 719 469 KiB | 3,458 KiB/s | 0,408 KiB/s | 49,717 % | 0,083 % | 50,317 % | 0,000 % |
| node2 | 120 | 722 891 KiB | 3,483 KiB/s | 0,675 KiB/s | 49,758 % | 0,108 % | 50,292 % | 0,000 % |
| node3 | 120 | 735 341 KiB | 3,392 KiB/s | 0,767 KiB/s | 49,758 % | 0,158 % | 50,275 % | 0,000 % |

Le CPU système montre environ 49,7 % de temps utilisateur et environ 50,3 %
d'inactivité. Cette mesure est celle de la VM entière, tandis que `pidstat`
mesure le processus Python. Elle est compatible avec un processus blockchain
occupant environ un cœur logique dans chaque VM ; aucune conclusion sur le
nombre exact de vCPU ne doit cependant être tirée sans la sortie `lscpu`.

L'attente I/O (`wa`) est nulle dans les trois VMs. L'activité bloc système
reste faible (`bi` environ 3,4 KiB/s et `bo` inférieur à 0,8 KiB/s).

## 5. Mémoire et swap

| Nœud | Mémoire utilisée avant | libre avant | disponible avant | utilisée après | libre après | swap utilisée |
|---|---:|---:|---:|---:|---:|---:|
| node1 | 496 MiB | 702 MiB | 1,1 GiB | 496 MiB | 702 MiB | 0 B |
| node2 | 501 MiB | 705 MiB | 1,1 GiB | 500 MiB | 705 MiB | 0 B |
| node3 | 510 MiB | 718 MiB | 1,1 GiB | 510 MiB | 717 MiB | 0 B |

La charge B7 ne provoque pas de croissance mesurable de la mémoire globale et
n'utilise pas le swap. Les petites variations de 1 MiB sont normales et ne
constituent pas une tendance.

## 6. Trafic réseau observé sur `ens33`

Les compteurs ont été relevés avant et après la collecte. Les deltas sont donc
ceux observés sur l'intervalle de mesure ; ils comprennent le trafic blockchain
et le trafic de contrôle éventuel de la VM.

| Nœud | RX avant | RX après | Delta RX | TX avant | TX après | Delta TX | Erreurs/pertes |
|---|---:|---:|---:|---:|---:|---:|---|
| node1 | 7 313 977 B | 7 321 921 B | **7 944 B** | 8 971 049 B | 8 980 749 B | **9 700 B** | 0 / 0 |
| node2 | 5 797 689 B | 5 805 429 B | **7 740 B** | 6 062 176 B | 6 071 346 B | **9 170 B** | 0 / 0 |
| node3 | 10 495 872 B | 10 503 624 B | **7 752 B** | 8 517 875 B | 8 527 147 B | **9 272 B** | 0 / 0 |

Les deltas totaux RX+TX sont donc :

```text
node1 : 17 644 octets
node2 : 16 910 octets
node3 : 17 024 octets
```

Aucune erreur, perte, collision ou porteuse n'est observée dans les compteurs
fournis. Un ratio approximatif par transaction soumise donnerait environ 294,
282 et 284 octets par transaction respectivement, mais ce ratio ne doit pas
être présenté comme un coût réseau pur par transaction : les compteurs
contiennent également les échanges P2P et le trafic de contrôle.

## 7. Disque et taille de la chaîne

La taille affichée par `du -sh` reste :

```text
node1 : 3,5M avant → 3,5M après
node2 : 3,5M avant → 3,5M après
node3 : 3,5M avant → 3,5M après
```

Le système de fichiers reste également stable :

```text
node1 : / utilisé à 50 % avant et après
node2 : / utilisé à 49 % avant et après
node3 : / utilisé à 49 % avant et après
```

La résolution de `du -sh` est trop grossière pour mesurer une petite croissance
des blocs. Cette observation signifie seulement qu'aucune variation n'est
visible à l'arrondi MiB. Les 182 blocs existants ne doivent pas être supprimés ;
B7 s'exécute sur la chaîne persistante et les nouveaux blocs éventuels sont
analysés avec cet historique.

## 8. Conclusion scientifique prudente

Dans le mode expérimental contraint, avec un client logique à `1 tx/s`, les
`60` transactions soumises ont été incluses sur les trois VMs sans doublon,
rejet explicite ni erreur de charge. Le profil de ressources est fortement
CPU-bound au niveau du processus Python, avec environ `99,8 %` de CPU par nœud
et environ `49 MiB` de RSS par processus. La mémoire globale reste stable, le
swap n'est pas utilisé, l'attente I/O est nulle et le trafic réseau observé
reste de l'ordre de `17 KiB` par VM sur la fenêtre capturée.

Ce run ne permet pas de conclure à une capacité maximale, ni de comparer une
machine physique à une VM. Il s'agit d'une comparaison entre trois VMs VMware
sous une charge unique et contrôlée. Les latences numériques inter-VM ne sont
pas déduites de B7, conformément à la limitation sur la synchronisation des
horloges.

## 9. Artefacts attendus

Les fichiers bruts correspondants doivent être conservés dans le dépôt de
développement :

- `b7-profile-1p0-20260915-node1-manifest.json`
- `b7-profile-1p0-20260915-summary.json`
- `b7-profile-1p0-20260915-generator.log`
- journaux node1/node2/node3 ;
- fichiers `pidstat`, `vmstat`, `net-before`, `net-after` ;
- fichiers `free-before`, `free-after`, `df-before`, `df-after` ;
- fichiers `data-before`, `data-after` ;
- timestamps de début et de fin des trois collectes ;
- copies des répertoires `blocks` des trois nœuds.

Cette note est basée sur la sortie de contrôle fournie après l'exécution. Les
fichiers bruts doivent rester la source de preuve principale et être récupérés
dans `results/raw_data/b7-profile-1p0-20260915-*` sur la machine de
Développement.
