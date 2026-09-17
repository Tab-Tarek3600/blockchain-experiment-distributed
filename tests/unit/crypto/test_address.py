import pytest

from src.crypto.address import (
    ADDRESS_LENGTH,
    AddressError,
    address_to_hex,
    hex_to_address,
    is_valid_address,
    public_key_to_address,
)


def test_public_key_to_address_returns_correct_length():
    address = public_key_to_address(b"some-public-key")
    assert len(address) == ADDRESS_LENGTH


def test_public_key_to_address_is_deterministic():
    pk = b"same-public-key"
    assert public_key_to_address(pk) == public_key_to_address(pk)


def test_public_key_to_address_differs_for_different_keys():
    assert public_key_to_address(b"key-a") != public_key_to_address(b"key-b")


def test_public_key_to_address_rejects_empty_key():
    with pytest.raises(AddressError):
        public_key_to_address(b"")


def test_public_key_to_address_rejects_non_bytes():
    with pytest.raises(AddressError):
        public_key_to_address("not-bytes")


def test_address_to_hex_roundtrip():
    address = public_key_to_address(b"some-public-key")
    hex_address = address_to_hex(address)

    assert hex_address.startswith("0x")
    assert hex_to_address(hex_address) == address


def test_address_to_hex_rejects_wrong_length():
    with pytest.raises(AddressError):
        address_to_hex(b"\x00" * 5)


def test_hex_to_address_rejects_missing_prefix():
    with pytest.raises(AddressError):
        hex_to_address("00" * ADDRESS_LENGTH)


def test_hex_to_address_rejects_invalid_hex():
    with pytest.raises(AddressError):
        hex_to_address("0x" + "zz" * ADDRESS_LENGTH)


def test_hex_to_address_rejects_wrong_length():
    with pytest.raises(AddressError):
        hex_to_address("0x" + "00" * (ADDRESS_LENGTH - 1))


def test_is_valid_address_true_for_correct_address():
    address = public_key_to_address(b"some-public-key")
    assert is_valid_address(address) is True


def test_is_valid_address_false_for_wrong_length():
    assert is_valid_address(b"\x00" * 5) is False


def test_is_valid_address_false_for_non_bytes():
    assert is_valid_address("not-bytes") is False