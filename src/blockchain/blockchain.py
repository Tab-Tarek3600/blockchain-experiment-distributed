"""
Blockchain — orchestration de la chaîne complète.

Assemble les modules précédents :
    - genesis.py    : création/validation du bloc initial
    - validation.py : validation structurelle des blocs et du chaînage
    - storage.py     : persistance sur disque

Blockchain maintient un cache en mémoire (liste ordonnée de blocs)
synchronisé avec le stockage disque : toute écriture persiste
d'abord sur disque, puis met à jour le cache — jamais l'inverse,
pour ne jamais désynchroniser mémoire et disque en cas d'échec de
persistance.

Comme le reste de la couche blockchain/, ce module ne réalise AUCUNE
vérification cryptographique (ML-DSA). Il valide uniquement la
structure des blocs et la cohérence du chaînage (previous_block_hash,
height séquentiel). La vérification des signatures reste la
responsabilité d'une couche supérieure (node/consensus), qui pourra
appeler tx.signing_hash/block.signing_hash avec un MLDSA avant
d'accepter un bloc proposé par le réseau.
"""

from __future__ import annotations

from typing import Optional

from src.blockchain.block import Block
from src.blockchain.genesis import (
    DEFAULT_GENESIS_TIMESTAMP,
    GenesisError,
    create_genesis_block,
    is_genesis_block,
    validate_genesis_block,
)
from src.blockchain.storage import ChainStorage, StorageError
from src.blockchain.validation import (
    ValidationError,
    validate_block,
    validate_block_chain_link,
    validate_block_sequence,
)


class BlockchainError(Exception):
    """Raised when a chain-level operation fails."""


class Blockchain:
    """In-memory chain, backed by a ChainStorage for persistence."""

    def __init__(self, storage: ChainStorage, blocks: list[Block]) -> None:
        self._storage = storage
        self._blocks = blocks

    # ── Construction ────────────────────────────────────────────────

    @classmethod
    def create_new(
        cls,
        storage: ChainStorage,
        *,
        validator_public_key: bytes,
        timestamp: int = DEFAULT_GENESIS_TIMESTAMP,
    ) -> "Blockchain":
        """
        Initialize a brand new chain: create, validate and persist the
        genesis block.

        Raises:
            BlockchainError: If the storage already contains a chain,
                or if the genesis block cannot be created/validated.
        """
        if storage.get_tip_height() is not None:
            raise BlockchainError(
                "storage already contains a chain; use Blockchain.load() instead"
            )

        try:
            genesis = create_genesis_block(
                validator_public_key=validator_public_key, timestamp=timestamp
            )
            validate_genesis_block(genesis)
        except GenesisError as exc:
            raise BlockchainError(f"failed to create genesis block: {exc}") from exc

        try:
            storage.save_block(genesis)
        except StorageError as exc:
            raise BlockchainError(f"failed to persist genesis block: {exc}") from exc

        return cls(storage, [genesis])

    @classmethod
    def load(cls, storage: ChainStorage) -> "Blockchain":
        """
        Load an existing chain from storage, re-validating its full
        structure and chaining.

        Raises:
            BlockchainError: If the storage is empty, or the stored
                chain is structurally invalid, or does not start with
                a valid genesis block.
        """
        try:
            blocks = storage.load_chain()
        except StorageError as exc:
            raise BlockchainError(f"failed to load chain from storage: {exc}") from exc

        if not blocks:
            raise BlockchainError(
                "storage is empty; use Blockchain.create_new() to initialize a chain"
            )

        try:
            validate_block_sequence(blocks)
        except ValidationError as exc:
            raise BlockchainError(f"stored chain failed validation: {exc}") from exc

        if not is_genesis_block(blocks[0]):
            raise BlockchainError(
                "stored chain's first block is not a valid genesis block"
            )

        return cls(storage, blocks)

    @classmethod
    def open(
        cls,
        storage: ChainStorage,
        *,
        validator_public_key: Optional[bytes] = None,
        timestamp: int = DEFAULT_GENESIS_TIMESTAMP,
    ) -> "Blockchain":
        """
        Convenience factory: load the chain if the storage already
        contains one, otherwise create a new one.

        Raises:
            BlockchainError: If the storage is empty and
                validator_public_key was not provided, or if
                create_new/load fails for their own reasons.
        """
        if storage.get_tip_height() is None:
            if validator_public_key is None:
                raise BlockchainError(
                    "validator_public_key is required to initialize a new chain"
                )
            return cls.create_new(
                storage, validator_public_key=validator_public_key, timestamp=timestamp
            )

        return cls.load(storage)

    # ── Lecture ─────────────────────────────────────────────────────

    @property
    def height(self) -> int:
        """Height of the current chain tip."""
        return self._blocks[-1].height

    @property
    def block_count(self) -> int:
        """Number of blocks in the chain (height + 1)."""
        return len(self._blocks)

    @property
    def genesis_block(self) -> Block:
        """The chain's genesis block."""
        return self._blocks[0]

    def get_latest_block(self) -> Block:
        """The current tip of the chain."""
        return self._blocks[-1]

    def get_block(self, height: int) -> Optional[Block]:
        """Return the block at the given height, or None if out of range."""
        if 0 <= height < len(self._blocks):
            return self._blocks[height]
        return None

    def get_block_by_hash(self, block_hash: bytes) -> Optional[Block]:
        """Return the block with the given block_hash, or None if not found."""
        for block in self._blocks:
            if block.block_hash == block_hash:
                return block
        return None

    # ── Écriture ────────────────────────────────────────────────────

    def add_block(self, block: Block) -> None:
        """
        Validate, persist, then append a new block to the chain.

        The block is first structurally validated on its own, then
        checked for correct chaining against the current tip. It is
        persisted to disk before the in-memory cache is updated, so
        that a storage failure never leaves the cache ahead of disk.

        Raises:
            BlockchainError: If the block is structurally invalid,
                does not correctly follow the current tip, or cannot
                be persisted.
        """
        try:
            validate_block(block)
        except ValidationError as exc:
            raise BlockchainError(f"block is structurally invalid: {exc}") from exc

        current_tip = self.get_latest_block()

        try:
            validate_block_chain_link(current_tip, block)
        except ValidationError as exc:
            raise BlockchainError(
                f"block does not correctly link to current tip: {exc}"
            ) from exc

        try:
            self._storage.append_block(block)
        except StorageError as exc:
            raise BlockchainError(f"failed to persist block: {exc}") from exc

        self._blocks.append(block)
