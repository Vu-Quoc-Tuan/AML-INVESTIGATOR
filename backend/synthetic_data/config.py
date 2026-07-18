"""Generator configuration defaults and CLI-overridable settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class GeneratorConfig:
    """Runtime configuration for the synthetic banking world."""

    random_seed: int = 42
    n_customers: int = 2000
    n_companies: int = 50
    n_transactions: int = 40_000
    # Final account population (including demo/external accounts).
    min_accounts: int = 2500
    max_accounts: int = 3000
    window_days: int = 90
    base_currency: str = "VND"
    output_dir: Path = field(default_factory=lambda: Path("./data/generated"))

    # SHB data boundary
    home_bank_id: str = "BANK-SHB-001"
    n_external_accounts: int = 1_000
    internal_transaction_ratio: float = 0.45
    inbound_transaction_ratio: float = 0.275
    outbound_transaction_ratio: float = 0.275
    cross_border_ratio: float = 0.05

    # Timeline anchors (UTC). World "now" is end of window.
    world_end: datetime = field(
        default_factory=lambda: datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    )

    # Scenario injection
    n_suspicious_scenarios: int = 3
    n_lookalike_scenarios: int = 3
    inject_incomplete_evidence: bool = True

    # Domestic + demo institutions
    domestic_bank_ids: tuple[str, ...] = (
        "BANK-VCB-EXT",
        "BANK-TCB-EXT",
        "BANK-MBB-EXT",
        "BANK-ACB-EXT",
        "BANK-VPB-EXT",
    )
    crypto_platform_bank_id: str = "BANK-CRYPTO-DEMO-99"
    high_risk_foreign_bank_id: str = "BANK-FOREIGN-HR-88"
    high_risk_foreign_country: str = "CY"
    normal_foreign_countries: tuple[str, ...] = ("SG", "CN", "US", "JP", "KR", "DE")

    # Overdraft
    default_allow_overdraft: bool = False

    # Manifest
    write_manifest: bool = True
    run_validation: bool = True

    def validate(self) -> None:
        if self.min_accounts > self.max_accounts:
            raise ValueError("min_accounts cannot exceed max_accounts")
        if not 500 <= self.n_external_accounts <= 1_500:
            raise ValueError("n_external_accounts must be between 500 and 1500")
        ratios = (
            self.internal_transaction_ratio
            + self.inbound_transaction_ratio
            + self.outbound_transaction_ratio
        )
        if abs(ratios - 1.0) > 1e-9:
            raise ValueError("transaction direction ratios must sum to 1.0")
        external_ratio = self.inbound_transaction_ratio + self.outbound_transaction_ratio
        if not 0.0 <= self.cross_border_ratio <= external_ratio:
            raise ValueError("cross_border_ratio must fit within external traffic")

    @property
    def world_start(self) -> datetime:
        return self.world_end - timedelta(days=self.window_days)

    def to_dict(self) -> dict[str, Any]:
        return {
            "random_seed": self.random_seed,
            "n_customers": self.n_customers,
            "n_companies": self.n_companies,
            "n_transactions": self.n_transactions,
            "min_accounts": self.min_accounts,
            "max_accounts": self.max_accounts,
            "window_days": self.window_days,
            "base_currency": self.base_currency,
            "home_bank_id": self.home_bank_id,
            "n_external_accounts": self.n_external_accounts,
            "internal_transaction_ratio": self.internal_transaction_ratio,
            "inbound_transaction_ratio": self.inbound_transaction_ratio,
            "outbound_transaction_ratio": self.outbound_transaction_ratio,
            "cross_border_ratio": self.cross_border_ratio,
            "output_dir": str(self.output_dir),
            "world_end": self.world_end.isoformat(),
            "world_start": self.world_start.isoformat(),
            "n_suspicious_scenarios": self.n_suspicious_scenarios,
            "n_lookalike_scenarios": self.n_lookalike_scenarios,
            "inject_incomplete_evidence": self.inject_incomplete_evidence,
            "domestic_bank_ids": list(self.domestic_bank_ids),
            "crypto_platform_bank_id": self.crypto_platform_bank_id,
            "high_risk_foreign_bank_id": self.high_risk_foreign_bank_id,
            "normal_foreign_countries": list(self.normal_foreign_countries),
        }


# ---------------------------------------------------------------------------
# Static reference data (entirely fictitious)
# ---------------------------------------------------------------------------

FAKE_FIRST_NAMES = (
    "An", "Binh", "Chi", "Dung", "Em", "Giang", "Hai", "Hanh", "Hung", "Khanh",
    "Lan", "Linh", "Minh", "Nam", "Nga", "Phong", "Quang", "Son", "Tam", "Thao",
    "Tuan", "Van", "Yen", "Bao", "Cuong", "Diep", "Hoa", "Khoa", "My", "Oanh",
    "Phuong", "Quynh", "Trang", "Uy", "Viet", "Xuan", "Dao", "Hieu", "Kiet", "Nhi",
)

FAKE_LAST_NAMES = (
    "Nguyen", "Tran", "Le", "Pham", "Hoang", "Huynh", "Phan", "Vu", "Vo", "Dang",
    "Bui", "Do", "Ho", "Ngo", "Duong", "Ly", "Trinh", "Doan", "Mai", "Cao",
)

FAKE_STREETS = (
    "So 12 Duong Gia", "So 45 Pho Ao", "So 7 Ngach Demo", "So 99 Hem Mock",
    "So 3 Duong Synthetic", "So 21 Pho Fictitious", "So 88 Lo Demo Data",
    "So 15 Duong Sandbox", "So 60 Pho Placeholder", "So 33 Ngach Testbed",
)

FAKE_WARDS = (
    "Phuong Gia Lap", "Phuong Mo Phong", "Xa Du Lieu", "Phuong Sandbox",
    "Phuong Thu Nghiem", "Xa Mo Hinh", "Phuong Demo", "Xa Synthetic",
)

FAKE_DISTRICTS = (
    "Quan Mock 1", "Quan Mock 2", "Huyen Sandbox", "Quan Test 3", "Huyen Demo",
)

FAKE_CITIES = ("Thanh pho Gia", "Thanh pho Ao", "Tinh Mo Phong", "Thanh pho Demo")

NATIONALITIES = ("VN", "VN", "VN", "VN", "VN", "SG", "US", "JP", "KR", "AU")

OCCUPATIONS = (
    "Software Engineer", "Teacher", "Accountant", "Nurse", "Sales Associate",
    "Student", "Freelancer", "Retired", "Retail Manager", "Driver",
    "Marketing Specialist", "Civil Servant", "Factory Worker", "Consultant",
)

INDUSTRY_CODES = (
    "6201",  # computer programming
    "6202",  # consultancy
    "4690",  # non-specialised wholesale
    "4711",  # retail food
    "5610",  # restaurants
    "8230",  # convention/event
    "6419",  # other monetary
    "8299",  # other business support
    "5229",  # other transport support
    "7020",  # management consultancy
)

COMPANY_NAME_PREFIXES = (
    "Cong ty TNHH", "Cong ty CP", "Cong ty MTV", "Doanh nghiep Tu nhan",
)
COMPANY_NAME_CORES = (
    "Sao Mai Demo", "Hoang Gia Ao", "Minh Phat Sandbox", "Thinh Vuong Mock",
    "Phuong Dong Synthetic", "Dai Viet Test", "An Binh Placeholder",
    "Tan Phat Demo", "Viet Hung Sandbox", "Kim Long Mock",
    "Thanh Dat Synthetic", "Bao Tin Demo", "Nhat Quang Sandbox",
    "Phuc Loc Mock", "Hai Au Synthetic", "Song Hong Demo",
    "Dong A Sandbox", "Tay Nguyen Mock", "Mekong Synthetic", "Red River Demo",
)

PURPOSE_CODES = (
    "PAYROLL", "SUPPLIER", "RENT", "UTILITIES", "GOODS", "SERVICES",
    "TRANSFER", "CASH_IN", "CASH_OUT", "FX", "TICKET", "INVOICE",
    "LOAN", "REFUND", "OTHER",
)

CHANNELS = ("MOBILE", "INTERNET", "BRANCH", "ATM", "POS", "API", "SWIFT")

ACCOUNT_TYPES = ("PAYMENT", "SAVINGS", "BUSINESS_CURRENT", "ESCROW")

DOCUMENT_TYPES = (
    "NATIONAL_ID", "PASSPORT", "BUSINESS_LICENSE", "TAX_CERTIFICATE",
    "ARTICLES_OF_ASSOCIATION", "UBO_DECLARATION", "PROOF_OF_ADDRESS",
)

# Ground-truth column names that must NEVER appear in feature tables
GROUND_TRUTH_FORBIDDEN_COLUMNS = frozenset(
    {
        "scenario_id",
        "is_suspicious",
        "suspicious",
        "expected_alert_type",
        "expected_case_disposition",
        "ground_truth",
        "label",
        "aml_label",
        "true_label",
        "disposition",
        "explanation",
    }
)
