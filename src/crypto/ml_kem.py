"""
ML-KEM (Module-Lattice Key Encapsulation Mechanism) wrapper.

Encapsulation de clé post-quantique (NIST FIPS 203), utilisée dans ce
projet pour établir des secrets partagés entre nœuds (confidentialité
des canaux réseau, chiffrement de charges utiles sensibles).

Implémentation basée sur liboqs via le binding Python `oqs`.
"""

from __future__ import annotations

from dataclasses import dataclass

import oqs


DEFAULT_VARIANT = "ML-KEM-768"


class MLKEMError(Exception):
    """Erreur levée lors d'une opération ML-KEM invalide."""


@dataclass(frozen=True)
class MLKEMKeyPair:
    public_key: bytes
    secret_key: bytes


@dataclass(frozen=True)
class MLKEMEncapsulation:
    ciphertext: bytes
    shared_secret: bytes


class MLKEM:
    """Wrapper autour de la primitive KEM ML-KEM de liboqs."""

    def __init__(self, variant: str = DEFAULT_VARIANT) -> None:
        if variant not in oqs.get_enabled_kem_mechanisms():
            raise MLKEMError(
                f"Variante ML-KEM '{variant}' non disponible dans liboqs."
            )
        self.variant = variant

    def generate_keypair(self) -> MLKEMKeyPair:
        """Génère une nouvelle paire de clés ML-KEM."""
        with oqs.KeyEncapsulation(self.variant) as kem:
            public_key = kem.generate_keypair()
            secret_key = kem.export_secret_key()
        return MLKEMKeyPair(public_key=public_key, secret_key=secret_key)

    def encapsulate(self, public_key: bytes) -> MLKEMEncapsulation:
        """Encapsule un secret partagé à partir d'une clé publique."""
        with oqs.KeyEncapsulation(self.variant) as kem:
            ciphertext, shared_secret = kem.encap_secret(public_key)
        return MLKEMEncapsulation(ciphertext=ciphertext, shared_secret=shared_secret)

    def decapsulate(self, ciphertext: bytes, secret_key: bytes) -> bytes:
        """Décapsule un secret partagé à partir d'une clé secrète."""
        with oqs.KeyEncapsulation(self.variant, secret_key) as kem:
            shared_secret = kem.decap_secret(ciphertext)
        return shared_secret
