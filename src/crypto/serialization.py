"""
Deterministic binary serialization primitives.
"""

from __future__ import annotations

LENGTH_PREFIX_SIZE = 8


class SerializationError(Exception):
    """Raised when a value cannot be canonically encoded."""


def encode_uint(value: int, length: int) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SerializationError("value must be an integer")
    if value < 0:
        raise SerializationError("value must be non-negative")
    try:
        return value.to_bytes(length, byteorder="big", signed=False)
    except OverflowError as exc:
        raise SerializationError(f"value does not fit in {length} bytes") from exc


def encode_bytes(data: bytes) -> bytes:
    if not isinstance(data, bytes):
        raise SerializationError("data must be bytes")
    return encode_uint(len(data), LENGTH_PREFIX_SIZE) + data


def encode_fields(*fields: bytes) -> bytes:
    for i, field in enumerate(fields):
        if not isinstance(field, bytes):
            raise SerializationError(f"field at index {i} must be bytes")
    return b"".join(fields)
