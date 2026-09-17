# Phase 5 — Relais transactionnel

## Objectif

Documenter le passage d'un envoi expérimental vers un scénario où un seul nœud d'entrée valide, place en mempool et relaie la transaction au réseau.

## Document

1. `01_RELAIS_TRANSACTIONNEL_PRODUCTION_A_LA_DEMANDE.md`

## Principe

Le relais transactionnel ne remplace pas le consensus : le validateur autorisé produit le bloc, puis les autres nœuds le diffusent, le valident et convergent.
