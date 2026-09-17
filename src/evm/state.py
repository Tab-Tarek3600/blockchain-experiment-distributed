"""
Etat du monde EVM : comptes, soldes, nonces, code et stockage.

SEUL MODULE DU PROJET AUTORISE A IMPORTER py-evm (`eth.*`).

Cette regle n'est pas cosmetique. py-evm est epingle sur une version
beta (0.12.1b1) dont l'API interne bouge d'une release a l'autre. En
confinant tous les `import eth.*` ici, une rupture de leur API se
repare dans UN fichier au lieu d'etre disseminee dans executor.py,
receipt.py et le reste du noeud. Le prix a payer est que cette classe
expose une interface volontairement etroite, en types Python natifs
(bytes, int) : aucun objet py-evm ne doit franchir cette frontiere.

Modele : l'etat n'est jamais reconstruit a partir de rien. Il est
obtenu par REJEU des blocs depuis ChainStorage (decision D4), ce qui
evite tout hook dans Node._accept_block() et garantit qu'un noeud
redemarre sur exactement le meme etat que ses pairs.


DETERMINISME -- proprietes verifiees experimentalement sur py-evm
0.12.1b1, et sur lesquelles repose le critere n.12 (meme state_root
sur les 3 VMs) :

  * La racine est reproductible : les memes ecritures sur une base
    neuve redonnent bit pour bit la meme racine.
  * Elle est independante de l'ORDRE des ecritures : ecrire A puis B
    ou B puis A donne la meme racine (propriete du trie de Merkle).
  * Une LECTURE seule ne modifie pas la racine : lire le solde d'un
    compte inexistant laisse l'etat vierge.

PIEGE MAJEUR, a l'origine de la garde de ce module : ECRIRE une valeur
nulle n'est PAS neutre. set_balance(addr, 0) sur un compte inexistant
CREE le compte et change la racine, alors que ne rien ecrire la laisse
inchangee. Deux noeuds dont l'un ecrit un zero inutile et l'autre non
calculeraient des state_root differents -- et, le state_root etant
signe et hache (decision D3), produiraient un FORK. Toutes les
methodes d'ecriture de cette classe ignorent donc les ecritures sans
effet (voir _skip_noop_write).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from eth.constants import BLANK_ROOT_HASH
from eth.db.atomic import AtomicDB
from eth.db.backends.memory import MemoryDB
from eth.vm.execution_context import ExecutionContext
from eth.vm.forks import ShanghaiVM
from eth.vm.forks.shanghai.computation import ShanghaiComputation
from eth.vm.message import Message
from eth.vm.transaction_context import BaseTransactionContext

from src.evm.addresses import validate_address
from src.evm.errors import StateError
from src.evm.logs import EVMLog

# --- Constantes -------------------------------------------------------

#: Fork EVM cible. Shanghai est le dernier fork qui ne requiert PAS de
#: beacon chain ni de blobs (EIP-4844), donc le plus adapte a une
#: chaine PoA autonome. Il inclut PUSH0, present dans le bytecode
#: produit par les compilateurs Solidity recents.
EVM_FORK = ShanghaiVM

#: Identifiant de chaine, isole des reseaux publics.
CHAIN_ID = 1337

#: Racine d'un etat entierement vide (trie sans aucune feuille).
EMPTY_STATE_ROOT = BLANK_ROOT_HASH

#: Plafond de gas par bloc.
BLOCK_GAS_LIMIT = 30_000_000

#: Bornes du modele de compte EVM (mots de 256 bits).
MAX_UINT256 = 2**256 - 1


@dataclass(frozen=True)
class ExecutionOutcome:
    """
    Resultat d'une execution EVM, en types Python natifs.

    Ce type existe pour que l'objet `Computation` de py-evm ne
    franchisse JAMAIS la frontiere de ce module. L'executeur raisonne
    sur ces six champs et n'a donc aucune dependance a py-evm.

    Attributes:
        succeeded: Vrai si l'execution s'est terminee normalement.
        gas_used: Gas consomme par l'execution elle-meme (hors cout
            intrinseque de la transaction).
        output: Donnees retournees. Vide si py-evm demande d'effacer
            le retour (cas de l'out-of-gas).
        error: Motif de l'echec en texte court, None en cas de succes.
        burns_all_gas: Vrai si l'echec consomme la totalite du budget
            (out-of-gas) plutot que le seul gas depense (revert).
        logs: événements émis par une exécution réussie, dans l'ordre
            canonique de py-evm. Une exécution en erreur n'en expose aucun.
    """

    succeeded: bool
    gas_used: int
    output: bytes
    error: Optional[str]
    burns_all_gas: bool
    logs: tuple[EVMLog, ...] = ()


class EVMState:
    """
    Enveloppe autour de l'etat py-evm, exposant uniquement des types
    Python natifs.

    Usage typique :

        state = EVMState()                  # etat vide, en memoire
        state.set_balance(alice, 1000)
        state.commit()                      # -> nouvelle racine
        root = state.state_root
    """

    def __init__(self, state_root: Optional[bytes] = None, *, _db=None) -> None:
        """
        Construit un etat VIERGE.

        Args:
            state_root: Doit valoir None ou EMPTY_STATE_ROOT. Voir
                ci-dessous pourquoi une autre racine est refusee.
            _db: Usage interne (at_root). Ne pas fournir.

        Une racine n'a de sens que RELATIVEMENT a la base qui contient
        les noeuds du trie correspondant. Chaque EVMState() cree sa
        propre base en memoire, vide : lui demander de repartir d'une
        racine arbitraire produirait un MissingAccountTrieNode
        illisible au premier acces, potentiellement loin de l'appel
        fautif. On refuse donc immediatement, avec un message qui
        indique l'alternative -- at_root(), qui partage la base.

        Persistance : l'etat vit EN MEMOIRE, volontairement. La
        decision D4 veut que l'etat soit reconstruit par rejeu des
        blocs depuis ChainStorage, seule source de verite ; une base
        d'etat sur disque serait un second etat persistant a maintenir
        coherent avec la chaine, donc une source de divergences.

        py-evm expose bien un backend LevelDB, mais il n'est PAS livre
        avec le paquet (`eth.db.backends.level` absent, il dependrait
        de `plyvel`, une extension C non installee sur les VMs). Ne pas
        l'exposer ici evite de promettre une persistance qui
        echouerait a l'import au premier usage reel.
        """
        if state_root is not None and not isinstance(state_root, bytes):
            raise StateError("state_root must be bytes or None")

        if state_root is not None and len(state_root) != 32:
            raise StateError(
                f"state_root must contain exactly 32 bytes, got {len(state_root)}"
            )

        if (
            _db is None
            and state_root is not None
            and state_root != EMPTY_STATE_ROOT
        ):
            raise StateError(
                "cannot start from an arbitrary state_root: a fresh EVMState "
                "owns an empty database that does not contain the trie nodes "
                "for that root. Rebuild the state by replaying blocks, or use "
                "existing_state.at_root(root) to reuse the same database."
            )

        self._db = _db if _db is not None else AtomicDB(MemoryDB())
        self._state_class = EVM_FORK.get_state_class()
        self._root = state_root if state_root is not None else EMPTY_STATE_ROOT
        self._state = self._build_state(self._root, block_number=0, timestamp=0)

    # -- Construction interne -------------------------------------------

    def _build_state(
        self,
        root: bytes,
        *,
        block_number: int,
        timestamp: int,
        coinbase: bytes = b"\x00" * 20,
    ):
        """
        Instancie un objet State py-evm sur une racine donnee.

        Le contexte d'execution influence le resultat des opcodes
        NUMBER, TIMESTAMP, COINBASE et CHAINID. Il doit donc etre
        IDENTIQUE sur les trois noeuds pour un meme bloc, sans quoi un
        contrat lisant block.timestamp divergerait. Ces valeurs
        proviennent toutes du bloc lui-meme, qui est partage : le
        determinisme est structurel.

        difficulty=0 et mix_hash=0 refletent le post-Merge ; en PoA il
        n'y a pas de preuve de travail. prev_hashes reste vide :
        l'opcode BLOCKHASH renverra 0, comportement accepte et
        documente pour cette chaine.
        """
        context = ExecutionContext(
            coinbase=coinbase,
            timestamp=timestamp,
            block_number=block_number,
            difficulty=0,
            mix_hash=b"\x00" * 32,
            gas_limit=BLOCK_GAS_LIMIT,
            prev_hashes=(),
            chain_id=CHAIN_ID,
            base_fee_per_gas=0,
            excess_blob_gas=0,
        )
        return self._state_class(self._db, context, root)

    def set_block_context(
        self,
        *,
        block_number: int,
        timestamp: int,
        coinbase: bytes = b"\x00" * 20,
    ) -> None:
        """
        Repositionne l'etat dans le contexte d'un bloc donne.

        Appele par l'executeur avant de traiter les transactions d'un
        bloc. Conserve la racine courante : seul le contexte change,
        les donnees restent.
        """
        if not isinstance(block_number, int) or isinstance(block_number, bool):
            raise StateError("block_number must be an integer")
        if not isinstance(timestamp, int) or isinstance(timestamp, bool):
            raise StateError("timestamp must be an integer")
        if block_number < 0:
            raise StateError("block_number must be >= 0")

        validate_address(coinbase, "coinbase")
        self._state = self._build_state(
            self.state_root,
            block_number=block_number,
            timestamp=timestamp,
            coinbase=coinbase,
        )

    def at_root(self, state_root: bytes) -> "EVMState":
        """
        Nouvelle vue de l'etat a une racine anterieure, sur la MEME
        base de donnees.

        Le trie est immuable et par partage de structure : les noeuds
        d'une racine deja calculee restent presents apres de nouvelles
        ecritures. Revenir en arriere est donc possible sans copie,
        tant qu'on reste sur la meme base -- d'ou cette methode plutot
        qu'un constructeur.

        Sert a comparer l'etat obtenu au state_root annonce par un
        bloc, et a rejouer une portion de chaine.

        Raises:
            StateError: Si la racine est absente de la base, ce qui
                signifie qu'elle n'a jamais ete calculee ici.
        """
        if not isinstance(state_root, bytes) or len(state_root) != 32:
            raise StateError("state_root must be exactly 32 bytes")

        view = EVMState(_db=self._db)
        view._state = view._build_state(state_root, block_number=0, timestamp=0)

        if state_root != EMPTY_STATE_ROOT:
            try:
                view._state.get_balance(b"\x00" * 20)
            except Exception as exc:
                raise StateError(
                    f"state root 0x{state_root.hex()[:16]}... is not present "
                    "in this database"
                ) from exc

        return view

    # -- Racine ---------------------------------------------------------

    @property
    def state_root(self) -> bytes:
        """Racine courante de l'etat (32 octets)."""
        return self._state.state_root

    @property
    def is_empty(self) -> bool:
        """Vrai si aucun compte n'a jamais ete ecrit."""
        return self.state_root == EMPTY_STATE_ROOT

    def commit(self) -> bytes:
        """
        Ecrit les modifications en attente et retourne la nouvelle
        racine.

        C'est cette valeur qui alimentera Block.state_root. Tant que
        commit() n'est pas appele, les ecritures restent en memoire et
        la racine ne reflete pas les changements.
        """
        try:
            self._state.persist()
        except Exception as exc:
            raise StateError(f"failed to persist state: {exc}") from exc
        return self._state.state_root

    def snapshot(self):
        """
        Point de restauration, a utiliser avant une transaction.

        Une transaction qui echoue (revert, out-of-gas) ne doit laisser
        AUCUNE trace dans l'etat, hormis l'incrementation du nonce et
        le paiement du gas. C'est ce mecanisme qui l'assure.
        """
        return self._state.snapshot()

    def revert(self, snapshot) -> None:
        """Annule toutes les ecritures faites depuis `snapshot`."""
        self._state.revert(snapshot)

    # -- Garde anti-divergence ------------------------------------------

    @staticmethod
    def _skip_noop_write(current, new_value) -> bool:
        """
        Indique qu'une ecriture est sans effet et doit etre ignoree.

        Voir le piege documente en tete de module : ecrire une valeur
        deja presente (typiquement 0 sur un compte inexistant) peut
        materialiser un compte et donc changer la racine. Ne jamais
        ecrire ce qui ne change rien rend la racine insensible a la
        maniere dont l'executeur est ecrit.
        """
        return current == new_value

    # -- Comptes ---------------------------------------------------------

    def account_exists(self, address: bytes) -> bool:
        """Indique si le compte est materialise dans le trie."""
        validate_address(address)
        return self._state.account_exists(address)

    def get_balance(self, address: bytes) -> int:
        """Solde du compte. Un compte inexistant vaut 0, sans etre cree."""
        validate_address(address)
        return self._state.get_balance(address)

    def set_balance(self, address: bytes, value: int) -> None:
        """Fixe le solde. Ignore si la valeur est deja celle-ci."""
        validate_address(address)
        self._validate_uint256(value, "balance")

        if self._skip_noop_write(self._state.get_balance(address), value):
            return

        self._state.set_balance(address, value)

    def add_balance(self, address: bytes, amount: int) -> None:
        """Cree du solde. Ignore un montant nul."""
        validate_address(address)
        self._validate_uint256(amount, "amount")

        if amount == 0:
            return

        new_balance = self._state.get_balance(address) + amount
        if new_balance > MAX_UINT256:
            raise StateError("balance overflow: exceeds 2**256 - 1")

        self._state.set_balance(address, new_balance)

    def subtract_balance(self, address: bytes, amount: int) -> None:
        """
        Debite le solde. Ignore un montant nul.

        Raises:
            StateError: Si le solde est insuffisant. L'appelant DOIT
                verifier le solde avant, et traduire l'insuffisance en
                Receipt(status=0) -- jamais en exception remontant
                jusqu'au noeud, sous peine de fork.
        """
        validate_address(address)
        self._validate_uint256(amount, "amount")

        if amount == 0:
            return

        balance = self._state.get_balance(address)
        if balance < amount:
            raise StateError(
                f"insufficient balance: has {balance}, needs {amount}"
            )

        self._state.set_balance(address, balance - amount)

    def transfer(self, sender: bytes, recipient: bytes, amount: int) -> None:
        """
        Transfert atomique de valeur.

        Un transfert vers soi-meme est ignore : il ne change rien, et
        le decomposer en debit puis credit pourrait echouer a tort.
        """
        validate_address(sender, "sender")
        validate_address(recipient, "recipient")
        self._validate_uint256(amount, "amount")

        if amount == 0 or sender == recipient:
            return

        self.subtract_balance(sender, amount)
        self.add_balance(recipient, amount)

    # -- Nonces -----------------------------------------------------------

    def get_nonce(self, address: bytes) -> int:
        """Nonce du compte (0 si inexistant)."""
        validate_address(address)
        return self._state.get_nonce(address)

    def set_nonce(self, address: bytes, nonce: int) -> None:
        """Fixe le nonce. Ignore si inchange."""
        validate_address(address)
        self._validate_uint256(nonce, "nonce")

        if self._skip_noop_write(self._state.get_nonce(address), nonce):
            return

        self._state.set_nonce(address, nonce)

    def increment_nonce(self, address: bytes) -> None:
        """
        Incremente le nonce, y compris pour une transaction en echec.

        C'est la protection contre le rejeu : une transaction consommee
        ne doit jamais pouvoir etre resoumise, meme si elle a echoue.
        """
        validate_address(address)
        self._state.increment_nonce(address)

    # -- Code -------------------------------------------------------------

    def get_code(self, address: bytes) -> bytes:
        """Bytecode deploye (b"" si le compte n'est pas un contrat)."""
        validate_address(address)
        return self._state.get_code(address)

    def set_code(self, address: bytes, code: bytes) -> None:
        """Installe le bytecode d'un contrat. Ignore si inchange."""
        validate_address(address)
        if not isinstance(code, bytes):
            raise StateError("code must be bytes")

        if self._skip_noop_write(self._state.get_code(address), code):
            return

        self._state.set_code(address, code)

    def is_contract(self, address: bytes) -> bool:
        """Indique si l'adresse porte du code deploye."""
        return self.get_code(address) != b""

    # -- Stockage ---------------------------------------------------------

    def get_storage(self, address: bytes, slot: int) -> int:
        """Lit un emplacement de stockage (0 par defaut)."""
        validate_address(address)
        self._validate_uint256(slot, "slot")
        return self._state.get_storage(address, slot)

    def set_storage(self, address: bytes, slot: int, value: int) -> None:
        """Ecrit un emplacement de stockage. Ignore si inchange."""
        validate_address(address)
        self._validate_uint256(slot, "slot")
        self._validate_uint256(value, "value")

        if self._skip_noop_write(self._state.get_storage(address, slot), value):
            return

        self._state.set_storage(address, slot, value)

    # -- Validation interne ------------------------------------------------

    @staticmethod
    def _validate_uint256(value: object, name: str) -> None:
        """
        Verifie qu'une valeur tient dans un mot EVM de 256 bits.

        Le booleen est exclu explicitement : isinstance(True, int) vaut
        True en Python, et un booleen passe par megarde serait traite
        comme 0 ou 1 en silence.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise StateError(f"{name} must be an integer")

        if value < 0:
            raise StateError(f"{name} must be >= 0")

        if value > MAX_UINT256:
            raise StateError(f"{name} must be <= 2**256 - 1")

    # -- Acces controle a py-evm -------------------------------------------

    def run_message(
        self,
        *,
        sender: bytes,
        to: bytes,
        value: int,
        data: bytes,
        code: bytes,
        gas: int,
        gas_price: int,
        create_address: Optional[bytes] = None,
    ) -> ExecutionOutcome:
        """
        Execute un message EVM et renvoie un ExecutionOutcome.

        Unique point d'appel de la machine d'execution py-evm du
        projet. Il vit ici, et non dans executor.py, pour la raison
        donnee en tete de module : aucun objet py-evm ne franchit
        cette frontiere. L'executeur recoit un resultat en types
        natifs et reste insensible aux ruptures d'API de py-evm.

        Le projet n'utilise ni RLP ni ECDSA (signatures ML-DSA
        validees en amont) : on court-circuite donc la couche
        transaction de py-evm pour piloter directement le Message.

        Args:
            create_address: Adresse du contrat a creer. Non-None
                declenche une creation plutot qu'un appel.

        Returns:
            ExecutionOutcome decrivant succes, gas et sortie.
        """
        est_creation = create_address is not None

        contexte = BaseTransactionContext(gas_price=gas_price, origin=sender)

        # to=b"" signale une creation a py-evm ; create_address porte
        # alors l'adresse calculee. Omettre create_address provoque
        # « Storage Address b'' is not a valid canonical address ».
        message = Message(
            gas=gas,
            to=b"" if est_creation else to,
            sender=sender,
            value=value,
            data=b"" if est_creation else data,
            code=code,
            create_address=create_address,
            should_transfer_value=True,
        )

        if est_creation:
            computation = ShanghaiComputation.apply_create_message(
                self._state, message, contexte
            )
        else:
            computation = ShanghaiComputation.apply_message(
                self._state, message, contexte
            )

        return self._to_outcome(computation)

    @staticmethod
    def _to_outcome(computation) -> ExecutionOutcome:
        """Convertit un Computation py-evm en ExecutionOutcome neutre."""
        logs = tuple(
            EVMLog(
                address=address,
                topics=tuple(topic.to_bytes(32, "big") for topic in topics),
                data=data,
            )
            for address, topics, data in computation.get_log_entries()
        )

        if not computation.is_error:
            return ExecutionOutcome(
                succeeded=True,
                gas_used=computation.get_gas_used(),
                output=computation.output,
                error=None,
                burns_all_gas=False,
                logs=logs,
            )

        # computation.error leve AttributeError s'il n'y a pas
        # d'erreur : cette branche n'est atteinte que sous is_error.
        erreur = computation.error
        nom = type(erreur).__name__
        detail = str(erreur)

        # Un out-of-gas ne retourne rien ; un revert peut transporter
        # un motif encode.
        sortie = b"" if computation.should_erase_return_data else computation.output

        return ExecutionOutcome(
            succeeded=False,
            gas_used=computation.get_gas_used(),
            output=sortie,
            error=f"{nom}: {detail}" if detail else nom,
            burns_all_gas=bool(computation.should_burn_gas),
            logs=logs,
        )

    def __repr__(self) -> str:
        return f"EVMState(state_root=0x{self.state_root.hex()[:16]}...)"
