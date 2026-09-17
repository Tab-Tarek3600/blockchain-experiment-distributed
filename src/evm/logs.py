"""Types natifs pour les logs d'exécution EVM.

Le type py-evm ne franchit pas la frontière de ``src.evm.state``. Les
événements Solidity sont donc convertis ici en bytes canoniques : une adresse
de 20 octets, des topics de 32 octets et des données binaires.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.evm.addresses import validate_address


@dataclass(frozen=True)
class EVMLog:
    """Un événement EVM indépendant de py-evm."""

    address: bytes
    topics: tuple[bytes, ...]
    data: bytes

    def __post_init__(self) -> None:
        validate_address(self.address, "log address")
        if not isinstance(self.topics, tuple):
            raise ValueError("log topics must be a tuple")
        for topic in self.topics:
            if not isinstance(topic, bytes) or len(topic) != 32:
                raise ValueError("each log topic must contain exactly 32 bytes")
        if not isinstance(self.data, bytes):
            raise ValueError("log data must be bytes")

    def to_dict(self) -> dict[str, Any]:
        """Représentation JSON-friendly et déterministe."""
        return {
            "address": self.address.hex(),
            "topics": [topic.hex() for topic in self.topics],
            "data": self.data.hex(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EVMLog":
        """Reconstruit un log depuis sa représentation sérialisée."""
        try:
            topics = data["topics"]
            if not isinstance(topics, list):
                raise ValueError("topics must be a list")
            return cls(
                address=bytes.fromhex(data["address"]),
                topics=tuple(bytes.fromhex(topic) for topic in topics),
                data=bytes.fromhex(data.get("data", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid EVM log dict: {exc}") from exc

    def __repr__(self) -> str:
        return (
            f"EVMLog(address=0x{self.address.hex()}, "
            f"topics={len(self.topics)}, data={len(self.data)} bytes)"
        )
