#!/usr/bin/env python3
"""Test local de confidentialite pour les versions synthetiques de la phase 7.

Le test ne lit ni ne cree de donnee medicale reelle. Il modelise deux versions
immutables d'un meme dossier controle :

    plaintext v1 -> ML-KEM encapsulation -> AES-256-GCM envelope v1
    plaintext v2 -> ML-KEM encapsulation -> AES-256-GCM envelope v2

Le meme destinataire/client possede la paire de cles ML-KEM pour les deux
versions. Un outsider possede une autre cle secrete, mais jamais la cle du
client. Il peut lire l'enveloppe chiffree et son hash, mais la verification
GCM echoue lorsqu'il tente de dechiffrer.

Le test est local, ne contacte pas IPFS, ne contacte pas la blockchain et ne
persiste aucun plaintext ni aucune cle. Il utilise uniquement le ciphertext
et les metadonnees de l'enveloppe en memoire.

Execution depuis la racine du depot :

    source .venv/bin/activate
    python3 scripts/testing/test_phase7_confidentiality.py
"""

from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# Permet l'execution depuis n'importe quel repertoire du depot.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

try:
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes
except ImportError as exc:  # pragma: no cover - message d'installation
    raise SystemExit(
        "pycryptodome est requis : activez .venv puis installez requirements.txt"
    ) from exc

from src.crypto.ml_kem import MLKEM, MLKEMKeyPair


AAD_PREFIX = b"phase7/medical-record/"


@dataclass(frozen=True)
class CiphertextEnvelope:
    """Objet chiffre stockable hors chaine, par exemple dans IPFS."""

    version: str
    kem_ciphertext: bytes
    nonce: bytes
    tag: bytes
    ciphertext: bytes

    def serialized(self) -> bytes:
        """Serialise les octets qui seraient envoyes a IPFS."""
        version = self.version.encode("ascii")
        fields = (
            version,
            self.kem_ciphertext,
            self.nonce,
            self.tag,
            self.ciphertext,
        )
        return b"".join(
            struct.pack(">I", len(field)) + field
            for field in fields
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.serialized()).hexdigest()


def derive_aes_key(shared_secret: bytes) -> bytes:
    """Derive une cle AES-256 depuis le secret partage ML-KEM."""
    return hashlib.sha256(b"phase7/aes-gcm/" + shared_secret).digest()


def seal(
    kem: MLKEM,
    recipient_public_key: bytes,
    *,
    version: str,
    plaintext: bytes,
) -> CiphertextEnvelope:
    """Chiffre un payload synthetique avec une nouvelle encapsulation."""
    encapsulation = kem.encapsulate(recipient_public_key)
    key = derive_aes_key(encapsulation.shared_secret)
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(AAD_PREFIX + version.encode("ascii"))
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return CiphertextEnvelope(
        version=version,
        kem_ciphertext=encapsulation.ciphertext,
        nonce=nonce,
        tag=tag,
        ciphertext=ciphertext,
    )


def open_envelope(
    kem: MLKEM,
    recipient_secret_key: bytes,
    envelope: CiphertextEnvelope,
) -> bytes:
    """Dechiffre et authentifie une enveloppe avec une cle ML-KEM."""
    shared_secret = kem.decapsulate(
        envelope.kem_ciphertext,
        recipient_secret_key,
    )
    key = derive_aes_key(shared_secret)
    cipher = AES.new(key, AES.MODE_GCM, nonce=envelope.nonce)
    cipher.update(AAD_PREFIX + envelope.version.encode("ascii"))
    return cipher.decrypt_and_verify(envelope.ciphertext, envelope.tag)


def synthetic_plaintext(version: str) -> bytes:
    """Retourne un contenu de test explicitement non medical."""
    return (
        f"PHASE7-CONTROLLED-TEST; dossier-synthetique; {version}; "
        "aucune donnee medicale reelle"
    ).encode("utf-8")


def main() -> int:
    kem = MLKEM()

    # Meme client/beneficiaire pour v1 et v2.
    client_keys: MLKEMKeyPair = kem.generate_keypair()
    outsider_keys: MLKEMKeyPair = kem.generate_keypair()

    envelopes = {
        version: seal(
            kem,
            client_keys.public_key,
            version=version,
            plaintext=synthetic_plaintext(version),
        )
        for version in ("v1", "v2")
    }

    print("mode       : test local controle, sans IPFS ni blockchain")
    print("algorithm  : ML-KEM-768 + AES-256-GCM")
    print("same client: oui (meme cle publique destinataire pour v1 et v2)")
    print("plaintext  : synthetique uniquement, aucune donnee medicale reelle")

    envelope_hashes: list[str] = []
    for version, envelope in envelopes.items():
        expected_plaintext = synthetic_plaintext(version)
        recovered = open_envelope(kem, client_keys.secret_key, envelope)
        if recovered != expected_plaintext:
            raise RuntimeError(f"dechiffrement autorise incorrect pour {version}")

        try:
            outsider_plaintext = open_envelope(
                kem,
                outsider_keys.secret_key,
                envelope,
            )
        except (ValueError, RuntimeError):
            outsider_result = "REJETE (authentification AES-GCM echouee)"
        else:
            raise RuntimeError(
                f"echec du test negatif {version}: plaintext outsider obtenu "
                f"({len(outsider_plaintext)} octets)"
            )

        envelope_hash = envelope.sha256()
        envelope_hashes.append(envelope_hash)
        print()
        print(f"version                 : {version}")
        print(f"ciphertext envelope     : {len(envelope.serialized())} octets")
        print(f"ciphertext sha256       : {envelope_hash}")
        print("dechiffrement client    : OK")
        print(f"dechiffrement outsider  : {outsider_result}")

    if envelope_hashes[0] == envelope_hashes[1]:
        raise RuntimeError("les envelopes v1 et v2 ont le meme hash")

    print()
    print("RESULT                   : confidentialite v1/v2 OK")
    print("immutable versions      : v1 et v2 ont des ciphertexts distincts")
    print("unauthorized decryption : rejetee pour v1 et v2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
