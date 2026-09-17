"""
ML-DSA (Module-Lattice Digital Signature Algorithm) wrapper.

Signature numérique post-quantique (NIST FIPS 204), utilisée dans ce
projet pour :
- l'identité cryptographique d'un nœud (PoA)
- la signature des transactions
- la signature des blocs

Implémentation basée sur liboqs via le binding Python `oqs`.
"""

from __future__ import annotations

from dataclasses import dataclass

import oqs


DEFAULT_VARIANT = "ML-DSA-44"


class MLDSAError(Exception):
    """Erreur levée lors d'une opération ML-DSA invalide."""


@dataclass(frozen=True)
class MLDSAKeyPair:
    public_key: bytes
    secret_key: bytes


class MLDSA:
    """Wrapper autour de la primitive de signature ML-DSA de liboqs."""

    def __init__(self, variant: str = DEFAULT_VARIANT) -> None:
        if variant not in oqs.get_enabled_sig_mechanisms():
            raise MLDSAError(
                f"Variante ML-DSA '{variant}' non disponible dans liboqs."
            )
        self.variant = variant

    def generate_keypair(self) -> MLDSAKeyPair:
        """Génère une nouvelle paire de clés ML-DSA."""
        with oqs.Signature(self.variant) as signer:
            public_key = signer.generate_keypair()
            secret_key = signer.export_secret_key()
        return MLDSAKeyPair(public_key=public_key, secret_key=secret_key)

    def sign(self, message: bytes, secret_key: bytes) -> bytes:
        """Signe un message avec une clé secrète ML-DSA."""
        if not isinstance(message, bytes):
            raise MLDSAError("Le message à signer doit être de type bytes.")

        with oqs.Signature(self.variant, secret_key) as signer:
            signature = signer.sign(message)
        return signature

    def verify(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        """Vérifie une signature ML-DSA. Retourne False en cas d'échec."""
        if not isinstance(message, bytes):
            raise MLDSAError("Le message à vérifier doit être de type bytes.")

        with oqs.Signature(self.variant) as verifier:
            try:
                return bool(verifier.verify(message, signature, public_key))
            except Exception:
                return False
