"""
Node — orchestrator for the experimental blockchain node.

Assembles all components and defines the high-level node lifecycle:
    - Blockchain  (chain state + persistence)
    - Mempool     (pending transactions)
    - Validator   (structural + cryptographic acceptance checks)
    - Consensus   (PoA round-robin scheduling + block production)
    - P2PTransport (broadcast / receive)

Single-responsibility rule enforced here:
    Node._accept_block() is the ONLY place in the entire codebase
    that calls Blockchain.add_block(). Both self-produced blocks
    (propose_block) and externally received blocks (receive_block)
    go through exactly the same acceptance pipeline:

        validate_block_for_acceptance()   (validator.py)
              ↓
        is_expected_proposer()            (consensus.py)
              ↓
        blockchain.add_block()            (blockchain.py)
              ↓
        mempool.remove_transactions()     (mempool.py)
              ↓
        p2p.broadcast_block()             (p2p.py)

    This guarantees that no block ever enters the chain without
    passing the full validation + consensus pipeline, regardless
    of its origin.

Known limitations:
    - No real account/state model: nonce uniqueness across the full
      chain history is not enforced (only within the mempool queue).
    - No fork choice: only one canonical chain, no branch management.

Round advancement is deliberately small and deterministic: an active
node advances its local proposal round only after a configured timeout,
and the round is authenticated in the block. The transport may still
invoke the callbacks from background threads, so the round state is
protected by a lock.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Sequence

from src.blockchain.blockchain import Blockchain, BlockchainError
from src.blockchain.block import Block
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.crypto.address import public_key_to_address
from src.crypto.ml_dsa import MLDSA, MLDSAKeyPair
from src.evm.errors import EVMError
from src.evm.state import BLOCK_GAS_LIMIT
from src.evm.replay import StateReplayer
from src.node.config import NodeConfig, load_or_generate_validator_keys
from src.node.consensus import Consensus, ConsensusError
from src.node.mempool import Mempool, MempoolError
from src.node.p2p import NullP2P, P2PTransport
from src.node.validator import ValidatorError, validate_block_for_acceptance

logger = logging.getLogger(__name__)

# A transaction is relayed at most once by a node.  The TCP transport has
# its own cache, but keeping the invariant here also makes InMemoryP2P and
# future transports behave identically and prevents relay loops at the node
# layer.  The bound keeps long-running validators from retaining every tx id
# forever.
SEEN_TRANSACTION_CACHE_MAX_SIZE = 10_000


class NodeError(Exception):
    """Raised when a node-level operation fails."""


class Node:
    """
    A single PoA blockchain node.

    Instantiate via Node.from_config() for production use, or
    construct directly (with all dependencies injected) for testing.
    """

    def __init__(
        self,
        config: NodeConfig,
        blockchain: Blockchain,
        keypair: MLDSAKeyPair,
        mempool: Mempool,
        consensus: Consensus,
        p2p: P2PTransport,
        ml_dsa: Optional[MLDSA] = None,
        state_replayer: Optional[StateReplayer] = None,
    ) -> None:
        self._config = config
        self._blockchain = blockchain
        self._keypair = keypair
        self._mempool = mempool
        self._consensus = consensus
        self._p2p = p2p
        self._ml_dsa = ml_dsa or MLDSA()

        # Relay transactionnel : une transaction acceptée localement ou
        # reçue d'un pair est retransmise une seule fois. Le verrou ne
        # protège que ce cache court ; le mempool reste la source de vérité
        # pour l'acceptation et les conflits de nonce.
        self._seen_transaction_ids: OrderedDict[bytes, None] = OrderedDict()
        self._seen_transaction_ids_lock = threading.Lock()

        # Round state is local liveness state for the next height. It is
        # reset after a block is committed; the selected round itself is
        # persisted and authenticated by Block when a proposal succeeds.
        self._proposal_round_lock = threading.Lock()
        # P2P callbacks run on transport threads while the production loop
        # may propose locally. Serialize the acceptance pipeline so two
        # concurrent proposals cannot both pass the tip-height check.
        self._accept_lock = threading.RLock()
        self._round_height = self._blockchain.height + 1
        self._proposal_round = 0
        self._round_started_at: Optional[float] = None

        # L'etat EVM n'est jamais absent. Un Node sans etat produirait
        # des blocs a racine vide impossibles a distinguer de blocs
        # legitimement vides : la divergence resterait muette. On en
        # construit donc toujours un, depuis la configuration -- seule
        # source de verite du chemin de donnees.
        self._state_replayer = state_replayer or StateReplayer(
            ChainStorage(config.data_dir)
        )

        # Rejeu au demarrage plutot qu'au premier tour de proposition :
        # le round-robin n'attend pas, et un noeud occupe a rattraper
        # son retard au mauvais moment raterait son tour. Mesure : de
        # 0,04 ms (bloc vide) a 1 ms (bloc d'une transaction) par bloc.
        self._state_replayer.sync_to(self._blockchain.height)

        self._p2p.register_transaction_handler(self._on_transaction_received)
        self._p2p.register_block_handler(self._on_block_received)
        self._p2p.register_sync_providers(
            self._local_height_for_sync,
            self._blocks_for_sync,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: NodeConfig,
        p2p: Optional[P2PTransport] = None,
        ml_dsa: Optional[MLDSA] = None,
    ) -> "Node":
        """
        Build a Node from a NodeConfig.

        Loads or generates the validator keypair, opens (or creates)
        the blockchain, verifies that the local validator address
        belongs to authorized_validators, and wires all components.

        Args:
            config: Loaded NodeConfig.
            p2p: Transport implementation. Defaults to NullP2P (for
                the mono-node stage).
            ml_dsa: Optional MLDSA instance (shared across all
                components for testability).
        """
        signer = ml_dsa or MLDSA()

        keypair = load_or_generate_validator_keys(config.validator_key_dir, signer)
        local_address = public_key_to_address(keypair.public_key)

        if local_address not in config.authorized_validators:
            raise NodeError(
                f"local validator address {local_address.hex()} is not "
                "in authorized_validators; check node configuration"
            )

        storage = ChainStorage(config.data_dir)
        blockchain = Blockchain.open(
            storage,
            validator_public_key=config.genesis_validator_public_key,
            timestamp=config.genesis_timestamp,
        )

        mempool = Mempool(ml_dsa=signer, max_size=config.mempool_max_size)

        consensus = Consensus(
            authorized_validators=config.authorized_validators,
            local_address=local_address,
        )

        transport = p2p or NullP2P()

        return cls(
            config=config,
            blockchain=blockchain,
            keypair=keypair,
            mempool=mempool,
            consensus=consensus,
            p2p=transport,
            ml_dsa=signer,
        )

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def height(self) -> int:
        """Current chain tip height."""
        return self._blockchain.height

    @property
    def local_address(self) -> bytes:
        """20-byte PoA address of this node's validator."""
        return public_key_to_address(self._keypair.public_key)

    @property
    def mempool_size(self) -> int:
        """Number of transactions currently in the mempool."""
        # Keep this observation atomic with block acceptance.  The chain
        # height is advanced before the included transactions are removed;
        # without the same lock, callers could observe that intermediate
        # state and mistake an in-flight commit for a reinserted tx.
        with self._accept_lock:
            return self._mempool.size()

    @property
    def genesis_hash(self) -> bytes:
        """
        Hash of the genesis block.

        Read-only accessor. All nodes on the network must report the
        same value; a mismatch means the configs disagree and no block
        will ever be accepted across nodes. Exposed so that runtime
        entry points can log it without reaching into private state.
        """
        return self._blockchain.genesis_block.block_hash

    @property
    def tip_hash(self) -> bytes:
        """Hash of the current chain tip. Read-only accessor."""
        return self._blockchain.get_latest_block().block_hash

    def _sync_round_height_locked(self, height: int) -> None:
        """Reset local timeout state when the next height changes."""
        if self._round_height != height:
            self._round_height = height
            self._proposal_round = 0
            self._round_started_at = None

    def current_round(self, height: Optional[int] = None) -> int:
        """Return the local proposal round for the next block height."""
        requested_height = self._blockchain.height + 1 if height is None else height
        with self._proposal_round_lock:
            self._sync_round_height_locked(requested_height)
            return self._proposal_round

    def is_my_turn(self, height: int) -> bool:
        """
        Whether this node is the expected proposer at `height` in the
        node's current timeout round.
        """
        return self._consensus.is_local_node_turn(
            height, self.current_round(height)
        )

    def advance_round_if_timed_out(
        self,
        height: int,
        timeout_seconds: float,
        *,
        now: Optional[float] = None,
    ) -> bool:
        """
        Advance the proposal round once work has waited long enough.

        No timer runs while the mempool is empty, preserving the
        on-demand rule. Every active node that sees the same pending
        height applies the same timeout policy; the next round's
        proposer is determined by Consensus, not chosen arbitrarily.
        The optional monotonic `now` exists for deterministic tests.
        """
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise NodeError("round timeout must be a positive number")

        current_time = time.monotonic() if now is None else now
        with self._proposal_round_lock:
            self._sync_round_height_locked(height)

            if self._mempool.size() == 0:
                self._round_started_at = None
                return False

            if self._round_started_at is None:
                self._round_started_at = current_time
                return False

            if current_time - self._round_started_at < timeout_seconds:
                return False

            self._proposal_round += 1
            self._round_started_at = current_time
            logger.info(
                "proposal timeout at height %d; advancing to round %d",
                height,
                self._proposal_round,
            )
            return True

    def _note_work_available(self) -> None:
        """Start the timeout clock when the first pending tx is available."""
        with self._proposal_round_lock:
            self._sync_round_height_locked(self._blockchain.height + 1)
            if self._round_started_at is None and self._mempool.size() > 0:
                self._round_started_at = time.monotonic()

    def _check_incoming_round(self, block: Block) -> None:
        """Reject an authenticated proposal from an already-abandoned round."""
        with self._proposal_round_lock:
            self._sync_round_height_locked(block.height)
            if block.round < self._proposal_round:
                raise NodeError(
                    f"block rejected: stale proposal round {block.round}; "
                    f"local round is {self._proposal_round}"
                )

    def _observe_incoming_round(self, block: Block) -> None:
        """Adopt a higher round after the complete block has been verified."""
        with self._proposal_round_lock:
            self._sync_round_height_locked(block.height)
            if block.round < self._proposal_round:
                raise NodeError(
                    f"block rejected: stale proposal round {block.round}; "
                    f"local round is {self._proposal_round}"
                )
            if block.round > self._proposal_round:
                self._proposal_round = block.round
                self._round_started_at = time.monotonic()

    # ------------------------------------------------------------------
    # Transaction handling
    # ------------------------------------------------------------------

    def _remember_transaction_if_new(self, tx_id: bytes) -> bool:
        """Record a transaction id and return whether it was new.

        The cache is deliberately bounded. It is an anti-relay-loop
        mechanism, not a replacement for the mempool or chain history.
        """
        with self._seen_transaction_ids_lock:
            if tx_id in self._seen_transaction_ids:
                return False
            self._seen_transaction_ids[tx_id] = None
            while len(self._seen_transaction_ids) > SEEN_TRANSACTION_CACHE_MAX_SIZE:
                self._seen_transaction_ids.popitem(last=False)
            return True

    def _transaction_is_committed(self, tx_id: bytes) -> bool:
        """Return whether a transaction is already present in the chain."""
        for height in range(self._blockchain.height + 1):
            block = self._blockchain.get_block(height)
            if block is not None and any(tx.tx_id == tx_id for tx in block.transactions):
                return True
        return False

    def receive_transaction(self, transaction: Transaction) -> None:
        """
        Accept a transaction from an external client or local caller.

        An accepted transaction is placed in this node's mempool and
        immediately broadcast to all peers. The receiving node is an
        ingress point; it does not need to be the next proposer.

        Raises:
            MempoolError: If the transaction is rejected (invalid,
                duplicate, already committed, nonce conflict, or mempool
                full).
        """
        # Serialize the chain-membership check with block acceptance. A
        # transaction broadcast just before a commit must not be able to
        # re-enter the mempool after the commit has removed it.
        with self._accept_lock:
            if self._transaction_is_committed(transaction.tx_id):
                raise MempoolError(
                    f"transaction already committed: {transaction.tx_id.hex()}"
                )
            self._mempool.add_transaction(transaction)
            self._remember_transaction_if_new(transaction.tx_id)
            self._note_work_available()
            logger.info(
                "BENCHMARK_ACCEPT accept_wall_ns=%d tx_id=%s source=local "
                "mempool_size=%d",
                time.time_ns(),
                transaction.tx_id.hex(),
                self._mempool.size(),
            )
        self._p2p.broadcast_transaction(transaction)

    # ------------------------------------------------------------------
    # Block production
    # ------------------------------------------------------------------

    def propose_block(self, timestamp: Optional[int] = None) -> Block:
        """Serialize proposal construction with transaction/block callbacks."""
        with self._accept_lock:
            return self._propose_block_locked(timestamp)

    def _propose_block_locked(self, timestamp: Optional[int] = None) -> Block:
        """
        Build, validate, persist and broadcast a new block if it is
        this node's turn to propose.

        Raises:
            NodeError: If it is not this node's turn, or if the
                candidate block fails its own acceptance check (which
                would indicate a bug in block construction).
        """
        ts = timestamp if timestamp is not None else int(time.time())

        # Rattrapage des blocs produits par les autres validateurs
        # depuis notre dernier tour. En round-robin a 3 noeuds, il y en
        # a normalement deux, soit environ 2 ms. Sans effet si l'etat
        # est deja a jour.
        self._state_replayer.sync_to(self._blockchain.height)

        # Les transactions sont choisies UNE SEULE FOIS, puis servent a
        # la fois au calcul de la racine et a la construction du bloc.
        # Les relire depuis le mempool pour la seconde etape laisserait
        # une transaction arrivee entre-temps rendre la racine annoncee
        # incoherente avec le contenu du bloc.
        selected = self._select_within_gas_limit(self._mempool.get_pending())

        projection = self._state_replayer.root_after(
            selected,
            block_number=self._blockchain.height + 1,
            timestamp=ts,
            coinbase=self.local_address,
        )
        state_root = projection.state_root
        proposal_round = self.current_round(self._blockchain.height + 1)

        try:
            candidate = self._consensus.build_candidate_block(
                blockchain=self._blockchain,
                mempool=self._mempool,
                local_public_key=self._keypair.public_key,
                local_secret_key=self._keypair.secret_key,
                timestamp=ts,
                ml_dsa=self._ml_dsa,
                state_root=state_root,
                transactions=selected,
                round=proposal_round,
            )
        except ConsensusError as exc:
            raise NodeError(f"cannot propose block: {exc}") from exc

        # Self-check: the block we just built must pass the same
        # acceptance pipeline as any externally received block.
        self._accept_block(candidate, broadcast=True)
        return candidate

    @staticmethod
    def _select_within_gas_limit(
        transactions: "Sequence[Transaction]",
    ) -> list[Transaction]:
        """
        Ne retenir que les transactions qui tiennent dans le pool de gas
        du bloc.

        POURQUOI ICI ET PAS DANS consensus.py. Le module de consensus
        ne doit pas dependre de src.evm (donc de py-evm) pour ce qui
        n'est qu'une question d'ordonnancement ; c'est deja la raison
        pour laquelle state_root lui est passe en parametre. Node
        possede l'etat EVM, c'est donc lui qui applique la regle.

        POURQUOI C'EST INDISPENSABLE. Le receveur refuse un bloc des
        qu'une transaction annonce plus de gas qu'il n'en reste dans le
        pool. Si le producteur ne filtrait pas ici avec la MEME regle,
        un noeud parfaitement honnete fabriquerait des blocs que ses
        pairs rejetteraient -- et, comme propose_block passe par le
        meme pipeline, il rejetterait meme son propre bloc.

        Le critere est volontairement identique a celui de
        EVMExecutor.execute_block : borne sur le gas annonce de la
        prochaine transaction, budget consomme estime au pire cas
        (gas_limit). Le producteur est donc CONSERVATEUR -- il peut
        laisser un peu de place inutilisee, jamais en prendre trop.
        Sous-remplir un bloc est benin ; en produire un invalide ne
        l'est pas.

        La transaction trop grosse est sautee, pas arretee net : une
        transaction suivante plus petite peut encore tenir. Elle reste
        dans le mempool pour un bloc ulterieur.
        """
        retenues: list[Transaction] = []
        budget = BLOCK_GAS_LIMIT

        for transaction in transactions:
            if transaction.gas_limit > budget:
                logger.debug(
                    "tx 0x%s deferred: announces %d gas, %d left in block",
                    transaction.tx_id.hex()[:16],
                    transaction.gas_limit,
                    budget,
                )
                continue
            retenues.append(transaction)
            budget -= transaction.gas_limit

        return retenues

    # ------------------------------------------------------------------
    # Block reception (from P2P)
    # ------------------------------------------------------------------

    def receive_block(self, block: Block) -> None:
        """
        Accept a block received from a peer.

        Silently ignores blocks at or below the current tip height
        (already known / obsolete), before paying any validation cost.

        If the block is too far ahead (a gap: we are missing one or
        more intermediate blocks), it cannot be linked to our tip and
        is dropped -- but a synchronisation request is issued so the
        missing range can be fetched. Without this, a node that misses
        a single block would stay stuck forever.

        Raises:
            NodeError: If the block fails validation or consensus.
        """
        current_height = self._blockchain.height

        if block.height <= current_height:
            return

        if block.height > current_height + 1:
            # Trou dans la chaine : ce bloc ne peut pas etre chaine a
            # notre tip. On ne le conserve pas (aucun buffer
            # d'orphelins a ce stade) : on demande les blocs manquants
            # et il nous reviendra dans l'ordre.
            self._p2p.request_blocks_from(current_height + 1)
            return

        self._accept_block(block, broadcast=True)

    # ------------------------------------------------------------------
    # Core acceptance pipeline (SINGLE point of call to add_block)
    # ------------------------------------------------------------------

    def _accept_block(self, block: Block, *, broadcast: bool) -> None:
        """Serialize block acceptance across the production and P2P threads."""
        with self._accept_lock:
            self._accept_block_locked(block, broadcast=broadcast)

    def _accept_block_locked(self, block: Block, *, broadcast: bool) -> None:
        """
        THE unique path through which any block enters the chain.

        Pipeline (fail-fast order, per fixed architecture decision):
            1. validate_block_for_acceptance  (structure + chain link
                                               + auth + ML-DSA sigs)
            2. consensus.is_expected_proposer (turn check)
            2bis. state_root verification     (EVM replay)
            3. blockchain.add_block           (ONLY call site)
            4. mempool.remove_transactions    (post-acceptance cleanup)
            5. p2p.broadcast_block            (if broadcast=True)

        ORDERING. Step 2bis comes last among the checks because it is
        the only expensive one: replaying a block costs ~1 ms per
        transaction, against 0.038 ms for an ML-DSA signature
        verification. A forged or out-of-turn block is therefore
        discarded by steps 1-2 without ever reaching the EVM.

        It runs BEFORE step 3, never after: a block whose state is
        wrong must not be persisted, and must not be rebroadcast to
        peers (step 5). There is no way to retract either.

        The genesis block never travels through this path -- it is
        installed directly by Blockchain.create_new()/open() -- so no
        special case is needed for it here.

        Raises:
            NodeError: On any failure in steps 1-3, including a
                state_root mismatch.
        """
        # Step 1: structural + cryptographic validation.
        try:
            validate_block_for_acceptance(
                block=block,
                previous_block=self._blockchain.get_latest_block(),
                authorized_validators=self._config.authorized_validators,
                ml_dsa=self._ml_dsa,
            )
        except ValidatorError as exc:
            raise NodeError(f"block rejected by validator: {exc}") from exc

        # Step 2: PoA turn check.
        if not self._consensus.is_expected_proposer(block):
            raise NodeError(
                f"block rejected: validator {block.validator.hex()} was "
                f"not the expected proposer at height {block.height}"
            )

        # A late proposal from a round that this node already abandoned
        # must not resurrect the old proposer. Check this only after the
        # block signature and proposer have been authenticated; otherwise
        # an invalid packet could move local liveness state.
        self._check_incoming_round(block)

        # Step 2bis: verify the announced state_root by replaying the
        # block ourselves. Until this check existed, state_root was a
        # signed comment: an authorised validator could announce any
        # 32 bytes and every peer would accept them.
        self._verify_state_root(block)

        # Adopt a higher authenticated round only after all expensive
        # validation has succeeded. A valid commit resets the next-height
        # state to round zero below.
        self._observe_incoming_round(block)

        # Step 3: persist (ONLY call to blockchain.add_block in node/).
        try:
            self._blockchain.add_block(block)
        except BlockchainError as exc:
            raise NodeError(f"block could not be added to chain: {exc}") from exc

        # Commit the EVM state, now that the block is durably in the
        # chain. Deliberately AFTER add_block: advancing the state for
        # a block that failed to persist would leave this node
        # silently diverging from its peers.
        self._commit_state(block)

        # Événement structuré sans secret pour les campagnes B2/B4. Le
        # timestamp est pris sur l'horloge murale locale du nœud : il ne
        # doit pas être soustrait directement aux horodatages d'une autre
        # VM tant que les horloges ne sont pas synchronisées. Les tx_id,
        # block_hash et state_root sont des identifiants publics du journal
        # de chaîne, jamais des clés ou des plaintexts.
        logger.info(
            "BENCHMARK_COMMIT commit_wall_ns=%d height=%d block_hash=%s "
            "state_root=%s tx_count=%d tx_ids=%s",
            time.time_ns(),
            block.height,
            block.block_hash.hex(),
            block.state_root.hex(),
            len(block.transactions),
            ",".join(tx.tx_id.hex() for tx in block.transactions) or "-",
        )

        # Step 4: remove included transactions from mempool and start a
        # fresh timeout window for any transactions that remain at the
        # next height.
        self._mempool.remove_transactions(tx.tx_id for tx in block.transactions)
        with self._proposal_round_lock:
            self._round_height = block.height + 1
            self._proposal_round = 0
            self._round_started_at = (
                time.monotonic() if self._mempool.size() > 0 else None
            )

        # Step 5: broadcast to peers (only if requested).
        if broadcast:
            self._p2p.broadcast_block(block)

    def _verify_state_root(self, block: Block) -> None:
        """
        Reject the block unless its announced state_root is the one we
        obtain by replaying it ourselves.

        This is what turns state_root from a claim into a guarantee.
        The block is replayed on a throwaway view (root_after), so
        nothing is committed here: at this point the block may still
        be refused by add_block.

        Raises:
            NodeError: If the root differs, if the block cannot be
                replayed, or if it exceeds the block gas limit.
        """
        try:
            self._state_replayer.sync_to(block.height - 1)
            projection = self._state_replayer.root_after(
                block.transactions,
                block_number=block.height,
                timestamp=block.timestamp,
                coinbase=block.validator,
            )
        except EVMError as exc:
            # Covers a gas-limit overrun and any replay failure. Either
            # way we cannot vouch for this block, so we refuse it
            # rather than accept it unverified.
            logger.error(
                "BLOCK REJECTED: cannot verify state at height %d from "
                "validator %s: %s",
                block.height,
                block.validator.hex(),
                exc,
            )
            raise NodeError(
                f"block rejected: state verification failed at height "
                f"{block.height}: {exc}"
            ) from exc

        if projection.state_root != block.state_root:
            # An authorised validator, whose signature checked out,
            # announced a state it did not produce. This is either a
            # consensus bug or an attack -- never routine. Logged at
            # ERROR with a distinctive wording so it stands out from
            # ordinary rejections.
            logger.error(
                "BLOCK REJECTED: STATE ROOT MISMATCH at height %d. "
                "Validator %s announced 0x%s but replay yields 0x%s. "
                "An authorised validator signed a state it did not "
                "produce: suspect a consensus bug or a malicious peer.",
                block.height,
                block.validator.hex(),
                block.state_root.hex(),
                projection.state_root.hex(),
            )
            raise NodeError(
                f"block rejected: state_root mismatch at height "
                f"{block.height}: announced 0x{block.state_root.hex()}, "
                f"computed 0x{projection.state_root.hex()}"
            )

    def _commit_state(self, block: Block) -> None:
        """
        Advance the EVM state over a block that is now in the chain.

        Called only after add_block has succeeded. A failure here means
        the chain and the state have drifted apart, which no later
        block can repair: the node would compute wrong roots from now
        on and diverge from its peers. It is raised rather than
        swallowed.
        """
        try:
            self._state_replayer.sync_to(block.height)
        except EVMError as exc:
            logger.error(
                "STATE DESYNCHRONISED: block %d is in the chain but "
                "could not be applied to the EVM state: %s. This node "
                "can no longer compute correct state roots.",
                block.height,
                exc,
            )
            raise NodeError(
                f"block {block.height} was added to the chain but the "
                f"EVM state could not be advanced: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Sync providers (called by the transport, PHASE 2)
    # ------------------------------------------------------------------

    def _local_height_for_sync(self) -> int:
        """Current tip height, so the transport knows what to request."""
        return self._blockchain.height

    def _blocks_for_sync(self, from_height: int, max_count: int) -> list[Block]:
        """
        Return the blocks we hold from `from_height` onwards, capped at
        `max_count`, to answer a peer that is behind.

        Read-only: serving a peer never mutates local state. An
        out-of-range request simply yields an empty list rather than
        an error -- a peer ahead of us is a normal situation, not a
        fault.
        """
        if from_height < 0 or max_count <= 0:
            return []

        last_height = min(from_height + max_count - 1, self._blockchain.height)

        blocks: list[Block] = []
        for height in range(from_height, last_height + 1):
            block = self._blockchain.get_block(height)
            if block is None:
                break  # trou local inattendu : on sert ce qu'on a
            blocks.append(block)

        return blocks

    # ------------------------------------------------------------------
    # P2P callbacks (registered in __init__)
    # ------------------------------------------------------------------

    def _on_transaction_received(self, transaction: Transaction) -> None:
        """
        Called by the P2P layer when a transaction arrives from a peer.

        A valid, new transaction is accepted into the local mempool and
        re-broadcast. The bounded tx-id cache stops the transaction from
        circulating forever in a triangle or line topology. Invalid,
        duplicate, conflicting, or over-capacity transactions are silently
        dropped at the peer boundary.
        """
        # The block-acceptance lock closes the race where a transaction
        # frame was already in flight when its block committed.
        with self._accept_lock:
            if self._transaction_is_committed(transaction.tx_id):
                return
            try:
                self._mempool.add_transaction(transaction)
            except MempoolError:
                logger.info(
                    "BENCHMARK_REJECT reject_wall_ns=%d tx_id=%s "
                    "source=p2p reason=mempool_rejection",
                    time.time_ns(),
                    transaction.tx_id.hex(),
                )
                return  # invalid/duplicate/conflicting tx from peer

            # Ne marquer qu'après l'acceptation locale : une transaction
            # invalide ne doit pas consommer une entrée du cache anti-relais.
            self._note_work_available()
            should_broadcast = self._remember_transaction_if_new(transaction.tx_id)
            logger.info(
                "BENCHMARK_ACCEPT accept_wall_ns=%d tx_id=%s source=p2p "
                "mempool_size=%d",
                time.time_ns(),
                transaction.tx_id.hex(),
                self._mempool.size(),
            )

        if should_broadcast:
            self._p2p.broadcast_transaction(transaction)

    def _on_block_received(self, block: Block) -> None:
        """
        Called by the P2P layer when a block arrives from a peer.
        Silently drops invalid or obsolete blocks.
        """
        try:
            self.receive_block(block)
        except NodeError:
            pass  # invalid block from peer: silently ignore
