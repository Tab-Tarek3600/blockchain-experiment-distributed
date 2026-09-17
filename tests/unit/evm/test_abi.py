"""Tests de l'encodeur ABI utilisé par les contrats PHASE 4."""

from __future__ import annotations

import pytest

from src.evm.abi import (
    ABIError,
    decode_function_output,
    encode_function_call,
    function_selector,
)


def test_selecteur_est_deterministe_et_long_de_quatre_octets():
    assert function_selector("isRegistered(bytes32)") == function_selector(
        "isRegistered(bytes32)"
    )
    assert len(function_selector("isRegistered(bytes32)")) == 4


def test_encode_static_and_dynamic_arguments():
    patient_id = b"\x01" * 32
    caller = b"\x02" * 20
    data = encode_function_call(
        "grantConsent(bytes32,address,bytes32,uint256)",
        (patient_id, caller, b"\x03" * 32, 1_700_000_000),
    )

    assert data[:4] == function_selector(
        "grantConsent(bytes32,address,bytes32,uint256)"
    )
    assert len(data) == 4 + 32 * 4
    assert data[4 + 32 + 12 : 4 + 64] == caller


def test_encode_bytes_place_un_offset_dans_la_tete():
    encoded = encode_function_call("f(bytes,bytes32)", (b"abc", b"\x01" * 32))

    assert int.from_bytes(encoded[4:36], "big") == 64
    assert encoded[4 + 32 : 4 + 64] == b"\x01" * 32
    assert int.from_bytes(encoded[4 + 64 : 4 + 96], "big") == 3
    assert encoded[4 + 96 : 4 + 99] == b"abc"


def test_decode_output_mixed_static_dynamic():
    dynamic = b"cid"
    encoded = (
        (42).to_bytes(32, "big")
        + (96).to_bytes(32, "big")
        + (1).to_bytes(32, "big")
        + len(dynamic).to_bytes(32, "big")
        + dynamic
        + b"\x00" * 29
    )

    assert decode_function_output(("uint256", "bytes", "bool"), encoded) == (
        42,
        dynamic,
        True,
    )


def test_decode_rejette_une_sortie_trop_courte():
    with pytest.raises(ABIError, match="shorter"):
        decode_function_output(("uint256",), b"\x00")
