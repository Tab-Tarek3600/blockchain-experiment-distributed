# Phase 7 — IPFS distribué

## Objectif

Documenter le stockage distribué de références de dossiers chiffrés avec un fournisseur IPFS co-localisé sur chacune des trois machines blockchain.

## Document

1. `01_IPFS_DISTRIBUE_REFERENCES_CHIFFREES.md`

## Topologie

- node1 + blockchain + IPFS-1
- node2 + blockchain + IPFS-2
- node3 + blockchain + IPFS-3

Le contenu est chiffré avant son ajout à IPFS ; la blockchain ne contient ni le contenu en clair ni une clé secrète.
