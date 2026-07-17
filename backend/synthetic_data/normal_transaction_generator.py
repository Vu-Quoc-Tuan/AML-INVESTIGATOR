"""Generate normal (baseline) transactions from behavioral profiles."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from synthetic_data.models import (
    Account,
    AccountStatus,
    BehavioralProfile,
    Channel,
    EntityType,
    Transaction,
    TransactionType,
)
from synthetic_data.profiles import PROFILE_SPECS, ProfileSpec
from synthetic_data.world import WorldState

# Roles that should resolve to company-owned accounts
_COMPANY_ROLES = frozenset(
    {
        "merchant",
        "utility",
        "employer",
        "supplier",
        "vendor",
        "platform",
        "client",
        "venue",
        "logistics",
        "customs",
        "payroll",
        "cloud",
        "service",
        "tax",
        "insurance",
        "ticket_buyer",  # ticket_buyer is customer paying company — handled specially
        "foreign_supplier",
        "domestic_buyer",
        "artist",
    }
)
_CUSTOMER_ROLES = frozenset(
    {
        "peer",
        "family",
        "employee",
        "parent",
        "customer",
        "ticket_buyer",
    }
)

_PURPOSE_TO_TYPE = {
    "PAYROLL": TransactionType.TRANSFER,
    "SUPPLIER": TransactionType.PAYMENT,
    "RENT": TransactionType.PAYMENT,
    "UTILITIES": TransactionType.PAYMENT,
    "GOODS": TransactionType.PAYMENT,
    "SERVICES": TransactionType.PAYMENT,
    "TRANSFER": TransactionType.TRANSFER,
    "CASH_IN": TransactionType.CASH_DEPOSIT,
    "CASH_OUT": TransactionType.CASH_WITHDRAWAL,
    "FX": TransactionType.FX,
    "TICKET": TransactionType.PAYMENT,
    "INVOICE": TransactionType.PAYMENT,
    "LOAN": TransactionType.TRANSFER,
    "REFUND": TransactionType.TRANSFER,
    "OTHER": TransactionType.TRANSFER,
    "PAYMENT": TransactionType.PAYMENT,
}


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def _weighted_channel(rng, channels: tuple) -> Channel:
    items = [c for c, _ in channels]
    weights = [w for _, w in channels]
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for item, w in zip(items, weights):
        acc += w
        if r <= acc:
            return item if isinstance(item, Channel) else Channel(item)
    return items[-1] if isinstance(items[-1], Channel) else Channel(items[-1])


def _sample_hour(rng, weights: tuple[float, ...]) -> int:
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for h, w in enumerate(weights):
        acc += w
        if r <= acc:
            return h
    return 12


def _sample_amount(rng, spec: ProfileSpec) -> int:
    mu = math.log(max(spec.amount_median, 1))
    sigma = 0.4 * spec.volatility
    val = int(math.exp(rng.gauss(mu, sigma)))
    return max(spec.amount_min, min(spec.amount_max, val))


def _can_debit(world: WorldState, account: Account, amount: int) -> bool:
    bal = world.balances.get(account.account_id, 0)
    if account.allow_overdraft:
        return bal - amount >= -account.overdraft_limit
    return bal >= amount


def _apply_transfer(world: WorldState, source_id: str, dest_id: str, amount: int) -> None:
    world.balances[source_id] = world.balances.get(source_id, 0) - amount
    world.balances[dest_id] = world.balances.get(dest_id, 0) + amount


def _device_ip_for(world: WorldState, entity_id: str) -> tuple[str, str]:
    devices = world.entity_devices.get(entity_id) or [world.ids.device()]
    ips = world.entity_ips.get(entity_id) or [
        f"10.{world.rng.randint(0, 255)}.{world.rng.randint(0, 255)}.{world.rng.randint(1, 254)}"
    ]
    world.entity_devices.setdefault(entity_id, devices)
    world.entity_ips.setdefault(entity_id, ips)
    return _pick(world.rng, devices), _pick(world.rng, ips)


def _active_accounts(world: WorldState) -> list[Account]:
    return [a for a in world.accounts.values() if a.status == AccountStatus.ACTIVE]


def _accounts_for_entity_type(world: WorldState, entity_type: EntityType) -> list[Account]:
    return [
        a
        for a in _active_accounts(world)
        if a.owner_entity_type == entity_type
    ]


def _counterpart_account(
    world: WorldState, source: Account, role: str
) -> Optional[Account]:
    """Resolve a counterparty account compatible with the behavioral role."""
    rng = world.rng
    candidates = [
        a
        for a in _active_accounts(world)
        if a.account_id != source.account_id
    ]
    if not candidates:
        return None

    if role == "foreign_supplier":
        foreign = _normal_foreign_account(world, source)
        if foreign is not None:
            return foreign

    if role in ("employer", "payroll", "platform", "cloud", "utility"):
        pool = [
            a
            for a in candidates
            if a.owner_entity_type == EntityType.COMPANY
            and a.behavioral_profile
            in (
                BehavioralProfile.PAYROLL_COMPANY,
                BehavioralProfile.SME_SOFTWARE_COMPANY,
                BehavioralProfile.RETAIL_MERCHANT,
                BehavioralProfile.IMPORT_EXPORT_COMPANY,
                BehavioralProfile.EVENT_ORGANIZER,
            )
        ]
        if pool:
            return _pick(rng, pool)
        company_pool = _accounts_for_entity_type(world, EntityType.COMPANY)
        company_pool = [a for a in company_pool if a.account_id != source.account_id]
        if company_pool:
            return _pick(rng, company_pool)

    if role in ("merchant", "supplier", "vendor", "venue", "logistics", "customs", "service", "domestic_buyer", "client", "artist", "tax", "insurance"):
        company_pool = [
            a for a in candidates if a.owner_entity_type == EntityType.COMPANY
        ]
        if company_pool:
            return _pick(rng, company_pool)

    if role in ("peer", "family", "employee", "parent", "customer", "ticket_buyer"):
        peer_pool = [
            a for a in candidates if a.owner_entity_type == EntityType.CUSTOMER
        ]
        if peer_pool:
            return _pick(rng, peer_pool)

    # Unknown roles must not silently pick random if we can still classify
    if role in _COMPANY_ROLES:
        company_pool = [
            a for a in candidates if a.owner_entity_type == EntityType.COMPANY
        ]
        if company_pool:
            return _pick(rng, company_pool)
    if role in _CUSTOMER_ROLES:
        peer_pool = [
            a for a in candidates if a.owner_entity_type == EntityType.CUSTOMER
        ]
        if peer_pool:
            return _pick(rng, peer_pool)

    return _pick(rng, candidates)


def _expected_foreign_countries(world: WorldState, source: Account) -> list[str]:
    """Return declared, non-high-risk countries for ordinary cross-border traffic."""
    countries: list[str] = []
    if source.owner_entity_type == EntityType.COMPANY:
        company = world.companies.get(source.owner_entity_id)
        if company is not None:
            countries.extend(company.expected_countries)
    elif source.owner_entity_type == EntityType.CUSTOMER:
        profile = source.behavioral_profile
        if profile is not None and PROFILE_SPECS[profile].p_cross_border >= 0.1:
            countries.extend(("US", "SG"))

    allowed = set(world.config.normal_foreign_countries)
    declared = [country for country in countries if country in allowed]
    return declared or list(world.config.normal_foreign_countries)


def _normal_foreign_account(world: WorldState, source: Account) -> Optional[Account]:
    countries = _expected_foreign_countries(world, source)
    if not countries:
        return None
    country = _pick(world.rng, countries)
    return world.demo_accounts.get(f"ACCT-FOREIGN-{country}-001")


def _transaction_type_for(purpose: str, is_xb: bool) -> TransactionType:
    if is_xb:
        return TransactionType.FX
    return _PURPOSE_TO_TYPE.get(purpose, TransactionType.TRANSFER)


def ensure_balance(
    world: WorldState,
    account_id: str,
    minimum: int,
    *,
    reason: str = "scenario-prefund",
) -> None:
    """Fund an account transparently without rewriting its opening balance."""
    current = world.balances.get(account_id, 0)
    if current >= minimum:
        return
    fund_account(world, account_id, minimum - current, reason=reason)


def fund_account(
    world: WorldState,
    account_id: str,
    amount: int,
    *,
    reason: str = "liquidity-support",
) -> None:
    """Create a visible bank-settlement funding transaction for a liquidity gap."""
    if amount <= 0:
        return
    acc = world.get_account(account_id)
    if acc is None:
        raise ValueError(f"Cannot fund unknown account: {account_id}")
    preferred = f"ACCT-SETTLEMENT-{acc.bank_id.removeprefix('BANK-')}"
    settlement = world.demo_accounts.get(preferred)
    if settlement is None:
        fallback_bank = world.config.domestic_bank_ids[0]
        settlement = world.demo_accounts[
            f"ACCT-SETTLEMENT-{fallback_bank.removeprefix('BANK-')}"
        ]
    funding_time = max(world.config.world_start, acc.opened_at) + timedelta(seconds=1)
    txn = create_transaction(
        world,
        settlement,
        acc,
        amount,
        funding_time,
        transaction_type=TransactionType.TRANSFER,
        channel=Channel.API,
        purpose_code="LOAN",
        description=f"DECLARED-FUNDING-{reason.upper()}",
    )
    if txn is None:
        raise RuntimeError(f"Unable to fund account {account_id}")


def create_transaction(
    world: WorldState,
    source: Account,
    dest: Account,
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
) -> Optional[Transaction]:
    """Create a transaction if balance allows (or force via initial-balance top-up)."""
    cfg = world.config
    if amount <= 0:
        return None

    if channel is None:
        profile = source.behavioral_profile
        if profile and profile in PROFILE_SPECS:
            channel = _weighted_channel(world.rng, PROFILE_SPECS[profile].channels)
        else:
            channel = Channel.MOBILE

    source_bank = world.banks.get(source.bank_id)
    destination_bank = world.banks.get(dest.bank_id)
    source_country = source_bank.country if source_bank is not None else "VN"
    dest_country = destination_bank.country if destination_bank is not None else "VN"
    is_xb = source_country != dest_country

    if transaction_type is None:
        transaction_type = _transaction_type_for(purpose_code, is_xb)

    if device_id is None or source_ip is None:
        d, ip = _device_ip_for(world, source.owner_entity_id)
        device_id = device_id or d
        source_ip = source_ip or ip

    min_open = max(source.opened_at, dest.opened_at)
    if occurred_at < min_open:
        occurred_at = min_open + timedelta(minutes=1)

    if not _can_debit(world, source, amount):
        if force or source.account_id in world.demo_accounts:
            ensure_balance(world, source.account_id, amount)
        else:
            return None

    if not _can_debit(world, source, amount):
        return None

    txn = Transaction(
        transaction_id=world.ids.transaction(),
        source_account_id=source.account_id,
        destination_account_id=dest.account_id,
        source_bank_id=source.bank_id,
        destination_bank_id=dest.bank_id,
        amount=amount,
        currency=cfg.base_currency,
        transaction_type=transaction_type,
        channel=channel,
        purpose_code=purpose_code,
        description=description or f"PMT-{world.rng.randint(100000, 999999)}",
        occurred_at=occurred_at,
        source_ip=source_ip,
        device_id=device_id,
        is_cross_border=is_xb,
        destination_country=dest_country,
    )
    _apply_transfer(world, source.account_id, dest.account_id, amount)
    world.transactions[txn.transaction_id] = txn
    if count_as_normal:
        world.normal_transaction_ids.add(txn.transaction_id)
    return txn


def _payroll_sources(world: WorldState) -> list[Account]:
    out = [
        a
        for a in _active_accounts(world)
        if a.behavioral_profile
        in (
            BehavioralProfile.PAYROLL_COMPANY,
            BehavioralProfile.SME_SOFTWARE_COMPANY,
            BehavioralProfile.RETAIL_MERCHANT,
        )
    ]
    return out


def generate_normal_transactions(world: WorldState) -> None:
    """Phase 3: profile-driven baseline activity (no SYSTEM-FLOAT super-node)."""
    cfg = world.config
    rng = world.rng
    target = cfg.n_transactions
    accounts = _active_accounts(world)
    if not accounts:
        return

    months = max(1.0, cfg.window_days / 30.0)
    weights = []
    for acc in accounts:
        prof = acc.behavioral_profile
        if prof and prof in PROFILE_SPECS:
            spec = PROFILE_SPECS[prof]
            mid = (spec.tx_count_min + spec.tx_count_max) / 2.0
            weights.append(mid * months)
        else:
            weights.append(10 * months)

    total_w = sum(weights) or 1.0
    planned = []
    for i, _acc in enumerate(accounts):
        share = int(round(target * (weights[i] / total_w)))
        planned.append(max(0, share))
    diff = target - sum(planned)
    if planned:
        planned[0] = max(0, planned[0] + diff)

    start = cfg.world_start
    end = cfg.world_end
    payroll_pool = _payroll_sources(world)

    # Plan events then apply chronologically so funding order is realistic
    events: list[tuple[datetime, str, dict]] = []

    for acc, n_tx in zip(accounts, planned):
        if n_tx <= 0:
            continue
        prof = acc.behavioral_profile
        if not prof or prof not in PROFILE_SPECS:
            continue
        spec = PROFILE_SPECS[prof]
        open_at = max(acc.opened_at, start)

        # Periodic legitimate inflows (salary/revenue) from real counterparties
        n_inflows = max(1, int(months))
        for k in range(n_inflows):
            day_offset = int((k + 0.5) * (cfg.window_days / max(1, n_inflows)))
            ts = open_at + timedelta(days=day_offset, hours=9, minutes=rng.randint(0, 59))
            if ts > end or ts < open_at:
                continue
            inflow_amt = _sample_amount(rng, spec) * rng.randint(2, 6)
            events.append(
                (
                    ts,
                    "inflow",
                    {
                        "dest": acc,
                        "amount": inflow_amt,
                        "purpose": "PAYROLL" if not spec.is_company else "INVOICE",
                    },
                )
            )

        for _ in range(n_tx):
            day = rng.randint(0, max(0, (end - open_at).days))
            hour = _sample_hour(rng, spec.hour_weights)
            base_day = open_at + timedelta(days=day)
            ts = datetime(
                base_day.year,
                base_day.month,
                base_day.day,
                hour,
                rng.randint(0, 59),
                rng.randint(0, 59),
                tzinfo=timezone.utc,
            )
            if ts < open_at or ts > end:
                continue
            role = _pick(rng, spec.counterpart_roles)
            purpose = _pick(rng, spec.typical_purpose_codes)
            amount = _sample_amount(rng, spec)
            cross_border = rng.random() < spec.p_cross_border
            events.append(
                (
                    ts,
                    "transfer",
                    {
                        "source": acc,
                        "role": role,
                        "purpose": purpose,
                        "amount": amount,
                        "cross_border": cross_border,
                        "channel": _weighted_channel(rng, spec.channels),
                        "spec": spec,
                    },
                )
            )

    events.sort(key=lambda e: (e[0], e[1]))

    for ts, kind, payload in events:
        if len(world.normal_transaction_ids) >= target:
            break
        if kind == "inflow":
            dest: Account = payload["dest"]
            amount = payload["amount"]
            # Prefer payroll/company sources; else peer with funds
            source = None
            if payroll_pool:
                source = _pick(rng, [a for a in payroll_pool if a.account_id != dest.account_id] or payroll_pool)
            if source is None:
                funded = [
                    a
                    for a in accounts
                    if a.account_id != dest.account_id
                    and world.balances.get(a.account_id, 0) >= amount
                ]
                if funded:
                    source = _pick(rng, funded)
            if source is None:
                # Skip invisible float — leave balance as-is
                continue
            if not _can_debit(world, source, amount):
                continue
            create_transaction(
                world,
                source,
                dest,
                amount,
                ts,
                channel=Channel.API if payload["purpose"] == "PAYROLL" else Channel.INTERNET,
                purpose_code=payload["purpose"],
                description=f"INFLOW-{rng.randint(10000, 99999)}",
                count_as_normal=True,
            )
        else:
            source = payload["source"]
            amount = payload["amount"]
            purpose = payload["purpose"]
            if payload["cross_border"]:
                dest = _normal_foreign_account(world, source)
                if dest is None:
                    continue
                channel = Channel.SWIFT
                purpose = "FX" if purpose not in ("GOODS", "INVOICE", "SERVICES") else purpose
            else:
                dest = _counterpart_account(world, source, payload["role"])
                channel = payload["channel"]
                if dest is None:
                    continue
            if not _can_debit(world, source, amount):
                bal = world.balances.get(source.account_id, 0)
                if bal > payload["spec"].amount_min * 2:
                    amount = min(amount, max(payload["spec"].amount_min, bal // 2))
                else:
                    continue
            create_transaction(
                world,
                source,
                dest,
                amount,
                ts,
                channel=channel,
                purpose_code=purpose,
                description=f"{purpose}-{rng.randint(100000, 999999)}",
                count_as_normal=True,
            )

    # Density fill if under target (still balance-safe, no system float)
    safety = 0
    while len(world.normal_transaction_ids) < target and safety < target * 3:
        safety += 1
        acc = _pick(rng, accounts)
        prof = acc.behavioral_profile
        if not prof or prof not in PROFILE_SPECS:
            continue
        spec = PROFILE_SPECS[prof]
        cross_border = rng.random() < spec.p_cross_border
        if cross_border:
            dest = _normal_foreign_account(world, acc)
            if dest is None:
                continue
            purpose = "FX"
            channel = Channel.SWIFT
        else:
            dest = _counterpart_account(world, acc, _pick(rng, spec.counterpart_roles))
            if dest is None:
                continue
            purpose = _pick(rng, spec.typical_purpose_codes)
            channel = _weighted_channel(rng, spec.channels)
        amount = _sample_amount(rng, spec)
        day = rng.randint(0, cfg.window_days - 1)
        hour = _sample_hour(rng, spec.hour_weights)
        ts = cfg.world_start + timedelta(
            days=day, hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
        )
        if ts < acc.opened_at:
            continue
        if not _can_debit(world, acc, amount):
            bal = world.balances.get(acc.account_id, 0)
            if bal > spec.amount_min:
                amount = min(amount, bal)
            else:
                continue
        create_transaction(
            world,
            acc,
            dest,
            amount,
            ts,
            channel=channel,
            purpose_code=purpose,
            description=f"TX-{rng.randint(100000, 999999)}",
            count_as_normal=True,
        )
