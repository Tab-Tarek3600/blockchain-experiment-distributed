# PHASE 3 (EVM) — Où en sommes-nous ?

> Document de repérage. Aucune décision technique ici, uniquement
> l'état des lieux.

---

## Avertissement : d'où vient la confusion

J'ai employé les mots « point 1 » et « point 2 » pour désigner **deux
choses différentes**, à deux moments différents. C'est ma faute, et
c'est ce qui donne l'impression de sauts.

| Ce que j'ai dit | Ce que ça désignait vraiment |
|---|---|
| « point 1 » (au début) | Le chantier **D5** : mettre `state_root` dans le bloc |
| « point 2 » (au début) | Le chantier **D6** : faire vérifier cette racine par le receveur |
| « point 1 » (récemment) | Un **défaut interne à D6** : le plafond de gas mal placé |
| « point 2 » (récemment) | Un **second défaut** : `build_candidate_block` sans plafond |

Autrement dit : les « points 1 et 2 » récents étaient des **sous-défauts
à l'intérieur du chantier D6**, pas les chantiers eux-mêmes.

**On n'a donc jamais reculé.** À partir d'ici j'abandonne « point N » et
je n'utilise plus que les noms de chantiers : **D1 … D8**.

---

## Le schéma

```
PHASE 3 — EVM
│
├─ D1  Analyse d'ouverture A→G .......................... ✅ FAIT
│      (livrable sans code, décisions de conception)
│
├─ D2  Socle EVM ........................................ ✅ FAIT
│      src/evm/state.py, errors.py, addresses.py
│      py-evm branché, fork Shanghai, chain_id 1337
│
├─ D3  state_root dans Block ............................ ✅ FAIT
│      rupture de format assumée, genesis = EMPTY_STATE_ROOT
│
├─ D4  Exécuteur de transactions ........................ ✅ FAIT
│      executor.py, receipt.py
│      un échec de tx ne casse pas le bloc
│
├─ D5  Rejeu de l'état depuis le disque ................. ✅ FAIT
│      replay.py (StateReplayer)
│      le producteur calcule la vraie racine
│
├─ D6  Vérification par le receveur ..................... ✅ CODE FINI
│   │                                                       ⚠️ NON VALIDÉ SUR VMs
│   ├─ étape 1  plafond de gas ......................... ✅
│   ├─ étape 2  root_after() (essai à blanc) ........... ✅
│   ├─ étape 3  branchement _accept_block .............. ✅
│   │
│   ├─ correctif A  gas consommé, pas annoncé .......... ✅
│   │               (l'ancien « point 1 »)
│   ├─ correctif B  même règle chez le producteur ...... ✅
│   │               (l'ancien « point 2 »)
│   │
│   └─ étape 4  vérification sur les 3 VMs ............. ✅ VALIDÉE EN CHARGE
│                (convergence observée dans B3 à h116)
│
├─ D7  receipts_root .................................... ⬜ PAS COMMENCÉ
│      (décidé : hors périmètre pour l'instant)
│
└─ D8  Déploiement de contrats de bout en bout .......... ⬜ PAS COMMENCÉ
       (c'est ce qui ouvre la PHASE 4)
```

**Position exacte au 15/09/2026 : D6 est validé pour le fonctionnement normal
sur les trois VMs ; la convergence des blocs valides a été confirmée dans le
run B3 à la hauteur 116. Les contrôles dédiés de blocs hostiles restent des
preuves de durcissement distinctes du benchmark de charge.**

---

## Ce qui est acquis (ne bouge plus)

- 7 fichiers dans `src/evm/`
- **385 tests passent** (369 unitaires + 16 intégration)
- Un bloc dont la racine est falsifiée est **rejeté**
- Un bloc qui dépasse le plafond de gas est **rejeté**
- Un bloc honnête qui annonce large est **accepté** (correctif A)
- Le producteur ne fabrique plus de bloc que ses pairs refuseraient
  (correctif B)

Tout cela est vérifié **sur cette machine uniquement**.

---

## Ce qui pose problème

### Réserve actuelle : complétude de l'observation sous charge

Le blocage py-evm n'existe plus : le moteur EVM et les signatures fonctionnent
sur les trois VMs, et le run B3 a produit des blocs valides convergents jusqu'à
la hauteur 116.

La réserve actuelle est méthodologique : à 3 tx/s, le générateur a offert 180
transactions mais seulement 121 ont été observées comme acceptées et incluses.
Aucun rejet explicite n'a été enregistré pour les 59 restantes. Il faut donc
séparer strictement soumission TCP, acceptation node1, inclusion et convergence.

### Problèmes secondaires (non bloquants)

| Sujet | Gravité | Statut |
|---|---|---|
| 2 tests *flaky* (sockets TCP) | faible | connu, préexistant, à relancer seul |
| `docs/INSTALL-py-evm.md` référencé mais absent | faible | contourné (procédure dans le doc de transmission) |
| Tag de référence PHASE 2 | faible | jamais posé |
| Pas de `receipts_root` (D7) | moyen | décidé hors périmètre |

---

## L'étape suivante, découpée

D6 n'est plus bloqué par l'installation de py-evm. La suite de travail est
maintenant expérimentale et documentaire :

```
  B3-3 tx/s   ─ résultat archivé : 121/180, convergence h116
        │
        ▼
  B4          ─ mesurer inclusion, commit local et convergence à 1 ou 2 tx/s
        │
        ▼
  B3 suite    ─ clients logiques puis éventuellement 5 tx/s
        │
        ▼
  B5/B6       ─ crash/reprise puis délai/perte réseau
        │
        ▼
  article     ─ tableaux, limites et interprétation scientifique
```

La collecte, les blocs et l'analyse B2/B3 doivent rester sur la machine de
développement. Node1 ne sert qu'à exécuter le générateur selon le scénario
client/médecin → node1 → P2P. Les clés secrètes et configurations générées ne
doivent pas être supprimées.

Le détail du prochain test est dans `docs/08_PHASE8_BENCHMARKS/01_PLAN_TESTS_BENCHMARKS.md` et dans
`docs/08_PHASE8_BENCHMARKS/02_ETAT_EXECUTION_PHASE8_2026-09-15.md`.
