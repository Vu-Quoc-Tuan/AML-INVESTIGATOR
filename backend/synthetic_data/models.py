"""Pydantic models for all synthetic banking entities."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityType(str, Enum):
    CUSTOMER = "CUSTOMER"
    COMPANY = "COMPANY"
    BANK = "BANK"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"
    FROZEN = "FROZEN"


class AccountType(str, Enum):
    PAYMENT = "PAYMENT"
    SAVINGS = "SAVINGS"
    BUSINESS_CURRENT = "BUSINESS_CURRENT"
    ESCROW = "ESCROW"


class TransactionType(str, Enum):
    TRANSFER = "TRANSFER"
    PAYMENT = "PAYMENT"
    CASH_DEPOSIT = "CASH_DEPOSIT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"
    FX = "FX"
    FEE = "FEE"
    INTEREST = "INTEREST"


class Channel(str, Enum):
    MOBILE = "MOBILE"
    INTERNET = "INTERNET"
    BRANCH = "BRANCH"
    ATM = "ATM"
    POS = "POS"
    API = "API"
    SWIFT = "SWIFT"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"


class ListType(str, Enum):
    SANCTIONS = "SANCTIONS"
    PEP = "PEP"
    WATCHLIST = "WATCHLIST"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"


class WatchlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DELISTED = "DELISTED"


class ScenarioType(str, Enum):
    SUSPICIOUS = "SUSPICIOUS"
    LEGITIMATE_LOOKALIKE = "LEGITIMATE_LOOKALIKE"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"


class Disposition(str, Enum):
    ESCALATE_FOR_SAR_REVIEW = "ESCALATE_FOR_SAR_REVIEW"
    CLEARED_WITH_RATIONALE = "CLEARED_WITH_RATIONALE"
    NEED_MORE_EVIDENCE = "NEED_MORE_EVIDENCE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class BehavioralProfile(str, Enum):
    SALARIED_INDIVIDUAL = "SALARIED_INDIVIDUAL"
    STUDENT = "STUDENT"
    FREELANCER = "FREELANCER"
    RETIRED_CUSTOMER = "RETIRED_CUSTOMER"
    RETAIL_MERCHANT = "RETAIL_MERCHANT"
    EVENT_ORGANIZER = "EVENT_ORGANIZER"
    SME_SOFTWARE_COMPANY = "SME_SOFTWARE_COMPANY"
    IMPORT_EXPORT_COMPANY = "IMPORT_EXPORT_COMPANY"
    PAYROLL_COMPANY = "PAYROLL_COMPANY"
    NEWLY_INCORPORATED_COMPANY = "NEWLY_INCORPORATED_COMPANY"


class StrictModel(BaseModel):
    # Keep enums as enum instances in-memory for profile lookups; JSON export uses mode="json".
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# ---------------------------------------------------------------------------
# Core records
# ---------------------------------------------------------------------------


class Address(StrictModel):
    address_id: str
    line1: str
    ward: str
    district: str
    city: str
    country: str = "VN"
    postal_code: str


class Bank(StrictModel):
    bank_id: str
    bank_entity_id: str
    legal_name: str
    country: str
    risk_score: float
    is_demo: bool = False
    bank_type: str = "COMMERCIAL"


class Customer(StrictModel):
    customer_id: str
    full_name: str
    date_of_birth: date
    nationality: str
    national_id: str
    phone: str
    email: str
    address_id: str
    occupation: str
    annual_income: int
    customer_risk_level: RiskLevel
    created_at: datetime
    behavioral_profile: BehavioralProfile


class Company(StrictModel):
    company_id: str
    legal_name: str
    registration_number: str
    incorporation_date: date
    industry_code: str
    registered_address_id: str
    expected_monthly_turnover: int
    expected_cross_border: bool
    expected_countries: list[str]
    declared_source_of_funds: str
    account_purpose: str
    representative_customer_id: str
    kyc_risk_level: RiskLevel
    behavioral_profile: BehavioralProfile


class Account(StrictModel):
    account_id: str
    owner_entity_id: str
    owner_entity_type: EntityType
    account_type: AccountType
    currency: str
    opened_at: datetime
    status: AccountStatus
    home_branch: str
    initial_balance: int
    allow_overdraft: bool = False
    overdraft_limit: int = 0
    bank_id: str = "BANK-VCB-001"
    # Runtime only — stripped from feature CSV
    behavioral_profile: Optional[BehavioralProfile] = None


class Transaction(StrictModel):
    transaction_id: str
    source_account_id: str
    destination_account_id: str
    source_bank_id: str
    destination_bank_id: str
    amount: int
    currency: str
    transaction_type: TransactionType
    channel: Channel
    purpose_code: str
    description: str
    occurred_at: datetime
    source_ip: str
    device_id: str
    is_cross_border: bool
    destination_country: str

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class KYCProfile(StrictModel):
    kyc_profile_id: str
    entity_id: str
    entity_type: EntityType
    expected_monthly_inflow: int
    expected_monthly_outflow: int
    expected_transaction_count: int
    expected_cross_border: bool
    expected_countries: list[str]
    source_of_funds: str
    source_of_wealth: str
    last_reviewed_at: datetime
    next_review_at: datetime


class KYCDocument(StrictModel):
    document_id: str
    entity_id: str
    document_type: str
    document_number: str
    issued_at: date
    expires_at: Optional[date]
    extracted_fields: dict[str, Any]
    verification_status: VerificationStatus


class CompanyOwnership(StrictModel):
    ownership_id: str
    owner_entity_id: str
    owner_entity_type: EntityType
    owned_company_id: str
    ownership_percentage: float
    effective_from: date
    effective_to: Optional[date]
    source_document_id: Optional[str]
    verified: bool

    @field_validator("ownership_percentage")
    @classmethod
    def pct_range(cls, v: float) -> float:
        if not (0 < v <= 100):
            raise ValueError("ownership_percentage must be in (0, 100]")
        return v


class EntityRelationship(StrictModel):
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    valid_from: date
    valid_to: Optional[date]
    source: str
    confidence: float


class WatchlistEntry(StrictModel):
    watchlist_id: str
    list_type: ListType
    full_name: str
    aliases: list[str]
    date_of_birth: Optional[date]
    nationalities: list[str]
    document_numbers: list[str]
    addresses: list[str]
    company_registration_number: Optional[str]
    source_name: str
    effective_from: date
    effective_to: Optional[date]
    status: WatchlistStatus
    # Screening dependency metadata (not a match result)
    screening_dependency: Optional[str] = None  # e.g. "available" | "unavailable"
    related_entity_id: Optional[str] = None


class GroundTruthScenario(StrictModel):
    scenario_id: str
    scenario_type: ScenarioType
    start_time: datetime
    end_time: datetime
    involved_account_ids: list[str]
    involved_entity_ids: list[str]
    suspicious_transaction_ids: list[str]
    expected_alert_type: str
    expected_case_disposition: Disposition
    explanation: str
    typology_tags: list[str] = Field(default_factory=list)
    notes: dict[str, Any] = Field(default_factory=dict)


# Feature-export column sets (no ground-truth labels)
CUSTOMER_FEATURE_COLUMNS = (
    "customer_id", "full_name", "date_of_birth", "nationality", "national_id",
    "phone", "email", "address_id", "occupation", "annual_income",
    "customer_risk_level", "created_at",
)

COMPANY_FEATURE_COLUMNS = (
    "company_id", "legal_name", "registration_number", "incorporation_date",
    "industry_code", "registered_address_id", "expected_monthly_turnover",
    "expected_cross_border", "expected_countries", "declared_source_of_funds",
    "account_purpose", "representative_customer_id", "kyc_risk_level",
)

ACCOUNT_FEATURE_COLUMNS = (
    "account_id", "owner_entity_id", "owner_entity_type", "account_type",
    "currency", "opened_at", "status", "home_branch", "initial_balance",
    "bank_id",
)

TRANSACTION_FEATURE_COLUMNS = (
    "transaction_id", "source_account_id", "destination_account_id",
    "source_bank_id", "destination_bank_id", "amount", "currency",
    "transaction_type", "channel", "purpose_code", "description",
    "occurred_at", "source_ip", "device_id", "is_cross_border",
    "destination_country",
)
