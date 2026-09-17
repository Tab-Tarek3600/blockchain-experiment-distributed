# Synchronisation indépendante des horloges — clôture Phase 8

**Date de contrôle :** 17 septembre 2026  
**Heure des captures :** 11:04 UTC environ  
**Périmètre :** node1, node2 et node3  
**Méthode :** `timedatectl`, `chronyc tracking` et `chronyc sources -v` exécutés à distance puis capturés sur la machine de développement.

## 1. Objectif

La documentation initiale de la Phase 8 signalait que la synchronisation
indépendante des horloges n'était pas établie. Ce contrôle de clôture a été
réalisé afin de vérifier l'état NTP/chrony des trois nœuds avant de finaliser
les résultats du 17 septembre 2026.

Cette étape comble le manque de preuve documentaire pour l'environnement de la
campagne du 17 septembre. Elle ne réécrit pas les résultats historiques des
campagnes des 13 au 16 septembre, qui restent documentés avec leurs limites
au moment où elles ont été exécutées.

## 2. Résultats

| Nœud | Heure de capture UTC | Synchronisé | Service NTP | Écart système indiqué | État chrony | Source sélectionnée |
|---|---|---|---:|---:|---|---|
| node1 | 2026-09-17 11:04:22 UTC | `yes` | `active` | 0,000092790 s rapide | `Leap status: Normal` | `^* ntp-nts-3.ps5.canonical.com` |
| node2 | 2026-09-17 11:04:36 UTC | `yes` | `active` | 0,002155502 s lent | `Leap status: Normal` | `^* ntp-nts-2.ps5.canonical.com` |
| node3 | 2026-09-17 11:04:47 UTC | `yes` | `active` | 0,000000732 s rapide | `Leap status: Normal` | `^* ntp-nts-3.ps5.canonical.com` |

Les trois nœuds indiquent simultanément :

- `System clock synchronized: yes` ;
- `NTPSynchronized=yes` ;
- `NTP service: active` ;
- `Leap status : Normal` ;
- une source NTP courante marquée `^*` dans `chronyc sources -v`.

Les valeurs `^*` identifient la meilleure source NTP actuellement sélectionnée
par chrony. Les autres sources disponibles sont conservées par chrony comme
sources secondaires ou combinées selon leur état.

## 3. Artefacts conservés

Les captures brutes correspondantes sont conservées dans `results/raw_data/` :

```text
clock-status-node1-20260917T110411Z.txt
clock-status-node2-20260917T110411Z.txt
clock-status-node3-20260917T110411Z.txt
```

Les fichiers contenant le script de commande issus d'essais précédents mal
formés ne sont pas utilisés comme preuve finale. Seules les trois captures
`20260917T110411Z` sont référencées ici.

## 4. Portée et limite d'interprétation

Ce contrôle établit que les trois systèmes étaient synchronisés avec NTP/chrony
au moment des captures. Il ne constitue pas, à lui seul, une mesure directe de
l'offset entre chaque paire de VMs ni une mesure de latence réseau. Il ne faut
pas utiliser les timestamps locaux pour publier une latence inter-VM numérique
sans mesure bidirectionnelle dédiée et hypothèses explicites sur le réseau.

Pour les mesures cryptographiques locales `keygen`, `sign_32B` et `verify_32B`,
les durées ont été mesurées avec `time.perf_counter_ns` sur chaque nœud ; elles
ne sont pas des mesures de TPS blockchain et ne nécessitent pas de soustraire
des timestamps inter-VM.

## 5. Conclusion pour l'article

La synchronisation NTP/chrony des trois nœuds a été vérifiée indépendamment le
17 septembre 2026 et les captures de preuve sont conservées. Le point faible
relatif à l'absence de preuve de synchronisation est donc corrigé pour
l'environnement et la campagne de clôture du 17 septembre. Les limites propres
aux campagnes historiques antérieures restent toutefois applicables à leurs
mesures de convergence inter-VM.
