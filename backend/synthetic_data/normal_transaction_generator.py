"""Generate SHB-centric normal transactions and typed account references."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from synthetic_data.models import (
    Account,
    AccountReferenceType,
    AccountStatus,
    Channel,
    DataVisibility,
    ExternalAccount,
    Transaction,
    TransactionDirection,
    TransactionType,
)
from synthetic_data.profiles import PROFILE_SPECS, ProfileSpec
from synthetic_data.world import WorldState


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def _weighted_channel(rng, channels: tuple) -> Channel:
    items = [channel for channel, _ in channels]
    weights = [weight for _, weight in channels]
    threshold = rng.random() * sum(weights)
    cumulative = 0.0
    for item, weight in zip(items, weights):
        cumulative += weight
        if threshold <= cumulative:
            return item if isinstance(item, Channel) else Channel(item)
    item = items[-1]
    return item if isinstance(item, Channel) else Channel(item)


def _sample_hour(rng, weights: tuple[float, ...]) -> int:
    threshold = rng.random() * sum(weights)
    cumulative = 0.0
    for hour, weight in enumerate(weights):
        cumulative += weight
        if threshold <= cumulative:
            return hour
    return 12


def _sample_amount(rng, spec: ProfileSpec) -> int:
    value = int(math.exp(rng.gauss(math.log(max(spec.amount_median, 1)), 0.4 * spec.volatility)))
    return max(spec.amount_min, min(spec.amount_max, value))


def _can_debit(world: WorldState, account: Account, amount: int) -> bool:
    balance = world.balances.get(account.account_id, 0)
    floor = -account.overdraft_limit if account.allow_overdraft else 0
    return balance - amount >= floor


def _apply_transfer(
    world: WorldState,
    source: Account | ExternalAccount,
    destination: Account | ExternalAccount,
    amount: int,
) -> None:
    if isinstance(source, Account):
        world.balances[source.account_id] -= amount
    if isinstance(destination, Account):
        world.balances[destination.account_id] += amount


def _device_ip_for(world: WorldState, entity_id: str) -> tuple[str, str]:
    devices = world.entity_devices.get(entity_id) or [world.ids.device()]
    ips = world.entity_ips.get(entity_id) or [
        f"10.{world.rng.randint(0, 255)}.{world.rng.randint(0, 255)}.{world.rng.randint(1, 254)}"
    ]
    world.entity_devices.setdefault(entity_id, devices)
    world.entity_ips.setdefault(entity_id, ips)
    return _pick(world.rng, devices), _pick(world.rng, ips)


def _active_accounts(world: WorldState) -> list[Account]:
    return [account for account in world.accounts.values() if account.status == AccountStatus.ACTIVE]


def _reference_type(account: Account | ExternalAccount) -> AccountReferenceType:
    if isinstance(account, Account):
        return AccountReferenceType.INTERNAL_SHB
    return AccountReferenceType.EXTERNAL


def _direction(
    source: Account | ExternalAccount,
    destination: Account | ExternalAccount,
) -> TransactionDirection:
    topology = (_reference_type(source), _reference_type(destination))
    mapping = {
        (AccountReferenceType.INTERNAL_SHB, AccountReferenceType.INTERNAL_SHB): TransactionDirection.INTERNAL,
        (AccountReferenceType.EXTERNAL, AccountReferenceType.INTERNAL_SHB): TransactionDirection.INBOUND,
        (AccountReferenceType.INTERNAL_SHB, AccountReferenceType.EXTERNAL): TransactionDirection.OUTBOUND,
    }
    if topology not in mapping:
        raise ValueError("External-to-external transactions are outside the SHB data boundary")
    return mapping[topology]


def _country(world: WorldState, account: Account | ExternalAccount) -> str:
    if isinstance(account, ExternalAccount):
        return account.country_code
    return world.banks[account.bank_id].country_code


def _touch_external(account: Account | ExternalAccount, occurred_at: datetime) -> None:
    if not isinstance(account, ExternalAccount):
        return
    if account.first_seen_at is None or occurred_at < account.first_seen_at:
        account.first_seen_at = occurred_at
    if account.last_seen_at is None or occurred_at > account.last_seen_at:
        account.last_seen_at = occurred_at


def ensure_balance(
    world: WorldState,
    account_id: str,
    minimum: int,
    *,
    reason: str = "scenario-prefund",
) -> None:
    """Fund an SHB account visibly without changing its opening balance."""
    current = world.balances.get(account_id, 0)
    if current < minimum:
        fund_account(world, account_id, minimum - current, reason=reason)


def fund_account(
    world: WorldState,
    account_id: str,
    amount: int,
    *,
    reason: str = "liquidity-support",
) -> None:
    """Create a payment-message inbound for an SHB liquidity gap."""
    if amount <= 0:
        return
    account = world.get_account(account_id)
    if account is None:
        raise ValueError(f"Cannot fund unknown SHB account: {account_id}")
    settlement = world.external_accounts["EXT-ACC-SETTLEMENT-001"]
    funding_time = max(world.config.world_start, account.opened_at) + timedelta(seconds=1)
    transaction = create_transaction(
        world,
        settlement,
        account,
        amount,
        funding_time,
        transaction_type=TransactionType.TRANSFER,
        channel=Channel.API,
        purpose_code="LOAN",
        description=f"DECLARED-FUNDING-{reason.upper()}",
        evidence_source="INTERBANK_PAYMENT_MESSAGE",
    )
    if transaction is None:
        raise RuntimeError(f"Unable to fund SHB account {account_id}")


def create_transaction(
    world: WorldState,
    source: Account | ExternalAccount,
    dest: Account | ExternalAccount,
    amount: int,
    occurred_at: datetime,
    *,
    transaction_type: Optional[TransactionType] = None,
    channel: Optional[Channel] = None,
    purpose_code: str = "TRANSFER",
    description: str = "",
    source_ip: Optional[str] = None,
    device_id: Optional[str] = None,
    force: bool = False,
    count_as_normal: bool = False,
    data_visibility: Optional[DataVisibility] = None,
    evidence_source: Optional[str] = None,
) -> Optional[Transaction]:
    """Create one SHB-observable transaction with typed endpoints."""
    if amount <= 0:
        return None
    direction = _direction(source, dest)
    source_country = _country(world, source)
    destination_country = _country(world, dest)
    is_cross_border = source_country != destination_country

    if isinstance(source, Account):
        if occurred_at < source.opened_at:
            occurred_at = source.opened_at + timedelta(minutes=1)
        if isinstance(dest, Account) and occurred_at < dest.opened_at:
            occurred_at = dest.opened_at + timedelta(minutes=1)
        if not _can_debit(world, source, amount):
            if force:
                ensure_balance(world, source.account_id, amount)
            else:
                return None
        if not _can_debit(world, source, amount):
            return None
        if device_id is None or source_ip is None:
            generated_device, generated_ip = _device_ip_for(world, source.owner_entity_id)
            device_id = device_id or generated_device
            source_ip = source_ip or generated_ip
        if channel is None:
            profile = source.behavioral_profile
            channel = (
                _weighted_channel(world.rng, PROFILE_SPECS[profile].channels)
                if profile in PROFILE_SPECS
                else Channel.MOBILE
            )
    else:
        source_ip = None
        device_id = None
        channel = channel or (Channel.SWIFT if is_cross_border else Channel.API)

    if transaction_type is None:
        transaction_type = TransactionType.FX if is_cross_border else TransactionType.TRANSFER

    visibility = data_visibility
    if visibility is None:
        visibility = (
            DataVisibility.FULL_INTERNAL
            if direction == TransactionDirection.INTERNAL
            else DataVisibility.PAYMENT_MESSAGE_ONLY
        )
    if evidence_source is None:
        evidence_source = (
            "SHB_TRANSACTION_LEDGER"
            if direction == TransactionDirection.INTERNAL
            else "PAYMENT_MESSAGE"
        )

    transaction = Transaction(
        transaction_id=world.ids.transaction(),
        source_account_ref=source.account_id,
        source_account_type=_reference_type(source),
        source_bank_id=source.bank_id,
        destination_account_ref=dest.account_id,
        destination_account_type=_reference_type(dest),
        destination_bank_id=dest.bank_id,
        amount=amount,
        currency=world.config.base_currency,
        transaction_type=transaction_type,
        channel=channel,
        purpose_code=purpose_code,
        description=description or f"PMT-{world.rng.randint(100000, 999999)}",
        occurred_at=occurred_at,
        direction=direction,
        source_ip=source_ip,
        device_id=device_id,
        is_cross_border=is_cross_border,
        source_country=source_country,
        destination_country=destination_country,
        data_visibility=visibility,
        evidence_source=evidence_source,
        payment_reference=f"PAYREF-{world.rng.randint(10000000, 99999999)}",
    )
    _apply_transfer(world, source, dest, amount)
    _touch_external(source, occurred_at)
    _touch_external(dest, occurred_at)
    world.transactions[transaction.transaction_id] = transaction
    if count_as_normal:
        world.normal_transaction_ids.add(transaction.transaction_id)
    return transaction


def _largest_remainder_counts(total: int, ratios: dict[TransactionDirection, float]) -> dict[TransactionDirection, int]:
    raw = {direction: total * ratio for direction, ratio in ratios.items()}
    counts = {direction: int(value) for direction, value in raw.items()}
    remainder = total - sum(counts.values())
    order = sorted(ratios, key=lambda direction: (raw[direction] - counts[direction], direction.value), reverse=True)
    for direction in order[:remainder]:
        counts[direction] += 1
    return counts


def _transaction_timestamp(world: WorldState, index: int, total: int) -> datetime:
    span_seconds = int((world.config.world_end - world.config.world_start).total_seconds())
    offset = int((index + 1) * span_seconds / (total + 1))
    return world.config.world_start + timedelta(seconds=offset)


def generate_normal_transactions(world: WorldState) -> None:
    """Generate exact SHB-centric direction quotas with no external ledger."""
    cfg = world.config
    accounts = _active_accounts(world)
    if not accounts or cfg.n_transactions <= 0:
        return

    counts = _largest_remainder_counts(
        cfg.n_transactions,
        {
            TransactionDirection.INTERNAL: cfg.internal_transaction_ratio,
            TransactionDirection.INBOUND: cfg.inbound_transaction_ratio,
            TransactionDirection.OUTBOUND: cfg.outbound_transaction_ratio,
        },
    )
    schedule = [direction for direction, count in counts.items() for _ in range(count)]
    world.rng.shuffle(schedule)

    external_slots = [index for index, direction in enumerate(schedule) if direction != TransactionDirection.INTERNAL]
    cross_border_count = min(round(cfg.n_transactions * cfg.cross_border_ratio), len(external_slots))
    cross_border_slots = set(world.rng.sample(external_slots, cross_border_count))

    domestic_external = [
        account for account in world.external_accounts.values() if account.country_code == "VN"
    ]
    foreign_external = [
        account
        for account in world.external_accounts.values()
        if account.country_code != "VN" and account.bank_id != cfg.high_risk_foreign_bank_id
    ]
    if not domestic_external or not foreign_external:
        raise ValueError("Normal transaction generation requires domestic and foreign external accounts")
    world.rng.shuffle(domestic_external)
    world.rng.shuffle(foreign_external)
    domestic_index = 0
    foreign_index = 0

    for index, direction in enumerate(schedule):
        timestamp = _transaction_timestamp(world, index, len(schedule))
        eligible = [account for account in accounts if account.opened_at <= timestamp]
        if len(eligible) < 2:
            timestamp = max(timestamp, max(account.opened_at for account in accounts) + timedelta(minutes=1))
            eligible = accounts
        source_internal = _pick(world.rng, eligible)
        if direction != TransactionDirection.INBOUND:
            funded = [
                account
                for account in eligible
                if world.balances.get(account.account_id, 0)
                > (-account.overdraft_limit if account.allow_overdraft else 0)
            ]
            if not funded:
                raise RuntimeError("No funded SHB source is available for normal traffic")
            source_internal = _pick(world.rng, funded)
        profile = source_internal.behavioral_profile
        spec = PROFILE_SPECS[profile]
        amount = _sample_amount(world.rng, spec)
        if direction != TransactionDirection.INBOUND:
            floor = (
                -source_internal.overdraft_limit
                if source_internal.allow_overdraft
                else 0
            )
            spendable = world.balances[source_internal.account_id] - floor
            amount = min(amount, spendable)
        purpose = _pick(world.rng, spec.typical_purpose_codes)
        channel = _weighted_channel(world.rng, spec.channels)

        if direction == TransactionDirection.INTERNAL:
            destinations = [account for account in eligible if account.account_id != source_internal.account_id]
            destination_internal = _pick(world.rng, destinations)
            transaction = create_transaction(
                world,
                source_internal,
                destination_internal,
                amount,
                timestamp,
                channel=channel,
                purpose_code=purpose,
                description=f"{purpose}-{world.rng.randint(100000, 999999)}",
                count_as_normal=True,
            )
        else:
            if index in cross_border_slots:
                external = foreign_external[foreign_index % len(foreign_external)]
                foreign_index += 1
                channel = Channel.SWIFT
                if purpose not in ("GOODS", "INVOICE", "SERVICES"):
                    purpose = "FX"
            else:
                external = domestic_external[domestic_index % len(domestic_external)]
                domestic_index += 1
            if direction == TransactionDirection.INBOUND:
                transaction = create_transaction(
                    world,
                    external,
                    source_internal,
                    amount,
                    timestamp,
                    channel=channel,
                    purpose_code=purpose,
                    description=f"INBOUND-{world.rng.randint(100000, 999999)}",
                    count_as_normal=True,
                )
            else:
                transaction = create_transaction(
                    world,
                    source_internal,
                    external,
                    amount,
                    timestamp,
                    channel=channel,
                    purpose_code=purpose,
                    description=f"OUTBOUND-{world.rng.randint(100000, 999999)}",
                    count_as_normal=True,
                )
        if transaction is None:
            raise RuntimeError(f"Failed to create normal transaction at schedule index {index}")

    if len(world.normal_transaction_ids) != cfg.n_transactions:
        raise RuntimeError(
            f"Normal transaction count {len(world.normal_transaction_ids)} != {cfg.n_transactions}"
        )
