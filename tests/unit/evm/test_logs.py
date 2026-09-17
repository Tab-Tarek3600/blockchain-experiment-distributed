"""Tests de conversion et de transport des événements EVM."""

from __future__ import annotations

import json

import pytest

from src.evm.abi import ABIError, encode_function_call
from src.evm.logs import EVMLog
from src.evm.receipt import Receipt
from src.evm.state import EVMState

TX_ID = b"\x11" * 32
ADDRESS = b"\xaa" * 20
TOPIC = b"\xbb" * 32


def test_log_est_immuable_et_serialisable():
    log = EVMLog(address=ADDRESS, topics=(TOPIC,), data=b"payload")

    assert json.loads(json.dumps(log.to_dict())) == {
        "address": ADDRESS.hex(),
        "topics": [TOPIC.hex()],
        "data": "payload".encode().hex(),
    }
    assert EVMLog.from_dict(log.to_dict()) == log
    with pytest.raises(Exception):
        log.data = b"other"  # type: ignore[misc]


def test_receipt_transporte_les_logs_dans_l_ordre():
    logs = (
        EVMLog(address=ADDRESS, topics=(TOPIC,), data=b"one"),
        EVMLog(address=ADDRESS, topics=(), data=b"two"),
    )
    receipt = Receipt.success(tx_id=TX_ID, gas_used=1, logs=logs)

    assert Receipt.from_dict(receipt.to_dict()) == receipt
    assert receipt.to_dict()["logs"][0]["data"] == "one".encode().hex()


def test_receipt_en_echec_ne_peut_pas_conserver_de_log():
    with pytest.raises(ValueError, match="failed receipt cannot carry logs"):
        Receipt(
            tx_id=TX_ID,
            status=0,
            gas_used=1,
            logs=(EVMLog(address=ADDRESS, topics=(), data=b"x"),),
        )


def test_state_convertit_les_topics_py_evm_en_mots_de_32_octets():
    class Computation:
        is_error = False
        output = b""

        def get_log_entries(self):
            return ((ADDRESS, (1, 2**255), b"data"),)

        def get_gas_used(self):
            return 3

    outcome = EVMState._to_outcome(Computation())

    assert outcome.succeeded
    assert outcome.logs == (
        EVMLog(
            address=ADDRESS,
            topics=(b"\x00" * 31 + b"\x01", b"\x80" + b"\x00" * 31),
            data=b"data",
        ),
    )


def test_abi_refuse_un_type_non_supporte():
    with pytest.raises(ABIError, match="unsupported ABI type"):
        encode_function_call("f(string)", ("medical",))
