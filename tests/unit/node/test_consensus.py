"""
Tests de Consensus : tour de rôle PoA, construction de bloc
candidat. Utilise tmp_path + vraies clés ML-DSA.
"""

import pytest

from src.blockchain.block import Block, ZERO_HASH
from src.blockchain.blockchain import Blockchain
from src.blockchain.storage import ChainStorage
from src.blockchain.transaction import Transaction
from src.crypto.address import ADDRESS_LENGTH, public_key_to_address
from src.crypto.ml_dsa import MLDSA
from src.node.consensus import Consensus, ConsensusError
from src.node.mempool import Mempool

RECIPIENT = b"\x01" * ADDRESS_LENGTH


@pytest.fixture
def ml_dsa():
    return MLDSA()


@pytest.fixture
def validator_keypairs(ml_dsa):
    """Three distinct validator keypairs for a 3-node PoA network."""
    return [ml_dsa.generate_keypair() for _ in range(3)]


@pytest.fixture
def validator_addresses(validator_keypairs):
    return [public_key_to_address(kp.public_key) for kp in validator_keypairs]


def make_consensus(validator_addresses, local_index=0):
    return Consensus(
        authorized_validators=validator_addresses,
        local_address=validator_addresses[local_index],
    )


def make_signed_tx(ml_dsa, keypair, nonce=0):
    tx = Transaction.create(
        nonce=nonce,
        public_key=keypair.public_key,
        recipient=RECIPIENT,
        value=10,
        gas_limit=21000,
        gas_price=1,
        data=b"",
    )
    sig = ml_dsa.sign(tx.signing_hash, keypair.secret_key)
    return tx.with_signature(sig)


def make_chain(tmp_path, validator_keypair):
    storage = ChainStorage(tmp_path)
    return Blockchain.create_new(
        storage,
        validator_public_key=validator_keypair.public_key,
        timestamp=1_700_000_000,
    )


# ---------------------------------------------------------------------
# Construction de Consensus
# ---------------------------------------------------------------------


def test_consensus_creation_succeeds(validator_addresses):
    consensus = make_consensus(validator_addresses, local_index=0)
    assert consensus is not None


def test_consensus_rejects_empty_validator_set():
    with pytest.raises(ConsensusError, match="empty"):
        Consensus(authorized_validators=[], local_address=b"\x01" * ADDRESS_LENGTH)


def test_consensus_rejects_local_address_not_in_validators(validator_addresses):
    unknown_address = b"\xff" * ADDRESS_LENGTH
    with pytest.raises(ConsensusError, match="not in authorized_validators"):
        Consensus(
            authorized_validators=validator_addresses,
            local_address=unknown_address,
        )


# ---------------------------------------------------------------------
# get_expected_proposer
# ---------------------------------------------------------------------


def test_get_expected_proposer_cycles_through_validators(validator_addresses):
    consensus = make_consensus(validator_addresses, local_index=0)

    assert consensus.get_expected_proposer(0) == validator_addresses[0]
    assert consensus.get_expected_proposer(1) == validator_addresses[1]
    assert consensus.get_expected_proposer(2) == validator_addresses[2]
    assert consensus.get_expected_proposer(3) == validator_addresses[0]
    assert consensus.get_expected_proposer(4) == validator_addresses[1]


def test_get_expected_proposer_with_single_validator():
    address = b"\xaa" * ADDRESS_LENGTH
    consensus = Consensus(authorized_validators=[address], local_address=address)

    for height in range(5):
        assert consensus.get_expected_proposer(height) == address


def test_get_expected_proposer_rejects_negative_height(validator_addresses):
    consensus = make_consensus(validator_addresses)
    with pytest.raises(ConsensusError, match="non-negative"):
        consensus.get_expected_proposer(-1)


def test_get_expected_proposer_rejects_bool_height(validator_addresses):
    consensus = make_consensus(validator_addresses)
    with pytest.raises(ConsensusError):
        consensus.get_expected_proposer(True)


# ---------------------------------------------------------------------
# is_local_node_turn
# ---------------------------------------------------------------------


def test_is_local_node_turn_true_on_own_turn(validator_addresses):
    consensus = make_consensus(validator_addresses, local_index=0)
    assert consensus.is_local_node_turn(0) is True
    assert consensus.is_local_node_turn(3) is True


def test_is_local_node_turn_false_on_other_turn(validator_addresses):
    consensus = make_consensus(validator_addresses, local_index=0)
    assert consensus.is_local_node_turn(1) is False
    assert consensus.is_local_node_turn(2) is False


def test_is_local_node_turn_for_each_validator(validator_addresses):
    for local_index in range(3):
        consensus = make_consensus(validator_addresses, local_index=local_index)
        assert consensus.is_local_node_turn(local_index) is True
        assert consensus.is_local_node_turn((local_index + 1) % 3) is False


# ---------------------------------------------------------------------
# is_expected_proposer
# ---------------------------------------------------------------------


def test_is_expected_proposer_true_for_correct_validator(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    consensus = make_consensus(validator_addresses, local_index=0)
    chain = make_chain(tmp_path, validator_keypairs[0])

    # height 1 → tour du validator_keypairs[1]
    block = Block.create(
        height=1,
        previous_block_hash=chain.genesis_block.block_hash,
        timestamp=1_700_000_010,
        transactions=(),
        validator_public_key=validator_keypairs[1].public_key,
    )

    assert consensus.is_expected_proposer(block) is True


def test_is_expected_proposer_false_for_wrong_validator(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    consensus = make_consensus(validator_addresses, local_index=0)
    chain = make_chain(tmp_path, validator_keypairs[0])

    # height 1 → tour du validator[1], mais on met validator[0]
    block = Block.create(
        height=1,
        previous_block_hash=chain.genesis_block.block_hash,
        timestamp=1_700_000_010,
        transactions=(),
        validator_public_key=validator_keypairs[0].public_key,
    )

    assert consensus.is_expected_proposer(block) is False


# ---------------------------------------------------------------------
# build_candidate_block
# ---------------------------------------------------------------------


def test_build_candidate_block_produces_signed_block(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    # height 1 → tour du validator[1]
    consensus = make_consensus(validator_addresses, local_index=1)
    chain = make_chain(tmp_path, validator_keypairs[0])

    mempool = Mempool(ml_dsa)

    block = consensus.build_candidate_block(
        blockchain=chain,
        mempool=mempool,
        local_public_key=validator_keypairs[1].public_key,
        local_secret_key=validator_keypairs[1].secret_key,
        timestamp=1_700_000_010,
        ml_dsa=ml_dsa,
    )

    assert block.is_signed is True
    assert block.height == 1
    assert block.previous_block_hash == chain.genesis_block.block_hash


def test_build_candidate_block_signature_is_cryptographically_valid(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    consensus = make_consensus(validator_addresses, local_index=1)
    chain = make_chain(tmp_path, validator_keypairs[0])

    block = consensus.build_candidate_block(
        blockchain=chain,
        mempool=Mempool(ml_dsa),
        local_public_key=validator_keypairs[1].public_key,
        local_secret_key=validator_keypairs[1].secret_key,
        timestamp=1_700_000_010,
        ml_dsa=ml_dsa,
    )

    assert ml_dsa.verify(
        block.signing_hash, block.signature, block.validator_public_key
    ) is True


def test_build_candidate_block_includes_mempool_transactions(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    consensus = make_consensus(validator_addresses, local_index=1)
    chain = make_chain(tmp_path, validator_keypairs[0])

    sender_keypair = ml_dsa.generate_keypair()
    mempool = Mempool(ml_dsa)
    tx_a = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    tx_b = make_signed_tx(ml_dsa, sender_keypair, nonce=1)
    mempool.add_transaction(tx_a)
    mempool.add_transaction(tx_b)

    block = consensus.build_candidate_block(
        blockchain=chain,
        mempool=mempool,
        local_public_key=validator_keypairs[1].public_key,
        local_secret_key=validator_keypairs[1].secret_key,
        timestamp=1_700_000_010,
        ml_dsa=ml_dsa,
    )

    assert block.transaction_count == 2
    included_tx_ids = {tx.tx_id for tx in block.transactions}
    assert tx_a.tx_id in included_tx_ids
    assert tx_b.tx_id in included_tx_ids


def test_build_candidate_block_respects_max_transactions_limit(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    consensus = make_consensus(validator_addresses, local_index=1)
    chain = make_chain(tmp_path, validator_keypairs[0])

    sender_keypair = ml_dsa.generate_keypair()
    mempool = Mempool(ml_dsa)
    for nonce in range(5):
        mempool.add_transaction(make_signed_tx(ml_dsa, sender_keypair, nonce=nonce))

    block = consensus.build_candidate_block(
        blockchain=chain,
        mempool=mempool,
        local_public_key=validator_keypairs[1].public_key,
        local_secret_key=validator_keypairs[1].secret_key,
        timestamp=1_700_000_010,
        ml_dsa=ml_dsa,
        max_transactions=2,
    )

    assert block.transaction_count == 2


def test_build_candidate_block_does_not_modify_mempool(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    """
    build_candidate_block() ne retire pas les transactions du mempool.
    C'est Node._accept_block() qui le fait, après validation et ajout
    à la blockchain.
    """
    consensus = make_consensus(validator_addresses, local_index=1)
    chain = make_chain(tmp_path, validator_keypairs[0])

    sender_keypair = ml_dsa.generate_keypair()
    mempool = Mempool(ml_dsa)
    tx = make_signed_tx(ml_dsa, sender_keypair, nonce=0)
    mempool.add_transaction(tx)

    consensus.build_candidate_block(
        blockchain=chain,
        mempool=mempool,
        local_public_key=validator_keypairs[1].public_key,
        local_secret_key=validator_keypairs[1].secret_key,
        timestamp=1_700_000_010,
        ml_dsa=ml_dsa,
    )

    assert mempool.size() == 1
    assert mempool.contains(tx.tx_id) is True


def test_build_candidate_block_raises_when_not_local_turn(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    # local = validator[0], height 1 = tour du validator[1]
    consensus = make_consensus(validator_addresses, local_index=0)
    chain = make_chain(tmp_path, validator_keypairs[0])

    with pytest.raises(ConsensusError, match="not this node's turn"):
        consensus.build_candidate_block(
            blockchain=chain,
            mempool=Mempool(ml_dsa),
            local_public_key=validator_keypairs[0].public_key,
            local_secret_key=validator_keypairs[0].secret_key,
            timestamp=1_700_000_010,
            ml_dsa=ml_dsa,
        )


def test_build_candidate_block_not_added_to_blockchain(
    tmp_path, ml_dsa, validator_keypairs, validator_addresses
):
    consensus = make_consensus(validator_addresses, local_index=1)
    chain = make_chain(tmp_path, validator_keypairs[0])
    height_before = chain.height

    consensus.build_candidate_block(
        blockchain=chain,
        mempool=Mempool(ml_dsa),
        local_public_key=validator_keypairs[1].public_key,
        local_secret_key=validator_keypairs[1].secret_key,
        timestamp=1_700_000_010,
        ml_dsa=ml_dsa,
    )

    assert chain.height == height_before
