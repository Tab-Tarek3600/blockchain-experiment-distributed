"""
SocketP2P — transport TCP reel implementant P2PTransport.

Troisieme implementation de P2PTransport, aux cotes de NullP2P
(noeud isole) et InMemoryP2P (in-process). Contrairement a ces deux
la, SocketP2P permet a des noeuds situes dans des PROCESSUS et sur des
MACHINES differentes de communiquer.

node.py reste inchange dans sa logique : il ne connait que
l'interface P2PTransport et ignore tout de TCP.

--------------------------------------------------------------------
PROTOCOLE DE TRAME (framing)
--------------------------------------------------------------------
TCP est un flux d'octets, pas un protocole de messages : un recv()
peut retourner un fragment de message, ou plusieurs messages colles.
Chaque message est donc precede de sa longueur :

    [4 octets big-endian : longueur N] [N octets : JSON UTF-8]

_read_exactly() boucle jusqu'a avoir exactement le nombre d'octets
demande ; aucun code ici ne suppose qu'un recv() rend un message
complet.

Un plafond MAX_MESSAGE_BYTES protege contre un pair malveillant ou
bogue qui annoncerait une trame enorme.

--------------------------------------------------------------------
FORMAT DES MESSAGES
--------------------------------------------------------------------
    {"type": "hello", "node_id": "node1",
     "listen_host": "192.168.1.101", "listen_port": 5000}
    {"type": "tx",    "payload": <Transaction.to_dict()>}
    {"type": "block", "payload": <Block.to_dict()>}

La serialisation reutilise telles quelles les methodes to_dict() /
from_dict() deja presentes sur Block et Transaction, qui sont
explicitement documentees comme servant a la persistance ET a la
diffusion reseau. Aucune representation concurrente n'est introduite,
et aucune classe de src/blockchain/ n'est modifiee.

from_dict() passe par le constructeur, donc par __post_init__ ->
validate(). Toute trame corrompue leve BlockError/TransactionError,
qui est interceptee ici : le message est ignore, la connexion reste
ouverte, le processus ne meurt pas.

--------------------------------------------------------------------
STRATEGIE DE CONNEXION
--------------------------------------------------------------------
Chaque noeud, simultanement :
    - ECOUTE sur (host, port) et accepte les connexions entrantes ;
    - COMPOSE en boucle vers chaque pair de config.peers non encore
      connecte, avec re-essai periodique.

Le re-essai rend l'ordre de demarrage des 3 machines indifferent :
un noeud lance en premier finira par joindre les autres.

Consequence : les deux extremites peuvent se composer mutuellement
en meme temps et creer DEUX liens TCP pour une seule paire. C'est
traite a deux niveaux :

  1. Handshake HELLO + departage deterministe. A l'ouverture, chaque
     cote annonce son node_id. Si un lien vers ce node_id existe
     deja, il faut choisir lequel garder — et les DEUX extremites
     doivent faire le MEME choix, sinon chacune ferme un lien
     different et la paire se retrouve totalement deconnectee.

     Regle retenue (_prefers_outbound) : on conserve le lien
     compose par le noeud dont le node_id est le plus petit.
         self.node_id < remote_id  -> garder notre lien SORTANT
         self.node_id > remote_id  -> garder le lien ENTRANT
     Cette regle ne depend que des deux node_id, donc les deux cotes
     aboutissent au meme lien physique sans negociation.

  2. Deduplication par hash (ci-dessous). C'est le vrai filet de
     securite : meme si un lien double survit a une course, aucun
     message n'est traite ni propage deux fois.

Ce choix est deliberement plus simple qu'une election de lien
formelle : il est suffisant pour 3 noeuds et reste lisible.

--------------------------------------------------------------------
ANTI-BOUCLE DE BROADCAST
--------------------------------------------------------------------
Scenario a eviter :
    A diffuse X -> B recoit X, l'accepte, rediffuse X -> A recoit X,
    rediffuse X -> ... boucle infinie.

Un cache borne des identifiants deja vus (tx_id / block_hash) est
tenu par le transport. Un identifiant y est inscrit :
    - a l'EMISSION dans broadcast_*()
    - a la RECEPTION dans _handle_message()

Si l'identifiant est deja connu, le message entrant est ignore avant
meme d'appeler le handler. La boucle est donc coupee au premier
retour. Lorsqu'un handler applicatif relaie le message qu'il vient de
recevoir, un contexte thread-local autorise cette diffusion sortante
malgre la marque deja posee ; le pair qui recoit l'echo le filtre alors.
Cette exception est necessaire au relais multi-sauts
`node1 -> node2 -> node3`.

Note : node.py coupe deja la boucle pour les blocs (receive_block
ignore tout bloc de hauteur <= tip). La deduplication transport est
complementaire : elle couvre aussi les transactions, agit plus tot
(avant tout cout de validation) et ne depend d'aucune hypothese sur
le comportement de la couche superieure.

Le cache est borne (SEEN_CACHE_MAX_SIZE) et purge en FIFO, pour ne
pas croitre indefiniment dans un processus de longue duree.

--------------------------------------------------------------------
HORS PERIMETRE (assume)
--------------------------------------------------------------------
peer discovery, NAT traversal, TLS, chiffrement du transport,
authentification au niveau transport, gossip avance, synchronisation
de l'historique. Les blocs et transactions restent signes en ML-DSA
au niveau applicatif : le transport ne fait que convoyer des octets.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
from collections import OrderedDict
from typing import Iterable, Optional

from src.blockchain.block import Block, BlockError
from src.blockchain.transaction import Transaction, TransactionError
from src.node.p2p import (
    BlockHandler,
    BlockRangeProvider,
    LocalHeightProvider,
    P2PTransport,
    TransactionHandler,
)

logger = logging.getLogger(__name__)

LENGTH_PREFIX_FORMAT = ">I"
LENGTH_PREFIX_SIZE = 4

# Plafond de taille d'une trame (8 MiB). Un bloc plein reste tres en
# dessous ; au dela, on suppose un pair bogue ou hostile.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

# Nombre d'identifiants (tx_id/block_hash) memorises pour la
# deduplication anti-boucle.
SEEN_CACHE_MAX_SIZE = 10_000

MSG_HELLO = "hello"
MSG_TRANSACTION = "tx"
MSG_BLOCK = "block"

# Synchronisation de chaine (PHASE 2).
#   getblocks {from_height}  -> demande
#   blocks    {payload: [..]} -> reponse (liste ordonnee, peut etre vide)
MSG_GET_BLOCKS = "getblocks"
MSG_BLOCKS = "blocks"

# Nombre maximum de blocs par reponse `blocks`. Borne la taille de la
# trame bien en dessous de MAX_MESSAGE_BYTES : un noeud tres en retard
# rattrape en plusieurs allers-retours plutot qu'en une trame geante.
MAX_SYNC_BLOCKS = 50

ACCEPT_TIMEOUT_SECONDS = 0.5
DEFAULT_DIAL_INTERVAL_SECONDS = 2.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 3.0


class SocketP2PError(Exception):
    """Raised when the TCP transport cannot be started."""


def _encode_frame(message: dict) -> bytes:
    """Serialise un message en trame [longueur][JSON]."""
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")

    if len(payload) > MAX_MESSAGE_BYTES:
        raise SocketP2PError(
            f"outgoing message too large: {len(payload)} bytes "
            f"(max {MAX_MESSAGE_BYTES})"
        )

    return struct.pack(LENGTH_PREFIX_FORMAT, len(payload)) + payload


def _read_exactly(sock: socket.socket, size: int) -> Optional[bytes]:
    """
    Lit exactement `size` octets.

    Retourne None si le pair ferme la connexion avant la fin : c'est
    une fin de flux normale, pas une erreur.
    """
    chunks: list[bytes] = []
    remaining = size

    while remaining > 0:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)

    return b"".join(chunks)


def _read_frame(sock: socket.socket) -> Optional[dict]:
    """
    Lit une trame complete et retourne le message decode.

    Retourne None si la connexion est fermee proprement.
    Leve SocketP2PError si la trame est malformee (longueur
    aberrante, JSON invalide, racine non-objet).
    """
    header = _read_exactly(sock, LENGTH_PREFIX_SIZE)
    if header is None:
        return None

    (length,) = struct.unpack(LENGTH_PREFIX_FORMAT, header)

    if length == 0:
        raise SocketP2PError("received empty frame")

    if length > MAX_MESSAGE_BYTES:
        raise SocketP2PError(
            f"incoming frame too large: {length} bytes "
            f"(max {MAX_MESSAGE_BYTES})"
        )

    payload = _read_exactly(sock, length)
    if payload is None:
        raise SocketP2PError("connection closed mid-frame")

    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SocketP2PError(f"invalid JSON frame: {exc}") from exc

    if not isinstance(message, dict):
        raise SocketP2PError("frame root must be a JSON object")

    return message


class _Connection:
    """
    Un lien TCP etabli avec un pair identifie.

    Regroupe la socket, le verrou d'envoi et l'adresse d'ECOUTE
    annoncee par le pair dans son HELLO. Cette derniere est
    indispensable : pour une connexion entrante, getpeername() rend
    le port ephemere du client, pas le port sur lequel il ecoute. La
    boucle de composition ne pourrait donc jamais reconnaitre qu'un
    pair est deja relie et recomposerait indefiniment.
    """

    __slots__ = ("socket", "send_lock", "outbound", "listen_address")

    def __init__(self, sock, send_lock, outbound, listen_address):
        self.socket = sock
        self.send_lock = send_lock
        self.outbound = outbound
        self.listen_address = listen_address


class _SeenCache:
    """Cache FIFO borne d'identifiants deja vus (anti-boucle)."""

    def __init__(self, max_size: int = SEEN_CACHE_MAX_SIZE) -> None:
        self._max_size = max_size
        self._items: OrderedDict[bytes, None] = OrderedDict()
        self._lock = threading.Lock()

    def add_if_new(self, key: bytes) -> bool:
        """
        Enregistre `key`. Retourne True si elle etait inconnue,
        False si elle avait deja ete vue.
        """
        with self._lock:
            if key in self._items:
                return False
            self._items[key] = None
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)
            return True

    def __contains__(self, key: bytes) -> bool:
        with self._lock:
            return key in self._items

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class SocketP2P(P2PTransport):
    """
    Transport TCP pour un reseau de quelques noeuds.

    Cycle de vie :
        transport = SocketP2P(host, port, peers, node_id)
        transport.start()     # bind + listen + threads
        ...
        transport.stop()      # fermeture propre

    Thread-safe pour broadcast_* : l'envoi est protege par un verrou
    par connexion.
    """

    def __init__(
        self,
        host: str,
        port: int,
        peers: Iterable = (),
        node_id: str = "",
        dial_interval: float = DEFAULT_DIAL_INTERVAL_SECONDS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        self.host = host
        self.port = port
        self.node_id = node_id or f"{host}:{port}"

        # Accepte des PeerConfig (attributs .host/.port) ou des
        # tuples (host, port), pour rester testable sans NodeConfig.
        self._peer_addresses: list[tuple[str, int]] = []
        for peer in peers:
            if isinstance(peer, tuple):
                self._peer_addresses.append((peer[0], int(peer[1])))
            else:
                self._peer_addresses.append((peer.host, int(peer.port)))

        self._dial_interval = dial_interval
        self._connect_timeout = connect_timeout

        self._transaction_handler: Optional[TransactionHandler] = None
        self._block_handler: Optional[BlockHandler] = None
        self._block_range_provider: Optional[BlockRangeProvider] = None
        self._local_height_provider: Optional[LocalHeightProvider] = None

        self._server_socket: Optional[socket.socket] = None
        self._running = threading.Event()
        self._threads: list[threading.Thread] = []

        # node_id distant -> _Connection
        self._connections: dict[str, _Connection] = {}
        self._connections_lock = threading.RLock()

        # Adresses vers lesquelles une connexion sortante est en
        # cours (socket ouverte, HELLO pas encore echange). Sans ce
        # garde, la boucle de composition ouvrirait un nouveau lien a
        # chaque tour tant que le handshake n'est pas termine.
        self._dialing: set[tuple[str, int]] = set()

        self._seen = _SeenCache()
        # Lorsqu'un handler applicatif relaie le message qu'il vient de
        # recevoir, le tx_id/hash est déjà présent dans `_seen`. Ce
        # contexte permet cette unique sortie vers les pairs tout en
        # conservant le filtrage des échos sur les connexions entrantes.
        self._forwarding_ids = threading.local()

    # ------------------------------------------------------------------
    # P2PTransport : enregistrement des handlers
    # ------------------------------------------------------------------

    def register_transaction_handler(self, handler: TransactionHandler) -> None:
        self._transaction_handler = handler

    def register_block_handler(self, handler: BlockHandler) -> None:
        self._block_handler = handler

    def register_sync_providers(
        self,
        local_height: LocalHeightProvider,
        block_range: BlockRangeProvider,
    ) -> None:
        self._local_height_provider = local_height
        self._block_range_provider = block_range

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Demarre le serveur TCP et les threads.

        Responsabilite : ouvrir la socket d'ecoute, lancer le thread
        d'acceptation et le thread de composition vers les pairs.
        Ne bloque pas.
        """
        if self._running.is_set():
            return

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            server.bind((self.host, self.port))
            server.listen(16)
        except OSError as exc:
            server.close()
            raise SocketP2PError(
                f"cannot listen on {self.host}:{self.port}: {exc}"
            ) from exc

        server.settimeout(ACCEPT_TIMEOUT_SECONDS)
        self._server_socket = server
        self._running.set()

        self._spawn(self._accept_loop, "p2p-accept")
        if self._peer_addresses:
            self._spawn(self._dial_loop, "p2p-dial")

        logger.info(
            "SocketP2P %s listening on %s:%d (peers: %s)",
            self.node_id, self.host, self.port,
            ", ".join(f"{h}:{p}" for h, p in self._peer_addresses) or "none",
        )

    def stop(self) -> None:
        """
        Arret propre : ferme la socket d'ecoute, toutes les
        connexions, puis attend la fin des threads.

        Idempotent.
        """
        if not self._running.is_set():
            return

        self._running.clear()

        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None

        with self._connections_lock:
            connections = list(self._connections.values())
            self._connections.clear()

        for connection in connections:
            self._close_quietly(connection.socket)

        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._threads.clear()

        logger.info("SocketP2P %s stopped", self.node_id)

    def _spawn(self, target, name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    @staticmethod
    def _close_quietly(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Introspection (tests / diagnostic)
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def connected_peer_ids(self) -> list[str]:
        """node_ids des pairs actuellement connectes."""
        with self._connections_lock:
            return sorted(self._connections.keys())

    def connection_count(self) -> int:
        with self._connections_lock:
            return len(self._connections)

    # ------------------------------------------------------------------
    # Boucle d'acceptation (connexions entrantes)
    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        while self._running.is_set():
            server = self._server_socket
            if server is None:
                break
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue  # permet de reverifier _running
            except OSError:
                break  # socket fermee par stop()

            self._spawn_connection_thread(conn, addr, outbound=False)

    def _spawn_connection_thread(self, conn, addr, *, outbound: bool) -> None:
        thread = threading.Thread(
            target=self._handle_connection,
            args=(conn, addr, outbound),
            name=f"p2p-conn-{addr[0]}:{addr[1]}",
            daemon=True,
        )
        thread.start()
        self._threads.append(thread)

    # ------------------------------------------------------------------
    # Boucle de composition (connexions sortantes)
    # ------------------------------------------------------------------

    def _dial_loop(self) -> None:
        """
        Tente periodiquement de joindre les pairs non connectes.

        Le re-essai rend l'ordre de demarrage des noeuds indifferent.
        """
        while self._running.is_set():
            for host, port in self._peer_addresses:
                if not self._running.is_set():
                    break
                # Use a single deterministic dial owner for each
                # undirected pair.  Both nodes still list one another
                # as peers and both listen, so startup order remains
                # irrelevant; only the endpoint with the lower
                # address opens the outbound socket.  This removes the
                # transient double-link race during simultaneous
                # startup (the HELLO tie-break below remains a
                # defensive guard for callers that create links by
                # other means).
                if not self._is_dial_owner(host, port):
                    continue
                if self._has_connection_to_address(host, port):
                    continue
                self._try_dial(host, port)

            # attente interruptible par stop()
            self._running.wait(self._dial_interval)
            if not self._running.is_set():
                break

    def _is_dial_owner(self, host: str, port: int) -> bool:
        """Return whether this endpoint owns the outbound dial."""
        return (self.host, self.port) < (host, port)

    def _has_connection_to_address(self, host: str, port: int) -> bool:
        """
        Un lien existe-t-il deja vers ce pair ?

        La comparaison porte sur l'adresse d'ECOUTE annoncee dans le
        HELLO, pas sur getpeername() : pour un lien entrant, ce
        dernier rend le port ephemere du client et ne correspondrait
        jamais a l'adresse configuree.

        Un pair en cours de handshake n'est pas encore enregistre ;
        _dialing protege cette fenetre pour eviter d'ouvrir plusieurs
        connexions sortantes vers la meme adresse.
        """
        with self._connections_lock:
            if (host, port) in self._dialing:
                return True
            for connection in self._connections.values():
                if connection.listen_address == (host, port):
                    return True
        return False

    def _try_dial(self, host: str, port: int) -> None:
        with self._connections_lock:
            self._dialing.add((host, port))

        try:
            conn = socket.create_connection(
                (host, port), timeout=self._connect_timeout
            )
        except OSError:
            with self._connections_lock:
                self._dialing.discard((host, port))
            return  # pair pas encore la : on reessaiera

        conn.settimeout(None)
        self._spawn_connection_thread(conn, (host, port), outbound=True)

    # ------------------------------------------------------------------
    # Gestion d'une connexion
    # ------------------------------------------------------------------

    def _prefers_outbound(self, remote_id: str) -> bool:
        """
        En cas de lien double avec `remote_id`, faut-il garder NOTRE
        lien sortant ?

        Regle : le noeud au node_id le plus petit est celui dont la
        connexion sortante est conservee. Les deux extremites
        evaluent cette expression sur le meme couple de node_id et
        obtiennent des reponses complementaires : l'une garde son
        sortant, l'autre garde son entrant. C'est ce qui evite que
        les deux cotes ferment chacun un lien different et se
        retrouvent sans aucune connexion.
        """
        return self.node_id < remote_id

    def _handle_connection(self, conn: socket.socket, addr, outbound: bool) -> None:
        """
        Handshake HELLO puis boucle de lecture jusqu'a deconnexion.

        Toute erreur reseau ou de protocole ferme cette connexion
        seulement : ni le thread principal ni les autres connexions
        ne sont affectes.
        """
        send_lock = threading.Lock()
        remote_id: Optional[str] = None
        registered = False

        try:
            with send_lock:
                conn.sendall(_encode_frame({
                    "type": MSG_HELLO,
                    "node_id": self.node_id,
                    "listen_host": self.host,
                    "listen_port": self.port,
                }))

            hello = _read_frame(conn)
            if hello is None or hello.get("type") != MSG_HELLO:
                logger.warning("peer %s: missing HELLO, dropping", addr)
                return

            remote_id = str(hello.get("node_id") or f"{addr[0]}:{addr[1]}")

            # Adresse d'ecoute annoncee par le pair. Pour un lien
            # sortant, on connait deja l'adresse composee et on la
            # garde : c'est celle qui figure dans la config locale,
            # donc celle que la boucle de dial comparera.
            if outbound:
                listen_address = (addr[0], int(addr[1]))
            else:
                try:
                    listen_address = (
                        str(hello.get("listen_host") or addr[0]),
                        int(hello.get("listen_port") or 0),
                    )
                except (TypeError, ValueError):
                    listen_address = (addr[0], 0)

            if remote_id == self.node_id:
                logger.warning("peer %s announced our own node_id, dropping", addr)
                return

            superseded: Optional[socket.socket] = None

            with self._connections_lock:
                existing = self._connections.get(remote_id)

                if existing is not None and existing.outbound == outbound:
                    # Meme direction : ce n'est pas une course
                    # entrant/sortant mais un doublon pur. Le lien
                    # deja en place reste, le nouveau est ferme.
                    logger.debug("redundant %s link to %s, dropping",
                                 "outbound" if outbound else "inbound", remote_id)
                    return

                if existing is not None:
                    # Lien double (course de composition mutuelle).
                    # Departage deterministe : les deux extremites
                    # appliquent la meme regle et gardent donc le
                    # meme lien physique.
                    if outbound == self._prefers_outbound(remote_id):
                        # Celui-ci est le lien a conserver : il
                        # remplace celui deja enregistre.
                        superseded = existing.socket
                        self._connections[remote_id] = _Connection(
                            conn, send_lock, outbound, listen_address
                        )
                        registered = True
                    else:
                        logger.debug(
                            "duplicate link to %s, dropping %s connection",
                            remote_id, "outbound" if outbound else "inbound",
                        )
                        return
                else:
                    self._connections[remote_id] = _Connection(
                        conn, send_lock, outbound, listen_address
                    )
                    registered = True

            if superseded is not None:
                self._close_quietly(superseded)

            logger.info(
                "SocketP2P %s connected to %s (%s)",
                self.node_id, remote_id, "outbound" if outbound else "inbound",
            )

            # Un nouveau pair est peut-etre plus avance que nous : on
            # lui demande la suite de la chaine. C'est ce qui permet a
            # un noeud demarre en retard, ou redemarre, de rattraper.
            # Sans fournisseur de hauteur locale, on ne demande rien.
            self._request_sync_from_peer(remote_id)

            while self._running.is_set():
                try:
                    message = _read_frame(conn)
                except SocketP2PError as exc:
                    logger.warning("peer %s: protocol error: %s", remote_id, exc)
                    break
                except OSError:
                    break

                if message is None:
                    break  # deconnexion propre du pair

                self._handle_message(message, remote_id)

        except OSError as exc:
            logger.debug("peer %s: connection error: %s", addr, exc)
        except Exception:  # pragma: no cover - filet de securite thread
            logger.exception("peer %s: unexpected error", addr)
        finally:
            if outbound:
                with self._connections_lock:
                    self._dialing.discard((addr[0], int(addr[1])))
            if registered and remote_id is not None:
                with self._connections_lock:
                    existing = self._connections.get(remote_id)
                    if existing is not None and existing.socket is conn:
                        del self._connections[remote_id]
            self._close_quietly(conn)
            if registered:
                logger.info("SocketP2P %s disconnected from %s",
                            self.node_id, remote_id)

    # ------------------------------------------------------------------
    # Traitement des messages entrants
    # ------------------------------------------------------------------

    def _handle_message(self, message: dict, remote_id: Optional[str]) -> None:
        """
        Decode et dispatche un message.

        Un message invalide est journalise et ignore : il ne ferme pas
        la connexion et ne remonte jamais d'exception dans le thread
        de lecture.
        """
        msg_type = message.get("type")
        payload = message.get("payload")

        if msg_type == MSG_TRANSACTION:
            if not isinstance(payload, dict):
                logger.warning("peer %s: tx payload is not an object", remote_id)
                return
            try:
                transaction = Transaction.from_dict(payload)
            except (TransactionError, TypeError, AttributeError) as exc:
                logger.warning("peer %s: invalid transaction: %s", remote_id, exc)
                return

            if not self._seen.add_if_new(transaction.tx_id):
                return  # deja vu : anti-boucle

            handler = self._transaction_handler
            if handler is not None:
                self._dispatch_with_forwarding(
                    handler, transaction, "transaction", transaction.tx_id
                )

        elif msg_type == MSG_BLOCK:
            if not isinstance(payload, dict):
                logger.warning("peer %s: block payload is not an object", remote_id)
                return
            try:
                block = Block.from_dict(payload)
            except (BlockError, TransactionError, TypeError, AttributeError) as exc:
                logger.warning("peer %s: invalid block: %s", remote_id, exc)
                return

            if not self._seen.add_if_new(block.block_hash):
                return  # deja vu : anti-boucle

            handler = self._block_handler
            if handler is not None:
                self._dispatch_with_forwarding(
                    handler, block, "block", block.block_hash
                )

        elif msg_type == MSG_GET_BLOCKS:
            self._handle_get_blocks(message, remote_id)

        elif msg_type == MSG_BLOCKS:
            self._handle_blocks(payload, remote_id)

        elif msg_type == MSG_HELLO:
            logger.debug("peer %s: duplicate HELLO ignored", remote_id)

        else:
            logger.warning("peer %s: unknown message type %r", remote_id, msg_type)

    # ------------------------------------------------------------------
    # Synchronisation de chaine
    # ------------------------------------------------------------------

    def _handle_get_blocks(self, message: dict, remote_id: str) -> None:
        """
        Un pair demande les blocs a partir d'une hauteur donnee.

        La reponse est envoyee UNIQUEMENT au demandeur (jamais diffusee) :
        les autres pairs n'ont aucune raison de la recevoir.
        """
        from_height = message.get("from_height")
        if not isinstance(from_height, int) or from_height < 0:
            logger.warning(
                "peer %s: invalid getblocks from_height %r", remote_id, from_height
            )
            return

        provider = self._block_range_provider
        if provider is None:
            return  # aucun fournisseur enregistre : rien a servir

        try:
            blocks = provider(from_height, MAX_SYNC_BLOCKS)
        except Exception:
            logger.exception("block range provider raised")
            return

        if not blocks:
            return  # rien a envoyer : on reste silencieux

        logger.debug(
            "serving %d block(s) from height %d to %s",
            len(blocks), from_height, remote_id,
        )
        self._send_to(
            remote_id,
            {
                "type": MSG_BLOCKS,
                "payload": [block.to_dict() for block in blocks],
            },
        )

    def _handle_blocks(self, payload, remote_id: str) -> None:
        """
        Reponse a notre propre demande de synchronisation.

        Les blocs sont remis au handler applicatif DANS L'ORDRE, un par
        un : node.py les traite exactement comme des blocs ordinaires,
        via le meme pipeline d'acceptation.

        Point important -- le cache anti-boucle `_seen` est
        DELIBEREMENT contourne ici. Un bloc peut tres bien avoir deja
        ete vu puis rejete parce qu'il arrivait trop tot (orphelin) ;
        le filtrer une seconde fois rendrait la synchronisation
        inoperante, ce qu'elle est precisement censee reparer. Le
        risque de boucle est nul : une reponse `blocks` n'est jamais
        rediffusee, elle est envoyee au seul demandeur.
        """
        if not isinstance(payload, list):
            logger.warning("peer %s: blocks payload is not a list", remote_id)
            return

        if len(payload) > MAX_SYNC_BLOCKS:
            logger.warning(
                "peer %s: blocks response too large (%d), ignoring",
                remote_id, len(payload),
            )
            return

        handler = self._block_handler
        if handler is None:
            return

        for item in payload:
            if not isinstance(item, dict):
                logger.warning("peer %s: block entry is not an object", remote_id)
                return
            try:
                block = Block.from_dict(item)
            except (BlockError, TransactionError, TypeError, AttributeError) as exc:
                logger.warning("peer %s: invalid block in sync: %s", remote_id, exc)
                return

            # Marque comme vu pour que la diffusion normale ne le
            # retraite pas ensuite, mais SANS filtrer sur le resultat.
            self._seen.add_if_new(block.block_hash)
            self._dispatch_with_forwarding(
                handler, block, "block", block.block_hash
            )

    def request_blocks_from(self, from_height: int) -> None:
        """
        Demande a tous les pairs connectes les blocs a partir de
        `from_height`.

        Envoi non bloquant et sans garantie : les blocs arriveront (ou
        non) plus tard via le handler de bloc habituel. Interroger tous
        les pairs plutot qu'un seul evite de rester bloque derriere un
        pair lui-meme en retard ; les blocs recus en double sont
        ignores sans dommage par node.py.
        """
        if from_height < 0:
            raise ValueError("from_height must be >= 0")

        self._broadcast({"type": MSG_GET_BLOCKS, "from_height": from_height})

    def _request_sync_from_peer(self, remote_id: str) -> None:
        """
        Demande a UN pair fraichement connecte la suite de la chaine.

        Appele a la fin du handshake. Sans fournisseur de hauteur
        locale enregistre (transport utilise sans node.py, cas des
        tests unitaires), aucune demande n'est emise.
        """
        provider = self._local_height_provider
        if provider is None:
            return

        try:
            height = provider()
        except Exception:
            logger.exception("local height provider raised")
            return

        self._send_to(
            remote_id,
            {"type": MSG_GET_BLOCKS, "from_height": height + 1},
        )

    def _send_to(self, remote_id: str, message: dict) -> None:
        """
        Envoie un message a UN pair precis.

        Utilise pour les reponses de synchronisation, qui ne doivent
        pas etre diffusees a tout le reseau.
        """
        try:
            frame = _encode_frame(message)
        except SocketP2PError as exc:
            logger.error("cannot encode message for %s: %s", remote_id, exc)
            return

        with self._connections_lock:
            connection = self._connections.get(remote_id)

        if connection is None:
            return  # pair deconnecte entre-temps

        sock = connection.socket
        try:
            with connection.send_lock:
                sock.sendall(frame)
        except OSError as exc:
            logger.warning("send to %s failed: %s", remote_id, exc)
            with self._connections_lock:
                existing = self._connections.get(remote_id)
                if existing is not None and existing.socket is sock:
                    del self._connections[remote_id]
            self._close_quietly(sock)

    @staticmethod
    def _safe_dispatch(handler, item, kind: str) -> None:
        """
        Appelle un handler applicatif sans jamais laisser une
        exception tuer le thread de lecture.

        node.py enveloppe deja ses handlers (_on_block_received avale
        NodeError), mais le transport ne doit pas dependre de cette
        garantie.
        """
        try:
            handler(item)
        except Exception:
            logger.exception("handler raised on incoming %s", kind)

    def _dispatch_with_forwarding(self, handler, item, kind: str, key: bytes) -> None:
        """Autorise le handler à relayer le message reçu une seule fois."""
        forwarding = getattr(self._forwarding_ids, "keys", None)
        if forwarding is None:
            forwarding = set()
            self._forwarding_ids.keys = forwarding

        forwarding.add(key)
        try:
            self._safe_dispatch(handler, item, kind)
        finally:
            forwarding.discard(key)

    def _may_broadcast(self, key: bytes) -> bool:
        """Apply the transport cache while allowing an application relay."""
        forwarding = getattr(self._forwarding_ids, "keys", ())
        if key in forwarding:
            return True
        return self._seen.add_if_new(key)

    # ------------------------------------------------------------------
    # P2PTransport : diffusion
    # ------------------------------------------------------------------

    def broadcast_transaction(self, transaction: Transaction) -> None:
        if not self._may_broadcast(transaction.tx_id):
            return
        self._broadcast(
            {"type": MSG_TRANSACTION, "payload": transaction.to_dict()}
        )

    def broadcast_block(self, block: Block) -> None:
        if not self._may_broadcast(block.block_hash):
            return
        self._broadcast({"type": MSG_BLOCK, "payload": block.to_dict()})

    def _broadcast(self, message: dict) -> None:
        """
        Envoie un message a tous les pairs connectes.

        Un pair injoignable est retire et n'empeche pas la livraison
        aux autres.
        """
        try:
            frame = _encode_frame(message)
        except SocketP2PError as exc:
            logger.error("cannot encode outgoing message: %s", exc)
            return

        with self._connections_lock:
            targets = list(self._connections.items())

        for remote_id, connection in targets:
            sock = connection.socket
            try:
                with connection.send_lock:
                    sock.sendall(frame)
            except OSError as exc:
                logger.warning("send to %s failed: %s", remote_id, exc)
                with self._connections_lock:
                    existing = self._connections.get(remote_id)
                    if existing is not None and existing.socket is sock:
                        del self._connections[remote_id]
                self._close_quietly(sock)
