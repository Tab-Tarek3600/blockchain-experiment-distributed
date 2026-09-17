"""
Tests unitaires de l'executeur de transactions.

Deux familles de tests dominent ce fichier :

  * « Un echec ne casse pas le bloc » -- verifie qu'aucun echec
    d'execution ne remonte sous forme d'exception. C'est la garantie
    anti-fork : un noeud qui leverait la ou ses pairs produisent un
    recu rejetterait un bloc valide.

  * « Determinisme » -- verifie que plusieurs executions independantes
    du meme bloc donnent le meme state_root, condition du critere n.12
    (les 3 VMs convergent).
"""

from __future__ import annotations

import pytest

from src.blockchain.transaction import Transaction
from src.crypto.address import public_key_to_address
from src.evm.addresses import ZERO_ADDRESS, generate_contract_address
from src.evm.errors import BlockGasLimitExceeded, ExecutionError
from src.evm.executor import (
    BASE_TX_GAS,
    EVMExecutor,
    intrinsic_gas,
)
from src.evm.state import BLOCK_GAS_LIMIT, EVMState

# Cles publiques ML-DSA-44 (1312 octets). Transaction impose que
# sender derive de public_key : les adresses sont donc calculees.
PK_ALICE = b"\x01" * 1312
PK_BOB = b"\x02" * 1312
ALICE = public_key_to_address(PK_ALICE)
BOB = public_key_to_address(PK_BOB)

SIGNATURE = b"\x03" * 2420

#: Runtime qui retourne toujours 42.
RUNTIME_42 = bytes.fromhex("602a60005260206000f3")

#: Initcode deployant RUNTIME_42 (CODECOPY puis RETURN).
INITCODE_42 = (
    bytes([0x60, len(RUNTIME_42), 0x60, 12, 0x60, 0x00, 0x39,
           0x60, len(RUNTIME_42), 0x60, 0x00, 0xF3])
    + RUNTIME_42
)

#: SSTORE(0, 42) puis REVERT -- pour verifier l'annulation d'etat.
STORE_PUIS_REVERT = bytes.fromhex("602a60005560006000fd")

#: Boucle infinie -- epuise le gas.
BOUCLE_INFINIE = bytes.fromhex("5b600056")


def make_tx(
    nonce: int = 0,
    recipient: bytes = BOB,
    value: int = 0,
    data: bytes = b"",
    gas_limit: int = 1_000_000,
    gas_price: int = 0,
) -> Transaction:
    return Transaction(
        nonce=nonce,
        sender=ALICE,
        recipient=recipient,
        value=value,
        gas_limit=gas_limit,
        gas_price=gas_price,
        data=data,
        public_key=PK_ALICE,
        signature=SIGNATURE,
    )


@pytest.fixture
def state() -> EVMState:
    etat = EVMState()
    etat.set_balance(ALICE, 10**18)
    etat.commit()
    return etat


@pytest.fixture
def executor(state) -> EVMExecutor:
    return EVMExecutor(state)


# --- Gas intrinseque ---------------------------------------------------

def test_gas_intrinseque_sans_donnees():
    assert intrinsic_gas(b"") == BASE_TX_GAS


def test_octet_nul_moins_cher_qu_un_octet_non_nul():
    assert intrinsic_gas(b"\x00") == BASE_TX_GAS + 4
    assert intrinsic_gas(b"\x01") == BASE_TX_GAS + 16


def test_gas_intrinseque_est_additif():
    assert intrinsic_gas(b"\x01\x00") == BASE_TX_GAS + 20


# --- Transferts de valeur ----------------------------------------------

def test_transfert_simple(executor, state):
    recu = executor.execute_transaction(make_tx(0, BOB, 500))

    assert recu.is_success
    assert recu.gas_used == BASE_TX_GAS
    assert state.get_balance(BOB) == 500
    assert state.get_balance(ALICE) == 10**18 - 500


def test_le_nonce_est_incremente_apres_succes(executor, state):
    executor.execute_transaction(make_tx(0, BOB, 1))
    assert state.get_nonce(ALICE) == 1


# --- Echecs : jamais d'exception ---------------------------------------

def test_nonce_invalide_donne_un_recu_en_echec(executor, state):
    recu = executor.execute_transaction(make_tx(99, BOB, 1))

    assert recu.is_failure
    assert "invalid nonce" in recu.error
    assert recu.gas_used == 0
    # Rien ne doit avoir bouge : la transaction n'a jamais demarre.
    assert state.get_nonce(ALICE) == 0
    assert state.get_balance(BOB) == 0


def test_solde_insuffisant_donne_un_recu_en_echec(executor, state):
    recu = executor.execute_transaction(make_tx(0, BOB, 10**30))

    assert recu.is_failure
    assert "insufficient balance" in recu.error
    assert state.get_nonce(ALICE) == 0


def test_gas_limit_sous_le_cout_intrinseque_echoue(executor):
    recu = executor.execute_transaction(make_tx(0, BOB, gas_limit=1000))

    assert recu.is_failure
    assert "below intrinsic cost" in recu.error


def test_revert_donne_un_recu_en_echec(executor, state):
    state.set_code(BOB, STORE_PUIS_REVERT)
    state.commit()

    recu = executor.execute_transaction(make_tx(0, BOB))

    assert recu.is_failure
    assert "Revert" in recu.error


def test_revert_annule_les_ecritures_du_contrat(executor, state):
    """Une transaction qui revert ne laisse aucune trace en stockage."""
    state.set_code(BOB, STORE_PUIS_REVERT)
    state.commit()

    executor.execute_transaction(make_tx(0, BOB))

    assert state.get_storage(BOB, 0) == 0


def test_out_of_gas_donne_un_recu_en_echec(executor, state):
    state.set_code(BOB, BOUCLE_INFINIE)
    state.commit()

    recu = executor.execute_transaction(make_tx(0, BOB, gas_limit=60_000))

    assert recu.is_failure
    assert "OutOfGas" in recu.error


def test_out_of_gas_consomme_tout_le_budget(executor, state):
    """Sinon un attaquant ferait tourner l'EVM gratuitement."""
    state.set_code(BOB, BOUCLE_INFINIE)
    state.commit()

    recu = executor.execute_transaction(make_tx(0, BOB, gas_limit=60_000))

    assert recu.gas_used == 60_000


def test_le_nonce_avance_meme_apres_un_echec_d_execution(executor, state):
    """
    Protection contre le rejeu : une transaction consommee ne doit
    jamais pouvoir etre resoumise, meme si elle a echoue.
    """
    state.set_code(BOB, STORE_PUIS_REVERT)
    state.commit()

    executor.execute_transaction(make_tx(0, BOB))

    assert state.get_nonce(ALICE) == 1


def test_aucun_echec_ne_leve_d_exception(executor, state):
    """
    Test central anti-fork. Chaque cas ci-dessous ferait rejeter le
    bloc s'il levait, alors que les autres noeuds l'acceptent.
    """
    state.set_code(BOB, STORE_PUIS_REVERT)
    state.commit()

    cas = [
        make_tx(99, BOB),                       # nonce invalide
        make_tx(0, BOB, value=10**30),          # solde insuffisant
        make_tx(0, BOB, gas_limit=100),         # gas insuffisant
        make_tx(0, BOB),                        # revert
        make_tx(0, ZERO_ADDRESS, data=b""),     # deploiement sans code
    ]

    for transaction in cas:
        recu = executor.execute_transaction(transaction)
        assert recu.is_failure


# --- Deploiement de contrat --------------------------------------------

def test_deploiement_installe_le_bytecode(executor, state):
    recu = executor.execute_transaction(
        make_tx(0, ZERO_ADDRESS, data=INITCODE_42)
    )

    assert recu.is_success
    assert recu.created_contract
    assert state.get_code(recu.contract_address) == RUNTIME_42


def test_adresse_de_contrat_previsible(executor):
    """Le nonce utilise est celui d'AVANT la transaction."""
    attendue = generate_contract_address(ALICE, 0)
    recu = executor.execute_transaction(
        make_tx(0, ZERO_ADDRESS, data=INITCODE_42)
    )

    assert recu.contract_address == attendue


def test_deux_deploiements_donnent_deux_adresses(executor):
    a = executor.execute_transaction(make_tx(0, ZERO_ADDRESS, data=INITCODE_42))
    b = executor.execute_transaction(make_tx(1, ZERO_ADDRESS, data=INITCODE_42))

    assert a.contract_address != b.contract_address


def test_deploiement_sans_initcode_echoue(executor):
    recu = executor.execute_transaction(make_tx(0, ZERO_ADDRESS, data=b""))

    assert recu.is_failure
    assert "init code" in recu.error


# --- Appel de contrat ---------------------------------------------------

def test_appel_de_contrat_retourne_la_sortie(executor):
    deploiement = executor.execute_transaction(
        make_tx(0, ZERO_ADDRESS, data=INITCODE_42)
    )
    appel = executor.execute_transaction(make_tx(1, deploiement.contract_address))

    assert appel.is_success
    assert int.from_bytes(appel.output, "big") == 42


def test_appel_a_un_compte_sans_code_reste_un_transfert(executor, state):
    recu = executor.execute_transaction(make_tx(0, BOB, value=10))

    assert recu.is_success
    assert state.get_balance(BOB) == 10


# --- Frais de gas -------------------------------------------------------

def test_gas_price_nul_ne_debite_rien(executor, state):
    solde_avant = state.get_balance(ALICE)
    executor.execute_transaction(make_tx(0, BOB, gas_price=0))

    assert state.get_balance(ALICE) == solde_avant


def test_gas_price_non_nul_debite_l_expediteur(executor, state):
    solde_avant = state.get_balance(ALICE)
    recu = executor.execute_transaction(make_tx(0, BOB, gas_price=10))

    assert state.get_balance(ALICE) == solde_avant - recu.gas_used * 10


def test_le_gas_inutilise_est_rembourse(executor, state):
    """Seul le gas reellement consomme est facture."""
    solde_avant = state.get_balance(ALICE)
    recu = executor.execute_transaction(
        make_tx(0, BOB, gas_limit=1_000_000, gas_price=10)
    )

    depense = solde_avant - state.get_balance(ALICE)
    assert depense == recu.gas_used * 10
    assert depense < 1_000_000 * 10


def test_les_frais_reviennent_au_validateur(executor, state):
    recu = executor.execute_transaction(
        make_tx(0, BOB, gas_price=10), coinbase=BOB
    )

    assert state.get_balance(BOB) == recu.gas_used * 10


# --- Execution d'un bloc -------------------------------------------------

def test_execution_d_un_bloc_produit_une_racine(executor):
    resultat = executor.execute_block(
        [make_tx(0, BOB, 100), make_tx(1, BOB, 200)],
        block_number=1,
        timestamp=1_700_000_000,
    )

    assert len(resultat.receipts) == 2
    assert resultat.all_succeeded
    assert resultat.gas_used == 2 * BASE_TX_GAS
    assert len(resultat.state_root) == 32


def test_bloc_vide_laisse_l_etat_intact(executor, state):
    racine_avant = state.state_root
    resultat = executor.execute_block([], block_number=1, timestamp=0)

    assert resultat.receipts == ()
    assert resultat.gas_used == 0
    assert resultat.state_root == racine_avant


def test_un_bloc_reste_valide_malgre_une_transaction_echouee(executor):
    """
    Le point le plus important de la PHASE 3 : un echec est un fait
    enregistre, pas un motif de rejet du bloc.
    """
    resultat = executor.execute_block(
        [make_tx(0, BOB, 100), make_tx(42, BOB, 1), make_tx(1, BOB, 50)],
        block_number=1,
        timestamp=0,
    )

    assert len(resultat.receipts) == 3
    assert resultat.failure_count == 1
    assert not resultat.all_succeeded
    assert [r.status for r in resultat.receipts] == [1, 0, 1]


def test_l_ordre_des_recus_suit_celui_du_bloc(executor):
    transactions = [make_tx(0, BOB, 1), make_tx(1, BOB, 2), make_tx(2, BOB, 3)]
    resultat = executor.execute_block(transactions, block_number=1, timestamp=0)

    attendus = [t.tx_id for t in transactions]
    assert [r.tx_id for r in resultat.receipts] == attendus


# --- Determinisme (critere n.12) -----------------------------------------

def _executer_un_bloc():
    """Rejoue le meme bloc sur un etat neuf, comme le ferait un noeud."""
    etat = EVMState()
    etat.set_balance(ALICE, 10**18)
    etat.commit()

    return EVMExecutor(etat).execute_block(
        [
            make_tx(0, BOB, 500),
            make_tx(1, ZERO_ADDRESS, data=INITCODE_42),
            make_tx(2, BOB, 1),
            make_tx(99, BOB, 1),  # echec deliberе
        ],
        block_number=7,
        timestamp=1_700_000_000,
        coinbase=BOB,
    )


def test_trois_noeuds_convergent_sur_la_meme_racine():
    """
    Simule les 3 VMs : memes transactions, memes conditions, etats
    independants. Le state_root etant signe et hache, la moindre
    divergence provoquerait un fork.
    """
    vm1, vm2, vm3 = _executer_un_bloc(), _executer_un_bloc(), _executer_un_bloc()

    assert vm1.state_root == vm2.state_root == vm3.state_root


def test_les_noeuds_produisent_les_memes_recus():
    vm1, vm2 = _executer_un_bloc(), _executer_un_bloc()

    assert [r.status for r in vm1.receipts] == [r.status for r in vm2.receipts]
    assert vm1.gas_used == vm2.gas_used


def test_une_transaction_echouee_ne_perturbe_pas_la_racine():
    """
    Un echec prealable a l'execution ne touche pas l'etat : la racine
    doit etre celle d'un bloc qui ne contiendrait pas cette
    transaction.
    """
    def bloc(transactions):
        etat = EVMState()
        etat.set_balance(ALICE, 10**18)
        etat.commit()
        return EVMExecutor(etat).execute_block(
            transactions, block_number=1, timestamp=0
        )

    avec_echec = bloc([make_tx(0, BOB, 100), make_tx(77, BOB, 1)])
    sans_echec = bloc([make_tx(0, BOB, 100)])

    assert avec_echec.state_root == sans_echec.state_root


# --- Plafond de gas par bloc (anti-DoS) ----------------------------------

def test_bloc_sous_le_plafond_est_accepte(executor):
    """Le cas normal ne doit surtout pas etre gene par le plafond."""
    resultat = executor.execute_block(
        [make_tx(0, BOB, 100)], block_number=1, timestamp=0
    )

    assert resultat.gas_used == BASE_TX_GAS


def test_bloc_depassant_le_plafond_est_refuse(executor, state):
    """
    Le pool s'epuise et le bloc est refuse. Les transactions brulent
    ici tout leur gas (boucle infinie), donc le gas consomme egale le
    gas annonce : 31 x 1 000 000 depasse le plafond.
    """
    state.set_code(BOB, BOUCLE_INFINIE)
    state.commit()

    transactions = [
        make_tx(nonce, BOB, gas_limit=1_000_000) for nonce in range(31)
    ]

    with pytest.raises(BlockGasLimitExceeded, match="block gas limit"):
        executor.execute_block(transactions, block_number=1, timestamp=0)


def test_bloc_exactement_au_plafond_est_accepte(executor):
    """
    La borne est un maximum inclusif : atteindre le plafond est legal,
    le depasser ne l'est pas. Test de la valeur frontiere exacte.
    """
    transactions = [make_tx(0, BOB, gas_limit=BLOCK_GAS_LIMIT)]

    resultat = executor.execute_block(
        transactions, block_number=1, timestamp=0
    )

    assert resultat.receipts[0].is_success


def test_un_gas_de_plus_que_le_plafond_est_refuse(executor):
    """L'autre cote de la frontiere : plafond + 1 doit echouer."""
    transactions = [make_tx(0, BOB, gas_limit=BLOCK_GAS_LIMIT + 1)]

    with pytest.raises(BlockGasLimitExceeded):
        executor.execute_block(transactions, block_number=1, timestamp=0)


# --- Restitution du gas inutilise (modele GasPool) -----------------------


def test_le_gas_inutilise_est_rendu_au_pool(executor):
    """
    LE TEST QUI AURAIT REVELE LE BUG INITIAL.

    Plusieurs transactions successives dans un MEME bloc, annoncant
    chacune bien plus que necessaire. Cumul annonce : 100 x 1 000 000 =
    100 000 000, largement au-dessus du plafond de 30 000 000. Cumul
    reellement consomme : 100 x 21 000 = 2 100 000.

    Une pre-passe sur le gas annonce refusait ce bloc parfaitement
    honnete. Avec restitution, il passe -- et c'est le comportement
    correct : annoncer large est le fait normal d'un portefeuille.
    """
    transactions = [
        make_tx(nonce, BOB, value=1, gas_limit=1_000_000)
        for nonce in range(100)
    ]

    annonce = sum(t.gas_limit for t in transactions)
    assert annonce > BLOCK_GAS_LIMIT, "le cumul annonce doit depasser le plafond"

    resultat = executor.execute_block(transactions, block_number=1, timestamp=0)

    assert all(recu.is_success for recu in resultat.receipts)
    assert resultat.gas_used == 100 * BASE_TX_GAS
    assert resultat.gas_used < BLOCK_GAS_LIMIT


def test_la_restitution_s_accumule_sur_de_nombreuses_transactions(executor):
    """
    Verification du cumul lui-meme, transaction par transaction : le
    pool ne doit se vider que du gas consomme. Avec 1 400 transferts,
    le gas annonce (1 400 000 000) est 46 fois le plafond, alors que le
    consomme (29 400 000) reste juste en dessous.

    C'est la capacite reelle d'un bloc : ~1 400 transferts. La
    pre-passe la plafonnait a 300.

    Note sur la marge annoncee : chaque transaction annonce 100 000
    (marge typique d'un portefeuille). Le pool refuse de DEMARRER une
    transaction dont l'annonce depasse le solde restant, donc une
    annonce demesuree reduit malgre tout la capacite -- exactement
    comme SubGas() chez geth. C'est voulu : on ne s'engage jamais
    au-dela de ce qu'on peut payer.
    """
    transactions = [
        make_tx(nonce, BOB, value=1, gas_limit=100_000)
        for nonce in range(1_400)
    ]

    resultat = executor.execute_block(transactions, block_number=1, timestamp=0)

    assert len(resultat.receipts) == 1_400
    assert resultat.gas_used == 1_400 * BASE_TX_GAS
    assert resultat.gas_used <= BLOCK_GAS_LIMIT


def test_restitution_partielle_puis_epuisement(executor, state):
    """
    Les deux regimes dans un seul bloc : d'abord des transferts bon
    marche qui rendent presque tout leur gas, ensuite des appels en
    boucle infinie qui brulent le leur. Le pool doit survivre aux
    premiers et finir par ceder sous les seconds.
    """
    gouffre = b"\x5c" * 20
    state.set_code(gouffre, BOUCLE_INFINIE)
    state.commit()

    # 10 transferts : 10 x 21 000 = 210 000 consommes sur 10 000 000 annonces.
    transactions = [
        make_tx(nonce, BOB, value=1, gas_limit=1_000_000)
        for nonce in range(10)
    ]
    # Puis des gouffres a gas : 31 x 1 000 000 reellement consommes.
    transactions += [
        make_tx(nonce, gouffre, gas_limit=1_000_000)
        for nonce in range(10, 41)
    ]

    with pytest.raises(BlockGasLimitExceeded):
        executor.execute_block(transactions, block_number=1, timestamp=0)


def test_une_transaction_trop_grosse_pour_le_solde_restant_est_refusee(executor, state):
    """
    Le refus porte sur le gas ANNONCE de la prochaine transaction
    comparee au solde RESTANT : on ne demarre jamais une transaction
    qu'on ne pourrait pas payer entierement, meme si elle allait en
    realite consommer peu.
    """
    state.set_code(BOB, BOUCLE_INFINIE)
    state.commit()

    # 29 x 1 000 000 reellement brules -> il reste 1 000 000 au pool.
    transactions = [
        make_tx(nonce, BOB, gas_limit=1_000_000) for nonce in range(29)
    ]
    # Celle-ci en annonce 2 000 000 : plus que le solde restant.
    transactions.append(make_tx(29, ZERO_ADDRESS, gas_limit=2_000_000))

    with pytest.raises(BlockGasLimitExceeded, match="remains"):
        executor.execute_block(transactions, block_number=1, timestamp=0)


def test_le_refus_signale_la_transaction_fautive(executor):
    """
    Le message doit permettre de designer le bloc hostile, pas
    seulement de constater un depassement.
    """
    transactions = [
        make_tx(0, BOB, gas_limit=BLOCK_GAS_LIMIT),
        make_tx(1, BOB, gas_limit=BLOCK_GAS_LIMIT),
    ]

    with pytest.raises(BlockGasLimitExceeded, match="transaction 1"):
        executor.execute_block(transactions, block_number=1, timestamp=0)


def test_bloc_hostile_en_boucle_infinie_est_borne(executor, state):
    """
    Scenario d'attaque mesure pendant l'analyse : 10 000 transactions
    appelant un contrat en boucle infinie, soit environ 45 MINUTES par
    noeud si tout etait execute.

    Le pool borne le travail : le gas consomme ne peut pas depasser
    BLOCK_GAS_LIMIT, donc l'attaque s'arrete apres ~30 transactions.
    Le test borne le temps pour que la protection ne puisse pas
    disparaitre sans etre remarquee.
    """
    import time

    state.set_code(BOB, BOUCLE_INFINIE)
    state.commit()

    transactions = [
        make_tx(nonce, BOB, gas_limit=1_000_000) for nonce in range(10_000)
    ]

    debut = time.monotonic()
    with pytest.raises(BlockGasLimitExceeded):
        executor.execute_block(transactions, block_number=1, timestamp=0)
    duree = time.monotonic() - debut

    assert duree < 30.0, (
        f"refus trop lent ({duree:.2f}s) : le travail n'est plus borne"
    )


def test_bloc_vide_passe_le_plafond(executor):
    """Aucune transaction : pool intact, jamais de refus."""
    resultat = executor.execute_block([], block_number=1, timestamp=0)

    assert resultat.gas_used == 0


def test_le_plafond_porte_sur_le_gas_consomme_non_annonce(executor):
    """
    Choix de conception explicite, INVERSE de la version initiale.

    Ces transactions annoncent 1 000 000 chacune -- cumul de
    31 000 000, au-dessus du plafond -- mais n'en consomment que
    21 000. Le bloc est donc parfaitement valide et doit passer.
    """
    transactions = [
        make_tx(nonce, BOB, value=1, gas_limit=1_000_000)
        for nonce in range(31)
    ]

    assert sum(t.gas_limit for t in transactions) > BLOCK_GAS_LIMIT

    resultat = executor.execute_block(transactions, block_number=1, timestamp=0)

    assert resultat.gas_used == 31 * BASE_TX_GAS


def test_le_refus_est_deterministe(state):
    """
    Anti-fork : le meme bloc doit etre refuse par les trois noeuds.
    Deux executeurs independants doivent conclure identiquement.
    """
    transactions = [
        make_tx(nonce, BOB, gas_limit=BLOCK_GAS_LIMIT) for nonce in range(2)
    ]

    for _ in range(2):
        etat = EVMState()
        etat.set_balance(ALICE, 10**18)
        etat.commit()
        with pytest.raises(BlockGasLimitExceeded):
            EVMExecutor(etat).execute_block(
                transactions, block_number=1, timestamp=0
            )


# --- Garde-fous ----------------------------------------------------------

def test_executor_exige_un_evm_state():
    with pytest.raises(ExecutionError, match="EVMState"):
        EVMExecutor("pas un etat")


def test_execute_transaction_exige_une_transaction(executor):
    with pytest.raises(ExecutionError, match="Transaction"):
        executor.execute_transaction({"nonce": 0})


def test_coinbase_invalide_refuse(executor):
    from src.evm.errors import AddressError

    with pytest.raises(AddressError):
        executor.execute_block([], block_number=1, timestamp=0, coinbase=b"\x01" * 19)
