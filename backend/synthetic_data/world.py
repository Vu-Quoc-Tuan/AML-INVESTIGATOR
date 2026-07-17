"""In-memory world state shared across generator phases."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from synthetic_data.config import GeneratorConfig
from synthetic_data.id_factory import IDFactory
from synthetic_data.models import (
    Account,
    Address,
    Bank,
    Company,
    CompanyOwnership,
    Customer,
    EntityRelationship,
    GroundTruthScenario,
    KYCDocument,
    KYCProfile,
    Transaction,
    WatchlistEntry,
)


@dataclass
class WorldState:
    """Mutable container for all generated records."""

    config: GeneratorConfig
    rng: random.Random
    ids: IDFactory = field(default_factory=IDFactory)

    addresses: dict[str, Address] = field(default_factory=dict)
    banks: dict[str, Bank] = field(default_factory=dict)
    customers: dict[str, Customer] = field(default_factory=dict)
    companies: dict[str, Company] = field(default_factory=dict)
    accounts: dict[str, Account] = field(default_factory=dict)
    transactions: dict[str, Transaction] = field(default_factory=dict)
    kyc_profiles: dict[str, KYCProfile] = field(default_factory=dict)
    kyc_documents: dict[str, KYCDocument] = field(default_factory=dict)
    ownerships: dict[str, CompanyOwnership] = field(default_factory=dict)
    relationships: dict[str, EntityRelationship] = field(default_factory=dict)
    watchlist: dict[str, WatchlistEntry] = field(default_factory=dict)
    scenarios: dict[str, GroundTruthScenario] = field(default_factory=dict)

    # Runtime balance tracking: account_id -> current balance (VND int)
    balances: dict[str, int] = field(default_factory=dict)
    # Devices / IPs assigned to entities for behavioural consistency
    entity_devices: dict[str, list[str]] = field(default_factory=dict)
    entity_ips: dict[str, list[str]] = field(default_factory=dict)

    # Index: entity_id -> account_ids
    entity_accounts: dict[str, list[str]] = field(default_factory=dict)

    # Demo external accounts (crypto platform, high-risk foreign bank)
    demo_accounts: dict[str, Account] = field(default_factory=dict)

    # Quota-first scenario bookkeeping
    scenario_used_customers: set[str] = field(default_factory=set)
    scenario_used_companies: set[str] = field(default_factory=set)
    normal_transaction_ids: set[str] = field(default_factory=set)

    @classmethod
    def create(cls, config: GeneratorConfig) -> "WorldState":
        return cls(config=config, rng=random.Random(config.random_seed))

    def register_account(self, account: Account) -> None:
        self.accounts[account.account_id] = account
        self.balances[account.account_id] = account.initial_balance
        self.entity_accounts.setdefault(account.owner_entity_id, []).append(
            account.account_id
        )

    def get_account(self, account_id: str) -> Optional[Account]:
        if account_id in self.accounts:
            return self.accounts[account_id]
        return self.demo_accounts.get(account_id)

    def all_account_ids(self) -> list[str]:
        return list(self.accounts.keys()) + list(self.demo_accounts.keys())
