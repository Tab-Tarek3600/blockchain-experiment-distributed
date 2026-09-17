"""
Maintien de l'etat EVM par rejeu des blocs depuis ChainStorage.

Ce module existe pour repondre a une contrainte precise (decision D4) :
l'etat EVM n'est PAS persiste sur disque et aucun crochet n'est pose
dans Node._accept_block. La chaine stockee est la seule source de
verite ; l'etat est reconstruit en rejouant les blocs.

Cela pose un probleme propre au PoA round-robin : avec trois
validateurs, un noeud ne propose qu'un bloc sur trois. Pour calculer la
racine du bloc h, il lui faut l'etat resultant des blocs 1..h-1, donc
y compris ceux proposes par les deux autres noeuds -- des blocs qu'il a
acceptes sans que personne ne previenne l'etat. StateReplayer comble
exactement ce vide : il compare sa propre avancee a celle du stockage
et rattrape ce qui manque, a la demande.

Repartition des responsabilites :
    - executor.EVMExecutor  execute UN bloc, ignore le stockage
    - state.EVMState        detient l'etat, ignore la notion de bloc
    - StateReplayer (ici)   relie les deux au stockage et suit
                            jusqu'ou l'etat est a jour

Cout mesure du rejeu : ~0,04 ms par bloc vide, ~1 ms par bloc d'une
transaction. Rattraper le retard nominal de deux blocs coute donc
environ 2 ms, negligeable devant un intervalle de bloc de 5 s.
"""

from __future__ import annotations

from typing import Optional, Sequence

from src.blockchain.block import Block
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.evm.errors import StateError
from src.evm.executor import BlockExecutionResult, EVMExecutor
from src.evm.state import EVMState

# Hauteur conventionnelle signifiant "aucun bloc encore applique".
# Le bloc de genese etant a la hauteur 0, il faut une valeur qui lui
# soit strictement inferieure.
NOTHING_APPLIED = -1


class StateReplayer:
    """
    Maintient un EVMState aligne sur les blocs presents dans un
    ChainStorage.

    Usage :

        replayer = StateReplayer(storage)
        replayer.sync_to(blockchain.height)      # rattrapage
        resultat = replayer.root_after(          # essai a blanc
            transactions, block_number=h, timestamp=ts, coinbase=addr,
        )
        racine = resultat.state_root

    L'invariant tenu par cette classe : `applied_height` est la hauteur
    du dernier bloc dont les effets sont engages dans `state`, et
    `state_root` est la racine correspondante.
    """

    def __init__(
        self,
        storage: ChainStorage,
        state: Optional[EVMState] = None,
    ) -> None:
        """
        Args:
            storage: Source de verite des blocs a rejouer.
            state: Etat de depart, VIERGE. Injectable pour les tests ;
                un EVMState neuf est cree par defaut.
        """
        self._storage = storage
        self._state = state if state is not None else EVMState()
        self._executor = EVMExecutor(self._state)
        self._applied_height = NOTHING_APPLIED

    # -- Lecture ---------------------------------------------------------

    @property
    def state(self) -> EVMState:
        """L'etat maintenu. Ne pas y ecrire directement."""
        return self._state

    @property
    def applied_height(self) -> int:
        """
        Hauteur du dernier bloc applique, ou NOTHING_APPLIED (-1) si
        aucun ne l'a encore ete.

        Le bloc de genese (hauteur 0) est compte comme applique une fois
        rejoue, bien qu'il ne contienne aucune transaction : sans cela,
        applied_height accuserait en permanence un decalage d'une unite
        par rapport a Blockchain.height, ecart qui finirait par etre mal
        interprete quelque part.
        """
        return self._applied_height

    @property
    def state_root(self) -> bytes:
        """Racine de l'etat apres application du bloc applied_height."""
        return self._state.state_root

    # -- Rattrapage ------------------------------------------------------

    def sync_to(self, height: int) -> bytes:
        """
        Rejoue les blocs manquants jusqu'a `height` inclus et retourne
        la racine obtenue.

        Seuls les blocs absents de l'etat sont rejoues : appeler cette
        methode alors qu'on est deja a jour ne coute rien. Il est donc
        correct -- et voulu -- de l'appeler avant chaque proposition.

        Args:
            height: Hauteur cible, typiquement Blockchain.height.

        Raises:
            StateError: Si la hauteur est invalide, si elle est
                inferieure a ce qui est deja applique (voir plus bas),
                ou si un bloc manque dans le stockage.
        """
        if isinstance(height, bool) or not isinstance(height, int):
            raise StateError("height must be an integer")

        if height < 0:
            raise StateError(f"height must be non-negative, got {height}")

        if height < self._applied_height:
            # Reculer voudrait dire que la chaine a ete tronquee ou
            # reorganisee. Cette chaine PoA n'a pas de mecanisme de
            # reorganisation ; le signaler plutot que de rendre
            # silencieusement une racine qui ne correspond a rien.
            raise StateError(
                f"cannot rewind state from height {self._applied_height} "
                f"to {height}: this chain has no reorganisation mechanism. "
                "Rebuild the state from a fresh StateReplayer instead."
            )

        for h in range(self._applied_height + 1, height + 1):
            self._apply_block(self._load(h))

        return self._state.state_root

    def _load(self, height: int) -> Block:
        try:
            return self._storage.load_block(height)
        except Exception as exc:
            raise StateError(
                f"cannot replay height {height}: {exc}"
            ) from exc

    def _apply_block(self, block: Block) -> None:
        """
        Applique un bloc a l'etat et avance le compteur.

        Le contexte d'execution (numero, horodatage, coinbase) provient
        integralement du bloc : c'est ce qui garantit que trois noeuds
        rejouant la meme chaine obtiennent la meme racine.
        """
        self._executor.execute_block(
            block.transactions,
            block_number=block.height,
            timestamp=block.timestamp,
            coinbase=block.validator,
        )
        self._applied_height = block.height

    # -- Essai a blanc ---------------------------------------------------

    def root_after(
        self,
        transactions: Sequence[Transaction],
        *,
        block_number: int,
        timestamp: int,
        coinbase: bytes,
    ) -> BlockExecutionResult:
        """
        Retourne le resultat qu'on obtiendrait en appliquant ce bloc,
        SANS engager l'etat.

        TYPE DE RETOUR. Cette methode rendait autrefois la seule racine
        (bytes). Elle rend desormais le BlockExecutionResult complet,
        car l'appelant a besoin du gas_used : c'est lui qui permet de
        journaliser le cout d'un bloc et, plus tard, d'inscrire le gas
        dans l'en-tete. Le type existant de l'executeur est reutilise
        plutot qu'un type parallele -- il porte deja exactement les
        trois informations produites (racine, recus, gas), et en
        introduire un second obligerait a les maintenir en phase.

        Le nom `root_after` est conserve : la racine reste la raison
        d'etre de l'appel, le reste est du contexte.

        Sert au producteur : il faut connaitre la racine pour l'inscrire
        dans le bloc *avant* de le signer, alors que ce bloc peut encore
        etre refuse (echec de validation, ou un pair a pris le tour). Si
        l'etat avait deja avance, il refleterait un bloc inexistant et
        divergerait silencieusement des deux autres noeuds.

        L'execution a lieu sur une VUE jetable obtenue par at_root() :
        meme base de donnees, donc meme resultat, mais ecritures sans
        effet sur l'etat maintenu ici.

        Note d'implementation : on n'utilise PAS snapshot()/revert()
        autour de execute_block. execute_block se termine par commit(),
        qui appelle persist() et invalide les points de restauration ;
        le revert consecutif echoue alors sur
        `ValidationError: No checkpoint N was found`. Ce comportement a
        ete verifie, pas suppose.

        Raises:
            BlockGasLimitExceeded: si le bloc annonce plus de gas que
                BLOCK_GAS_LIMIT. L'exception traverse volontairement
                cette methode sans etre convertie : un bloc hors
                plafond est invalide, et l'appelant doit le rejeter,
                pas recevoir une racine pour un bloc irrecevable.
        """
        vue = self._state.at_root(self._state.state_root)

        return EVMExecutor(vue).execute_block(
            transactions,
            block_number=block_number,
            timestamp=timestamp,
            coinbase=coinbase,
        )

    def __repr__(self) -> str:
        return (
            f"StateReplayer(applied_height={self._applied_height}, "
            f"state_root=0x{self.state_root.hex()[:16]}...)"
        )
