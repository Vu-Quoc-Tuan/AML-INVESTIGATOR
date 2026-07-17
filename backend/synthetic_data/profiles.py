"""Behavioral profiles driving normal transaction generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from synthetic_data.models import BehavioralProfile, Channel


@dataclass(frozen=True)
class ProfileSpec:
    """Statistical behaviour for an entity class."""

    profile: BehavioralProfile
    # Income (individual annual) or monthly turnover (company)
    income_or_turnover_min: int
    income_or_turnover_max: int
    # Transactions per month
    tx_count_min: int
    tx_count_max: int
    # Amount distribution (VND)
    amount_min: int
    amount_max: int
    amount_median: int
    # Hour-of-day weights (24 floats, will be normalised)
    hour_weights: tuple[float, ...]
    # Preferred counterpart roles
    counterpart_roles: tuple[str, ...]
    p_cross_border: float
    channels: tuple[tuple[Channel, float], ...]
    # Relative volatility multiplier (1.0 = baseline)
    volatility: float
    allow_overdraft: bool = False
    overdraft_limit: int = 0
    is_company: bool = False
    typical_purpose_codes: tuple[str, ...] = ("TRANSFER", "PAYMENT")
    initial_balance_min: int = 1_000_000
    initial_balance_max: int = 50_000_000
    notes: str = ""


def _business_hours() -> tuple[float, ...]:
    w = [0.1] * 24
    for h in range(8, 18):
        w[h] = 1.0
    w[12] = 0.6
    return tuple(w)


def _evening_hours() -> tuple[float, ...]:
    w = [0.15] * 24
    for h in range(18, 23):
        w[h] = 1.0
    for h in range(9, 17):
        w[h] = 0.5
    return tuple(w)


def _payroll_day_hours() -> tuple[float, ...]:
    w = [0.05] * 24
    for h in range(8, 12):
        w[h] = 1.0
    return tuple(w)


PROFILE_SPECS: dict[BehavioralProfile, ProfileSpec] = {
    BehavioralProfile.SALARIED_INDIVIDUAL: ProfileSpec(
        profile=BehavioralProfile.SALARIED_INDIVIDUAL,
        income_or_turnover_min=120_000_000,
        income_or_turnover_max=480_000_000,
        tx_count_min=8,
        tx_count_max=25,
        amount_min=50_000,
        amount_max=30_000_000,
        amount_median=2_000_000,
        hour_weights=_evening_hours(),
        counterpart_roles=("merchant", "utility", "peer", "employer"),
        p_cross_border=0.02,
        channels=((Channel.MOBILE, 0.7), (Channel.INTERNET, 0.2), (Channel.ATM, 0.1)),
        volatility=0.8,
        typical_purpose_codes=("TRANSFER", "PAYMENT", "UTILITIES", "RENT"),
        initial_balance_min=5_000_000,
        initial_balance_max=80_000_000,
    ),
    BehavioralProfile.STUDENT: ProfileSpec(
        profile=BehavioralProfile.STUDENT,
        income_or_turnover_min=24_000_000,
        income_or_turnover_max=72_000_000,
        tx_count_min=10,
        tx_count_max=35,
        amount_min=20_000,
        amount_max=5_000_000,
        amount_median=300_000,
        hour_weights=_evening_hours(),
        counterpart_roles=("merchant", "peer", "parent"),
        p_cross_border=0.01,
        channels=((Channel.MOBILE, 0.85), (Channel.ATM, 0.1), (Channel.POS, 0.05)),
        volatility=1.0,
        typical_purpose_codes=("TRANSFER", "PAYMENT", "CASH_OUT"),
        initial_balance_min=500_000,
        initial_balance_max=15_000_000,
    ),
    BehavioralProfile.FREELANCER: ProfileSpec(
        profile=BehavioralProfile.FREELANCER,
        income_or_turnover_min=100_000_000,
        income_or_turnover_max=600_000_000,
        tx_count_min=12,
        tx_count_max=40,
        amount_min=100_000,
        amount_max=80_000_000,
        amount_median=5_000_000,
        hour_weights=_business_hours(),
        counterpart_roles=("client", "peer", "merchant", "platform"),
        p_cross_border=0.15,
        channels=((Channel.INTERNET, 0.5), (Channel.MOBILE, 0.4), (Channel.API, 0.1)),
        volatility=1.4,
        typical_purpose_codes=("SERVICES", "TRANSFER", "INVOICE"),
        initial_balance_min=3_000_000,
        initial_balance_max=100_000_000,
    ),
    BehavioralProfile.RETIRED_CUSTOMER: ProfileSpec(
        profile=BehavioralProfile.RETIRED_CUSTOMER,
        income_or_turnover_min=60_000_000,
        income_or_turnover_max=180_000_000,
        tx_count_min=5,
        tx_count_max=15,
        amount_min=50_000,
        amount_max=15_000_000,
        amount_median=1_500_000,
        hour_weights=_business_hours(),
        counterpart_roles=("utility", "merchant", "peer", "family"),
        p_cross_border=0.005,
        channels=((Channel.BRANCH, 0.3), (Channel.MOBILE, 0.4), (Channel.ATM, 0.3)),
        volatility=0.5,
        typical_purpose_codes=("UTILITIES", "PAYMENT", "TRANSFER", "CASH_OUT"),
        initial_balance_min=10_000_000,
        initial_balance_max=200_000_000,
    ),
    BehavioralProfile.RETAIL_MERCHANT: ProfileSpec(
        profile=BehavioralProfile.RETAIL_MERCHANT,
        income_or_turnover_min=200_000_000,
        income_or_turnover_max=2_000_000_000,
        tx_count_min=40,
        tx_count_max=120,
        amount_min=50_000,
        amount_max=50_000_000,
        amount_median=1_000_000,
        hour_weights=_business_hours(),
        counterpart_roles=("customer", "supplier", "utility"),
        p_cross_border=0.03,
        channels=((Channel.POS, 0.5), (Channel.MOBILE, 0.2), (Channel.INTERNET, 0.2), (Channel.API, 0.1)),
        volatility=1.1,
        is_company=True,
        typical_purpose_codes=("GOODS", "SUPPLIER", "PAYMENT", "CASH_IN"),
        initial_balance_min=20_000_000,
        initial_balance_max=300_000_000,
    ),
    BehavioralProfile.EVENT_ORGANIZER: ProfileSpec(
        profile=BehavioralProfile.EVENT_ORGANIZER,
        income_or_turnover_min=500_000_000,
        income_or_turnover_max=5_000_000_000,
        tx_count_min=30,
        tx_count_max=100,
        amount_min=200_000,
        amount_max=20_000_000,
        amount_median=1_500_000,
        hour_weights=_evening_hours(),
        counterpart_roles=("ticket_buyer", "venue", "supplier", "artist"),
        p_cross_border=0.05,
        channels=((Channel.INTERNET, 0.5), (Channel.MOBILE, 0.3), (Channel.API, 0.2)),
        volatility=1.3,
        is_company=True,
        typical_purpose_codes=("TICKET", "SERVICES", "SUPPLIER", "PAYMENT"),
        initial_balance_min=50_000_000,
        initial_balance_max=500_000_000,
        notes="Legitimate fan-in from ticket sales with order IDs",
    ),
    BehavioralProfile.SME_SOFTWARE_COMPANY: ProfileSpec(
        profile=BehavioralProfile.SME_SOFTWARE_COMPANY,
        income_or_turnover_min=300_000_000,
        income_or_turnover_max=3_000_000_000,
        tx_count_min=20,
        tx_count_max=60,
        amount_min=500_000,
        amount_max=200_000_000,
        amount_median=15_000_000,
        hour_weights=_business_hours(),
        counterpart_roles=("client", "payroll", "vendor", "cloud"),
        p_cross_border=0.2,
        channels=((Channel.INTERNET, 0.5), (Channel.API, 0.3), (Channel.MOBILE, 0.2)),
        volatility=1.0,
        is_company=True,
        typical_purpose_codes=("SERVICES", "PAYROLL", "INVOICE", "TRANSFER"),
        initial_balance_min=50_000_000,
        initial_balance_max=800_000_000,
    ),
    BehavioralProfile.IMPORT_EXPORT_COMPANY: ProfileSpec(
        profile=BehavioralProfile.IMPORT_EXPORT_COMPANY,
        income_or_turnover_min=1_000_000_000,
        income_or_turnover_max=20_000_000_000,
        tx_count_min=15,
        tx_count_max=50,
        amount_min=10_000_000,
        amount_max=2_000_000_000,
        amount_median=100_000_000,
        hour_weights=_business_hours(),
        counterpart_roles=("foreign_supplier", "domestic_buyer", "logistics", "customs"),
        p_cross_border=0.55,
        channels=((Channel.SWIFT, 0.4), (Channel.INTERNET, 0.4), (Channel.API, 0.2)),
        volatility=1.5,
        is_company=True,
        typical_purpose_codes=("GOODS", "INVOICE", "FX", "SERVICES"),
        initial_balance_min=100_000_000,
        initial_balance_max=2_000_000_000,
    ),
    BehavioralProfile.PAYROLL_COMPANY: ProfileSpec(
        profile=BehavioralProfile.PAYROLL_COMPANY,
        income_or_turnover_min=2_000_000_000,
        income_or_turnover_max=30_000_000_000,
        tx_count_min=50,
        tx_count_max=200,
        amount_min=5_000_000,
        amount_max=100_000_000,
        amount_median=20_000_000,
        hour_weights=_payroll_day_hours(),
        counterpart_roles=("employee", "tax", "insurance", "client"),
        p_cross_border=0.02,
        channels=((Channel.API, 0.6), (Channel.INTERNET, 0.3), (Channel.BRANCH, 0.1)),
        volatility=0.7,
        is_company=True,
        typical_purpose_codes=("PAYROLL", "TRANSFER", "SERVICES"),
        initial_balance_min=200_000_000,
        initial_balance_max=5_000_000_000,
    ),
    BehavioralProfile.NEWLY_INCORPORATED_COMPANY: ProfileSpec(
        profile=BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
        income_or_turnover_min=50_000_000,
        income_or_turnover_max=400_000_000,
        tx_count_min=3,
        tx_count_max=15,
        amount_min=1_000_000,
        amount_max=50_000_000,
        amount_median=5_000_000,
        hour_weights=_business_hours(),
        counterpart_roles=("supplier", "peer", "service"),
        p_cross_border=0.1,
        channels=((Channel.INTERNET, 0.5), (Channel.MOBILE, 0.3), (Channel.BRANCH, 0.2)),
        volatility=1.8,
        is_company=True,
        typical_purpose_codes=("TRANSFER", "SERVICES", "GOODS"),
        initial_balance_min=5_000_000,
        initial_balance_max=50_000_000,
        notes="Low historical baseline; high deviation risk",
    ),
}


INDIVIDUAL_PROFILES: Sequence[BehavioralProfile] = (
    BehavioralProfile.SALARIED_INDIVIDUAL,
    BehavioralProfile.STUDENT,
    BehavioralProfile.FREELANCER,
    BehavioralProfile.RETIRED_CUSTOMER,
)

COMPANY_PROFILES: Sequence[BehavioralProfile] = (
    BehavioralProfile.RETAIL_MERCHANT,
    BehavioralProfile.EVENT_ORGANIZER,
    BehavioralProfile.SME_SOFTWARE_COMPANY,
    BehavioralProfile.IMPORT_EXPORT_COMPANY,
    BehavioralProfile.PAYROLL_COMPANY,
    BehavioralProfile.NEWLY_INCORPORATED_COMPANY,
)

# Sampling weights for realistic mix
INDIVIDUAL_WEIGHTS = (0.55, 0.12, 0.20, 0.13)
COMPANY_WEIGHTS = (0.25, 0.12, 0.25, 0.15, 0.13, 0.10)
