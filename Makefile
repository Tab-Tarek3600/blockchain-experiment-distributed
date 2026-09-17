# =====================================================================
#  Blockchain experiment distributed — raccourcis de developpement
# =====================================================================
#
#  `make help` liste les cibles disponibles.
#
#  liboqs : la bibliotheque native doit etre installee et localisable.
#  Voir docs/INSTALL-liboqs.md. Le chemin par defaut ci-dessous peut etre
#  surcharge :  make test OQS_INSTALL_PATH=/autre/chemin
# ---------------------------------------------------------------------

OQS_INSTALL_PATH ?= $(HOME)/_oqs
export OQS_INSTALL_PATH
export LD_LIBRARY_PATH := $(OQS_INSTALL_PATH)/lib:$(LD_LIBRARY_PATH)

PYTHON ?= python3
PYTEST := $(PYTHON) -m pytest

.DEFAULT_GOAL := help
.PHONY: help install install-dev check-oqs test test-unit test-integration \
        lint format typecheck clean clean-data node1 node2 node3

# --- Aide ------------------------------------------------------------
help:
	@echo "Cibles disponibles :"
	@echo "  install           installe les dependances runtime + le paquet (editable)"
	@echo "  install-dev       idem + outillage de developpement"
	@echo "  check-oqs         verifie que liboqs est trouvable et que ML-DSA-44 existe"
	@echo "  test              suite complete"
	@echo "  test-unit         tests unitaires seuls (rapides)"
	@echo "  test-integration  tests reseau multi-noeuds seuls (lents)"
	@echo "  lint              ruff"
	@echo "  format            black"
	@echo "  typecheck         mypy"
	@echo "  node1|node2|node3 demarre un noeud avec sa config"
	@echo "  clean             supprime les caches Python et pytest"
	@echo "  clean-data        VIDE data/nodeN — detruit les chaines locales"

# --- Installation ----------------------------------------------------
install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install -e .

# Verification prealable a tout lancement : echoue tot et clairement
# plutot que de laisser un ImportError obscur surgir en cours de test.
check-oqs:
	@$(PYTHON) -c "import oqs; \
	assert 'ML-DSA-44' in oqs.get_enabled_sig_mechanisms(), 'ML-DSA-44 absent'; \
	print('liboqs', oqs.oqs_version(), '- ML-DSA-44 OK')" \
	|| (echo ""; echo "ECHEC : voir docs/INSTALL-liboqs.md"; exit 1)

# --- Tests -----------------------------------------------------------
test: check-oqs
	$(PYTEST) tests/ -q

test-unit: check-oqs
	$(PYTEST) tests/unit/ -v

test-integration: check-oqs
	$(PYTEST) tests/integration/ -v -m integration

# --- Qualite ---------------------------------------------------------
lint:
	$(PYTHON) -m ruff check src/ tests/ scripts/

format:
	$(PYTHON) -m black src/ tests/ scripts/

typecheck:
	$(PYTHON) -m mypy src/

# --- Lancement des noeuds --------------------------------------------
# Chaque machine ne lance QUE sa propre cible.
node1: check-oqs
	$(PYTHON) -m src.node.main --config config/nodes/node1/node.yaml

node2: check-oqs
	$(PYTHON) -m src.node.main --config config/nodes/node2/node.yaml

node3: check-oqs
	$(PYTHON) -m src.node.main --config config/nodes/node3/node.yaml

# --- Nettoyage -------------------------------------------------------
clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name "*.egg-info" -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type f -name "*.pyc" -delete

# Destructif : demande une confirmation explicite.
clean-data:
	@echo "Cela va SUPPRIMER les chaines locales de data/node{1,2,3}."
	@read -p "Confirmer ? [y/N] " a; [ "$$a" = "y" ] || exit 1
	rm -rf data/node1/* data/node2/* data/node3/*
	@echo "data/ vide. Les noeuds repartiront du genesis."
