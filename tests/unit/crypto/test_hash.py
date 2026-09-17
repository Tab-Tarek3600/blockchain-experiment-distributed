"""
Deterministic binary serialization primitives.

These helpers produce canonical, unambiguous byte encodings used to
build the messages that are hashed and signed by Transaction and
Block. Every variable-length field is length-prefixed so that the
concatenation of several encoded fields cannot be reinterpreted in
more than one way.
"""

from __future__ import annotations

LENGTH_PREFIX_SIZE = 8  # uint64 length prefix for variable-length fields


class SerializationError(Exception):
    """Raised when a value cannot be canonically encoded."""


def encode_uint(value: int, length: int) -> bytes:
    """Encode a non-negative integer as a fixed-length big-endian value."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise SerializationError("value must be an integer")
    if value < 0:
        raise SerializationError("value must be non-negative")
    try:
        return value.to_bytes(length, byteorder="big", signed=False)
    except OverflowError as exc:
        raise SerializationError(f"value does not fit in {length} bytes") from exc


def encode_bytes(data: bytes) -> bytes:
    """Encode a variable-length byte string with an explicit length prefix."""
    if not isinstance(data, bytes):
        raise SerializationError("data must be bytes")
    return encode_uint(len(data), LENGTH_PREFIX_SIZE) + data


def encode_fields(*fields: bytes) -> bytes:
    """Concatenate already-encoded fields into one canonical byte string."""
    for i, field in enumerate(fields):
        if not isinstance(field, bytes):
            raise SerializationError(f"field at index {i} must be bytes")
    return b"".join(fields)