"""
Hashing primitives used across the blockchain layer.
"""

from __future__ import annotations

import hashlib


def sha256(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise TypeError("sha256 expects bytes")
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return sha256(data).hex()
