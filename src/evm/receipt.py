"""
Recus d'execution : le resultat d'une transaction passee dans l'EVM.

Un recu est un FAIT, pas un diagnostic. Il enregistre ce qui s'est
passe lorsqu'une transaction a ete executee, y compris -- et surtout --
lorsqu'elle a echoue.

    status = 1   la transaction a reussi
    status = 0   la transaction a echoue (revert, out-of-gas, nonce
                 invalide, solde insuffisant)

Un recu en echec n'invalide JAMAIS le bloc qui contient la
transaction. Les trois noeuds executent les memes transactions dans le
meme ordre : ils produisent donc les memes echecs, aux memes endroits.
L'echec est deterministe et partage. Si un noeud rejetait un bloc
parce qu'une de ses transactions a echoue, il divergerait de ses pairs
qui l'acceptent -- c'est-a-dire un fork.

C'est pourquoi l'executeur ne laisse jamais remonter une exception
d'execution : il la traduit en Receipt(status=0). Seules les
defaillances d'INFRASTRUCTURE (EVMError) remontent, car elles
signalent un bug du logiciel, pas un fait de la chaine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from src.evm.addresses import validate_address
from src.evm.logs import EVMLog

# --- Constantes -------------------------------------------------------

#: Transaction executee avec succes.
STATUS_SUCCESS = 1

#: Transaction executee mais echouee. Le bloc reste valide.
STATUS_FAILURE = 0


@dataclass(frozen=True)
class Receipt:
    """
    Resultat immuable de l'execution d'une transaction.

    Frozen, comme Block et Transaction : un recu constate, il ne se
    modifie pas apres coup.

    Attributes:
        tx_id: Identifiant de la transaction concernee (32 octets).
        status: STATUS_SUCCESS ou STATUS_FAILURE.
        gas_used: Gas reellement consomme. Non nul meme en cas
            d'echec : un revert consomme le gas deja depense, un
            out-of-gas consomme la totalite du gas_limit.
        contract_address: Adresse du contrat cree, si la transaction
            etait un deploiement REUSSI. None sinon.
        output: Donnees retournees par l'execution. Sur un revert,
            contient le motif encode s'il y en a un.
        error: Description courte de l'echec, pour le journal et le
            debogage. None en cas de succes.
        logs: événements Solidity émis par une exécution réussie, dans
            l'ordre canonique de l'EVM. Un échec ne conserve aucun log.

    Le bloom filter n'est pas encore calculé : les logs bruts sont
    transportés de façon déterministe, ce qui suffit à la PHASE 4 sans
    introduire de nouvelle racine de reçus.
    """

    tx_id: bytes
    status: int
    gas_used: int
    contract_address: Optional[bytes] = None
    output: bytes = b""
    error: Optional[str] = None
    logs: tuple[EVMLog, ...] = ()

    def __post_init__(self) -> None:
        self._validate()

    # -- Constructeurs -----------------------------------------------

    @classmethod
    def success(
        cls,
        *,
        tx_id: bytes,
        gas_used: int,
        contract_address: Optional[bytes] = None,
        output: bytes = b"",
        logs: tuple[EVMLog, ...] = (),
    ) -> "Receipt":
        """Recu d'une transaction reussie."""
        return cls(
            tx_id=tx_id,
            status=STATUS_SUCCESS,
            gas_used=gas_used,
            contract_address=contract_address,
            output=output,
            error=None,
            logs=logs,
        )

    @classmethod
    def failure(
        cls,
        *,
        tx_id: bytes,
        gas_used: int,
        error: str,
        output: bytes = b"",
    ) -> "Receipt":
        """
        Recu d'une transaction echouee.

        `contract_address` est toujours None : un deploiement qui
        echoue ne laisse aucun contrat derriere lui.
        """
        return cls(
            tx_id=tx_id,
            status=STATUS_FAILURE,
            gas_used=gas_used,
            contract_address=None,
            output=output,
            error=error,
        )

    # -- Proprietes derivees ------------------------------------------

    @property
    def is_success(self) -> bool:
        return self.status == STATUS_SUCCESS

    @property
    def is_failure(self) -> bool:
        return self.status == STATUS_FAILURE

    @property
    def created_contract(self) -> bool:
        """Vrai si un contrat a effectivement ete deploye."""
        return self.contract_address is not None

    # -- Validation ----------------------------------------------------

    def _validate(self) -> None:
        if not isinstance(self.tx_id, bytes) or len(self.tx_id) != 32:
            raise ValueError("tx_id must contain exactly 32 bytes")

        # `True in (0, 1)` vaut True en Python : sans exclusion
        # explicite du booleen, Receipt(status=True) serait accepte et
        # to_dict() ecrirait `true` au lieu de `1` dans le JSON.
        if isinstance(self.status, bool) or self.status not in (
            STATUS_SUCCESS,
            STATUS_FAILURE,
        ):
            raise ValueError("status must be 0 or 1")

        if isinstance(self.gas_used, bool) or not isinstance(self.gas_used, int):
            raise ValueError("gas_used must be an integer")

        if self.gas_used < 0:
            raise ValueError("gas_used must be >= 0")

        if not isinstance(self.output, bytes):
            raise ValueError("output must be bytes")

        if not isinstance(self.logs, tuple) or any(
            not isinstance(log, EVMLog) for log in self.logs
        ):
            raise ValueError("logs must be a tuple of EVMLog")

        if self.status == STATUS_FAILURE and self.logs:
            raise ValueError("a failed receipt cannot carry logs")

        if self.contract_address is not None:
            validate_address(self.contract_address, "contract_address")

            # Coherence : un contrat ne peut pas naitre d'un echec.
            if self.status == STATUS_FAILURE:
                raise ValueError(
                    "a failed transaction cannot create a contract"
                )

        if self.error is not None and not isinstance(self.error, str):
            raise ValueError("error must be a string or None")

        if self.status == STATUS_SUCCESS and self.error is not None:
            raise ValueError("a successful receipt cannot carry an error")

    # -- Serialisation --------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Representation JSON-friendly, meme convention que Block."""
        return {
            "tx_id": self.tx_id.hex(),
            "status": self.status,
            "gas_used": self.gas_used,
            "contract_address": (
                self.contract_address.hex()
                if self.contract_address is not None
                else None
            ),
            "output": self.output.hex(),
            "error": self.error,
            "logs": [log.to_dict() for log in self.logs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Receipt":
        """Reconstruit un recu depuis sa representation dict."""
        try:
            adresse = data.get("contract_address")
            return cls(
                tx_id=bytes.fromhex(data["tx_id"]),
                status=data["status"],
                gas_used=data["gas_used"],
                contract_address=bytes.fromhex(adresse) if adresse else None,
                output=bytes.fromhex(data.get("output", "")),
                error=data.get("error"),
                logs=tuple(
                    EVMLog.from_dict(item) for item in data.get("logs", [])
                ),
            )
        except KeyError as exc:
            raise ValueError(f"missing field in receipt dict: {exc}") from exc
        except ValueError as exc:
            raise ValueError(f"invalid receipt dict: {exc}") from exc

    def __repr__(self) -> str:
        etat = "success" if self.is_success else f"failed({self.error})"
        return (
            f"Receipt(tx=0x{self.tx_id.hex()[:8]}..., {etat}, "
            f"gas={self.gas_used})"
        )
