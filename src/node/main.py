"""
Point d'entree d'un noeud du reseau.

    python -m src.node.main --config config/node1.yaml

Responsabilites, dans l'ordre :
    1. charger le YAML via NodeConfig.from_file()
    2. construire le transport SocketP2P a partir de host/port/peers
    3. construire le Node via Node.from_config(config, p2p=transport)
    4. demarrer le transport, laisser le temps aux pairs de se joindre
    5. boucler : proposer un bloc quand c'est notre tour, et faire
       avancer le round après expiration du timeout si le proposant
       courant est indisponible
    6. arreter proprement sur Ctrl+C / SIGTERM

La logique de lancement vit ICI, pas dans NodeConfig : une classe de
configuration decrit des donnees, elle n'ouvre pas de sockets et ne
tient pas de boucle de production.

La boucle de production reste a la demande par defaut : aucun bloc
n'est produit si le mempool est vide. Avec une transaction en attente,
le proposant du round courant a la priorite. Si son timeout expire, tous
les noeuds actifs avancent vers le round suivant et le validateur
correspondant peut produire a la meme hauteur. Le round est signe dans
le bloc. Le mode historique de production periodique, y compris des
blocs vides, reste disponible avec --produce-empty-blocks pour les
benchmarks.

Options utiles pour un test manuel :
    --send-tx              injecte une transaction signee au demarrage
                           (pour observer sa propagation vers les pairs)
    --no-propose           ecoute seulement, ne produit aucun bloc
    --produce-empty-blocks conserve le mode periodique qui produit aussi
                           des blocs vides (benchmark uniquement)
    --log-level            DEBUG pour voir chaque connexion et message
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from src.blockchain.transaction import Transaction
from src.crypto.ml_dsa import MLDSA
from src.node.config import ConfigError, NodeConfig, load_or_generate_validator_keys
from src.node.node import Node, NodeError
from src.node.socket_p2p import SocketP2P, SocketP2PError

logger = logging.getLogger("node")

# Delai laisse aux pairs pour s'inscrire avant la premiere
# proposition. Evite qu'un noeud lance en premier ne produise un bloc
# dans le vide.
STARTUP_GRACE_SECONDS = 5.0


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.node.main",
        description="Run a blockchain node with a real TCP P2P transport.",
    )
    parser.add_argument(
        "--config", required=True, metavar="PATH",
        help="path to the node YAML config (e.g. config/node1.yaml)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--no-propose", action="store_true",
        help="listen and relay only, never produce blocks",
    )
    parser.add_argument(
        "--send-tx", action="store_true",
        help="submit one signed test transaction at startup",
    )
    parser.add_argument(
        "--produce-empty-blocks", action="store_true",
        help=(
            "produce periodic blocks even when the mempool is empty; "
            "benchmark mode, disabled by default"
        ),
    )
    parser.add_argument(
        "--tx-value", type=int, default=100,
        help="value of the test transaction (default: 100)",
    )
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def build_test_transaction(node: Node, config: NodeConfig, value: int) -> Transaction:
    """
    Construit et signe une transaction de test emise par ce noeud.

    Sert uniquement a la validation manuelle de la propagation. La
    cle secrete ne quitte jamais la machine : seule la transaction
    signee circule.
    """
    ml_dsa = MLDSA()
    keypair = load_or_generate_validator_keys(config.validator_key_dir, ml_dsa)

    recipient = (
        config.authorized_validators[1]
        if len(config.authorized_validators) > 1
        else node.local_address
    )

    unsigned = Transaction(
        nonce=int(time.time()) % 100000,
        sender=node.local_address,
        recipient=recipient,
        value=value,
        gas_limit=21000,
        gas_price=1,
        data=b"",
        public_key=keypair.public_key,
        signature=None,
    )
    signature = ml_dsa.sign(unsigned.signing_hash, keypair.secret_key)
    return unsigned.with_signature(signature)


def run(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)

    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("config file not found: %s", config_path)
        return 2

    try:
        config = NodeConfig.from_file(config_path)
    except ConfigError as exc:
        logger.error("invalid config: %s", exc)
        return 2

    transport = SocketP2P(
        host=config.host,
        port=config.port,
        peers=config.peers,
        node_id=config.node_id,
    )

    try:
        node = Node.from_config(config, p2p=transport)
    except NodeError as exc:
        logger.error("cannot start node: %s", exc)
        return 2

    logger.info("node_id           : %s (%s)", config.node_id, config.node_name)
    logger.info("local address     : %s", node.local_address.hex())
    logger.info("listening on      : %s:%d", config.host, config.port)
    logger.info("peers             : %s",
                ", ".join(f"{p.host}:{p.port}" for p in config.peers) or "none")
    logger.info("validators        : %d", len(config.authorized_validators))
    logger.info("genesis hash      : %s", node.genesis_hash.hex())
    logger.info("chain height      : %d", node.height)

    try:
        transport.start()
    except SocketP2PError as exc:
        logger.error("cannot start transport: %s", exc)
        return 2

    stopping = {"flag": False}

    def request_stop(signum, _frame):
        logger.info("signal %s received, shutting down", signum)
        stopping["flag"] = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        logger.info("waiting %.0fs for peers to connect...", STARTUP_GRACE_SECONDS)
        deadline = time.time() + STARTUP_GRACE_SECONDS
        while time.time() < deadline and not stopping["flag"]:
            time.sleep(0.2)

        logger.info("connected peers   : %s",
                    transport.connected_peer_ids() or "none")

        if args.send_tx and not stopping["flag"]:
            try:
                transaction = build_test_transaction(node, config, args.tx_value)
                node.receive_transaction(transaction)
                logger.info("submitted test tx %s (mempool: %d)",
                            transaction.tx_id.hex()[:16], node.mempool_size)
            except (NodeError, ValueError) as exc:
                logger.error("could not submit test transaction: %s", exc)

        _production_loop(node, config, transport, args, stopping)

    finally:
        transport.stop()
        logger.info("final height: %d", node.height)
        logger.info("final tip   : %s", node.tip_hash.hex())

    return 0


def _production_loop(node, config, transport, args, stopping) -> None:
    """
    Boucle principale : propose un bloc quand c'est le tour du noeud.

    Le tour est determine par Node.is_my_turn(), qui utilise la hauteur
    et le round local. Le timeout est gere par Node : il n'est arme que
    lorsqu'une transaction est en attente, afin de conserver la
    production a la demande.
    """
    last_report = 0.0

    while not stopping["flag"]:
        next_height = node.height + 1

        produce_empty_blocks = getattr(args, "produce_empty_blocks", False)
        has_work = produce_empty_blocks or node.mempool_size > 0

        # Tous les noeuds actifs font progresser leur round local de la
        # meme facon. Cela permet au validateur suivant de prendre le
        # relais sans que l'ingress node ait a connaitre le proposant.
        if has_work and hasattr(node, "advance_round_if_timed_out"):
            round_timeout = getattr(
                config,
                "round_timeout_seconds",
                config.block_interval_seconds,
            )
            advanced = node.advance_round_if_timed_out(
                next_height, round_timeout
            )
            if advanced:
                logger.info(
                    "proposal timeout expired at height %d; next round is active",
                    next_height,
                )

        if not args.no_propose and has_work and node.is_my_turn(next_height):
            try:
                block = node.propose_block()
                logger.info(
                    "PROPOSED block h=%d hash=%s txs=%d -> broadcast to %d peer(s)",
                    block.height, block.block_hash.hex()[:16],
                    len(block.transactions), transport.connection_count(),
                )
            except NodeError as exc:
                logger.warning("could not propose block h=%d: %s", next_height, exc)

        now = time.time()
        if now - last_report >= 15.0:
            logger.info(
                "status: height=%d mempool=%d peers=%s",
                node.height, node.mempool_size,
                transport.connected_peer_ids() or "none",
            )
            last_report = now

        # En mode a la demande, une courte cadence de sondage limite la
        # latence entre l'arrivee d'une transaction et sa proposition.
        # En mode benchmark avec blocs vides, on conserve l'intervalle
        # configure pour mesurer le rythme historique.
        wait_seconds = (
            config.block_interval_seconds
            if produce_empty_blocks
            else min(0.1, config.block_interval_seconds)
        )
        deadline = time.time() + wait_seconds
        while time.time() < deadline and not stopping["flag"]:
            time.sleep(0.1)


def main(argv: Optional[list[str]] = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
