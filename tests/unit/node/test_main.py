"""
Tests unitaires du point d'entree src/node/main.py.

main.py est le seul module du chemin critique sans couverture (C4). Il
porte quatre responsabilites distinctes, testees separement ici :

  1. parse_args()          — contrat de la ligne de commande
  2. configure_logging()   — niveau de verbosite
  3. run()                 — orchestration et codes de sortie
  4. _production_loop()    — decision de proposer un bloc

Choix de conception : ces tests n'instancient NI Node, NI SocketP2P
reels. Les deux sont deja couverts par test_node.py et
test_socket_p2p.py ; les rejouer ici serait redondant, lent (generation
de paires ML-DSA) et testerait autre chose que main.py. On verifie donc
que main.py appelle les bons collaborateurs, dans le bon ordre, et
traduit correctement leurs erreurs en codes de sortie.

Consequence : aucun test de ce fichier ne charge liboqs.
"""

import argparse
import logging

import pytest
import yaml

from src.node import main as main_module
from src.node.config import ConfigError
from src.node.main import (
    STARTUP_GRACE_SECONDS,
    _production_loop,
    configure_logging,
    main,
    parse_args,
    run,
)
from src.node.node import NodeError
from src.node.socket_p2p import SocketP2PError


# --- doublures -------------------------------------------------------
#
# Volontairement minimales : elles n'exposent que les membres que
# main.py utilise reellement. Toute methode appelee par main.py et
# absente ici ferait echouer le test par AttributeError, ce qui est le
# comportement souhaite (le test documente la surface d'API attendue).


class FakeTransport:
    def __init__(self, start_error=None):
        self._start_error = start_error
        self.started = False
        self.stopped = False

    def start(self):
        if self._start_error is not None:
            raise self._start_error
        self.started = True

    def stop(self):
        self.stopped = True

    def connected_peer_ids(self):
        return ["node2", "node3"]

    def connection_count(self):
        return 2


class FakeBlock:
    def __init__(self, height):
        self.height = height
        self.block_hash = bytes([height % 256]) * 32
        self.transactions = ()


class StoppingAfter(dict):
    """
    Drapeau d'arret qui se leve tout seul apres N lectures.

    _production_loop() est une boucle infinie par nature : elle ne
    s'arrete que sur SIGINT. Pour la tester il faut donc un critere
    d'arret deterministe. Compter les lectures de stopping["flag"] —
    exactement une par tour de boucle — est plus fiable que de compter
    les appels a is_my_turn(), qui n'est pas atteint sous --no-propose
    (court-circuit du `and`).
    """

    def __init__(self, iterations=1):
        super().__init__(flag=False)
        self._remaining = iterations

    def __getitem__(self, key):
        if key == "flag" and not dict.__getitem__(self, "flag"):
            if self._remaining <= 0:
                dict.__setitem__(self, "flag", True)
            self._remaining -= 1
        return dict.__getitem__(self, key)


class FakeTransaction:
    """
    Transaction opaque : run() ne fait que la transmettre au noeud puis
    journaliser son tx_id. Aucun champ metier n'est necessaire ici.
    """

    def __init__(self):
        self.tx_id = b"\x7f" * 32


class FakeNode:
    """
    Noeud minimal pilotable.

    `turns` est la sequence de valeurs que renverra is_my_turn(). Une
    fois epuisee, is_my_turn() renvoie False ; l'arret de la boucle est
    pilote par StoppingAfter, pas par le noeud.
    """

    def __init__(self, turns=(), stopping=None, propose_error=None):
        self._turns = list(turns)
        self._stopping = stopping
        self._propose_error = propose_error
        self.height = 0
        # Par défaut, les tests de production disposent d'une transaction
        # prête. Les tests du mode à la demande mettent explicitement ce
        # champ à zéro.
        self.mempool_size = 1
        self.local_address = b"\xaa" * 20
        self.genesis_hash = b"\x11" * 32
        self.tip_hash = b"\x22" * 32
        self.proposed_heights = []
        self.received_transactions = []
        self.is_my_turn_calls = []

    def is_my_turn(self, height):
        self.is_my_turn_calls.append(height)
        if self._turns:
            return self._turns.pop(0)
        return False

    def propose_block(self, timestamp=None):
        if self._propose_error is not None:
            raise self._propose_error
        self.height += 1
        self.proposed_heights.append(self.height)
        return FakeBlock(self.height)

    def receive_transaction(self, transaction):
        self.received_transactions.append(transaction)


def make_args(**overrides):
    defaults = {
        "config": "config/nodes/node1/node.yaml",
        "log_level": "INFO",
        "no_propose": False,
        "send_tx": False,
        "produce_empty_blocks": False,
        "tx_value": 100,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class FakeConfig:
    def __init__(self, block_interval_seconds=0.0):
        self.node_id = "node1"
        self.node_name = "Node 1"
        self.host = "127.0.0.1"
        self.port = 9001
        self.peers = ()
        self.authorized_validators = (b"\xaa" * 20, b"\xbb" * 20, b"\xcc" * 20)
        self.block_interval_seconds = block_interval_seconds
        self.validator_key_dir = "keys/node1"


# --- parse_args ------------------------------------------------------


def test_parse_args_requires_config():
    """--config est obligatoire : argparse sort en erreur sans lui."""
    with pytest.raises(SystemExit):
        parse_args([])


def test_parse_args_defaults():
    args = parse_args(["--config", "c.yaml"])

    assert args.config == "c.yaml"
    assert args.log_level == "INFO"
    assert args.no_propose is False
    assert args.send_tx is False
    assert args.produce_empty_blocks is False
    assert args.tx_value == 100


def test_parse_args_all_flags():
    args = parse_args([
        "--config", "config/nodes/node2/node.yaml",
        "--log-level", "DEBUG",
        "--no-propose",
        "--send-tx",
        "--produce-empty-blocks",
        "--tx-value", "42",
    ])

    assert args.config == "config/nodes/node2/node.yaml"
    assert args.log_level == "DEBUG"
    assert args.no_propose is True
    assert args.send_tx is True
    assert args.produce_empty_blocks is True
    assert args.tx_value == 42


def test_parse_args_rejects_unknown_log_level():
    """Le niveau de log est contraint par choices=[...]."""
    with pytest.raises(SystemExit):
        parse_args(["--config", "c.yaml", "--log-level", "TRACE"])


def test_parse_args_rejects_non_integer_tx_value():
    with pytest.raises(SystemExit):
        parse_args(["--config", "c.yaml", "--tx-value", "beaucoup"])


# --- configure_logging -----------------------------------------------


def test_configure_logging_sets_level():
    """
    Note : logging.basicConfig() n'a d'effet que si le root logger n'a
    pas deja de handler. pytest en installe un, donc on force le niveau
    directement et on verifie que la traduction chaine -> constante est
    correcte, ce qui est la vraie responsabilite de la fonction.
    """
    root = logging.getLogger()
    previous_level = root.level
    previous_handlers = root.handlers[:]
    root.handlers = []
    try:
        configure_logging("WARNING")
        assert root.level == logging.WARNING

        root.handlers = []
        configure_logging("DEBUG")
        assert root.level == logging.DEBUG
    finally:
        root.handlers = previous_handlers
        root.setLevel(previous_level)


# --- run() : codes de sortie -----------------------------------------


def test_run_returns_2_when_config_file_missing(tmp_path):
    missing = tmp_path / "absent.yaml"
    assert run(make_args(config=str(missing))) == 2


def test_run_returns_2_on_invalid_config(tmp_path, monkeypatch):
    """
    Un YAML syntaxiquement lisible mais invalide metier doit produire un
    code 2, pas une exception qui remonte.
    """
    path = tmp_path / "node.yaml"
    path.write_text(yaml.safe_dump({"node_id": "node1"}), encoding="utf-8")

    def boom(_path):
        raise ConfigError("champ manquant : host")

    monkeypatch.setattr(main_module.NodeConfig, "from_file", staticmethod(boom))

    assert run(make_args(config=str(path))) == 2


def test_run_returns_2_when_node_cannot_start(tmp_path, monkeypatch):
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", lambda **kw: FakeTransport())

    def boom(_config, p2p=None):
        raise NodeError("cle de validateur illisible")

    monkeypatch.setattr(main_module.Node, "from_config", staticmethod(boom))

    assert run(make_args(config=str(path))) == 2


def test_run_returns_2_when_transport_cannot_start(tmp_path, monkeypatch):
    """
    Cas concret : le port 9001 est deja occupe. Le noeud est construit
    mais le transport refuse de demarrer.
    """
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    transport = FakeTransport(start_error=SocketP2PError("address already in use"))

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", lambda **kw: transport)
    monkeypatch.setattr(
        main_module.Node,
        "from_config",
        staticmethod(lambda _c, p2p=None: FakeNode()),
    )

    assert run(make_args(config=str(path))) == 2
    assert transport.started is False


# --- run() : chemin nominal ------------------------------------------


@pytest.fixture
def instant_startup(monkeypatch):
    """Neutralise le delai de grace de 5 s pour garder les tests rapides."""
    monkeypatch.setattr(main_module, "STARTUP_GRACE_SECONDS", 0.0)


def test_run_returns_0_and_stops_transport(tmp_path, monkeypatch, instant_startup):
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    transport = FakeTransport()
    node = FakeNode()

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", lambda **kw: transport)
    monkeypatch.setattr(
        main_module.Node, "from_config", staticmethod(lambda _c, p2p=None: node)
    )
    # La boucle de production a sa propre batterie de tests plus bas.
    monkeypatch.setattr(main_module, "_production_loop", lambda *a, **k: None)

    assert run(make_args(config=str(path))) == 0
    assert transport.started is True
    assert transport.stopped is True


def test_run_stops_transport_even_if_loop_raises(
    tmp_path, monkeypatch, instant_startup
):
    """
    Le bloc finally doit garantir l'arret du transport : sans cela, le
    port resterait occupe apres un crash et le noeud ne pourrait pas
    redemarrer.
    """
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    transport = FakeTransport()

    def boom(*_a, **_k):
        raise RuntimeError("panne inattendue dans la boucle")

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", lambda **kw: transport)
    monkeypatch.setattr(
        main_module.Node,
        "from_config",
        staticmethod(lambda _c, p2p=None: FakeNode()),
    )
    monkeypatch.setattr(main_module, "_production_loop", boom)

    with pytest.raises(RuntimeError):
        run(make_args(config=str(path)))

    assert transport.stopped is True


def test_run_submits_test_transaction_when_asked(
    tmp_path, monkeypatch, instant_startup
):
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    node = FakeNode()
    transaction = FakeTransaction()

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", lambda **kw: FakeTransport())
    monkeypatch.setattr(
        main_module.Node, "from_config", staticmethod(lambda _c, p2p=None: node)
    )
    monkeypatch.setattr(main_module, "_production_loop", lambda *a, **k: None)
    monkeypatch.setattr(
        main_module, "build_test_transaction", lambda *a, **k: transaction
    )

    assert run(make_args(config=str(path), send_tx=True)) == 0
    assert node.received_transactions == [transaction]


def test_run_does_not_submit_transaction_by_default(
    tmp_path, monkeypatch, instant_startup
):
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    node = FakeNode()

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", lambda **kw: FakeTransport())
    monkeypatch.setattr(
        main_module.Node, "from_config", staticmethod(lambda _c, p2p=None: node)
    )
    monkeypatch.setattr(main_module, "_production_loop", lambda *a, **k: None)

    assert run(make_args(config=str(path))) == 0
    assert node.received_transactions == []


def test_run_survives_failing_test_transaction(
    tmp_path, monkeypatch, instant_startup
):
    """
    Une transaction de test refusee est une erreur d'outillage, pas une
    raison d'arreter le noeud : run() doit continuer et rendre 0.
    """
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    def boom(*_a, **_k):
        raise NodeError("mempool plein")

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", lambda **kw: FakeTransport())
    monkeypatch.setattr(
        main_module.Node,
        "from_config",
        staticmethod(lambda _c, p2p=None: FakeNode()),
    )
    monkeypatch.setattr(main_module, "_production_loop", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "build_test_transaction", boom)

    assert run(make_args(config=str(path), send_tx=True)) == 0


def test_run_passes_config_values_to_transport(
    tmp_path, monkeypatch, instant_startup
):
    """
    Le transport doit etre construit avec l'adresse d'ECOUTE du noeud,
    pas avec des valeurs par defaut.
    """
    path = tmp_path / "node.yaml"
    path.write_text("{}", encoding="utf-8")

    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)
        return FakeTransport()

    monkeypatch.setattr(
        main_module.NodeConfig, "from_file", staticmethod(lambda _p: FakeConfig())
    )
    monkeypatch.setattr(main_module, "SocketP2P", capture)
    monkeypatch.setattr(
        main_module.Node,
        "from_config",
        staticmethod(lambda _c, p2p=None: FakeNode()),
    )
    monkeypatch.setattr(main_module, "_production_loop", lambda *a, **k: None)

    run(make_args(config=str(path)))

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["node_id"] == "node1"


# --- _production_loop() ----------------------------------------------


def test_production_loop_proposes_when_it_is_our_turn():
    stopping = StoppingAfter(1)
    node = FakeNode(turns=[True])

    _production_loop(node, FakeConfig(), FakeTransport(), make_args(), stopping)

    assert node.proposed_heights == [1]


def test_production_loop_targets_next_height():
    """
    Le tour se calcule sur height + 1, la prochaine hauteur a produire,
    et non sur la hauteur courante.
    """
    stopping = StoppingAfter(1)
    node = FakeNode(turns=[False])
    node.height = 41

    _production_loop(node, FakeConfig(), FakeTransport(), make_args(), stopping)

    assert node.is_my_turn_calls[0] == 42


def test_production_loop_proposes_on_consecutive_turns():
    """Deux tours consecutifs produisent deux blocs."""
    stopping = StoppingAfter(2)
    node = FakeNode(turns=[True, True])

    _production_loop(node, FakeConfig(), FakeTransport(), make_args(), stopping)

    assert node.proposed_heights == [1, 2]


def test_production_loop_respects_no_propose():
    """--no-propose : le noeud relaie mais ne produit jamais."""
    stopping = StoppingAfter(2)
    node = FakeNode(turns=[True, True])

    _production_loop(
        node, FakeConfig(), FakeTransport(), make_args(no_propose=True), stopping
    )

    assert node.proposed_heights == []
    # Court-circuit du `and` : is_my_turn() n'est meme pas interroge.
    assert node.is_my_turn_calls == []


def test_production_loop_silent_when_not_our_turn():
    stopping = StoppingAfter(2)
    node = FakeNode(turns=[False, False])

    _production_loop(node, FakeConfig(), FakeTransport(), make_args(), stopping)

    assert node.proposed_heights == []


def test_on_demand_mode_does_not_produce_empty_blocks():
    stopping = StoppingAfter(2)
    node = FakeNode(turns=[True, True])
    node.mempool_size = 0

    _production_loop(node, FakeConfig(), FakeTransport(), make_args(), stopping)

    assert node.proposed_heights == []
    assert node.is_my_turn_calls == []


def test_benchmark_mode_can_produce_empty_blocks():
    stopping = StoppingAfter(1)
    node = FakeNode(turns=[True])
    node.mempool_size = 0

    _production_loop(
        node,
        FakeConfig(),
        FakeTransport(),
        make_args(produce_empty_blocks=True),
        stopping,
    )

    assert node.proposed_heights == [1]


def test_production_loop_survives_propose_error():
    """
    Une NodeError sur propose_block() est journalisee en warning et la
    boucle continue : un echec ponctuel ne doit pas tuer le noeud.
    """
    stopping = StoppingAfter(2)
    node = FakeNode(
        turns=[True, True], propose_error=NodeError("chaine en retard")
    )

    _production_loop(node, FakeConfig(), FakeTransport(), make_args(), stopping)

    assert node.proposed_heights == []
    # La boucle a bien fait ses deux tours malgre les deux echecs.
    assert node.is_my_turn_calls == [1, 1]


def test_production_loop_exits_immediately_when_already_stopping():
    stopping = StoppingAfter(0)
    node = FakeNode(turns=[True])

    _production_loop(node, FakeConfig(), FakeTransport(), make_args(), stopping)

    assert node.is_my_turn_calls == []
    assert node.proposed_heights == []


# --- main() ----------------------------------------------------------


def test_main_delegates_to_run(monkeypatch):
    captured = {}

    def fake_run(args):
        captured["config"] = args.config
        captured["tx_value"] = args.tx_value
        return 0

    monkeypatch.setattr(main_module, "run", fake_run)

    assert main(["--config", "c.yaml", "--tx-value", "7"]) == 0
    assert captured == {"config": "c.yaml", "tx_value": 7}


def test_main_propagates_exit_code(monkeypatch):
    monkeypatch.setattr(main_module, "run", lambda _args: 2)
    assert main(["--config", "absent.yaml"]) == 2


def test_startup_grace_is_positive():
    """
    Garde-fou : sans delai de grace, le premier bloc serait propose
    avant que les pairs aient eu le temps de se connecter.
    """
    assert STARTUP_GRACE_SECONDS > 0
