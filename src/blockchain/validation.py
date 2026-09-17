"""
Blockchain validation utilities.
"""

from __future__ import annotations

from typing import Sequence

from src.blockchain.block import Block, BlockError
from src.blockchain.transaction import Transaction, TransactionError


class ValidationError(Exception):
    """Raised when blockchain data fails validation."""


def validate_transaction(transaction: Transaction) -> bool:
    if not isinstance(transaction, Transaction):
        raise ValidationError("transaction must be a Transaction")

    try:
        transaction.validate()
    except TransactionError as exc:
        raise ValidationError(str(exc)) from exc

    if not transaction.is_signed:
        raise ValidationError("transaction is not signed")

    return True


def is_transaction_valid(transaction: Transaction) -> bool:
    try:
        return validate_transaction(transaction)
    except ValidationError:
        return False


def validate_block(block: Block) -> bool:
    if not isinstance(block, Block):
        raise ValidationError("block must be a Block")

    try:
        block.validate()
    except BlockError as exc:
        raise ValidationError(str(exc)) from exc

    return True


def is_block_valid(block: Block) -> bool:
    try:
        return validate_block(block)
    except ValidationError:
        return False


def validate_transaction_list(transactions: Sequence[Transaction]) -> bool:
    if not isinstance(transactions, (list, tuple)):
        raise ValidationError("transactions must be a list or tuple")

    seen_tx_ids: set[bytes] = set()

    for transaction in transactions:
        validate_transaction(transaction)

        tx_id = transaction.tx_id

        if tx_id in seen_tx_ids:
            raise ValidationError(f"duplicate transaction ID: {tx_id.hex()}")

        seen_tx_ids.add(tx_id)

    return True


def validate_block_chain_link(previous_block: Block, current_block: Block) -> bool:
    validate_block(previous_block)
    validate_block(current_block)

    if current_block.height != previous_block.height + 1:
        raise ValidationError("current block height must equal previous block height + 1")

    if current_block.previous_block_hash != previous_block.block_hash:
        raise ValidationError(
            "current block previous_block_hash does not match previous block hash"
        )

    return True


def validate_block_sequence(blocks: Sequence[Block]) -> bool:
    if not isinstance(blocks, (list, tuple)):
        raise ValidationError("blocks must be a list or tuple")

    if not blocks:
        raise ValidationError("block sequence must not be empty")

    for block in blocks:
        validate_block(block)

    for previous_block, current_block in zip(blocks, blocks[1:]):
        validate_block_chain_link(previous_block, current_block)

    return True
