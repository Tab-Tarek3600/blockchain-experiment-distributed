import pytest

from src.crypto.serialization import (
    SerializationError,
    encode_bytes,
    encode_fields,
    encode_uint,
)


def test_encode_uint_produces_fixed_length_output():
    result = encode_uint(5, 8)
    assert len(result) == 8
    assert result == (5).to_bytes(8, "big")


def test_encode_uint_rejects_negative_value():
    with pytest.raises(SerializationError):
        encode_uint(-1, 8)


def test_encode_uint_rejects_non_integer():
    with pytest.raises(SerializationError):
        encode_uint("5", 8)


def test_encode_uint_rejects_value_too_large_for_length():
    with pytest.raises(SerializationError):
        encode_uint(2**64, 8)


def test_encode_bytes_prefixes_length():
    data = b"hello"
    result = encode_bytes(data)

    length_prefix = result[:8]
    payload = result[8:]

    assert int.from_bytes(length_prefix, "big") == len(data)
    assert payload == data


def test_encode_bytes_rejects_non_bytes():
    with pytest.raises(SerializationError):
        encode_bytes("not-bytes")


def test_encode_fields_concatenates_in_order():
    field_a = encode_bytes(b"aa")
    field_b = encode_bytes(b"bb")

    assert encode_fields(field_a, field_b) == field_a + field_b


def test_encode_fields_is_order_sensitive():
    field_a = encode_bytes(b"aa")
    field_b = encode_bytes(b"bb")

    assert encode_fields(field_a, field_b) != encode_fields(field_b, field_a)


def test_encode_fields_rejects_non_bytes_field():
    with pytest.raises(SerializationError):
        encode_fields(b"ok", "not-bytes")