"""
Node configuration.

NodeConfig holds pure configuration data for a single node: network
identity, storage location, PoA validator set, and simple numeric
parameters (mempool size, block interval, proposal-round timeout).

Genesis convention (network-wide shared configuration):
    All nodes in the same PoA network must produce an identical
    genesis block. To ensure this, the genesis validator public key
    is part of the shared network configuration (alongside
    genesis_timestamp and authorized_validators), not derived from
    the local node's validator key.

    By convention, genesis_validator_public_key must derive to
    authorized_validators[0] (the first PoA validator address).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
from src.crypto.ml_dsa import MLDSA, MLDSAKeyPair

DEFAULT_MEMPOOL_MAX_SIZE = 1000
DEFAULT_BLOCK_INTERVAL_SECONDS = 5.0
# Kept separate from the production polling interval so a deployment can
# tune failover independently. When omitted in an old config, the block
# interval is used for backwards-compatible behaviour.
DEFAULT_ROUND_TIMEOUT_SECONDS = 5.0
DEFAULT_GENESIS_TIMESTAMP = 1_700_000_000

VALIDATOR_PUBLIC_KEY_FILENAME = "validator_public_key.bin"
VALIDATOR_SECRET_KEY_FILENAME = "validator_secret_key.bin"

EXPECTED_PUBLIC_KEY_SIZE = 1312
EXPECTED_SECRET_KEY_SIZE = 2560


class ConfigError(Exception):
    """Raised when a node configuration is missing or invalid."""


@dataclass(frozen=True)
class PeerConfig:
    """Network address of a peer node. Pure data, no connection logic."""

    host: str
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host:
            raise ConfigError("peers[*].host must be a non-empty string")
        _validate_port("peers[*].port", self.port)


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    node_name: str
    data_dir: Path
    host: str
    port: int
    peers: tuple[PeerConfig, ...]
    validator_key_dir: Path
    authorized_validators: tuple[bytes, ...]
    genesis_validator_public_key: bytes
    genesis_timestamp: int
    mempool_max_size: int
    block_interval_seconds: float
    round_timeout_seconds: float

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id:
            raise ConfigError("node_id must be a non-empty string")

        if not isinstance(self.node_name, str) or not self.node_name:
            raise ConfigError("node_name must be a non-empty string")

        if not isinstance(self.host, str) or not self.host:
            raise ConfigError("host must be a non-empty string")

        _validate_port("port", self.port)

        if not isinstance(self.authorized_validators, tuple) or not self.authorized_validators:
            raise ConfigError("authorized_validators must not be empty")

        for i, address in enumerate(self.authorized_validators):
            if not isinstance(address, bytes) or len(address) != ADDRESS_LENGTH:
                raise ConfigError(
                    f"authorized_validators[{i}] must be exactly "
                    f"{ADDRESS_LENGTH} bytes"
                )

        if len(set(self.authorized_validators)) != len(self.authorized_validators):
            raise ConfigError("authorized_validators must not contain duplicates")

        if not isinstance(self.genesis_validator_public_key, bytes) or not self.genesis_validator_public_key:
            raise ConfigError("genesis_validator_public_key must be non-empty bytes")

        try:
            genesis_address = public_key_to_address(self.genesis_validator_public_key)
        except Exception as exc:
            raise ConfigError(f"invalid genesis_validator_public_key: {exc}") from exc

        if genesis_address != self.authorized_validators[0]:
            raise ConfigError(
                "genesis_validator_public_key must derive to authorized_validators[0] "
                f"(expected {self.authorized_validators[0].hex()}, "
                f"got {genesis_address.hex()})"
            )

        if (
            isinstance(self.mempool_max_size, bool)
            or not isinstance(self.mempool_max_size, int)
            or self.mempool_max_size <= 0
        ):
            raise ConfigError("mempool_max_size must be a positive integer")

        if (
            isinstance(self.block_interval_seconds, bool)
            or not isinstance(self.block_interval_seconds, (int, float))
            or self.block_interval_seconds <= 0
        ):
            raise ConfigError("block_interval_seconds must be a positive number")

        if (
            isinstance(self.round_timeout_seconds, bool)
            or not isinstance(self.round_timeout_seconds, (int, float))
            or self.round_timeout_seconds <= 0
        ):
            raise ConfigError("round_timeout_seconds must be a positive number")

        if (
            isinstance(self.genesis_timestamp, bool)
            or not isinstance(self.genesis_timestamp, int)
            or self.genesis_timestamp < 0
        ):
            raise ConfigError("genesis_timestamp must be a non-negative integer")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeConfig":
        try:
            peers = tuple(
                PeerConfig(host=peer["host"], port=peer["port"])
                for peer in data.get("peers", [])
            )

            authorized_validators = tuple(
                bytes.fromhex(address)
                for address in data["authorized_validators"]
            )

            genesis_validator_public_key = bytes.fromhex(data["genesis_validator_public_key"])

            return cls(
                node_id=data["node_id"],
                node_name=data["node_name"],
                data_dir=Path(data["data_dir"]),
                host=data["host"],
                port=data["port"],
                peers=peers,
                validator_key_dir=Path(data["validator_key_dir"]),
                authorized_validators=authorized_validators,
                genesis_validator_public_key=genesis_validator_public_key,
                genesis_timestamp=data.get("genesis_timestamp", DEFAULT_GENESIS_TIMESTAMP),
                mempool_max_size=data.get("mempool_max_size", DEFAULT_MEMPOOL_MAX_SIZE),
                block_interval_seconds=data.get(
                    "block_interval_seconds", DEFAULT_BLOCK_INTERVAL_SECONDS
                ),
                round_timeout_seconds=data.get(
                    "round_timeout_seconds",
                    data.get("block_interval_seconds", DEFAULT_ROUND_TIMEOUT_SECONDS),
                ),
            )
        except KeyError as exc:
            raise ConfigError(f"missing required config field: {exc}") from exc
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"invalid config field: {exc}") from exc

    @classmethod
    def from_file(cls, path: str | Path) -> "NodeConfig":
        path = Path(path)

        if not path.exists():
            raise ConfigError(f"config file not found: {path}")

        try:
            raw = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"failed to read config file {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError(f"config file {path} does not contain a mapping")

        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "data_dir": str(self.data_dir),
            "host": self.host,
            "port": self.port,
            "peers": [{"host": p.host, "port": p.port} for p in self.peers],
            "validator_key_dir": str(self.validator_key_dir),
            "authorized_validators": [addr.hex() for addr in self.authorized_validators],
            "genesis_validator_public_key": self.genesis_validator_public_key.hex(),
            "genesis_timestamp": self.genesis_timestamp,
            "mempool_max_size": self.mempool_max_size,
            "block_interval_seconds": self.block_interval_seconds,
            "round_timeout_seconds": self.round_timeout_seconds,
        }


def _validate_port(name: str, port: object) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not (0 < port <= 65535):
        raise ConfigError(
            f"{name} must be an integer between 1 and 65535, got {port!r}"
        )


def load_or_generate_validator_keys(
    key_dir: str | Path,
    ml_dsa: Optional[MLDSA] = None,
) -> MLDSAKeyPair:
    key_dir = Path(key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)

    public_key_path = key_dir / VALIDATOR_PUBLIC_KEY_FILENAME
    secret_key_path = key_dir / VALIDATOR_SECRET_KEY_FILENAME

    public_exists = public_key_path.exists()
    secret_exists = secret_key_path.exists()

    if public_exists != secret_exists:
        raise ConfigError(
            f"inconsistent validator key files in {key_dir}: "
            "only one of public/secret key file exists"
        )

    if public_exists and secret_exists:
        public_key = public_key_path.read_bytes()
        secret_key = secret_key_path.read_bytes()

        if len(public_key) != EXPECTED_PUBLIC_KEY_SIZE:
            raise ConfigError(
                f"validator public key file has unexpected size "
                f"({len(public_key)} bytes, expected {EXPECTED_PUBLIC_KEY_SIZE})"
            )

        if len(secret_key) != EXPECTED_SECRET_KEY_SIZE:
            raise ConfigError(
                f"validator secret key file has unexpected size "
                f"({len(secret_key)} bytes, expected {EXPECTED_SECRET_KEY_SIZE})"
            )

        return MLDSAKeyPair(public_key=public_key, secret_key=secret_key)

    signer = ml_dsa or MLDSA()
    keypair = signer.generate_keypair()

    public_key_path.write_bytes(keypair.public_key)
    secret_key_path.write_bytes(keypair.secret_key)

    return keypair
