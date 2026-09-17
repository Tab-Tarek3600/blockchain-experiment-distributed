"""
Tests unitaires de NodeConfig.
"""

import pytest
import yaml

from src.crypto.address import public_key_to_address
from src.node.config import (
    DEFAULT_BLOCK_INTERVAL_SECONDS,
    DEFAULT_GENESIS_TIMESTAMP,
    DEFAULT_MEMPOOL_MAX_SIZE,
    DEFAULT_ROUND_TIMEOUT_SECONDS,
    ConfigError,
    NodeConfig,
)

# --- en-tete corrige -------------------------------------------------
#
# public_key_to_address() est un SHA-256 tronque : il n'effectue aucune
# validation cryptographique de la cle. Ces tests de configuration
# n'ont donc pas besoin de generer une vraie paire ML-DSA (ni de
# charger liboqs) ; des octets deterministes de la bonne taille
# suffisent, et ADDRESS_A en est l'adresse derivee.

ML_DSA_44_PUBLIC_KEY_LENGTH = 1312

GENESIS_PUBLIC_KEY = bytes(
    i % 256 for i in range(ML_DSA_44_PUBLIC_KEY_LENGTH)
)

GENESIS_PUBLIC_KEY_HEX = GENESIS_PUBLIC_KEY.hex()

# authorized_validators[0] doit etre l'adresse derivee de la cle genesis.
ADDRESS_A = public_key_to_address(GENESIS_PUBLIC_KEY).hex()
ADDRESS_B = "bb" * 20
ADDRESS_C = "cc" * 20


def make_valid_config_dict(**overrides):
    data = {
        "node_id": "node1",
        "node_name": "Node 1",
        "data_dir": "data/node1",
        "host": "127.0.0.1",
        "port": 5001,
        "peers": [{"host": "127.0.0.1", "port": 5002}],
        "validator_key_dir": "keys/node1",
        "authorized_validators": [ADDRESS_A, ADDRESS_B, ADDRESS_C],
        "genesis_validator_public_key": GENESIS_PUBLIC_KEY_HEX,
        "genesis_timestamp": 1_700_000_000,
        "mempool_max_size": 500,
        "block_interval_seconds": 3.0,
        "round_timeout_seconds": 4.0,
    }
    data.update(overrides)
    return data


# --- tests -----------------------------------------------------------


def test_from_dict_parses_valid_config():
    config = NodeConfig.from_dict(make_valid_config_dict())
    assert config.node_id == "node1"
    assert config.port == 5001
    assert config.genesis_validator_public_key == GENESIS_PUBLIC_KEY


def test_from_dict_applies_defaults_when_optional_fields_missing():
    data = make_valid_config_dict()
    del data["genesis_timestamp"]
    del data["mempool_max_size"]
    del data["block_interval_seconds"]
    del data["round_timeout_seconds"]

    config = NodeConfig.from_dict(data)
    assert config.genesis_timestamp == DEFAULT_GENESIS_TIMESTAMP
    assert config.mempool_max_size == DEFAULT_MEMPOOL_MAX_SIZE
    assert config.block_interval_seconds == DEFAULT_BLOCK_INTERVAL_SECONDS
    assert config.round_timeout_seconds == DEFAULT_ROUND_TIMEOUT_SECONDS


def test_from_dict_allows_empty_peers_list():
    data = make_valid_config_dict(peers=[])
    config = NodeConfig.from_dict(data)
    assert config.peers == ()


def test_from_dict_accepts_int_block_interval():
    data = make_valid_config_dict(block_interval_seconds=10)
    config = NodeConfig.from_dict(data)
    assert config.block_interval_seconds == 10


def test_from_dict_rejects_missing_node_id():
    data = make_valid_config_dict()
    del data["node_id"]
    with pytest.raises(ConfigError, match="node_id"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_missing_authorized_validators():
    data = make_valid_config_dict()
    del data["authorized_validators"]
    with pytest.raises(ConfigError, match="authorized_validators"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_string_port():
    data = make_valid_config_dict(port="5001")
    with pytest.raises(ConfigError, match="port"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_bool_port():
    data = make_valid_config_dict(port=True)
    with pytest.raises(ConfigError, match="port"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_out_of_range_port():
    data = make_valid_config_dict(port=70000)
    with pytest.raises(ConfigError, match="port"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_zero_port():
    data = make_valid_config_dict(port=0)
    with pytest.raises(ConfigError, match="port"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_string_mempool_size():
    data = make_valid_config_dict(mempool_max_size="500")
    with pytest.raises(ConfigError, match="mempool_max_size"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_bool_mempool_size():
    data = make_valid_config_dict(mempool_max_size=True)
    with pytest.raises(ConfigError, match="mempool_max_size"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_zero_mempool_size():
    data = make_valid_config_dict(mempool_max_size=0)
    with pytest.raises(ConfigError, match="mempool_max_size"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_string_genesis_timestamp():
    data = make_valid_config_dict(genesis_timestamp="1700000000")
    with pytest.raises(ConfigError, match="genesis_timestamp"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_bool_genesis_timestamp():
    data = make_valid_config_dict(genesis_timestamp=False)
    with pytest.raises(ConfigError, match="genesis_timestamp"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_negative_genesis_timestamp():
    data = make_valid_config_dict(genesis_timestamp=-1)
    with pytest.raises(ConfigError, match="genesis_timestamp"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_zero_block_interval():
    data = make_valid_config_dict(block_interval_seconds=0)
    with pytest.raises(ConfigError, match="block_interval_seconds"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_bool_block_interval():
    data = make_valid_config_dict(block_interval_seconds=True)
    with pytest.raises(ConfigError, match="block_interval_seconds"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_zero_round_timeout():
    data = make_valid_config_dict(round_timeout_seconds=0)
    with pytest.raises(ConfigError, match="round_timeout_seconds"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_bool_round_timeout():
    data = make_valid_config_dict(round_timeout_seconds=True)
    with pytest.raises(ConfigError, match="round_timeout_seconds"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_invalid_host():
    data = make_valid_config_dict(host="")
    with pytest.raises(ConfigError, match="host"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_non_string_host():
    data = make_valid_config_dict(host=127001)
    with pytest.raises(ConfigError, match="host"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_empty_authorized_validators():
    data = make_valid_config_dict(authorized_validators=[])
    with pytest.raises(ConfigError, match="authorized_validators"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_wrong_length_validator_address():
    data = make_valid_config_dict(authorized_validators=["aa" * 5])
    with pytest.raises(ConfigError, match="authorized_validators"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_duplicate_validator_addresses():
    data = make_valid_config_dict(authorized_validators=[ADDRESS_A, ADDRESS_A])
    with pytest.raises(ConfigError, match="duplicate"):
        NodeConfig.from_dict(data)


def test_from_dict_rejects_empty_node_id():
    data = make_valid_config_dict(node_id="")
    with pytest.raises(ConfigError, match="node_id"):
        NodeConfig.from_dict(data)


def test_from_file_loads_valid_yaml(tmp_path):
    config_path = tmp_path / "node1.yaml"
    config_path.write_text(yaml.dump(make_valid_config_dict()), encoding="utf-8")

    config = NodeConfig.from_file(config_path)
    assert config.node_id == "node1"


def test_to_dict_from_dict_round_trip():
    config = NodeConfig.from_dict(make_valid_config_dict())
    restored = NodeConfig.from_dict(config.to_dict())
    assert restored == config
    assert restored.genesis_validator_public_key == GENESIS_PUBLIC_KEY


# --- nouveau test de la convention genesis ---------------------------


def test_from_dict_rejects_genesis_key_not_matching_first_validator():
    other_key = bytes(ML_DSA_44_PUBLIC_KEY_LENGTH)
    data = make_valid_config_dict(
        genesis_validator_public_key=other_key.hex()
    )
    with pytest.raises(ConfigError, match="authorized_validators\\[0\\]"):
        NodeConfig.from_dict(data)
