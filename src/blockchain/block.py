"""
Block — objet de données passif, sur le même modèle que Transaction.

Un Block ne connaît rien de ML-DSA. Il sait uniquement :
    - contenir des transactions déjà signées
    - porter le round de proposition (inclus dans la signature)
    - dériver l'adresse du validateur depuis sa clé publique
    - calculer transactions_root
    - se sérialiser de manière canonique (to_bytes, pour signing_hash/block_hash)
    - se sérialiser pour le stockage/réseau (to_dict/from_dict)
    - recevoir une signature externe via with_signature()
    - valider sa propre structure

Flux de signature, strictement identique à Transaction :

    block = Block.create(...)          # bloc non signé
    signature = mldsa.sign(block.signing_hash, secret_key)
    signed_block = block.with_signature(signature)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional, Sequence

from src.blockchain.transaction import Transaction, TransactionError
from src.crypto.address import ADDRESS_LENGTH, AddressError, public_key_to_address
from src.crypto.hash import sha256
from src.crypto.serialization import encode_bytes, encode_fields, encode_uint

BLOCK_HEIGHT_SIZE = 8       # uint64
BLOCK_ROUND_SIZE = 8        # uint64
TIMESTAMP_SIZE = 8          # uint64
TRANSACTION_COUNT_SIZE = 8  # uint64
HASH_SIZE = 32

MAX_TRANSACTIONS = 10_000

ZERO_HASH = b"\x00" * HASH_SIZE


#: Racine d'un etat EVM vide (trie vierge). Valeur figee ici plutot
#: qu'importee de src/evm/state.py : src/blockchain/ ne doit dependre
#: ni de la couche EVM ni de py-evm, sans quoi un noeud ne pourrait
#: plus relire un bloc sans py-evm installe. L'egalite des deux
#: constantes est verifiee cote tests EVM.
EMPTY_STATE_ROOT = bytes.fromhex(
    "56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
)


class BlockError(Exception):
    """Raised when a block is structurally invalid."""


def calculate_merkle_root(transactions: Sequence[Transaction]) -> bytes:
    """
    Return a deterministic aggregate hash of the ordered transaction IDs.

    NOTE — this is NOT a cryptographic Merkle tree. There is no pairwise
    hashing and no tree structure: it is a flat SHA-256 over the
    concatenation of tx_ids (via encode_fields). It only provides:
        - determinism (same tx set + same order => same root)
        - sensitivity to any change in content or order

    It does NOT provide Merkle proofs (no O(log n) inclusion proof).
    Should be described as "transactions_root" (not "Merkle root") in
    any report or documentation, to avoid overstating what it proves.
    """
    if not transactions:
        return ZERO_HASH

    return sha256(
        encode_fields(*(transaction.tx_id for transaction in transactions))
    )


@dataclass(frozen=True)
class Block:
    height: int
    previous_block_hash: bytes
    timestamp: int
    transactions: tuple[Transaction, ...]
    validator: bytes
    validator_public_key: bytes
    # Round is part of the signed block identity. Round 0 preserves the
    # original schedule; a higher round selects the next validator after a
    # proposal timeout at the same height.
    round: int = 0
    state_root: bytes = EMPTY_STATE_ROOT
    signature: Optional[bytes] = None

    def __post_init__(self) -> None:
        if not isinstance(self.transactions, tuple):
            object.__setattr__(self, "transactions", tuple(self.transactions))

        self.validate_structure()

    # -- Construction --------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        height: int,
        previous_block_hash: bytes,
        timestamp: int,
        transactions: Sequence[Transaction],
        validator_public_key: bytes,
        round: int = 0,
        state_root: bytes = EMPTY_STATE_ROOT,
    ) -> "Block":
        """
        Construit un bloc NON SIGNE. `validator` est derive
        automatiquement de `validator_public_key`, sur le meme principe
        que sender/public_key dans Transaction.

        Pour signer un bloc, utiliser with_signature() apres creation
        -- Block.create() ne prend jamais de signature en parametre.
        """
        try:
            validator = public_key_to_address(validator_public_key)
        except AddressError as exc:
            raise BlockError(str(exc)) from exc

        return cls(
            height=height,
            previous_block_hash=previous_block_hash,
            timestamp=timestamp,
            transactions=tuple(transactions),
            validator=validator,
            validator_public_key=validator_public_key,
            round=round,
            state_root=state_root,
            signature=None,
        )

    def with_signature(self, signature: bytes) -> "Block":
        """
        Retourne un NOUVEAU Block avec la signature attachee.
        L'instance originale reste inchangee (immutabilite).
        """
        if not isinstance(signature, bytes):
            raise BlockError("signature must be bytes")

        if not signature:
            raise BlockError("signature must not be empty")

        return replace(self, signature=signature)

    # -- Proprietes derivees --------------------------------------------

    @property
    def is_signed(self) -> bool:
        return self.signature is not None

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def transactions_root(self) -> bytes:
        """
        Racine derivee des tx_id de toutes les transactions du bloc.
        Jamais stockee : toujours recalculee pour eviter toute
        incoherence entre les transactions reelles et une racine
        declaree separement.
        """
        return calculate_merkle_root(self.transactions)

    # -- Serialisation canonique (hash/signature) ------------------------

    def to_bytes(self, *, include_signature: bool = True) -> bytes:
        """
        Serialisation canonique du bloc.

        include_signature=False -> representation "non signee", c'est
        exactement ce qui est hache pour produire signing_hash.
        include_signature=True  -> representation complete, utilisee
        pour block_hash.
        """
        fields = [
            encode_uint(self.height, BLOCK_HEIGHT_SIZE),
            encode_uint(self.round, BLOCK_ROUND_SIZE),
            encode_bytes(self.previous_block_hash),
            encode_uint(self.timestamp, TIMESTAMP_SIZE),
            encode_uint(self.transaction_count, TRANSACTION_COUNT_SIZE),
            encode_bytes(self.transactions_root),
            encode_bytes(self.validator),
            encode_bytes(self.validator_public_key),
            encode_bytes(self.state_root),
        ]

        if include_signature:
            fields.append(encode_bytes(self.signature or b""))

        return encode_fields(*fields)

    # -- Hash ---------------------------------------------------------------

    @property
    def signing_hash(self) -> bytes:
        """
        Hash du contenu NON signe -- c'est ce message que ML-DSA doit
        signer. Reste identique avant et apres with_signature().
        """
        return sha256(self.to_bytes(include_signature=False))

    @property
    def block_hash(self) -> bytes:
        """
        Identifiant complet du bloc, incluant la signature si elle
        est presente. Change de valeur au moment ou le bloc passe de
        non-signe a signe.
        """
        return sha256(self.to_bytes(include_signature=True))

    # -- Validation structurelle ------------------------------------------

    def validate_structure(self) -> None:
        self._validate_int_field("height", self.height)
        self._validate_int_field("round", self.round)
        self._validate_int_field("timestamp", self.timestamp)
        self._validate_hash_field("previous_block_hash", self.previous_block_hash)
        self._validate_hash_field("state_root", self.state_root)

        if not isinstance(self.transactions, tuple):
            raise BlockError("transactions must be a tuple")

        if len(self.transactions) > MAX_TRANSACTIONS:
            raise BlockError(
                f"block cannot contain more than {MAX_TRANSACTIONS} "
                "transactions"
            )

        seen_tx_ids: set[bytes] = set()
        for i, transaction in enumerate(self.transactions):
            if not isinstance(transaction, Transaction):
                raise BlockError(f"transactions[{i}] must be a Transaction")

            if not transaction.is_signed:
                raise BlockError(
                    f"transactions[{i}] must be signed before inclusion "
                    "in a block"
                )

            if transaction.tx_id in seen_tx_ids:
                raise BlockError(
                    f"duplicate transaction detected (tx_id="
                    f"{transaction.tx_id.hex()})"
                )
            seen_tx_ids.add(transaction.tx_id)

        self._validate_address_field("validator", self.validator)

        if not isinstance(self.validator_public_key, bytes) or not self.validator_public_key:
            raise BlockError("validator_public_key must be non-empty bytes")

        try:
            expected_validator = public_key_to_address(self.validator_public_key)
        except AddressError as exc:
            raise BlockError(str(exc)) from exc

        if self.validator != expected_validator:
            raise BlockError(
                "validator does not match the address derived from "
                "validator_public_key"
            )

        if self.signature is not None:
            if not isinstance(self.signature, bytes) or not self.signature:
                raise BlockError(
                    "signature must be non-empty bytes when present"
                )

    def validate(self) -> bool:
        """Valide le bloc et retourne True s'il est valide (sinon leve BlockError)."""
        self.validate_structure()
        return True

    @staticmethod
    def _validate_int_field(name: str, value: object) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise BlockError(f"{name} must be an integer")
        if value < 0:
            raise BlockError(f"{name} must be >= 0")

    @staticmethod
    def _validate_hash_field(name: str, value: object) -> None:
        if not isinstance(value, bytes):
            raise BlockError(f"{name} must be bytes")
        if len(value) != HASH_SIZE:
            raise BlockError(f"{name} must contain exactly {HASH_SIZE} bytes")

    @staticmethod
    def _validate_address_field(name: str, value: object) -> None:
        if not isinstance(value, bytes):
            raise BlockError(f"{name} must be bytes")
        if len(value) != ADDRESS_LENGTH:
            raise BlockError(
                f"{name} must contain exactly {ADDRESS_LENGTH} bytes"
            )

    # -- Serialisation pour stockage / reseau (distincte de to_bytes) ----

    def to_dict(self) -> dict[str, Any]:
        """
        Representation JSON-friendly du bloc, utilisee pour la
        persistance sur disque et la diffusion reseau. Distincte de
        to_bytes(), qui sert uniquement au hash/signature canonique.
        """
        return {
            "height": self.height,
            "round": self.round,
            "previous_block_hash": self.previous_block_hash.hex(),
            "timestamp": self.timestamp,
            "transactions": [tx.to_dict() for tx in self.transactions],
            "validator": self.validator.hex(),
            "validator_public_key": self.validator_public_key.hex(),
            "state_root": self.state_root.hex(),
            "signature": self.signature.hex() if self.signature is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Block":
        """
        Reconstruit un Block depuis sa representation dict.

        La reconstruction passe par le constructeur direct, ce qui
        declenche automatiquement __post_init__ -> validate_structure().
        Toute donnee corrompue ou incoherente (ex: validator ne
        correspondant pas a validator_public_key, transaction non
        signee, doublon) leve BlockError.
        """
        try:
            transactions = tuple(
                Transaction.from_dict(tx) for tx in data["transactions"]
            )
            signature_hex = data.get("signature")
            return cls(
                height=data["height"],
                # Older payloads can still be parsed as round 0. Their
                # canonical hash schema is intentionally not reused: a
                # deployment must start from a fresh chain when upgrading.
                round=data.get("round", 0),
                previous_block_hash=bytes.fromhex(data["previous_block_hash"]),
                timestamp=data["timestamp"],
                transactions=transactions,
                validator=bytes.fromhex(data["validator"]),
                validator_public_key=bytes.fromhex(data["validator_public_key"]),
                state_root=bytes.fromhex(data["state_root"]),
                signature=bytes.fromhex(signature_hex) if signature_hex else None,
            )
        except KeyError as exc:
            raise BlockError(f"missing field in block dict: {exc}") from exc
        except ValueError as exc:
            raise BlockError(f"invalid hex field in block dict: {exc}") from exc
        except TransactionError as exc:
            raise BlockError(f"invalid transaction in block dict: {exc}") from exc
