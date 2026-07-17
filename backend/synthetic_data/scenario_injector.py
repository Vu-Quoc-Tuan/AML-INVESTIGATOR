"""Inject suspicious and legitimate-lookalike scenarios into the world.

Quota-first: scenarios reuse reserved entities/accounts from the final roster
instead of creating records outside configured counts.

Does NOT write detector labels into feature tables. Ground-truth is produced
separately by ``ground_truth.py`` from scenario metadata returned here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from synthetic_data.entity_generator import generate_account
from synthetic_data.models import (
    Account,
    BehavioralProfile,
    Channel,
    Company,
    Customer,
    Disposition,
    EntityType,
    ScenarioType,
    TransactionType,
    VerificationStatus,
)
from synthetic_data.normal_transaction_generator import create_transaction, ensure_balance
from synthetic_data.ownership_generator import generate_ownership_for_company
from synthetic_data.world import WorldState


@dataclass
class ScenarioSpec:
    """Internal scenario metadata (not written to feature CSVs)."""

    scenario_key: str
    scenario_type: ScenarioType
    start_time: datetime
    end_time: datetime
    involved_account_ids: list[str] = field(default_factory=list)
    involved_entity_ids: list[str] = field(default_factory=list)
    suspicious_transaction_ids: list[str] = field(default_factory=list)
    expected_alert_type: str = ""
    expected_case_disposition: Disposition = Disposition.MANUAL_REVIEW_REQUIRED
    explanation: str = ""
    typology_tags: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def _entity_start_customer(c: Customer) -> datetime:
    return c.created_at


def _entity_start_company(c: Company) -> datetime:
    return datetime(
        c.incorporation_date.year,
        c.incorporation_date.month,
        c.incorporation_date.day,
        tzinfo=timezone.utc,
    )


def _primary_account(world: WorldState, entity_id: str) -> Optional[Account]:
    ids = world.entity_accounts.get(entity_id) or []
    for aid in ids:
        acc = world.accounts.get(aid)
        if acc is not None:
            return acc
    return None


def _ensure_account(
    world: WorldState,
    owner_entity_id: str,
    owner_entity_type: EntityType,
    profile: BehavioralProfile,
    opened_at: datetime,
    initial_balance: Optional[int] = None,
) -> Account:
    """Reuse the entity's existing account when possible (preserve open date).

    Never push ``opened_at`` forward after normal transactions may already exist.
    """
    existing = _primary_account(world, owner_entity_id)
    if existing is not None:
        if initial_balance is not None:
            runtime = world.balances.get(existing.account_id, existing.initial_balance)
            if runtime < initial_balance:
                ensure_balance(world, existing.account_id, initial_balance)
        return existing
    # Only create when the entity somehow has no account and cap allows
    if owner_entity_type == EntityType.CUSTOMER:
        start = world.customers[owner_entity_id].created_at
    else:
        start = _entity_start_company(world.companies[owner_entity_id])
    safe_open = max(opened_at, start + timedelta(hours=1))
    # Prefer opening before the transaction window so normal+scenario txs stay valid
    if safe_open > world.config.world_start:
        safe_open = max(start + timedelta(hours=1), world.config.world_start)
    return generate_account(
        world,
        owner_entity_id,
        owner_entity_type,
        profile,
        opened_at=safe_open,
        initial_balance=initial_balance,
    )


def _take_customers(
    world: WorldState,
    n: int,
    preferred: Optional[BehavioralProfile] = None,
) -> list[Customer]:
    rng = world.rng
    unused = [
        c
        for c in world.customers.values()
        if c.customer_id not in world.scenario_used_customers
    ]
    if preferred is not None:
        preferred_pool = [c for c in unused if c.behavioral_profile == preferred]
        pool = preferred_pool if len(preferred_pool) >= n else unused
    else:
        pool = unused
    if len(pool) < n:
        # Fall back to any customers (reuse allowed when pool exhausted)
        pool = list(world.customers.values())
    if len(pool) < n:
        raise RuntimeError(
            f"Need {n} customers for scenario but only {len(pool)} available"
        )
    chosen = rng.sample(pool, n) if len(pool) >= n else pool[:n]
    for c in chosen:
        world.scenario_used_customers.add(c.customer_id)
    return chosen


def _realign_company_kyc_turnover(world: WorldState, company: Company) -> None:
    for p in world.kyc_profiles.values():
        if p.entity_id != company.company_id:
            continue
        p.expected_monthly_inflow = company.expected_monthly_turnover
        p.expected_monthly_outflow = int(company.expected_monthly_turnover * 0.8)


def _take_company(
    world: WorldState,
    preferred: Optional[BehavioralProfile] = None,
    *,
    mutate_profile: Optional[BehavioralProfile] = None,
    require_min_age_years: Optional[int] = None,
    require_max_age_days: Optional[int] = None,
    expected_monthly_turnover: Optional[int] = None,
) -> Company:
    """Reserve a company without rewriting incorporation dates after generation.

    Date constraints are applied as selection filters so account/transaction
    timelines already generated for the normal world remain valid.
    """
    rng = world.rng
    unused = [
        c
        for c in world.companies.values()
        if c.company_id not in world.scenario_used_companies
    ]
    pool = unused or list(world.companies.values())
    if preferred is not None:
        pref = [c for c in pool if c.behavioral_profile == preferred]
        if pref:
            pool = pref

    world_end = world.config.world_end.date()
    filtered = pool
    if require_min_age_years is not None:
        aged = [
            c
            for c in filtered
            if (world_end - c.incorporation_date).days >= require_min_age_years * 365
        ]
        if aged:
            filtered = aged
    if require_max_age_days is not None:
        young = [
            c
            for c in filtered
            if (world_end - c.incorporation_date).days <= require_max_age_days
        ]
        if young:
            filtered = young

    if not filtered:
        raise RuntimeError("No companies available for scenario reservation")
    company = _pick(rng, filtered)
    world.scenario_used_companies.add(company.company_id)

    if mutate_profile is not None:
        company.behavioral_profile = mutate_profile
    if expected_monthly_turnover is not None:
        company.expected_monthly_turnover = expected_monthly_turnover
        _realign_company_kyc_turnover(world, company)
    return company


def inject_rapid_fan_in_pass_through(world: WorldState) -> ScenarioSpec:
    """Suspicious: RAPID_FAN_IN_PASS_THROUGH."""
    rng = world.rng
    cfg = world.config
    t0 = cfg.world_end - timedelta(days=rng.randint(5, 20))
    t0 = t0.replace(hour=14, minute=0, second=0, microsecond=0)

    n_src = min(10, max(3, len(world.customers) // 20))
    source_customers = _take_customers(
        world, n_src, preferred=BehavioralProfile.SALARIED_INDIVIDUAL
    )
    source_accounts: list[Account] = []
    for cust in source_customers:
        acc = _ensure_account(
            world,
            cust.customer_id,
            EntityType.CUSTOMER,
            BehavioralProfile.SALARIED_INDIVIDUAL,
            opened_at=t0 - timedelta(days=rng.randint(60, 180)),
        )
        source_accounts.append(acc)

    shared_device = world.ids.device()
    shared_ip = f"10.99.{rng.randint(1, 50)}.{rng.randint(1, 200)}"
    for cust in source_customers[: min(4, len(source_customers))]:
        world.entity_devices[cust.customer_id] = [
            shared_device,
            *world.entity_devices.get(cust.customer_id, []),
        ]
        world.entity_ips[cust.customer_id] = [
            shared_ip,
            *world.entity_ips.get(cust.customer_id, []),
        ]

    shell = _take_company(
        world,
        preferred=BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        mutate_profile=BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        require_max_age_days=120,
        expected_monthly_turnover=300_000_000,
    )
    shell_acc = _ensure_account(
        world,
        shell.company_id,
        EntityType.COMPANY,
        BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        opened_at=t0 - timedelta(days=20),
        initial_balance=5_000_000,
    )

    _inject_incomplete_ownership_chain(world, shell.company_id)
    to_remove = [
        did
        for did, d in world.kyc_documents.items()
        if d.entity_id == shell.company_id and d.document_type == "UBO_DECLARATION"
    ]
    for did in to_remove:
        del world.kyc_documents[did]
    for o in world.ownerships.values():
        if o.source_document_id in to_remove or (
            o.owned_company_id == shell.company_id
            and o.source_document_id
            and o.source_document_id not in world.kyc_documents
        ):
            o.source_document_id = None
            o.verified = False

    crypto = world.demo_accounts["ACCT-CRYPTO-DEMO-001"]
    foreign = world.demo_accounts["ACCT-FOREIGN-HR-001"]

    suspicious_ids: list[str] = []
    per_amount = 500_000_000

    for i, acc in enumerate(source_accounts):
        ts = t0 - timedelta(hours=2, minutes=i * 3)
        ensure_balance(world, crypto.account_id, per_amount + 1)
        txn = create_transaction(
            world,
            crypto,
            acc,
            per_amount,
            ts,
            channel=Channel.API,
            purpose_code="TRANSFER",
            description=f"CRYPTO-WD-{rng.randint(100000, 999999)}",
            device_id=shared_device if i < 4 else None,
            source_ip=shared_ip if i < 4 else None,
            force=True,
        )
        if txn:
            suspicious_ids.append(txn.transaction_id)

    for i, acc in enumerate(source_accounts):
        ts = t0 + timedelta(seconds=i * 28)
        ensure_balance(world, acc.account_id, per_amount)
        txn = create_transaction(
            world,
            acc,
            shell_acc,
            per_amount,
            ts,
            channel=Channel.MOBILE if i % 2 == 0 else Channel.INTERNET,
            purpose_code="TRANSFER",
            description=f"INV-CAPITAL-{rng.randint(1000, 9999)}",
            device_id=(
                shared_device
                if i < 4
                else world.entity_devices.get(acc.owner_entity_id, [None])[0]
            ),
            source_ip=shared_ip if i < 4 else None,
            force=True,
        )
        if txn:
            suspicious_ids.append(txn.transaction_id)

    total_in = per_amount * len(source_accounts)
    pass_through = int(total_in * 0.992)
    last_fan = t0 + timedelta(seconds=(len(source_accounts) - 1) * 28)
    out_ts = last_fan + timedelta(seconds=121)
    ensure_balance(world, shell_acc.account_id, pass_through)
    out_txn = create_transaction(
        world,
        shell_acc,
        foreign,
        pass_through,
        out_ts,
        channel=Channel.SWIFT,
        purpose_code="FX",
        description="OVERSEAS-SETTLEMENT-DEMO",
        transaction_type=TransactionType.FX,
        force=True,
    )
    if out_txn:
        suspicious_ids.append(out_txn.transaction_id)

    end_time = out_ts + timedelta(minutes=1)
    return ScenarioSpec(
        scenario_key="RAPID_FAN_IN_PASS_THROUGH",
        scenario_type=ScenarioType.SUSPICIOUS,
        start_time=t0 - timedelta(hours=3),
        end_time=end_time,
        involved_account_ids=[a.account_id for a in source_accounts]
        + [shell_acc.account_id, crypto.account_id, foreign.account_id],
        involved_entity_ids=[c.customer_id for c in source_customers]
        + [shell.company_id, "ENT-CRYPTO-PLATFORM-DEMO", "ENT-FOREIGN-HR-BANK"],
        suspicious_transaction_ids=suspicious_ids,
        expected_alert_type="RAPID_FAN_IN_PASS_THROUGH",
        expected_case_disposition=Disposition.ESCALATE_FOR_SAR_REVIEW,
        explanation=(
            "Ten personal accounts each transferred ~500M VND into a newly opened "
            "company account within five minutes. The company declared only 300M VND "
            "monthly turnover. Approximately 121 seconds later, 99.2% of received "
            "funds were sent to a high-risk foreign bank demo. Source accounts were "
            "funded from the same crypto-platform demo; several shared device/IP. "
            "Ultimate beneficial ownership documentation for the company is missing."
        ),
        typology_tags=["fan_in", "pass_through", "crypto_source", "rapid_outflow", "missing_ubo"],
        notes={
            "declared_monthly_turnover": 300_000_000,
            "pass_through_ratio": 0.992,
            "source_count": len(source_accounts),
        },
    )


def inject_event_collection(world: WorldState) -> ScenarioSpec:
    """Legitimate lookalike: EVENT_COLLECTION."""
    rng = world.rng
    cfg = world.config
    t0 = cfg.world_end - timedelta(days=rng.randint(25, 45))
    t0 = t0.replace(hour=10, minute=0, second=0, microsecond=0)

    event_co = _take_company(
        world,
        preferred=BehavioralProfile.EVENT_ORGANIZER,
        mutate_profile=BehavioralProfile.EVENT_ORGANIZER,
        require_min_age_years=5,
        expected_monthly_turnover=2_000_000_000,
    )
    event_acc = _ensure_account(
        world,
        event_co.company_id,
        EntityType.COMPANY,
        BehavioralProfile.EVENT_ORGANIZER,
        opened_at=datetime(cfg.world_end.year - 6, 4, 1, tzinfo=timezone.utc),
        initial_balance=200_000_000,
    )
    generate_ownership_for_company(
        world, event_co.company_id, incomplete_ubo=False, replace_existing=True
    )

    ticket_prices = (350_000, 750_000, 1_500_000, 3_000_000)
    n_buyers = min(40, max(5, len(world.customers) // 15))
    buyers = _take_customers(
        world, n_buyers, preferred=BehavioralProfile.SALARIED_INDIVIDUAL
    )
    involved_accounts = [event_acc.account_id]
    involved_entities = [event_co.company_id]
    tx_ids: list[str] = []

    for wave, base in enumerate((t0 - timedelta(days=30), t0)):
        for i, cust in enumerate(buyers):
            acc = _ensure_account(
                world,
                cust.customer_id,
                EntityType.CUSTOMER,
                BehavioralProfile.SALARIED_INDIVIDUAL,
                opened_at=base - timedelta(days=rng.randint(100, 400)),
            )
            price = _pick(rng, ticket_prices)
            ensure_balance(world, acc.account_id, price + 1_000_000)
            order_id = f"EVT-{cfg.world_end.year}-{100000 + wave * 1000 + i}"
            ts = base + timedelta(hours=rng.randint(0, 72), minutes=rng.randint(0, 59))
            txn = create_transaction(
                world,
                acc,
                event_acc,
                price,
                ts,
                channel=Channel.INTERNET,
                purpose_code="TICKET",
                description=f"Ticket order {order_id}",
                force=True,
            )
            if txn:
                tx_ids.append(txn.transaction_id)
            involved_accounts.append(acc.account_id)
            involved_entities.append(cust.customer_id)

    supplier = _take_company(
        world,
        preferred=BehavioralProfile.RETAIL_MERCHANT,
        mutate_profile=BehavioralProfile.RETAIL_MERCHANT,
    )
    sup_acc = _ensure_account(
        world,
        supplier.company_id,
        EntityType.COMPANY,
        BehavioralProfile.RETAIL_MERCHANT,
        opened_at=t0 - timedelta(days=500),
    )
    ensure_balance(world, event_acc.account_id, 50_000_000)
    create_transaction(
        world,
        event_acc,
        sup_acc,
        45_000_000,
        t0 + timedelta(days=5),
        purpose_code="SUPPLIER",
        description="Venue rental INV-VENUE-8821",
        force=True,
    )

    return ScenarioSpec(
        scenario_key="EVENT_COLLECTION",
        scenario_type=ScenarioType.LEGITIMATE_LOOKALIKE,
        start_time=t0 - timedelta(days=31),
        end_time=t0 + timedelta(days=6),
        involved_account_ids=list(dict.fromkeys(involved_accounts + [sup_acc.account_id])),
        involved_entity_ids=list(dict.fromkeys(involved_entities + [supplier.company_id])),
        suspicious_transaction_ids=[],
        expected_alert_type="FAN_IN_TICKET_SALES",
        expected_case_disposition=Disposition.CLEARED_WITH_RATIONALE,
        explanation=(
            "Multiple customers paid an established event organizer (>5 years) with "
            "valid ticket/order IDs and tiered amounts consistent with prior event "
            "sales. No shared crypto source, no abnormal shared devices, and no "
            "rapid near-total foreign outflow."
        ),
        typology_tags=["fan_in", "lookalike", "event_ticketing"],
        notes={"ticket_prices": list(ticket_prices), "history_wave": True, "n_buyers": n_buyers},
    )


def inject_incomplete_evidence(world: WorldState) -> ScenarioSpec:
    """Incomplete-evidence: pass-through pattern with weak KYC/screening deps."""
    rng = world.rng
    cfg = world.config
    t0 = cfg.world_end - timedelta(days=rng.randint(8, 15))
    t0 = t0.replace(hour=11, minute=30, second=0, microsecond=0)

    n_src = min(6, max(3, len(world.customers) // 30))
    source_customers = _take_customers(
        world, n_src, preferred=BehavioralProfile.FREELANCER
    )
    sources: list[tuple[Customer, Account]] = []
    for cust in source_customers:
        acc = _ensure_account(
            world,
            cust.customer_id,
            EntityType.CUSTOMER,
            BehavioralProfile.FREELANCER,
            opened_at=t0 - timedelta(days=90),
        )
        sources.append((cust, acc))

    shell = _take_company(
        world,
        preferred=BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        mutate_profile=BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        require_max_age_days=150,
        expected_monthly_turnover=200_000_000,
    )
    shell_acc = _ensure_account(
        world,
        shell.company_id,
        EntityType.COMPANY,
        BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        opened_at=t0 - timedelta(days=30),
        initial_balance=2_000_000,
    )
    _inject_incomplete_ownership_chain(world, shell.company_id)

    for d in list(world.kyc_documents.values()):
        if d.entity_id == shell.company_id:
            d.expires_at = (t0 - timedelta(days=10)).date()
            d.verification_status = VerificationStatus.EXPIRED
    for o in world.ownerships.values():
        if o.owned_company_id == shell.company_id:
            o.verified = False
            o.source_document_id = None

    foreign = world.demo_accounts["ACCT-FOREIGN-HR-001"]
    amount = 200_000_000
    sus_ids = []
    for i, (_cust, acc) in enumerate(sources):
        ensure_balance(world, acc.account_id, amount)
        txn = create_transaction(
            world,
            acc,
            shell_acc,
            amount,
            t0 + timedelta(seconds=i * 40),
            purpose_code="TRANSFER",
            description=f"SVC-PAY-{rng.randint(1000, 9999)}",
            force=True,
        )
        if txn:
            sus_ids.append(txn.transaction_id)

    total = amount * n_src
    out_amt = int(total * 0.95)
    ensure_balance(world, shell_acc.account_id, out_amt)
    out_txn = create_transaction(
        world,
        shell_acc,
        foreign,
        out_amt,
        t0 + timedelta(seconds=n_src * 40 + 90),
        channel=Channel.SWIFT,
        purpose_code="FX",
        description="CROSS-BORDER-PAY-DEMO",
        force=True,
    )
    if out_txn:
        sus_ids.append(out_txn.transaction_id)

    return ScenarioSpec(
        scenario_key="INCOMPLETE_EVIDENCE_PASS_THROUGH",
        scenario_type=ScenarioType.INCOMPLETE_EVIDENCE,
        start_time=t0,
        end_time=t0 + timedelta(minutes=15),
        involved_account_ids=[a.account_id for _, a in sources]
        + [shell_acc.account_id, foreign.account_id],
        involved_entity_ids=[c.customer_id for c, _ in sources] + [shell.company_id],
        suspicious_transaction_ids=sus_ids,
        expected_alert_type="RAPID_PASS_THROUGH_INCOMPLETE_KYC",
        expected_case_disposition=Disposition.NEED_MORE_EVIDENCE,
        explanation=(
            "Rapid fan-in and pass-through pattern is present, but KYC documents "
            "for the receiving company are expired, the ownership chain lacks a "
            "final natural-person UBO layer, and the screening dependency is marked "
            "unavailable. Disposition must be NEED_MORE_EVIDENCE / MANUAL_REVIEW_REQUIRED; "
            "do not conclude NO_MATCH."
        ),
        typology_tags=["pass_through", "expired_kyc", "incomplete_ubo", "screening_unavailable"],
        notes={
            "screening_dependency": "unavailable",
            "screening_entity_id": shell.company_id,
            "forbid_disposition": "NO_MATCH",
            "alt_disposition": Disposition.MANUAL_REVIEW_REQUIRED.value,
        },
    )


def inject_smurfing_structuring(world: WorldState) -> ScenarioSpec:
    """Suspicious: multiple just-under-threshold deposits then consolidation."""
    rng = world.rng
    cfg = world.config
    t0 = cfg.world_end - timedelta(days=rng.randint(12, 18))
    t0 = t0.replace(hour=9, minute=0, second=0, microsecond=0)

    cust = _take_customers(world, 1, preferred=BehavioralProfile.FREELANCER)[0]
    main = _ensure_account(
        world,
        cust.customer_id,
        EntityType.CUSTOMER,
        BehavioralProfile.FREELANCER,
        opened_at=t0 - timedelta(days=120),
    )
    n_feeders = min(12, max(4, len(world.customers) // 25))
    feeders = _take_customers(
        world, n_feeders, preferred=BehavioralProfile.SALARIED_INDIVIDUAL
    )
    thresholdish = 99_000_000
    sus_ids = []
    involved = [main.account_id]
    for i, feeder_c in enumerate(feeders):
        feeder = _ensure_account(
            world,
            feeder_c.customer_id,
            EntityType.CUSTOMER,
            BehavioralProfile.SALARIED_INDIVIDUAL,
            opened_at=t0 - timedelta(days=60),
        )
        ensure_balance(world, feeder.account_id, thresholdish + 1)
        amt = thresholdish - rng.randint(0, 2_000_000)
        txn = create_transaction(
            world,
            feeder,
            main,
            amt,
            t0 + timedelta(hours=i * 2),
            purpose_code="TRANSFER",
            description=f"CASH-EQ-{rng.randint(10000, 99999)}",
            force=True,
        )
        if txn:
            sus_ids.append(txn.transaction_id)
        involved.append(feeder.account_id)

    return ScenarioSpec(
        scenario_key="STRUCTURING_SMURFING",
        scenario_type=ScenarioType.SUSPICIOUS,
        start_time=t0,
        end_time=t0 + timedelta(hours=30),
        involved_account_ids=involved,
        involved_entity_ids=[cust.customer_id] + [f.customer_id for f in feeders],
        suspicious_transaction_ids=sus_ids,
        expected_alert_type="STRUCTURING",
        expected_case_disposition=Disposition.ESCALATE_FOR_SAR_REVIEW,
        explanation=(
            "Twelve inbound transfers just under a 100M VND monitoring threshold "
            "arrived within 24 hours into a single personal account, consistent "
            "with structuring/smurfing typology."
        ),
        typology_tags=["structuring", "smurfing", "threshold_avoidance"],
    )


def inject_payroll_lookalike(world: WorldState) -> ScenarioSpec:
    """Legitimate lookalike: payroll batch disbursement."""
    rng = world.rng
    cfg = world.config
    t0 = cfg.world_end - timedelta(days=rng.randint(3, 10))
    t0 = t0.replace(hour=8, minute=30, second=0, microsecond=0)

    payroll_co = _take_company(
        world,
        preferred=BehavioralProfile.PAYROLL_COMPANY,
        mutate_profile=BehavioralProfile.PAYROLL_COMPANY,
        require_min_age_years=5,
        expected_monthly_turnover=10_000_000_000,
    )
    pay_acc = _ensure_account(
        world,
        payroll_co.company_id,
        EntityType.COMPANY,
        BehavioralProfile.PAYROLL_COMPANY,
        opened_at=datetime(cfg.world_end.year - 8, 2, 1, tzinfo=timezone.utc),
        initial_balance=5_000_000_000,
    )
    generate_ownership_for_company(
        world, payroll_co.company_id, incomplete_ubo=False, replace_existing=True
    )

    n_emp = min(35, max(5, len(world.customers) // 20))
    employees = _take_customers(
        world, n_emp, preferred=BehavioralProfile.SALARIED_INDIVIDUAL
    )
    salaries = [rng.randint(12_000_000, 45_000_000) for _ in range(n_emp)]
    ensure_balance(world, pay_acc.account_id, sum(salaries) + 100_000_000)
    involved = [pay_acc.account_id]
    entities = [payroll_co.company_id]
    for i, (emp, sal) in enumerate(zip(employees, salaries)):
        emp_acc = _ensure_account(
            world,
            emp.customer_id,
            EntityType.CUSTOMER,
            BehavioralProfile.SALARIED_INDIVIDUAL,
            opened_at=t0 - timedelta(days=rng.randint(200, 800)),
        )
        create_transaction(
            world,
            pay_acc,
            emp_acc,
            sal,
            t0 + timedelta(seconds=i * 5),
            channel=Channel.API,
            purpose_code="PAYROLL",
            description=f"Payroll {t0.strftime('%Y-%m')} EMP-{1000+i}",
            force=True,
        )
        involved.append(emp_acc.account_id)
        entities.append(emp.customer_id)

    return ScenarioSpec(
        scenario_key="PAYROLL_BATCH",
        scenario_type=ScenarioType.LEGITIMATE_LOOKALIKE,
        start_time=t0,
        end_time=t0 + timedelta(hours=1),
        involved_account_ids=involved,
        involved_entity_ids=entities,
        suspicious_transaction_ids=[],
        expected_alert_type="FAN_OUT_PAYROLL",
        expected_case_disposition=Disposition.CLEARED_WITH_RATIONALE,
        explanation=(
            "Fan-out of consistent salary amounts from a long-established payroll "
            "company via API channel with payroll purpose codes and employee "
            "references. Matches declared payroll activity."
        ),
        typology_tags=["fan_out", "lookalike", "payroll"],
    )


def inject_trade_settlement_lookalike(world: WorldState) -> ScenarioSpec:
    """Legitimate lookalike: import/export invoice settlement with cross-border."""
    rng = world.rng
    cfg = world.config
    t0 = cfg.world_end - timedelta(days=rng.randint(15, 35))
    t0 = t0.replace(hour=15, minute=0, second=0, microsecond=0)

    trade = _take_company(
        world,
        preferred=BehavioralProfile.IMPORT_EXPORT_COMPANY,
        mutate_profile=BehavioralProfile.IMPORT_EXPORT_COMPANY,
        require_min_age_years=5,
        expected_monthly_turnover=8_000_000_000,
    )
    trade_acc = _ensure_account(
        world,
        trade.company_id,
        EntityType.COMPANY,
        BehavioralProfile.IMPORT_EXPORT_COMPANY,
        opened_at=datetime(cfg.world_end.year - 7, 7, 1, tzinfo=timezone.utc),
        initial_balance=1_000_000_000,
    )
    generate_ownership_for_company(
        world, trade.company_id, incomplete_ubo=False, replace_existing=True
    )
    foreign = world.demo_accounts["ACCT-FOREIGN-HR-001"]

    inv_amount = 850_000_000
    ensure_balance(world, trade_acc.account_id, inv_amount)
    create_transaction(
        world,
        trade_acc,
        foreign,
        inv_amount,
        t0,
        channel=Channel.SWIFT,
        purpose_code="INVOICE",
        description="Invoice INV-IMEX-2025-4412 goods settlement",
        transaction_type=TransactionType.FX,
        force=True,
    )
    buyer = _take_company(
        world,
        preferred=BehavioralProfile.RETAIL_MERCHANT,
        mutate_profile=BehavioralProfile.RETAIL_MERCHANT,
    )
    buyer_acc = _ensure_account(
        world,
        buyer.company_id,
        EntityType.COMPANY,
        BehavioralProfile.RETAIL_MERCHANT,
        opened_at=t0 - timedelta(days=400),
    )
    ensure_balance(world, buyer_acc.account_id, inv_amount + 50_000_000)
    create_transaction(
        world,
        buyer_acc,
        trade_acc,
        inv_amount + 40_000_000,
        t0 - timedelta(days=3),
        purpose_code="GOODS",
        description="PO-77821 domestic distribution payment",
        force=True,
    )

    return ScenarioSpec(
        scenario_key="TRADE_INVOICE_SETTLEMENT",
        scenario_type=ScenarioType.LEGITIMATE_LOOKALIKE,
        start_time=t0 - timedelta(days=4),
        end_time=t0 + timedelta(hours=2),
        involved_account_ids=[trade_acc.account_id, foreign.account_id, buyer_acc.account_id],
        involved_entity_ids=[trade.company_id, buyer.company_id],
        suspicious_transaction_ids=[],
        expected_alert_type="CROSS_BORDER_TRADE",
        expected_case_disposition=Disposition.CLEARED_WITH_RATIONALE,
        explanation=(
            "Cross-border payment by an established import/export company with "
            "matching domestic receivable, invoice references, and turnover "
            "consistent with declared trade profile."
        ),
        typology_tags=["cross_border", "lookalike", "trade_finance"],
    )


def inject_mule_layering(world: WorldState) -> ScenarioSpec:
    """Suspicious: short layering chain through mule accounts."""
    rng = world.rng
    cfg = world.config
    t0 = cfg.world_end - timedelta(days=rng.randint(6, 12))
    t0 = t0.replace(hour=16, minute=0, second=0, microsecond=0)

    amount = 350_000_000
    n_chain = min(4, max(3, len(world.customers) // 40))
    mules = _take_customers(world, n_chain)
    chain_accounts = []
    chain_entities = []
    for i, c in enumerate(mules):
        a = _ensure_account(
            world,
            c.customer_id,
            EntityType.CUSTOMER,
            c.behavioral_profile,
            opened_at=t0 - timedelta(days=30 + i * 10),
            initial_balance=1_000_000,
        )
        chain_accounts.append(a)
        chain_entities.append(c.customer_id)

    crypto = world.demo_accounts["ACCT-CRYPTO-DEMO-001"]
    foreign = world.demo_accounts["ACCT-FOREIGN-HR-001"]
    sus = []
    ensure_balance(world, crypto.account_id, amount)
    t = create_transaction(
        world,
        crypto,
        chain_accounts[0],
        amount,
        t0,
        purpose_code="TRANSFER",
        description="CRYPTO-IN-LAYER",
        force=True,
    )
    if t:
        sus.append(t.transaction_id)
    hop_amount = amount
    for i in range(len(chain_accounts) - 1):
        ensure_balance(world, chain_accounts[i].account_id, hop_amount)
        hop = int(hop_amount * 0.98)
        t = create_transaction(
            world,
            chain_accounts[i],
            chain_accounts[i + 1],
            hop,
            t0 + timedelta(minutes=3 * (i + 1)),
            purpose_code="TRANSFER",
            description=f"LAYER-HOP-{i+1}",
            force=True,
        )
        if t:
            sus.append(t.transaction_id)
        hop_amount = hop
    ensure_balance(world, chain_accounts[-1].account_id, hop_amount)
    t = create_transaction(
        world,
        chain_accounts[-1],
        foreign,
        int(hop_amount * 0.97),
        t0 + timedelta(minutes=15),
        channel=Channel.SWIFT,
        purpose_code="FX",
        description="LAYER-EXIT",
        force=True,
    )
    if t:
        sus.append(t.transaction_id)

    return ScenarioSpec(
        scenario_key="MULE_LAYERING_CHAIN",
        scenario_type=ScenarioType.SUSPICIOUS,
        start_time=t0,
        end_time=t0 + timedelta(minutes=20),
        involved_account_ids=[a.account_id for a in chain_accounts]
        + [crypto.account_id, foreign.account_id],
        involved_entity_ids=chain_entities,
        suspicious_transaction_ids=sus,
        expected_alert_type="LAYERING_CHAIN",
        expected_case_disposition=Disposition.ESCALATE_FOR_SAR_REVIEW,
        explanation=(
            "Funds entered from a crypto-platform demo, hopped through four personal "
            "accounts within 15 minutes with ~2% haircut each hop, then exited to a "
            "high-risk foreign bank — classic layering via mule accounts."
        ),
        typology_tags=["layering", "mule", "crypto_source", "rapid_chain"],
    )


def _inject_incomplete_ownership_chain(world: WorldState, company_id: str) -> None:
    """Wire shell → opaque holding with no natural-person UBO and no supporting docs."""
    from synthetic_data.models import CompanyOwnership
    from synthetic_data.ownership_generator import _add_relationship

    company = world.companies[company_id]
    drop = [oid for oid, o in world.ownerships.items() if o.owned_company_id == company_id]
    for oid in drop:
        del world.ownerships[oid]

    # Reserve another company as opaque holding (no new company outside quota)
    hold = _take_company(
        world,
        preferred=BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        mutate_profile=BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        require_max_age_days=180,
        expected_monthly_turnover=50_000_000,
    )
    for did in [
        d.document_id
        for d in list(world.kyc_documents.values())
        if d.entity_id in (company_id, hold.company_id)
        and d.document_type == "UBO_DECLARATION"
    ]:
        del world.kyc_documents[did]
    for oid in [
        oid for oid, o in world.ownerships.items() if o.owned_company_id == hold.company_id
    ]:
        del world.ownerships[oid]

    own = CompanyOwnership(
        ownership_id=world.ids.ownership(),
        owner_entity_id=hold.company_id,
        owner_entity_type=EntityType.COMPANY,
        owned_company_id=company_id,
        ownership_percentage=100.0,
        effective_from=company.incorporation_date,
        effective_to=None,
        source_document_id=None,
        verified=False,
    )
    world.ownerships[own.ownership_id] = own
    _add_relationship(
        world,
        hold.company_id,
        company_id,
        "UNRESOLVED_UBO_CHAIN",
        company.incorporation_date,
        confidence=0.3,
        source="incomplete_kyc",
    )


def inject_all_scenarios(world: WorldState) -> list[ScenarioSpec]:
    """Inject configured suspicious + lookalike scenarios (+ optional incomplete evidence)."""
    suspicious = [
        inject_rapid_fan_in_pass_through,
        inject_smurfing_structuring,
        inject_mule_layering,
    ]
    lookalikes = [
        inject_event_collection,
        inject_payroll_lookalike,
        inject_trade_settlement_lookalike,
    ]
    n_sus = max(0, min(world.config.n_suspicious_scenarios, len(suspicious)))
    n_look = max(0, min(world.config.n_lookalike_scenarios, len(lookalikes)))

    specs: list[ScenarioSpec] = []
    for fn in suspicious[:n_sus]:
        specs.append(fn(world))
    for fn in lookalikes[:n_look]:
        specs.append(fn(world))
    if world.config.inject_incomplete_evidence:
        specs.append(inject_incomplete_evidence(world))
    return specs
