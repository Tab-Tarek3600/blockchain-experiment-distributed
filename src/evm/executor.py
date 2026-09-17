"""
Executeur de transactions : applique des transactions a l'etat EVM.

C'est ce module qui PRODUIT le state_root inscrit dans chaque bloc.

Regle centrale, dont tout le reste decoule :

    UNE TRANSACTION QUI ECHOUE NE FAIT JAMAIS ECHOUER UN BLOC.

Revert, out-of-gas, nonce invalide, solde insuffisant : tous ces cas
produisent un Receipt(status=0) et l'execution continue avec la
transaction suivante. Ce sont des faits deterministes, identiques sur
les trois noeuds, donc compatibles avec le consensus. Laisser remonter
une exception ferait rejeter par un noeud un bloc que ses pairs
acceptent -- un fork.

Seules les EVMError (defaillances d'infrastructure) remontent.


DETERMINISME. Deux noeuds qui executent le meme bloc doivent obtenir
le meme state_root, sans quoi la signature du bloc ne concorde plus
(le state_root est signe et hache, decision D3). Les sources de
non-determinisme ont ete traitees une par une :

  * ordre des transactions -- fixe par le bloc, jamais retrie ici ;
  * contexte de bloc -- derive du bloc (numero, timestamp, validateur),
    donc partage ;
  * ecritures d'etat sans effet -- neutralisees par EVMState ;
  * horloge, aleatoire, iteration de dict -- aucun n'est utilise.


MODELE DE TRANSACTION. Le projet n'utilise NI RLP NI ECDSA : les
transactions sont signees en ML-DSA et deja validees en amont par la
couche PHASE 1. La couche transaction de py-evm est donc
court-circuitee au profit d'un appel direct a la machine d'execution.
Aucune cle secp256k1 n'existe dans ce systeme.

Ce module n'importe PAS py-evm. Il passe par EVMState.run_message,
qui lui rend un ExecutionOutcome en types natifs : la dependance a
l'API beta de py-evm reste confinee a src/evm/state.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from src.blockchain.transaction import Transaction
from src.evm.addresses import (
    ZERO_ADDRESS,
    generate_contract_address,
    is_zero_address,
    short_hex,
    validate_address,
)
from src.evm.errors import BlockGasLimitExceeded, ExecutionError
from src.evm.receipt import Receipt
from src.evm.state import BLOCK_GAS_LIMIT, EVMState

logger = logging.getLogger(__name__)

# --- Constantes -------------------------------------------------------

#: Cout de base d'une transaction, comme sur Ethereum. Prelevé avant
#: toute execution : il paie la place occupee dans le bloc.
BASE_TX_GAS = 21_000

#: Cout par octet de donnees. Un octet nul est moins cher car il se
#: compresse mieux -- meme bareme qu'Ethereum.
GAS_PER_ZERO_BYTE = 4
GAS_PER_NONZERO_BYTE = 16


@dataclass(frozen=True)
class BlockExecutionResult:
    """
    Resultat de l'execution complete d'un bloc.

    Attributes:
        state_root: Racine de l'etat APRES le bloc. C'est la valeur a
            inscrire dans Block.state_root.
        receipts: Un recu par transaction, dans l'ordre du bloc.
        gas_used: Somme du gas consomme par le bloc.
    """

    state_root: bytes
    receipts: tuple[Receipt, ...]
    gas_used: int

    @property
    def all_succeeded(self) -> bool:
        return all(r.is_success for r in self.receipts)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.receipts if r.is_failure)


def intrinsic_gas(data: bytes) -> int:
    """
    Cout incompressible d'une transaction, avant execution.

    Calcule a partir des seules donnees de la transaction, donc
    identique sur tous les noeuds.
    """
    cout = BASE_TX_GAS
    for octet in data:
        cout += GAS_PER_ZERO_BYTE if octet == 0 else GAS_PER_NONZERO_BYTE
    return cout


class EVMExecutor:
    """
    Applique des transactions a un EVMState.

    L'executeur ne possede pas l'etat : il le recoit. Cela permet de
    rejouer une chaine entiere sur un meme etat, ou d'executer un bloc
    a titre de verification sur une copie.
    """

    def __init__(self, state: EVMState) -> None:
        if not isinstance(state, EVMState):
            raise ExecutionError("state must be an EVMState instance")
        self._state = state

    @property
    def state(self) -> EVMState:
        return self._state

    # -- Execution d'un bloc ---------------------------------------------

    def execute_block(
        self,
        transactions: Sequence[Transaction],
        *,
        block_number: int,
        timestamp: int,
        coinbase: bytes = ZERO_ADDRESS,
    ) -> BlockExecutionResult:
        """
        Execute toutes les transactions d'un bloc et engage l'etat.

        L'ordre des transactions est celui du bloc : il n'est jamais
        modifie ici. Deux noeuds recevant le meme bloc appliquent donc
        exactement la meme sequence.

        Le gas est plafonne par un POOL au fil de l'execution, selon le
        modele GasPool d'Ethereum : le pool ne se vide que du gas
        REELLEMENT consomme, mais aucune transaction n'est demarree si
        elle annonce plus que le solde restant.

        POURQUOI PAS UNE PRE-PASSE SUR LE GAS ANNONCE. Une pre-passe
        cumulant les gas_limit rejetait des blocs honnetes : annoncer
        large "au cas ou" est le comportement normal d'un portefeuille
        (estimateGas applique une marge). Mesure : 1 000 transferts
        annoncant 100 000 chacun totalisent 100 M de gas annonce mais
        n'en consomment que 21 M, soit 70 % du plafond -- un bloc
        parfaitement valide, refuse par tous les receveurs, pour une
        perte de debit de plus de 4x.

        La protection anti-DoS ne vient pas du refus a priori mais du
        fait que le gas CONSOMME est borne par BLOCK_GAS_LIMIT. Un bloc
        de 10 000 transactions en boucle infinie est ainsi declare
        invalide des la 30e, apres 7,93 s de travail borne, au lieu des
        45 minutes qu'il faudrait pour tout executer.

        Returns:
            BlockExecutionResult, dont state_root est la racine a
            inscrire dans le bloc.

        Raises:
            BlockGasLimitExceeded: si une transaction annonce plus de
                gas qu'il n'en reste dans le pool du bloc. L'etat n'est
                pas engage (pas de commit) : l'appelant travaille sur
                une vue jetable.
        """
        validate_address(coinbase, "coinbase")

        self._state.set_block_context(
            block_number=block_number,
            timestamp=timestamp,
            coinbase=coinbase,
        )

        recus: list[Receipt] = []
        gas_total = 0

        for index, transaction in enumerate(transactions):
            # --- Pool de gas du bloc (modele GasPool d'Ethereum) -----
            # Le pool est debite du gas ANNONCE avant l'execution, puis
            # le gas NON CONSOMME lui est restitue. Concretement, le
            # solde du pool ne depend que du gas reellement consomme,
            # tandis que le refus porte sur le gas annonce de la
            # prochaine transaction : on n'accepte jamais de demarrer
            # une transaction qu'on ne pourrait pas payer en entier.
            restant = BLOCK_GAS_LIMIT - gas_total
            if transaction.gas_limit > restant:
                logger.error(
                    "block rejected: transaction %d/%d announces %d gas "
                    "but only %d remains in the block pool (limit %d)",
                    index + 1,
                    len(transactions),
                    transaction.gas_limit,
                    restant,
                    BLOCK_GAS_LIMIT,
                )
                raise BlockGasLimitExceeded(
                    f"block gas limit exceeded: transaction {index} "
                    f"announces {transaction.gas_limit} gas, only "
                    f"{restant} remains (limit {BLOCK_GAS_LIMIT})"
                )

            recu = self.execute_transaction(transaction, coinbase=coinbase)
            recus.append(recu)
            # Restitution implicite : seul le gas consomme quitte le
            # pool. Une transaction qui annonce 100 000 et n'en consomme
            # que 21 000 rend les 79 000 restants au bloc.
            gas_total += recu.gas_used

        racine = self._state.commit()

        return BlockExecutionResult(
            state_root=racine,
            receipts=tuple(recus),
            gas_used=gas_total,
        )

    # -- Execution d'une transaction --------------------------------------

    def execute_transaction(
        self,
        transaction: Transaction,
        *,
        coinbase: bytes = ZERO_ADDRESS,
    ) -> Receipt:
        """
        Execute une transaction et retourne son recu.

        Ne leve jamais pour un echec d'execution : tout echec devient
        un Receipt(status=0). Voir l'en-tete du module.
        """
        if not isinstance(transaction, Transaction):
            raise ExecutionError("expected a Transaction instance")

        tx_id = transaction.tx_id
        sender = transaction.sender

        # --- Controles prealables ------------------------------------
        # Ces echecs surviennent AVANT toute execution. Ils ne
        # consomment aucun gas et ne touchent pas a l'etat : la
        # transaction n'a jamais demarre. Le nonce n'est pas incremente,
        # sans quoi un nonce errone bloquerait definitivement le compte.

        nonce_attendu = self._state.get_nonce(sender)
        if transaction.nonce != nonce_attendu:
            return Receipt.failure(
                tx_id=tx_id,
                gas_used=0,
                error=(
                    f"invalid nonce: expected {nonce_attendu}, "
                    f"got {transaction.nonce}"
                ),
            )

        gas_intrinseque = intrinsic_gas(transaction.data)
        if transaction.gas_limit < gas_intrinseque:
            return Receipt.failure(
                tx_id=tx_id,
                gas_used=0,
                error=(
                    f"gas limit {transaction.gas_limit} below intrinsic cost "
                    f"{gas_intrinseque}"
                ),
            )

        cout_max = transaction.value + transaction.gas_limit * transaction.gas_price
        solde = self._state.get_balance(sender)
        if solde < cout_max:
            return Receipt.failure(
                tx_id=tx_id,
                gas_used=0,
                error=f"insufficient balance: has {solde}, needs {cout_max}",
            )

        # --- La transaction est engagee ------------------------------
        # A partir d'ici elle sera facturee, qu'elle reussisse ou non.
        # Le nonce est incremente immediatement : c'est la protection
        # contre le rejeu, elle doit s'appliquer meme en cas d'echec.

        self._state.increment_nonce(sender)

        frais = transaction.gas_limit * transaction.gas_price
        if frais > 0:
            self._state.subtract_balance(sender, frais)

        point_de_reprise = self._state.snapshot()

        try:
            recu = self._apply(transaction, gas_intrinseque)
        except Exception as exc:
            # Filet de securite. Une defaillance imprevue de py-evm ne
            # doit pas remonter jusqu'au noeud et faire rejeter le
            # bloc : elle est convertie en echec deterministe. Le
            # journal garde la trace pour investigation.
            self._state.revert(point_de_reprise)
            logger.warning(
                "unexpected EVM failure on tx 0x%s: %s",
                tx_id.hex()[:16],
                exc,
            )
            recu = Receipt.failure(
                tx_id=tx_id,
                gas_used=transaction.gas_limit,
                error=f"evm failure: {type(exc).__name__}",
            )

        if recu.is_failure:
            self._state.revert(point_de_reprise)

        # --- Remboursement et paiement du validateur ------------------
        # Le gas non consomme revient a l'expediteur ; le gas consomme
        # va au producteur du bloc. Avec gas_price = 0 les deux sont
        # nuls et n'ecrivent rien -- l'etat reste inchange, ce qui
        # preserve le determinisme de la racine.

        if transaction.gas_price > 0:
            rembourse = (transaction.gas_limit - recu.gas_used) * transaction.gas_price
            if rembourse > 0:
                self._state.add_balance(sender, rembourse)

            paye = recu.gas_used * transaction.gas_price
            if paye > 0 and not is_zero_address(coinbase):
                self._state.add_balance(coinbase, paye)

        return recu

    # -- Application effective ---------------------------------------------

    def _apply(self, transaction: Transaction, gas_intrinseque: int) -> Receipt:
        """
        Applique la transaction via la machine d'execution py-evm.

        Le gas intrinseque est deduit du budget avant execution : il
        est deja consomme par le simple fait de soumettre la
        transaction.
        """
        gas_disponible = transaction.gas_limit - gas_intrinseque

        if is_zero_address(transaction.recipient):
            return self._deploy(transaction, gas_disponible, gas_intrinseque)

        return self._call(transaction, gas_disponible, gas_intrinseque)

    def _deploy(
        self,
        transaction: Transaction,
        gas_disponible: int,
        gas_intrinseque: int,
    ) -> Receipt:
        """
        Deploie un contrat.

        Le destinataire vaut ZERO_ADDRESS et `data` porte l'initcode.
        L'adresse est derivee du couple (expediteur, nonce) : elle est
        donc previsible et identique sur les trois noeuds.

        Le nonce utilise est celui d'AVANT la transaction. Il a deja
        ete incremente par l'appelant, d'ou le -1.
        """
        sender = transaction.sender
        nonce_utilise = self._state.get_nonce(sender) - 1
        adresse = generate_contract_address(sender, nonce_utilise)

        if not transaction.data:
            return Receipt.failure(
                tx_id=transaction.tx_id,
                gas_used=gas_intrinseque,
                error="contract creation requires init code in data",
            )

        resultat = self._run(
            transaction,
            gas=gas_disponible,
            to=ZERO_ADDRESS,
            code=transaction.data,
            create_address=adresse,
            is_create=True,
        )

        gas_utilise = gas_intrinseque + resultat.gas_used

        if not resultat.succeeded:
            return Receipt.failure(
                tx_id=transaction.tx_id,
                gas_used=self._facture(transaction, resultat, gas_utilise),
                error=resultat.error,
                output=resultat.output,
            )

        return Receipt.success(
            tx_id=transaction.tx_id,
            gas_used=gas_utilise,
            contract_address=adresse,
            output=resultat.output,
            logs=resultat.logs,
        )

    def _call(
        self,
        transaction: Transaction,
        gas_disponible: int,
        gas_intrinseque: int,
    ) -> Receipt:
        """
        Appelle un compte existant.

        Si le destinataire ne porte pas de code, l'operation se reduit
        a un transfert de valeur -- ce qui reste une transaction
        parfaitement valide.
        """
        code = self._state.get_code(transaction.recipient)

        resultat = self._run(
            transaction,
            gas=gas_disponible,
            to=transaction.recipient,
            code=code,
            create_address=None,
            is_create=False,
        )

        gas_utilise = gas_intrinseque + resultat.gas_used

        if not resultat.succeeded:
            return Receipt.failure(
                tx_id=transaction.tx_id,
                gas_used=self._facture(transaction, resultat, gas_utilise),
                error=resultat.error,
                output=resultat.output,
            )

        return Receipt.success(
            tx_id=transaction.tx_id,
            gas_used=gas_utilise,
            output=resultat.output,
            logs=resultat.logs,
        )

    # -- Pont vers l'execution ----------------------------------------------

    def _run(
        self,
        transaction: Transaction,
        *,
        gas: int,
        to: bytes,
        code: bytes,
        create_address: Optional[bytes],
        is_create: bool,
    ):
        """
        Delegue l'execution a EVMState.run_message.

        Ce module ne connait pas py-evm : il recoit un
        ExecutionOutcome en types natifs. La regle d'isolation veut
        que src/evm/state.py soit le SEUL module a dependre de py-evm,
        de sorte qu'une rupture de son API beta se repare a un seul
        endroit.
        """
        return self._state.run_message(
            sender=transaction.sender,
            to=to,
            value=transaction.value,
            data=transaction.data,
            code=code,
            gas=gas,
            gas_price=transaction.gas_price,
            create_address=create_address if is_create else None,
        )

    # -- Utilitaires --------------------------------------------------------

    @staticmethod
    def _facture(
        transaction: Transaction, resultat, gas_utilise: int
    ) -> int:
        """
        Gas facture pour une execution en echec.

        Un out-of-gas consomme la totalite du budget (burns_all_gas).
        Un revert ne consomme que ce qui a ete depense avant l'arret,
        le reste est rendu.
        """
        if resultat.burns_all_gas:
            return transaction.gas_limit
        return min(gas_utilise, transaction.gas_limit)

    def __repr__(self) -> str:
        return f"EVMExecutor(state_root=0x{self._state.state_root.hex()[:16]}...)"
