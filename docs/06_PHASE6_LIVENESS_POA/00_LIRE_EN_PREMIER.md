# Phase 6 — Liveness PoA

## Objectif

Décrire le comportement du consensus lorsque le proposant courant est indisponible : expiration du timeout, passage au round suivant et reprise de la production à la même hauteur.

## Document

1. `01_TIMEOUT_ET_CHANGEMENT_DE_ROUND.md`

## Principe

La production reste à la demande : un mempool vide ne produit pas de bloc ; une transaction en attente permet la production dès qu'un proposant disponible est désigné.
