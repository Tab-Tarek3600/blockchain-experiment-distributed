"""
P2P transport abstraction.

node.py depends only on the P2PTransport interface, never on a
concrete transport implementation. This dependency inversion means a
future real network transport (sockets, HTTP) can replace NullP2P /
InMemoryP2P without any change to node.py.

Two implementations are provided for this stage:
    - NullP2P: no-op transport for a single, isolated node. Handlers
      can be registered but are never invoked (there are no peers).
    - InMemoryP2P: delivers messages directly to connected peer
      instances' registered handlers, in-process. Useful to simulate
      2-3 "nodes" communicating without opening real sockets, before
      a real network transport is implemented.

Deliberately out of scope for this stage:
    - peer discovery
    - message signing/authentication at the transport level
    - retry/reliability guarantees

Transaction re-broadcast / gossip is implemented by node.py, not by
this transport abstraction. A node accepts a valid transaction into its
mempool, records its tx_id in a bounded cache, and re-broadcasts it once.
The concrete TCP transport also keeps its own cache, so a triangle or a
line topology cannot circulate a transaction forever.

On propagation loops: broadcast_transaction()/broadcast_block() only
deliver a message to currently connected peers. The decision to
re-broadcast a received transaction is deliberately made by node.py,
where mempool validation is available.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

from src.blockchain.block import Block
from src.blockchain.transaction import Transaction

TransactionHandler = Callable[[Transaction], None]
BlockHandler = Callable[[Block], None]

# Answers a peer's block request: (from_height, max_count) -> blocks.
BlockRangeProvider = Callable[[int, int], "list[Block]"]

# Returns the local chain tip height.
LocalHeightProvider = Callable[[], int]


class P2PTransport(ABC):
    """Abstract transport for broadcasting and receiving transactions/blocks."""

    @abstractmethod
    def broadcast_transaction(self, transaction: Transaction) -> None:
        """Send a transaction to all currently connected peers."""
        raise NotImplementedError

    @abstractmethod
    def broadcast_block(self, block: Block) -> None:
        """Send a block to all currently connected peers."""
        raise NotImplementedError

    @abstractmethod
    def register_transaction_handler(self, handler: TransactionHandler) -> None:
        """Register the callback invoked when a transaction is received."""
        raise NotImplementedError

    @abstractmethod
    def register_block_handler(self, handler: BlockHandler) -> None:
        """Register the callback invoked when a block is received."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Chain synchronisation (PHASE 2)
    #
    # Deliberately NOT abstract: a transport that cannot synchronise
    # (NullP2P: no peers; InMemoryP2P: instances share a process and
    # are connected before any block is produced) stays valid without
    # modification. Only a transport that can lose or miss blocks --
    # i.e. a real network one -- needs to override these.
    # ------------------------------------------------------------------

    def request_blocks_from(self, from_height: int) -> None:
        """
        Ask peers to send every block from `from_height` onwards.

        Fire-and-forget: blocks arrive later through the regular block
        handler, exactly like any other incoming block. Default
        implementation is a no-op.
        """
        return None

    def register_sync_providers(
        self,
        local_height: LocalHeightProvider,
        block_range: BlockRangeProvider,
    ) -> None:
        """
        Register the two callbacks a transport needs to synchronise.

        They are registered together because neither is useful alone:
            - local_height() -> current tip height, to know what to ask for
            - block_range(from_height, max_count) -> blocks, to answer peers

        Default implementation ignores them.
        """
        return None


class NullP2P(P2PTransport):
    """
    No-op transport for a single, isolated node (mono-node stage).

    Handlers can be registered, but since there are never any
    connected peers, broadcasts are silently dropped and handlers are
    never invoked from within this class.
    """

    def __init__(self) -> None:
        self._transaction_handler: Optional[TransactionHandler] = None
        self._block_handler: Optional[BlockHandler] = None

    def broadcast_transaction(self, transaction: Transaction) -> None:
        pass  # no peers to deliver to

    def broadcast_block(self, block: Block) -> None:
        pass  # no peers to deliver to

    def register_transaction_handler(self, handler: TransactionHandler) -> None:
        self._transaction_handler = handler

    def register_block_handler(self, handler: BlockHandler) -> None:
        self._block_handler = handler


class InMemoryP2P(P2PTransport):
    """
    In-process transport connecting InMemoryP2P instances directly.

    Useful for simulating a small network (2-3 nodes) within a single
    Python process, without sockets. Connecting two instances via
    connect() is symmetric: after A.connect(B), both A and B consider
    each other connected peers.
    """

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self._peers: dict[str, "InMemoryP2P"] = {}
        self._transaction_handler: Optional[TransactionHandler] = None
        self._block_handler: Optional[BlockHandler] = None

    def connect(self, peer: "InMemoryP2P") -> None:
        """
        Connect this instance to another InMemoryP2P instance
        (symmetric: both sides register each other as peers).

        Connecting to self, or connecting the same peer twice, is a
        no-op rather than an error.
        """
        if peer.node_id == self.node_id:
            return

        self._peers[peer.node_id] = peer
        peer._peers[self.node_id] = self

    def disconnect(self, peer: "InMemoryP2P") -> None:
        """Remove a symmetric connection, if it exists."""
        self._peers.pop(peer.node_id, None)
        peer._peers.pop(self.node_id, None)

    def connected_peer_ids(self) -> list[str]:
        """Return the node_ids of currently connected peers."""
        return list(self._peers.keys())

    def broadcast_transaction(self, transaction: Transaction) -> None:
        for peer in self._peers.values():
            peer._receive_transaction(transaction)

    def broadcast_block(self, block: Block) -> None:
        for peer in self._peers.values():
            peer._receive_block(block)

    def register_transaction_handler(self, handler: TransactionHandler) -> None:
        self._transaction_handler = handler

    def register_block_handler(self, handler: BlockHandler) -> None:
        self._block_handler = handler

    def _receive_transaction(self, transaction: Transaction) -> None:
        if self._transaction_handler is not None:
            self._transaction_handler(transaction)

    def _receive_block(self, block: Block) -> None:
        if self._block_handler is not None:
            self._block_handler(block)
