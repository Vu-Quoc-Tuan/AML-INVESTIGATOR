"""Ledger helpers for strict chronological replay."""

from __future__ import annotations

from synthetic_data.world import WorldState


def fund_ledger_deficits(world: WorldState) -> int:
    """Materialise opening-window funding transactions for replay deficits.

    Unlike the old reconciliation approach, this never changes a behavioral
    profile's generated ``initial_balance`` after observing future activity.
    """
    txns = sorted(
        world.transactions.values(),
        key=lambda t: (t.occurred_at, t.transaction_id),
    )

    # Collect all account ids that appear
    account_ids = set(world.accounts) | set(world.demo_accounts)
    for t in txns:
        account_ids.add(t.source_account_id)
        account_ids.add(t.destination_account_id)

    # Start from declared initials and calculate each required liquidity gap.
    initial = {}
    for aid in account_ids:
        acc = world.get_account(aid)
        initial[aid] = acc.initial_balance if acc else 0

    # Simulate with current initials; track minimum balance per account
    bal = dict(initial)
    min_bal = dict(initial)
    for t in txns:
        bal[t.source_account_id] = bal.get(t.source_account_id, 0) - t.amount
        bal[t.destination_account_id] = bal.get(t.destination_account_id, 0) + t.amount
        s = t.source_account_id
        min_bal[s] = min(min_bal.get(s, 0), bal[s])
        d = t.destination_account_id
        min_bal[d] = min(min_bal.get(d, bal[d]), bal[d])

    required: dict[str, int] = {}
    for aid, mb in min_bal.items():
        acc = world.get_account(aid)
        if acc is None:
            continue
        floor = -acc.overdraft_limit if acc.allow_overdraft else 0
        if mb < floor:
            required[aid] = floor - mb

    if not required:
        return 0

    # Import here to avoid a module cycle at import time.
    from synthetic_data.normal_transaction_generator import fund_account

    for aid in sorted(required):
        fund_account(world, aid, required[aid], reason="opening-window-liquidity")
    return len(required)


def strict_replay_ok(world: WorldState) -> list[str]:
    """Return list of error strings if replay goes negative; empty if OK."""
    errors: list[str] = []
    bal: dict[str, int] = {}
    for a in world.accounts.values():
        bal[a.account_id] = a.initial_balance
    for a in world.demo_accounts.values():
        bal[a.account_id] = a.initial_balance
    txns = sorted(
        world.transactions.values(),
        key=lambda t: (t.occurred_at, t.transaction_id),
    )
    for t in txns:
        bal[t.source_account_id] = bal.get(t.source_account_id, 0) - t.amount
        bal[t.destination_account_id] = bal.get(t.destination_account_id, 0) + t.amount
        acc = world.get_account(t.source_account_id)
        if acc is None:
            continue
        floor = -acc.overdraft_limit if acc.allow_overdraft else 0
        if bal[t.source_account_id] < floor:
            if len(errors) < 8:
                errors.append(
                    f"{t.source_account_id} at {t.transaction_id}: {bal[t.source_account_id]}"
                )
    return errors
