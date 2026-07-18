"""Strict replay helpers for the SHB side of the observed ledger."""

from __future__ import annotations

from datetime import timedelta

from synthetic_data.models import AccountReferenceType, Channel, TransactionType
from synthetic_data.world import WorldState


def fund_ledger_deficits(world: WorldState) -> int:
    """Insert visible inbound funding immediately before an SHB replay deficit."""
    from synthetic_data.normal_transaction_generator import create_transaction

    balances = {
        account.account_id: account.initial_balance
        for account in world.accounts.values()
    }
    settlement = world.external_accounts["EXT-ACC-SETTLEMENT-001"]
    inserted = 0
    transactions = sorted(
        world.transactions.values(),
        key=lambda item: (item.occurred_at, item.transaction_id),
    )
    for transaction in transactions:
        if transaction.source_account_type == AccountReferenceType.INTERNAL_SHB:
            account = world.accounts[transaction.source_account_ref]
            floor = -account.overdraft_limit if account.allow_overdraft else 0
            projected = balances[account.account_id] - transaction.amount
            if projected < floor:
                shortfall = floor - projected
                funding_time = max(
                    account.opened_at + timedelta(seconds=1),
                    transaction.occurred_at - timedelta(seconds=1),
                )
                created = create_transaction(
                    world,
                    settlement,
                    account,
                    shortfall,
                    funding_time,
                    transaction_type=TransactionType.TRANSFER,
                    channel=Channel.API,
                    purpose_code="LOAN",
                    description="DECLARED-FUNDING-LEDGER-RECONCILE",
                    evidence_source="INTERBANK_PAYMENT_MESSAGE",
                )
                if created is None:
                    raise RuntimeError(
                        f"Unable to reconcile SHB balance for {account.account_id}"
                    )
                balances[account.account_id] += shortfall
                inserted += 1
            balances[account.account_id] -= transaction.amount
        if transaction.destination_account_type == AccountReferenceType.INTERNAL_SHB:
            balances[transaction.destination_account_ref] += transaction.amount
    return inserted


def strict_replay_ok(world: WorldState) -> list[str]:
    balances = {account.account_id: account.initial_balance for account in world.accounts.values()}
    errors: list[str] = []
    for transaction in sorted(
        world.transactions.values(), key=lambda item: (item.occurred_at, item.transaction_id)
    ):
        if transaction.source_account_type == AccountReferenceType.INTERNAL_SHB:
            source = world.accounts[transaction.source_account_ref]
            balances[source.account_id] -= transaction.amount
            floor = -source.overdraft_limit if source.allow_overdraft else 0
            if balances[source.account_id] < floor:
                errors.append(
                    f"{source.account_id} at {transaction.transaction_id}: {balances[source.account_id]}"
                )
        if transaction.destination_account_type == AccountReferenceType.INTERNAL_SHB:
            balances[transaction.destination_account_ref] += transaction.amount
    return errors
