"""
Blockchain address utilities.

Addresses are derived deterministically from public keys.
"""

from __future__ import annotations

from .hash import sha256

ADDRESS_LENGTH = 20
ADDRESS_HEX_LENGTH = 2 + ADDRESS_LENGTH * 2


class AddressError(Exception):
    """Raised when an invalid address or public key is provided."""


def public_key_to_address(public_key: bytes) -> bytes:
    if not isinstance(public_key, bytes):
        raise AddressError("public_key must be bytes")

    if not public_key:
        raise AddressError("public_key must not be empty")

    return sha256(public_key)[-ADDRESS_LENGTH:]


def address_to_hex(address: bytes) -> str:
    if not isinstance(address, bytes):
        raise AddressError("address must be bytes")

    if len(address) != ADDRESS_LENGTH:
        raise AddressError(
            f"address must contain exactly {ADDRESS_LENGTH} bytes"
        )

    return "0x" + address.hex()


def hex_to_address(hex_address: str) -> bytes:
    if not isinstance(hex_address, str):
        raise AddressError("hex_address must be a string")

    if not hex_address.startswith("0x"):
        raise AddressError("hex_address must start with '0x'")

    raw = hex_address[2:]

    try:
        address = bytes.fromhex(raw)
    except ValueError as exc:
        raise AddressError("hex_address is not valid hexadecimal") from exc

    if len(address) != ADDRESS_LENGTH:
        raise AddressError(
            f"address must contain exactly {ADDRESS_LENGTH} bytes"
        )

    return address


def is_valid_address(address: bytes) -> bool:
    return (
        isinstance(address, bytes)
        and len(address) == ADDRESS_LENGTH
    )
