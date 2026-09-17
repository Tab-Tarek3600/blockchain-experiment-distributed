"""Adaptateur minimal vers l'API HTTP de Kubo.

Le client ne chiffre pas les fichiers et ne reçoit donc que des octets déjà
chiffrés. Il est volontairement limité aux opérations nécessaires à la phase
7 : ajout, récupération, pin, unpin et vérification de présence.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import BinaryIO, Any

import requests


class IPFSError(RuntimeError):
    """Erreur retournée par l'API IPFS ou par le transport HTTP."""


class IPFSClient:
    """Client synchrone de l'API HTTP Kubo.

    Parameters
    ----------
    api_url:
        URL de base de l'API, par exemple ``http://127.0.0.1:5001/api/v0``.
        L'API reste normalement exposée uniquement sur loopback de la VM.
    timeout:
        Délai HTTP par défaut en secondes.
    session:
        Session ``requests`` injectable pour les tests sans daemon Kubo.
    """

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:5001/api/v0",
        *,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if not api_url or not isinstance(api_url, str):
            raise ValueError("api_url doit être une chaîne non vide")
        if timeout <= 0:
            raise ValueError("timeout doit être strictement positif")
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def add_encrypted_file(
        self,
        source: bytes | bytearray | memoryview | str | Path | BinaryIO,
        *,
        filename: str = "ciphertext.bin",
    ) -> str:
        """Ajoute un ciphertext et retourne son CID.

        ``source`` peut être un chemin, un flux binaire ou des octets. Le
        contenu est envoyé tel quel : le chiffrement doit avoir été effectué
        côté client avant l'appel.
        """
        payload, close_after = self._open_source(source)
        try:
            response = self._request(
                "add",
                params={"pin": "true", "cid-version": "1"},
                files={
                    "file": (
                        filename,
                        payload,
                        "application/octet-stream",
                    )
                },
            )
        finally:
            if close_after:
                payload.close()

        result = self._decode_json_lines(response)
        cid = result.get("Hash")
        if not isinstance(cid, str) or not cid:
            raise IPFSError("la réponse IPFS add ne contient pas de CID")
        return cid

    def get_file(self, cid: str) -> bytes:
        """Récupère exactement les octets associés à ``cid``."""
        response = self._request("cat", params={"arg": self._require_cid(cid)})
        return response.content

    def pin(self, cid: str) -> None:
        """Ajoute un pin récursif pour ``cid``."""
        self._request("pin/add", params={"arg": self._require_cid(cid)})

    def unpin(self, cid: str) -> None:
        """Supprime le pin de ``cid`` sans supprimer arbitrairement son bloc."""
        self._request("pin/rm", params={"arg": self._require_cid(cid)})

    def has(self, cid: str) -> bool:
        """Retourne si le bloc racine du CID est présent sur ce fournisseur."""
        cid = self._require_cid(cid)
        response = self.session.post(
            f"{self.api_url}/block/stat",
            params={"arg": cid},
            timeout=self.timeout,
        )
        if response.ok:
            return True
        if response.status_code >= 500 and "not found" in response.text.lower():
            return False
        self._raise_for_status(response, "block/stat")
        return False

    def close(self) -> None:
        """Ferme la session HTTP si elle est gérée par l'adaptateur."""
        self.session.close()

    @staticmethod
    def _open_source(
        source: bytes | bytearray | memoryview | str | Path | BinaryIO,
    ) -> tuple[BinaryIO, bool]:
        if isinstance(source, (bytes, bytearray, memoryview)):
            return io.BytesIO(bytes(source)), True
        if isinstance(source, (str, Path)):
            return Path(source).open("rb"), True
        if not hasattr(source, "read"):
            raise TypeError("source doit être un chemin, des octets ou un flux binaire")
        return source, False

    @staticmethod
    def _require_cid(cid: str) -> str:
        if not isinstance(cid, str) or not cid.strip():
            raise ValueError("cid doit être une chaîne non vide")
        return cid.strip()

    def _request(self, operation: str, **kwargs: Any) -> requests.Response:
        try:
            response = self.session.post(
                f"{self.api_url}/{operation}",
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise IPFSError(f"échec de communication IPFS pour {operation}: {exc}") from exc
        self._raise_for_status(response, operation)
        return response

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str) -> None:
        if response.ok:
            return
        detail = response.text.strip()[:500]
        raise IPFSError(
            f"API IPFS {operation} a répondu HTTP {response.status_code}: {detail}"
        )

    @staticmethod
    def _decode_json_lines(response: requests.Response) -> dict[str, Any]:
        values: list[dict[str, Any]] = []
        for line in response.text.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IPFSError("réponse JSON invalide de l'API IPFS") from exc
            if not isinstance(value, dict):
                raise IPFSError("réponse IPFS inattendue")
            values.append(value)
        if not values:
            raise IPFSError("réponse vide de l'API IPFS add")
        return values[-1]
