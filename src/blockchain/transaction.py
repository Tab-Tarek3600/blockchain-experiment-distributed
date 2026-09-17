"""
Transaction — objet de données passif.

Une Transaction ne connaît rien de ML-DSA. Elle sait uniquement :
    - se sérialiser de façon canonique (to_bytes, pour signing_hash/tx_id)
    - se sérialiser pour le stockage/réseau (to_dict/from_dict)
    - calculer le hash à signer (signing_hash)
    - calculer son identifiant complet (tx_id)
    - valider sa propre structure

Le flux de signature vit à l'extérieur :

    tx = Transaction.create(...)
    signature = mldsa.sign(tx.signing_hash, secret_key)
    signed_tx = tx.with_signature(signature)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from src.crypto.address import ADDRESS_LENGTH, AddressError, public_key_to_address
from src.crypto.hash import sha256
from src.crypto.serialization import encode_bytes, encode_fields, encode_uint

NONCE_SIZE = 8
GAS_LIMIT_SIZE = 8
VALUE_SIZE = 32
GAS_PRICE_SIZE = 32

MAX_DATA_SIZE = 1024 * 1024


class TransactionError(Exception):
    """Raised when a transaction is structurally invalid."""


@dataclass(frozen=True)
class Transaction:
    nonce: int
    sender: bytes
    recipient: bytes
    value: int
    gas_limit: int
    gas_price: int
    data: bytes
    public_key: bytes
    signature: Optional[bytes] = None

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def create(
        cls,
        nonce: int,
        public_key: bytes,
        recipient: bytes,
        value: int,
        gas_limit: int,
        gas_price: int,
        data: bytes = b"",
    ) -> "Transaction":
        try:
            sender = public_key_to_address(public_key)
        except AddressError as exc:
            raise TransactionError(str(exc)) from exc

        return cls(
            nonce=nonce,
            sender=sender,
            recipient=recipient,
            value=value,
            gas_limit=gas_limit,
            gas_price=gas_price,
            data=data,
            public_key=public_key,
            signature=None,
        )

    def with_signature(self, signature: bytes) -> "Transaction":
        if not isinstance(signature, bytes):
            raise TransactionError("signature must be bytes")

        if not signature:
            raise TransactionError("signature must not be empty")

        return replace(self, signature=signature)

    def to_bytes(self, include_signature: bool = True) -> bytes:
        fields = [
            encode_uint(self.nonce, NONCE_SIZE),
            encode_bytes(self.sender),
            encode_bytes(self.recipient),
            encode_uint(self.value, VALUE_SIZE),
            encode_uint(self.gas_limit, GAS_LIMIT_SIZE),
            encode_uint(self.gas_price, GAS_PRICE_SIZE),
            encode_bytes(self.data),
            encode_bytes(self.public_key),
        ]

        if include_signature:
            fields.append(encode_bytes(self.signature or b""))

        return encode_fields(*fields)

    @property
    def signing_hash(self) -> bytes:
        return sha256(self.to_bytes(include_signature=False))

    @property
    def tx_id(self) -> bytes:
        return sha256(self.to_bytes(include_signature=True))

    @property
    def is_signed(self) -> bool:
        return self.signature is not None

    def validate(self) -> None:
        self._validate_int_field("nonce", self.nonce)
        self._validate_int_field("value", self.value)
        self._validate_int_field("gas_limit", self.gas_limit)
        self._validate_int_field("gas_price", self.gas_price)

        self._validate_address_field("sender", self.sender)
        self._validate_address_field("recipient", self.recipient)

        if not isinstance(self.data, bytes):
            raise TransactionError("data must be bytes")

        if len(self.data) > MAX_DATA_SIZE:
            raise TransactionError(
                f"data exceeds maximum size of {MAX_DATA_SIZE} bytes"
            )

        if not isinstance(self.public_key, bytes) or not self.public_key:
            raise TransactionError("public_key must be non-empty bytes")

        try:
            expected_sender = public_key_to_address(self.public_key)
        except AddressError as exc:
            raise TransactionError(str(exc)) from exc

        if self.sender != expected_sender:
            raise TransactionError(
                "sender does not match the address derived from public_key"
            )

        if self.signature is not None:
            if not isinstance(self.signature, bytes) or not self.signature:
                raise TransactionError(
                    "signature must be non-empty bytes when present"
                )

    @staticmethod
    def _validate_int_field(name: str, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TransactionError(f"{name} must be an integer")
        if value < 0:
            raise TransactionError(f"{name} must be >= 0")

    @staticmethod
    def _validate_address_field(name: str, value: object) -> None:
        if not isinstance(value, bytes):
            raise TransactionError(f"{name} must be bytes")
        if len(value) != ADDRESS_LENGTH:
            raise TransactionError(
                f"{name} must contain exactly {ADDRESS_LENGTH} bytes"
            )

    # -- Serialisation pour stockage / reseau (distincte de to_bytes) ----

    def to_dict(self) -> dict[str, Any]:
        """
        Representation JSON-friendly de la transaction, utilisee pour
        la persistance sur disque et la diffusion reseau. Distincte de
        to_bytes(), qui sert uniquement au hash/signature canonique.
        """
        return {
            "nonce": self.nonce,
            "sender": self.sender.hex(),
            "recipient": self.recipient.hex(),
            "value": self.value,
            "gas_limit": self.gas_limit,
            "gas_price": self.gas_price,
            "data": self.data.hex(),
            "public_key": self.public_key.hex(),
            "signature": self.signature.hex() if self.signature is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transaction":
        """
        Reconstruit une Transaction depuis sa representation dict.

        La reconstruction passe par le constructeur direct, ce qui
        declenche automatiquement __post_init__ -> validate(). Toute
        donnee corrompue ou incoherente (ex: sender ne correspondant
        pas a public_key) leve TransactionError.
        """
        try:
            signature_hex = data.get("signature")
            return cls(
                nonce=data["nonce"],
                sender=bytes.fromhex(data["sender"]),
                recipient=bytes.fromhex(data["recipient"]),
                value=data["value"],
                gas_limit=data["gas_limit"],
                gas_price=data["gas_price"],
                data=bytes.fromhex(data["data"]),
                public_key=bytes.fromhex(data["public_key"]),
                signature=bytes.fromhex(signature_hex) if signature_hex else None,
            )
        except KeyError as exc:
            raise TransactionError(f"missing field in transaction dict: {exc}") from exc
        except ValueError as exc:
            raise TransactionError(f"invalid hex field in transaction dict: {exc}") from exc
