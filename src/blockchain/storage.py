"""
Block persistence on disk.

ChainStorage manages a directory containing one JSON file per block
(named by zero-padded height for correct lexicographic ordering),
under <base_dir>/blocks/.

Design choices:
    - One file per block (not a single monolithic chain file), so
      that a crash while writing a new block cannot corrupt already
      persisted blocks.
    - Atomic writes (write to a temp file, then os.replace) to avoid
      leaving a half-written, corrupted JSON file on disk if the
      process is interrupted mid-write.
    - Loading a block always reconstructs it via Block.from_dict(),
      which re-runs full structural validation (__post_init__). A
      corrupted or tampered file on disk is therefore detected at
      load time, not silently accepted.
    - This module only handles structural persistence. It does NOT
      perform cryptographic signature verification (consistent with
      validation.py) — that remains the responsibility of a higher
      layer (node/consensus).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.blockchain.block import Block, BlockError

HEIGHT_FILENAME_WIDTH = 20


class StorageError(Exception):
    """Raised when a block storage operation fails."""


class ChainStorage:
    """Filesystem-backed storage for an ordered sequence of blocks."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.blocks_dir = self.base_dir / "blocks"
        self.blocks_dir.mkdir(parents=True, exist_ok=True)

    def _block_path(self, height: int) -> Path:
        return self.blocks_dir / f"{height:0{HEIGHT_FILENAME_WIDTH}d}.json"

    def has_block(self, height: int) -> bool:
        """Return True if a block file exists at the given height."""
        return self._block_path(height).exists()

    def save_block(self, block: Block, *, overwrite: bool = False) -> None:
        """
        Persist a block to disk as JSON.

        Raises:
            StorageError: If a block already exists at this height and
                `overwrite` is False, or if the block cannot be
                serialized.
        """
        if not isinstance(block, Block):
            raise StorageError("block must be a Block instance")

        path = self._block_path(block.height)

        if path.exists() and not overwrite:
            raise StorageError(
                f"a block already exists at height {block.height} "
                "(pass overwrite=True to replace it)"
            )

        try:
            payload = json.dumps(block.to_dict(), indent=2, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise StorageError(f"failed to serialize block: {exc}") from exc

        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)  # atomic on POSIX filesystems

    def load_block(self, height: int) -> Block:
        """
        Load and validate a block from disk.

        Raises:
            StorageError: If no block exists at this height, or if the
                stored data is corrupted / structurally invalid.
        """
        path = self._block_path(height)

        if not path.exists():
            raise StorageError(f"no block found at height {height}")

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(
                f"failed to read block file at height {height}: {exc}"
            ) from exc

        try:
            return Block.from_dict(data)
        except BlockError as exc:
            raise StorageError(
                f"stored block at height {height} is invalid: {exc}"
            ) from exc

    def _existing_heights(self) -> list[int]:
        heights: list[int] = []
        for path in self.blocks_dir.glob("*.json"):
            try:
                heights.append(int(path.stem))
            except ValueError:
                continue  # ignore unrelated files
        return heights

    def get_tip_height(self) -> Optional[int]:
        """Return the highest stored block height, or None if empty."""
        heights = self._existing_heights()
        return max(heights) if heights else None

    def get_latest_block(self) -> Optional[Block]:
        """Return the block at the current tip height, or None if empty."""
        tip = self.get_tip_height()
        if tip is None:
            return None
        return self.load_block(tip)

    def append_block(self, block: Block) -> None:
        """
        Save a block, enforcing that it is exactly one height above
        the current tip (0 if the storage is empty).

        Raises:
            StorageError: If the block's height does not match the
                expected next height.
        """
        tip = self.get_tip_height()
        expected_height = 0 if tip is None else tip + 1

        if block.height != expected_height:
            raise StorageError(
                f"cannot append block at height {block.height}: "
                f"expected height {expected_height}"
            )

        self.save_block(block)

    def load_chain(self) -> list[Block]:
        """
        Load the full stored chain, ordered by height.

        Raises:
            StorageError: If stored heights are not contiguous
                starting at 0 (indicates a corrupted/incomplete
                storage directory).
        """
        heights = sorted(self._existing_heights())

        if not heights:
            return []

        if heights[0] != 0:
            raise StorageError("stored chain does not start at height 0")

        if heights != list(range(heights[0], heights[-1] + 1)):
            raise StorageError("stored chain has gaps in block heights")

        return [self.load_block(h) for h in heights]
