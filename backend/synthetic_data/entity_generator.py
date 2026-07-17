"""Generate customers, companies, accounts, addresses, banks, and KYC artefacts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from synthetic_data.config import (
    COMPANY_NAME_CORES,
    COMPANY_NAME_PREFIXES,
    FAKE_CITIES,
    FAKE_DISTRICTS,
    FAKE_FIRST_NAMES,
    FAKE_LAST_NAMES,
    FAKE_STREETS,
    FAKE_WARDS,
    INDUSTRY_CODES,
    NATIONALITIES,
    OCCUPATIONS,
)
from synthetic_data.models import (
    Account,
    AccountStatus,
    AccountType,
    Address,
    Bank,
    BehavioralProfile,
    Company,
    Customer,
    EntityType,
    KYCDocument,
    KYCProfile,
    RiskLevel,
    VerificationStatus,
)
from synthetic_data.profiles import (
    COMPANY_PROFILES,
    COMPANY_WEIGHTS,
    INDIVIDUAL_PROFILES,
    INDIVIDUAL_WEIGHTS,
    PROFILE_SPECS,
)
from synthetic_data.world import WorldState


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def _weighted_choice(rng, items, weights):
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for item, w in zip(items, weights):
        acc += w
        if r <= acc:
            return item
    return items[-1]


def generate_address(world: WorldState, country: str = "VN") -> Address:
    rng = world.rng
    addr = Address(
        address_id=world.ids.address(),
        line1=_pick(rng, FAKE_STREETS),
        ward=_pick(rng, FAKE_WARDS),
        district=_pick(rng, FAKE_DISTRICTS),
        city=_pick(rng, FAKE_CITIES),
        country=country,
        postal_code=f"{rng.randint(10000, 99999)}",
    )
    world.addresses[addr.address_id] = addr
    return addr


def _fake_name(rng) -> str:
    return f"{_pick(rng, FAKE_LAST_NAMES)} {_pick(rng, FAKE_FIRST_NAMES)} {_pick(rng, FAKE_FIRST_NAMES)}"


def _fake_national_id(rng) -> str:
    return f"9{rng.randint(10000000000, 99999999999)}"


def _fake_phone(rng) -> str:
    return f"+849{rng.randint(10000000, 99999999)}"


def _fake_email(rng, name_slug: str) -> str:
    domains = ("mail-demo.invalid", "example-sandbox.test", "fictitious-mail.dev")
    return f"{name_slug.lower().replace(' ', '.')}{rng.randint(1, 9999)}@{_pick(rng, domains)}"


def _risk_from_profile(profile: BehavioralProfile, rng) -> RiskLevel:
    if profile == BehavioralProfile.NEWLY_INCORPORATED_COMPANY:
        return RiskLevel.HIGH if rng.random() < 0.6 else RiskLevel.MEDIUM
    if profile in (
        BehavioralProfile.IMPORT_EXPORT_COMPANY,
        BehavioralProfile.FREELANCER,
    ):
        return _weighted_choice(
            rng, [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH], [0.4, 0.4, 0.2]
        )
    return _weighted_choice(
        rng, [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH], [0.7, 0.25, 0.05]
    )


def _clamp_review_window(
    entity_start: datetime, world_end: datetime, rng
) -> tuple[datetime, datetime]:
    """Return (last_reviewed_at, next_review_at) with last >= entity_start."""
    earliest = entity_start + timedelta(days=1)
    latest = world_end - timedelta(days=14)
    if earliest > latest:
        last_rev = min(entity_start + timedelta(hours=12), world_end)
        return last_rev, last_rev + timedelta(days=180)
    span_days = max(1, (latest - earliest).days)
    last_rev = earliest + timedelta(days=rng.randint(0, span_days))
    return last_rev, last_rev + timedelta(days=365)


def _doc_status(expires_at: Optional[date], world_end: datetime) -> VerificationStatus:
    if expires_at is not None and expires_at < world_end.date():
        return VerificationStatus.EXPIRED
    return VerificationStatus.VERIFIED


def generate_customer(
    world: WorldState,
    profile: Optional[BehavioralProfile] = None,
    created_at: Optional[datetime] = None,
) -> Customer:
    rng = world.rng
    cfg = world.config
    if profile is None:
        profile = _weighted_choice(rng, list(INDIVIDUAL_PROFILES), list(INDIVIDUAL_WEIGHTS))
    spec = PROFILE_SPECS[profile]
    addr = generate_address(world)
    full_name = _fake_name(rng)
    dob_year = rng.randint(1955, 2005)
    if profile == BehavioralProfile.STUDENT:
        dob_year = rng.randint(1998, 2006)
    elif profile == BehavioralProfile.RETIRED_CUSTOMER:
        dob_year = rng.randint(1945, 1965)

    days_before = rng.randint(cfg.window_days + 30, cfg.window_days + 2000)
    if created_at is None:
        created_at = cfg.world_end - timedelta(days=days_before)

    income = rng.randint(spec.income_or_turnover_min, spec.income_or_turnover_max)
    customer = Customer(
        customer_id=world.ids.customer(),
        full_name=full_name,
        date_of_birth=date(dob_year, rng.randint(1, 12), rng.randint(1, 28)),
        nationality=_pick(rng, NATIONALITIES),
        national_id=_fake_national_id(rng),
        phone=_fake_phone(rng),
        email=_fake_email(rng, full_name.split()[0]),
        address_id=addr.address_id,
        occupation=(
            "Student"
            if profile == BehavioralProfile.STUDENT
            else (
                "Retired"
                if profile == BehavioralProfile.RETIRED_CUSTOMER
                else _pick(rng, OCCUPATIONS)
            )
        ),
        annual_income=income,
        customer_risk_level=_risk_from_profile(profile, rng),
        created_at=created_at,
        behavioral_profile=profile,
    )
    world.customers[customer.customer_id] = customer
    _assign_devices_ips(world, customer.customer_id)
    _generate_kyc_for_customer(world, customer)
    return customer


def generate_company(
    world: WorldState,
    profile: Optional[BehavioralProfile] = None,
    representative_id: Optional[str] = None,
    incorporation_date: Optional[date] = None,
    expected_monthly_turnover: Optional[int] = None,
) -> Company:
    rng = world.rng
    cfg = world.config
    if profile is None:
        profile = _weighted_choice(rng, list(COMPANY_PROFILES), list(COMPANY_WEIGHTS))
    spec = PROFILE_SPECS[profile]
    addr = generate_address(world)

    if representative_id is None:
        if not world.customers:
            raise RuntimeError(
                "Cannot create company without customers: generate the customer roster first"
            )
        representative_id = _pick(rng, list(world.customers.keys()))

    if incorporation_date is None:
        if profile == BehavioralProfile.NEWLY_INCORPORATED_COMPANY:
            incorporation_date = (cfg.world_end - timedelta(days=rng.randint(15, 90))).date()
        else:
            years_ago = rng.randint(2, 15)
            incorporation_date = date(
                cfg.world_end.year - years_ago, rng.randint(1, 12), rng.randint(1, 28)
            )

    monthly = expected_monthly_turnover or rng.randint(
        spec.income_or_turnover_min, spec.income_or_turnover_max
    )

    p_xb = spec.p_cross_border
    countries = ["VN"]
    if p_xb > 0.05:
        for c in ("SG", "CN", "US", "JP", "KR", "DE", "CY"):
            if rng.random() < max(0.2, p_xb):
                countries.append(c)
    countries = list(dict.fromkeys(countries))

    company = Company(
        company_id=world.ids.company(),
        legal_name=f"{_pick(rng, COMPANY_NAME_PREFIXES)} {_pick(rng, COMPANY_NAME_CORES)}",
        registration_number=f"DN{rng.randint(1000000000, 9999999999)}",
        incorporation_date=incorporation_date,
        industry_code=_pick(rng, INDUSTRY_CODES),
        registered_address_id=addr.address_id,
        expected_monthly_turnover=monthly,
        expected_cross_border=p_xb >= 0.1,
        expected_countries=countries,
        declared_source_of_funds=_pick(
            rng,
            (
                "Business revenue",
                "Shareholder capital",
                "Trade receivables",
                "Investment income",
            ),
        ),
        account_purpose=_pick(
            rng,
            (
                "Operating expenses",
                "Trade settlement",
                "Payroll disbursement",
                "Event ticketing",
                "General corporate",
            ),
        ),
        representative_customer_id=representative_id,
        kyc_risk_level=_risk_from_profile(profile, rng),
        behavioral_profile=profile,
    )
    world.companies[company.company_id] = company
    _assign_devices_ips(world, company.company_id)
    _generate_kyc_for_company(world, company)
    return company


def _assign_devices_ips(world: WorldState, entity_id: str, n_devices: int = 1) -> None:
    rng = world.rng
    devices = [world.ids.device() for _ in range(n_devices)]
    ips = [
        f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"
        for _ in range(n_devices)
    ]
    world.entity_devices[entity_id] = devices
    world.entity_ips[entity_id] = ips


def _generate_kyc_for_customer(world: WorldState, customer: Customer) -> None:
    rng = world.rng
    cfg = world.config
    spec = PROFILE_SPECS[customer.behavioral_profile]
    monthly_in = max(1, customer.annual_income // 12)
    monthly_out = int(monthly_in * rng.uniform(0.7, 0.95))
    last_rev, next_rev = _clamp_review_window(customer.created_at, cfg.world_end, rng)
    expected_countries = ["VN"]
    if spec.p_cross_border >= 0.1:
        expected_countries.extend(["US", "SG"])
    profile = KYCProfile(
        kyc_profile_id=world.ids.kyc_profile(),
        entity_id=customer.customer_id,
        entity_type=EntityType.CUSTOMER,
        expected_monthly_inflow=monthly_in,
        expected_monthly_outflow=monthly_out,
        expected_transaction_count=rng.randint(spec.tx_count_min, spec.tx_count_max),
        expected_cross_border=spec.p_cross_border >= 0.1,
        expected_countries=expected_countries,
        source_of_funds=(
            "Salary"
            if customer.behavioral_profile == BehavioralProfile.SALARIED_INDIVIDUAL
            else "Mixed income"
        ),
        source_of_wealth="Employment savings",
        last_reviewed_at=last_rev,
        next_review_at=next_rev,
    )
    world.kyc_profiles[profile.kyc_profile_id] = profile

    issued = customer.date_of_birth + timedelta(days=365 * 18)
    # Keep most IDs valid through world_end; a minority expire (status reflects that).
    if rng.random() < 0.12:
        expires = cfg.world_end.date() - timedelta(days=rng.randint(30, 400))
        if expires <= issued:
            expires = issued + timedelta(days=365)
    else:
        expires = max(issued + timedelta(days=365 * 10), cfg.world_end.date() + timedelta(days=365))
    if issued > cfg.world_end.date():
        issued = cfg.world_end.date() - timedelta(days=365 * 5)
        expires = issued + timedelta(days=365 * 10)

    doc = KYCDocument(
        document_id=world.ids.document(),
        entity_id=customer.customer_id,
        document_type="NATIONAL_ID",
        document_number=customer.national_id,
        issued_at=issued,
        expires_at=expires,
        extracted_fields={
            "full_name": customer.full_name,
            "date_of_birth": customer.date_of_birth.isoformat(),
            "nationality": customer.nationality,
        },
        verification_status=_doc_status(expires, cfg.world_end),
    )
    world.kyc_documents[doc.document_id] = doc


def _generate_kyc_for_company(world: WorldState, company: Company) -> None:
    rng = world.rng
    cfg = world.config
    spec = PROFILE_SPECS[company.behavioral_profile]
    monthly = company.expected_monthly_turnover
    entity_start = datetime(
        company.incorporation_date.year,
        company.incorporation_date.month,
        company.incorporation_date.day,
        tzinfo=timezone.utc,
    )
    last_rev, next_rev = _clamp_review_window(entity_start, cfg.world_end, rng)
    profile = KYCProfile(
        kyc_profile_id=world.ids.kyc_profile(),
        entity_id=company.company_id,
        entity_type=EntityType.COMPANY,
        expected_monthly_inflow=monthly,
        expected_monthly_outflow=int(monthly * rng.uniform(0.6, 0.95)),
        expected_transaction_count=rng.randint(spec.tx_count_min, spec.tx_count_max),
        expected_cross_border=company.expected_cross_border,
        expected_countries=list(company.expected_countries),
        source_of_funds=company.declared_source_of_funds,
        source_of_wealth="Business equity",
        last_reviewed_at=last_rev,
        next_review_at=next_rev,
    )
    world.kyc_profiles[profile.kyc_profile_id] = profile

    issued = company.incorporation_date
    if rng.random() < 0.1:
        expires = cfg.world_end.date() - timedelta(days=rng.randint(10, 200))
        if expires < issued:
            expires = issued + timedelta(days=30)
    else:
        expires = max(issued + timedelta(days=365 * 5), cfg.world_end.date() + timedelta(days=180))
    doc = KYCDocument(
        document_id=world.ids.document(),
        entity_id=company.company_id,
        document_type="BUSINESS_LICENSE",
        document_number=company.registration_number,
        issued_at=issued,
        expires_at=expires,
        extracted_fields={
            "legal_name": company.legal_name,
            "registration_number": company.registration_number,
            "industry_code": company.industry_code,
        },
        verification_status=_doc_status(expires, cfg.world_end),
    )
    world.kyc_documents[doc.document_id] = doc

    # Ownership evidence (not a business license) for most companies
    if company.behavioral_profile != BehavioralProfile.NEWLY_INCORPORATED_COMPANY or rng.random() < 0.55:
        ubo_exp = max(issued + timedelta(days=365 * 3), cfg.world_end.date() + timedelta(days=90))
        ubo_doc = KYCDocument(
            document_id=world.ids.document(),
            entity_id=company.company_id,
            document_type="UBO_DECLARATION",
            document_number=f"UBO-{company.registration_number}",
            issued_at=issued,
            expires_at=ubo_exp,
            extracted_fields={"declared": True},
            verification_status=_doc_status(ubo_exp, cfg.world_end),
        )
        world.kyc_documents[ubo_doc.document_id] = ubo_doc


def _owner_start(world: WorldState, owner_entity_id: str, owner_entity_type: EntityType) -> datetime:
    if owner_entity_type == EntityType.CUSTOMER:
        return world.customers[owner_entity_id].created_at
    comp = world.companies[owner_entity_id]
    return datetime(
        comp.incorporation_date.year,
        comp.incorporation_date.month,
        comp.incorporation_date.day,
        tzinfo=timezone.utc,
    )


def generate_account(
    world: WorldState,
    owner_entity_id: str,
    owner_entity_type: EntityType,
    profile: BehavioralProfile,
    opened_at: Optional[datetime] = None,
    bank_id: Optional[str] = None,
    account_type: Optional[AccountType] = None,
    initial_balance: Optional[int] = None,
) -> Account:
    """Create an account. Raises if final account cap would be exceeded."""
    cfg = world.config
    total = len(world.accounts) + len(world.demo_accounts)
    if total >= cfg.max_accounts:
        raise RuntimeError(
            f"Account cap reached ({cfg.max_accounts}); cannot create more accounts"
        )

    rng = world.rng
    spec = PROFILE_SPECS[profile]
    owner_start = _owner_start(world, owner_entity_id, owner_entity_type)

    if opened_at is None:
        # Open after owner exists; prefer before or early in the transaction window.
        max_delay = max(0, (cfg.world_start - owner_start).days + 10)
        delay = rng.randint(0, max(1, max_delay))
        opened_at = owner_start + timedelta(days=delay, hours=rng.randint(0, 12))
        if opened_at < owner_start:
            opened_at = owner_start + timedelta(hours=1)
    else:
        if opened_at < owner_start:
            opened_at = owner_start + timedelta(hours=1)

    if account_type is None:
        if owner_entity_type == EntityType.COMPANY:
            account_type = AccountType.BUSINESS_CURRENT
        else:
            account_type = AccountType.PAYMENT if rng.random() < 0.75 else AccountType.SAVINGS

    if initial_balance is None:
        initial_balance = rng.randint(spec.initial_balance_min, spec.initial_balance_max)

    bank_id = bank_id or _pick(rng, cfg.domestic_bank_ids)
    account = Account(
        account_id=world.ids.account(),
        owner_entity_id=owner_entity_id,
        owner_entity_type=owner_entity_type,
        account_type=account_type,
        currency=cfg.base_currency,
        opened_at=opened_at,
        status=AccountStatus.ACTIVE,
        home_branch=f"BR-{rng.randint(100, 999)}",
        initial_balance=initial_balance,
        allow_overdraft=spec.allow_overdraft,
        overdraft_limit=spec.overdraft_limit,
        bank_id=bank_id,
        behavioral_profile=profile,
    )
    world.register_account(account)
    return account


def create_banks_catalog(world: WorldState) -> None:
    """Exportable bank / external-entity catalog with explicit risk scores."""
    cfg = world.config
    domestic_names = {
        "BANK-VCB-001": "Ngan hang Demo Vietcom",
        "BANK-TCB-002": "Ngan hang Demo Tech",
        "BANK-MBB-003": "Ngan hang Demo Military",
        "BANK-ACB-004": "Ngan hang Demo Asia",
        "BANK-VPB-005": "Ngan hang Demo VP",
    }
    for bank_id in cfg.domestic_bank_ids:
        world.banks[bank_id] = Bank(
            bank_id=bank_id,
            bank_entity_id=f"ENT-{bank_id}",
            legal_name=domestic_names.get(bank_id, f"Demo Domestic Bank {bank_id}"),
            country="VN",
            risk_score=round(world.rng.uniform(5.0, 25.0), 2),
            is_demo=True,
            bank_type="COMMERCIAL",
        )
    world.banks[cfg.crypto_platform_bank_id] = Bank(
        bank_id=cfg.crypto_platform_bank_id,
        bank_entity_id="ENT-CRYPTO-PLATFORM-DEMO",
        legal_name="Crypto Platform Demo Exchange",
        country="XX",
        risk_score=88.5,
        is_demo=True,
        bank_type="CRYPTO_PLATFORM",
    )
    world.banks[cfg.high_risk_foreign_bank_id] = Bank(
        bank_id=cfg.high_risk_foreign_bank_id,
        bank_entity_id="ENT-FOREIGN-HR-BANK",
        legal_name="High Risk Foreign Demo Bank",
        country=cfg.high_risk_foreign_country,
        risk_score=92.0,
        is_demo=True,
        bank_type="FOREIGN_CORRESPONDENT",
    )
    for country in cfg.normal_foreign_countries:
        bank_id = f"BANK-FOREIGN-{country}-DEMO"
        world.banks[bank_id] = Bank(
            bank_id=bank_id,
            bank_entity_id=f"ENT-FOREIGN-{country}-BANK",
            legal_name=f"Demo {country} Correspondent Bank",
            country=country,
            risk_score=round(world.rng.uniform(15.0, 45.0), 2),
            is_demo=True,
            bank_type="FOREIGN_CORRESPONDENT",
        )


def create_demo_external_accounts(world: WorldState) -> None:
    """Materialise valid external counterpart accounts (no system float)."""
    cfg = world.config
    crypto = Account(
        account_id="ACCT-CRYPTO-DEMO-001",
        owner_entity_id="ENT-CRYPTO-PLATFORM-DEMO",
        owner_entity_type=EntityType.BANK,
        account_type=AccountType.BUSINESS_CURRENT,
        currency=cfg.base_currency,
        opened_at=cfg.world_start - timedelta(days=400),
        status=AccountStatus.ACTIVE,
        home_branch="CRYPTO-DEMO",
        initial_balance=50_000_000_000_000,
        bank_id=cfg.crypto_platform_bank_id,
    )
    foreign = Account(
        account_id="ACCT-FOREIGN-HR-001",
        owner_entity_id="ENT-FOREIGN-HR-BANK",
        owner_entity_type=EntityType.BANK,
        account_type=AccountType.BUSINESS_CURRENT,
        currency=cfg.base_currency,
        opened_at=cfg.world_start - timedelta(days=800),
        status=AccountStatus.ACTIVE,
        home_branch="FOREIGN-HR",
        initial_balance=50_000_000_000_000,
        bank_id=cfg.high_risk_foreign_bank_id,
    )
    external_accounts = [crypto, foreign]
    for country in cfg.normal_foreign_countries:
        external_accounts.append(
            Account(
                account_id=f"ACCT-FOREIGN-{country}-001",
                owner_entity_id=f"ENT-FOREIGN-{country}-BANK",
                owner_entity_type=EntityType.BANK,
                account_type=AccountType.BUSINESS_CURRENT,
                currency=cfg.base_currency,
                opened_at=cfg.world_start - timedelta(days=800),
                status=AccountStatus.ACTIVE,
                home_branch=f"FOREIGN-{country}",
                initial_balance=50_000_000_000_000,
                bank_id=f"BANK-FOREIGN-{country}-DEMO",
            )
        )
    for bank_id in cfg.domestic_bank_ids:
        external_accounts.append(
            Account(
                account_id=f"ACCT-SETTLEMENT-{bank_id.removeprefix('BANK-')}",
                owner_entity_id=f"ENT-{bank_id}",
                owner_entity_type=EntityType.BANK,
                account_type=AccountType.BUSINESS_CURRENT,
                currency=cfg.base_currency,
                opened_at=cfg.world_start - timedelta(days=1_000),
                status=AccountStatus.ACTIVE,
                home_branch="BANK-SETTLEMENT",
                initial_balance=100_000_000_000_000,
                bank_id=bank_id,
            )
        )
    for acc in external_accounts:
        world.demo_accounts[acc.account_id] = acc
        world.balances[acc.account_id] = acc.initial_balance


def _total_accounts(world: WorldState) -> int:
    return len(world.accounts) + len(world.demo_accounts)


def generate_entities(world: WorldState) -> None:
    """Phase 1: exact-quota customers/companies, accounts, KYC, banks."""
    cfg = world.config
    create_banks_catalog(world)
    create_demo_external_accounts(world)

    # Exact customer quota (final export size)
    for _ in range(cfg.n_customers):
        generate_customer(world)
    if len(world.customers) != cfg.n_customers:
        raise RuntimeError("Customer quota mismatch after generation")

    # Exact company quota; representatives come from existing customers only
    for _ in range(cfg.n_companies):
        generate_company(world)
    if len(world.companies) != cfg.n_companies:
        raise RuntimeError("Company quota mismatch after generation")

    # At least one account per customer/company when the cap allows
    for cid, cust in list(world.customers.items()):
        if _total_accounts(world) >= cfg.max_accounts:
            break
        generate_account(world, cid, EntityType.CUSTOMER, cust.behavioral_profile)
        if (
            _total_accounts(world) < cfg.max_accounts
            and world.rng.random() < 0.18
        ):
            generate_account(world, cid, EntityType.CUSTOMER, cust.behavioral_profile)

    for coid, comp in list(world.companies.items()):
        if _total_accounts(world) >= cfg.max_accounts:
            break
        generate_account(world, coid, EntityType.COMPANY, comp.behavioral_profile)
        if (
            _total_accounts(world) < cfg.max_accounts
            and world.rng.random() < 0.35
        ):
            generate_account(world, coid, EntityType.COMPANY, comp.behavioral_profile)

    # Pad to min_accounts (final count includes demo accounts)
    customer_ids = list(world.customers.keys())
    company_ids = list(world.companies.keys())
    while _total_accounts(world) < cfg.min_accounts:
        if not customer_ids and not company_ids:
            break
        if world.rng.random() < 0.85 and customer_ids:
            cid = _pick(world.rng, customer_ids)
            cust = world.customers[cid]
            generate_account(world, cid, EntityType.CUSTOMER, cust.behavioral_profile)
        elif company_ids:
            coid = _pick(world.rng, company_ids)
            comp = world.companies[coid]
            generate_account(world, coid, EntityType.COMPANY, comp.behavioral_profile)
        else:
            break
        if _total_accounts(world) >= cfg.max_accounts:
            break

    if _total_accounts(world) < cfg.min_accounts:
        raise RuntimeError(
            f"Unable to reach min_accounts={cfg.min_accounts}; got {_total_accounts(world)}"
        )
    if _total_accounts(world) > cfg.max_accounts:
        raise RuntimeError(
            f"Exceeded max_accounts={cfg.max_accounts}; got {_total_accounts(world)}"
        )
