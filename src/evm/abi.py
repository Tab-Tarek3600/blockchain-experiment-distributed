"""Encodage ABI minimal et déterministe pour les contrats PHASE 4.

Le module ne connaît aucun contrat médical : il encode des signatures et les
types ABI utilisés par leurs interfaces (`bytes32`, `address`, `uint256`,
`bool` et `bytes`). Les artefacts Solidity restent la source de vérité de
l'ABI ; ces fonctions évitent seulement de reproduire manuellement les
sélecteurs dans chaque test ou appelant.
"""

from __future__ import annotations

from typing import Sequence

from eth_utils import keccak

from src.evm.addresses import validate_address

_WORD_SIZE = 32
_UINT256_MAX = 2**256 - 1
_SUPPORTED_TYPES = {"bytes32", "address", "uint256", "bool", "bytes"}


class ABIError(ValueError):
    """Erreur de type ou de structure lors d'un encodage/décodage ABI."""


def function_selector(signature: str) -> bytes:
    """Retourne les quatre premiers octets du hash Keccak de la signature."""
    if not isinstance(signature, str) or not signature or "(" not in signature:
        raise ABIError("function signature must be a non-empty canonical string")
    if not signature.endswith(")"):
        raise ABIError("function signature must end with ')'")
    return keccak(text=signature)[:4]


def encode_function_call(signature: str, values: Sequence[object]) -> bytes:
    """Encode un appel ABI avec son sélecteur et ses arguments."""
    types = _signature_types(signature)
    if len(types) != len(values):
        raise ABIError(
            f"signature expects {len(types)} values, got {len(values)}"
        )

    head_size = _WORD_SIZE * len(types)
    head: list[bytes] = []
    tail: list[bytes] = []
    tail_size = 0

    for type_name, value in zip(types, values):
        if type_name == "bytes":
            encoded = _encode_bytes(value)
            head.append(_word(head_size + tail_size))
            tail.append(encoded)
            tail_size += len(encoded)
        else:
            head.append(_encode_static(type_name, value))

    return function_selector(signature) + b"".join(head + tail)


def decode_function_output(
    types: Sequence[str], data: bytes
) -> tuple[object, ...]:
    """Decode les types de sortie ABI supportés par ce module."""
    if not isinstance(data, bytes):
        raise ABIError("ABI output must be bytes")
    normalized = tuple(types)
    for type_name in normalized:
        _validate_type(type_name)

    head_size = _WORD_SIZE * len(normalized)
    if len(data) < head_size:
        raise ABIError("ABI output is shorter than its head")

    values: list[object] = []
    for index, type_name in enumerate(normalized):
        word = data[index * _WORD_SIZE : (index + 1) * _WORD_SIZE]
        if type_name == "bytes":
            offset = _decode_uint(word)
            values.append(_decode_bytes_at(data, offset, minimum_offset=head_size))
        else:
            values.append(_decode_static(type_name, word))
    return tuple(values)


def _signature_types(signature: str) -> tuple[str, ...]:
    if not isinstance(signature, str):
        raise ABIError("function signature must be a string")
    try:
        arguments = signature[signature.index("(") + 1 : -1]
    except ValueError as exc:
        raise ABIError("invalid function signature") from exc
    if not arguments:
        return ()
    types = tuple(item.strip() for item in arguments.split(","))
    for type_name in types:
        _validate_type(type_name)
    return types


def _validate_type(type_name: str) -> None:
    if type_name not in _SUPPORTED_TYPES:
        raise ABIError(f"unsupported ABI type: {type_name}")


def _encode_static(type_name: str, value: object) -> bytes:
    _validate_type(type_name)
    if type_name == "bytes32":
        if not isinstance(value, bytes) or len(value) != 32:
            raise ABIError("bytes32 value must contain exactly 32 bytes")
        return value
    if type_name == "address":
        return _word(validate_address(value, "ABI address"))
    if type_name == "uint256":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ABIError("uint256 value must be an integer")
        if value < 0 or value > _UINT256_MAX:
            raise ABIError("uint256 value is outside the 256-bit range")
        return _word(value)
    if type_name == "bool":
        if not isinstance(value, bool):
            raise ABIError("bool value must be bool")
        return _word(1 if value else 0)
    raise ABIError(f"{type_name} is dynamic")


def _encode_bytes(value: object) -> bytes:
    if not isinstance(value, bytes):
        raise ABIError("bytes value must be bytes")
    padding = (-len(value)) % _WORD_SIZE
    return _word(len(value)) + value + (b"\x00" * padding)


def _decode_static(type_name: str, word: bytes) -> object:
    if type_name == "bytes32":
        return word
    if type_name == "address":
        if word[:12] != b"\x00" * 12:
            raise ABIError("ABI address has non-zero leading bytes")
        return word[12:]
    if type_name == "uint256":
        return _decode_uint(word)
    if type_name == "bool":
        value = _decode_uint(word)
        if value not in (0, 1):
            raise ABIError("ABI bool is neither zero nor one")
        return bool(value)
    raise ABIError(f"unsupported dynamic output type: {type_name}")


def _decode_bytes_at(
    data: bytes, offset: int, *, minimum_offset: int = 0
) -> bytes:
    if (
        offset < minimum_offset
        or offset % _WORD_SIZE != 0
        or offset + _WORD_SIZE > len(data)
    ):
        raise ABIError("invalid ABI dynamic offset")
    length = _decode_uint(data[offset : offset + _WORD_SIZE])
    start = offset + _WORD_SIZE
    end = start + length
    if end > len(data):
        raise ABIError("ABI dynamic value exceeds output")
    return data[start:end]


def _word(value: int | bytes) -> bytes:
    if isinstance(value, int):
        if value < 0 or value > _UINT256_MAX:
            raise ABIError("integer does not fit in an ABI word")
        return value.to_bytes(_WORD_SIZE, "big")
    if isinstance(value, bytes):
        if len(value) > _WORD_SIZE:
            raise ABIError("bytes value is longer than an ABI word")
        return (b"\x00" * (_WORD_SIZE - len(value))) + value
    raise ABIError("ABI word must be an integer or bytes")


def _decode_uint(word: bytes) -> int:
    if len(word) != _WORD_SIZE:
        raise ABIError("ABI word must contain exactly 32 bytes")
    return int.from_bytes(word, "big")
