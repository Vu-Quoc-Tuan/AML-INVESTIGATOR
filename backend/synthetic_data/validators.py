"""Validation suite for generated synthetic banking worlds."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from synthetic_data.config import GROUND_TRUTH_FORBIDDEN_COLUMNS
from synthetic_data.models import (
    ACCOUNT_FEATURE_COLUMNS,
    COMPANY_FEATURE_COLUMNS,
    CUSTOMER_FEATURE_COLUMNS,
    TRANSACTION_FEATURE_COLUMNS,
    EntityType,
    VerificationStatus,
)
from synthetic_data.profiles import PROFILE_SPECS
from synthetic_data.world import WorldState


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_world(world: WorldState) -> ValidationResult:
    result = ValidationResult()
    _check_quotas(world, result)
    _check_duplicate_ids(world, result)
    _check_foreign_keys(world, result)
    _check_missing_account_owners(world, result)
    _check_timestamps(world, result)
    _check_entity_timelines(world, result)
    _check_ownership_percentages(world, result)
    _check_ownership_evidence(world, result)
    _check_document_validity(world, result)
    _check_shared_address(world, result)
    _check_transaction_amounts(world, result)
    _check_no_system_float(world, result)
    _check_profile_initial_balances(world, result)
    _check_balances(world, result)
    _check_normal_cross_border_mix(world, result)
    _check_ground_truth_tx_ids(world, result)
    _check_screening_dependencies(world, result)
    _check_feature_columns_clean(result)
    return result


def _check_quotas(world: WorldState, result: ValidationResult) -> None:
    cfg = world.config
    if len(world.customers) != cfg.n_customers:
        result.fail(
            f"Customer count {len(world.customers)} != configured {cfg.n_customers}"
        )
    if len(world.companies) != cfg.n_companies:
        result.fail(
            f"Company count {len(world.companies)} != configured {cfg.n_companies}"
        )
    total_accounts = len(world.accounts) + len(world.demo_accounts)
    if total_accounts < cfg.min_accounts:
        result.fail(
            f"Account count {total_accounts} below min_accounts {cfg.min_accounts}"
        )
    if total_accounts > cfg.max_accounts:
        result.fail(
            f"Account count {total_accounts} above max_accounts {cfg.max_accounts}"
        )
    if len(world.normal_transaction_ids) != cfg.n_transactions:
        result.fail(
            f"Normal transactions {len(world.normal_transaction_ids)} != configured "
            f"{cfg.n_transactions}"
        )


def _check_duplicate_ids(world: WorldState, result: ValidationResult) -> None:
    collections: list[tuple[str, Iterable[str]]] = [
        ("customer", world.customers.keys()),
        ("company", world.companies.keys()),
        ("account", list(world.accounts.keys()) + list(world.demo_accounts.keys())),
        ("transaction", world.transactions.keys()),
        ("kyc_profile", world.kyc_profiles.keys()),
        ("kyc_document", world.kyc_documents.keys()),
        ("ownership", world.ownerships.keys()),
        ("relationship", world.relationships.keys()),
        ("watchlist", world.watchlist.keys()),
        ("scenario", world.scenarios.keys()),
        ("address", world.addresses.keys()),
        ("bank", world.banks.keys()),
    ]
    for name, keys in collections:
        seen = set()
        for k in keys:
            if k in seen:
                result.fail(f"Duplicate {name} id: {k}")
            seen.add(k)


def _check_foreign_keys(world: WorldState, result: ValidationResult) -> None:
    customer_ids = set(world.customers)
    company_ids = set(world.companies)
    bank_entity_ids = {bank.bank_entity_id for bank in world.banks.values()}
    entity_ids = customer_ids | company_ids | bank_entity_ids
    address_ids = set(world.addresses)
    account_ids = set(world.accounts) | set(world.demo_accounts)
    doc_ids = set(world.kyc_documents)
    bank_ids = set(world.banks) or (
        set(world.config.domestic_bank_ids)
        | {
            world.config.crypto_platform_bank_id,
            world.config.high_risk_foreign_bank_id,
        }
    )

    for c in world.customers.values():
        if c.address_id not in address_ids:
            result.fail(f"Customer {c.customer_id} address_id missing: {c.address_id}")

    for co in world.companies.values():
        if co.registered_address_id not in address_ids:
            result.fail(f"Company {co.company_id} address missing: {co.registered_address_id}")
        if co.representative_customer_id not in customer_ids:
            result.fail(
                f"Company {co.company_id} representative missing: {co.representative_customer_id}"
            )

    for a in list(world.accounts.values()) + list(world.demo_accounts.values()):
        otype = a.owner_entity_type.value if hasattr(a.owner_entity_type, "value") else a.owner_entity_type
        if otype == "CUSTOMER" and a.owner_entity_id not in customer_ids:
            result.fail(f"Account {a.account_id} owner customer missing")
        if otype == "COMPANY" and a.owner_entity_id not in company_ids:
            result.fail(f"Account {a.account_id} owner company missing")
        if otype == "BANK" and a.owner_entity_id not in bank_entity_ids:
            result.fail(f"Account {a.account_id} bank owner missing: {a.owner_entity_id}")
        if a.bank_id not in bank_ids:
            result.fail(f"Account {a.account_id} bank_id not in catalog: {a.bank_id}")

    for t in world.transactions.values():
        if t.source_account_id not in account_ids:
            result.fail(f"Txn {t.transaction_id} source account missing")
        if t.destination_account_id not in account_ids:
            result.fail(f"Txn {t.transaction_id} dest account missing")
        if t.source_bank_id not in bank_ids:
            result.fail(f"Txn {t.transaction_id} source_bank_id missing from catalog")
        if t.destination_bank_id not in bank_ids:
            result.fail(f"Txn {t.transaction_id} destination_bank_id missing from catalog")
        src = world.get_account(t.source_account_id)
        dst = world.get_account(t.destination_account_id)
        if src is not None and t.source_bank_id != src.bank_id:
            result.fail(f"Txn {t.transaction_id} source_bank_id mismatches source account")
        if dst is not None and t.destination_bank_id != dst.bank_id:
            result.fail(f"Txn {t.transaction_id} destination_bank_id mismatches destination account")
        if dst is not None and dst.bank_id in world.banks:
            expected_country = world.banks[dst.bank_id].country
            if t.destination_country != expected_country:
                result.fail(
                    f"Txn {t.transaction_id} destination_country {t.destination_country} "
                    f"!= destination bank country {expected_country}"
                )
        if src is not None and dst is not None:
            src_country = world.banks[src.bank_id].country
            dst_country = world.banks[dst.bank_id].country
            if t.is_cross_border != (src_country != dst_country):
                result.fail(
                    f"Txn {t.transaction_id} cross-border flag inconsistent with bank countries"
                )

    for o in world.ownerships.values():
        if o.owned_company_id not in company_ids:
            result.fail(f"Ownership {o.ownership_id} owned company missing")
        otype = o.owner_entity_type.value if hasattr(o.owner_entity_type, "value") else o.owner_entity_type
        if otype == "CUSTOMER" and o.owner_entity_id not in customer_ids:
            result.fail(f"Ownership {o.ownership_id} owner customer missing")
        if otype == "COMPANY" and o.owner_entity_id not in company_ids:
            result.fail(f"Ownership {o.ownership_id} owner company missing")
        if o.source_document_id and o.source_document_id not in doc_ids:
            result.fail(f"Ownership {o.ownership_id} source_document missing")

    for d in world.kyc_documents.values():
        if d.entity_id not in customer_ids and d.entity_id not in company_ids:
            result.fail(f"Document {d.document_id} entity missing: {d.entity_id}")

    for p in world.kyc_profiles.values():
        if p.entity_id not in customer_ids and p.entity_id not in company_ids:
            result.fail(f"KYC profile {p.kyc_profile_id} entity missing")

    for sc in world.scenarios.values():
        for eid in sc.involved_entity_ids:
            if eid not in entity_ids:
                result.fail(f"Scenario {sc.scenario_id} entity missing: {eid}")


def _check_missing_account_owners(world: WorldState, result: ValidationResult) -> None:
    for a in world.accounts.values():
        if not a.owner_entity_id:
            result.fail(f"Account {a.account_id} has empty owner")


def _check_timestamps(world: WorldState, result: ValidationResult) -> None:
    for t in world.transactions.values():
        src = world.get_account(t.source_account_id)
        dst = world.get_account(t.destination_account_id)
        if src and t.occurred_at < src.opened_at:
            result.fail(
                f"Txn {t.transaction_id} before source account open "
                f"({t.occurred_at} < {src.opened_at})"
            )
        if dst and t.occurred_at < dst.opened_at:
            result.fail(
                f"Txn {t.transaction_id} before dest account open "
                f"({t.occurred_at} < {dst.opened_at})"
            )

    for sc in world.scenarios.values():
        if sc.start_time > sc.end_time:
            result.fail(f"Scenario {sc.scenario_id} start > end")


def _check_entity_timelines(world: WorldState, result: ValidationResult) -> None:
    """Accounts/KYC must not predate their owning entity."""
    bad_acct = 0
    for a in world.accounts.values():
        otype = a.owner_entity_type.value if hasattr(a.owner_entity_type, "value") else a.owner_entity_type
        if otype == "CUSTOMER" and a.owner_entity_id in world.customers:
            created = world.customers[a.owner_entity_id].created_at
            if a.opened_at < created:
                bad_acct += 1
        elif otype == "COMPANY" and a.owner_entity_id in world.companies:
            inc = world.companies[a.owner_entity_id].incorporation_date
            if a.opened_at.date() < inc:
                bad_acct += 1
    if bad_acct:
        result.fail(f"{bad_acct} accounts opened before owner entity existed")

    bad_kyc = 0
    for p in world.kyc_profiles.values():
        et = p.entity_type.value if hasattr(p.entity_type, "value") else p.entity_type
        if et == "CUSTOMER" and p.entity_id in world.customers:
            if p.last_reviewed_at < world.customers[p.entity_id].created_at:
                bad_kyc += 1
        elif et == "COMPANY" and p.entity_id in world.companies:
            inc = world.companies[p.entity_id].incorporation_date
            if p.last_reviewed_at.date() < inc:
                bad_kyc += 1
        if p.next_review_at < p.last_reviewed_at:
            result.fail(f"KYC {p.kyc_profile_id} next_review_at before last_reviewed_at")
    if bad_kyc:
        result.fail(f"{bad_kyc} KYC profiles reviewed before entity existed")


def _check_ownership_percentages(world: WorldState, result: ValidationResult) -> None:
    by_company: dict[str, list[float]] = defaultdict(list)
    incomplete_companies = set()
    for rel in world.relationships.values():
        if rel.relationship_type == "UNRESOLVED_UBO_CHAIN":
            incomplete_companies.add(rel.target_entity_id)

    for o in world.ownerships.values():
        if o.ownership_percentage <= 0 or o.ownership_percentage > 100:
            result.fail(
                f"Ownership {o.ownership_id} invalid percentage {o.ownership_percentage}"
            )
        if o.effective_to is None:
            by_company[o.owned_company_id].append(o.ownership_percentage)

    for cid, pcts in by_company.items():
        total = sum(pcts)
        if total > 100.15:
            result.fail(f"Company {cid} ownership sum {total:.2f} exceeds 100")
        elif total < 99.0 and total > 0 and cid not in incomplete_companies:
            # Incomplete chains (corporate-only shell) may sum to 100 via holding,
            # but holding itself may intentionally have 0 owners.
            result.warn(f"Company {cid} ownership sum {total:.2f} below 100")


def _check_ownership_evidence(world: WorldState, result: ValidationResult) -> None:
    for o in world.ownerships.values():
        if not o.verified:
            continue
        if not o.source_document_id:
            result.fail(f"Ownership {o.ownership_id} verified without document")
            continue
        doc = world.kyc_documents.get(o.source_document_id)
        if doc is None:
            result.fail(f"Ownership {o.ownership_id} verified doc missing")
            continue
        if doc.document_type not in ("UBO_DECLARATION", "ARTICLES_OF_ASSOCIATION"):
            result.fail(
                f"Ownership {o.ownership_id} verified with non-ownership doc type "
                f"{doc.document_type}"
            )


def _check_document_validity(world: WorldState, result: ValidationResult) -> None:
    world_end = world.config.world_end
    for d in world.kyc_documents.values():
        if d.expires_at is not None and d.expires_at < d.issued_at:
            result.fail(
                f"Document {d.document_id} expires_at < issued_at "
                f"({d.expires_at} < {d.issued_at})"
            )
        status = (
            d.verification_status.value
            if hasattr(d.verification_status, "value")
            else d.verification_status
        )
        if (
            d.expires_at is not None
            and d.expires_at < world_end.date()
            and status == VerificationStatus.VERIFIED.value
        ):
            result.fail(
                f"Document {d.document_id} expired at world_end but status=VERIFIED"
            )


def _check_shared_address(world: WorldState, result: ValidationResult) -> None:
    addr_of = {}
    for c in world.customers.values():
        addr_of[c.customer_id] = c.address_id
    for c in world.companies.values():
        addr_of[c.company_id] = c.registered_address_id
    bad = 0
    for rel in world.relationships.values():
        if rel.relationship_type != "SHARED_ADDRESS":
            continue
        a1 = addr_of.get(rel.source_entity_id)
        a2 = addr_of.get(rel.target_entity_id)
        if not a1 or not a2 or a1 != a2:
            bad += 1
    if bad:
        result.fail(f"{bad} SHARED_ADDRESS relationships do not share address_id")


def _check_transaction_amounts(world: WorldState, result: ValidationResult) -> None:
    for t in world.transactions.values():
        if t.amount <= 0:
            result.fail(f"Txn {t.transaction_id} non-positive amount {t.amount}")


def _check_no_system_float(world: WorldState, result: ValidationResult) -> None:
    if "ACCT-SYSTEM-FLOAT-001" in world.accounts or "ACCT-SYSTEM-FLOAT-001" in world.demo_accounts:
        result.fail("SYSTEM float account must not be present in generated world")
    for t in world.transactions.values():
        if "SYSTEM" in t.source_account_id or "SYSTEM" in t.destination_account_id:
            result.fail(f"Txn {t.transaction_id} involves SYSTEM account")
            break
        if "SYSTEM-FLOAT" in (t.description or "").upper():
            result.fail(f"Txn {t.transaction_id} is system-float funding noise")
            break


def _check_profile_initial_balances(world: WorldState, result: ValidationResult) -> None:
    for account in world.accounts.values():
        profile = account.behavioral_profile
        if profile is None or profile not in PROFILE_SPECS:
            result.fail(f"Account {account.account_id} missing behavioral profile")
            continue
        spec = PROFILE_SPECS[profile]
        if not (spec.initial_balance_min <= account.initial_balance <= spec.initial_balance_max):
            result.fail(
                f"Account {account.account_id} initial_balance {account.initial_balance} "
                f"outside profile range [{spec.initial_balance_min}, {spec.initial_balance_max}]"
            )


def _check_balances(world: WorldState, result: ValidationResult) -> None:
    """Strict ledger replay: initial_balance + transactions must never go illegal-negative."""
    balances: dict[str, int] = {}
    for a in world.accounts.values():
        balances[a.account_id] = a.initial_balance
    for a in world.demo_accounts.values():
        balances[a.account_id] = a.initial_balance

    txns = sorted(
        world.transactions.values(),
        key=lambda t: (t.occurred_at, t.transaction_id),
    )
    neg_events = 0
    for t in txns:
        src = t.source_account_id
        dst = t.destination_account_id
        if src not in balances:
            balances[src] = 0
        if dst not in balances:
            balances[dst] = 0
        balances[src] -= t.amount
        balances[dst] += t.amount
        acc = world.get_account(src)
        if acc is None:
            continue
        if acc.allow_overdraft:
            if balances[src] < -acc.overdraft_limit:
                neg_events += 1
                if neg_events <= 5:
                    result.fail(
                        f"Replay overdraft exceeded for {src} at {t.transaction_id}: "
                        f"{balances[src]}"
                    )
        elif balances[src] < 0:
            neg_events += 1
            if neg_events <= 5:
                result.fail(
                    f"Replay negative balance for {src} at {t.transaction_id}: "
                    f"{balances[src]}"
                )
    if neg_events > 5:
        result.fail(f"... and {neg_events - 5} more ledger negative events")


def _check_normal_cross_border_mix(world: WorldState, result: ValidationResult) -> None:
    cross_border = [
        world.transactions[txn_id]
        for txn_id in world.normal_transaction_ids
        if world.transactions[txn_id].is_cross_border
    ]
    if not cross_border:
        result.warn("Normal transaction set has no cross-border activity")
        return
    high_risk = sum(
        txn.destination_bank_id == world.config.high_risk_foreign_bank_id
        for txn in cross_border
    )
    if high_risk / len(cross_border) >= 0.10:
        result.fail(
            "At least 10% of normal cross-border traffic targets the scenario high-risk bank"
        )


def _check_ground_truth_tx_ids(world: WorldState, result: ValidationResult) -> None:
    tx_ids = set(world.transactions)
    for sc in world.scenarios.values():
        for tid in sc.suspicious_transaction_ids:
            if tid not in tx_ids:
                result.fail(
                    f"Scenario {sc.scenario_id} suspicious_transaction_id missing: {tid}"
                )
        for aid in sc.involved_account_ids:
            if aid not in world.accounts and aid not in world.demo_accounts:
                result.fail(
                    f"Scenario {sc.scenario_id} involved_account missing: {aid}"
                )


def _check_screening_dependencies(world: WorldState, result: ValidationResult) -> None:
    entity_ids = (
        set(world.customers)
        | set(world.companies)
        | {bank.bank_entity_id for bank in world.banks.values()}
    )
    for entry in world.watchlist.values():
        if entry.screening_dependency != "unavailable":
            continue
        if not entry.related_entity_id:
            result.fail(
                f"Watchlist dependency {entry.watchlist_id} unavailable without related entity"
            )
        elif entry.related_entity_id not in entity_ids:
            result.fail(
                f"Watchlist dependency {entry.watchlist_id} related entity missing: "
                f"{entry.related_entity_id}"
            )


def _check_feature_columns_clean(result: ValidationResult) -> None:
    for colset, name in (
        (CUSTOMER_FEATURE_COLUMNS, "customers"),
        (COMPANY_FEATURE_COLUMNS, "companies"),
        (ACCOUNT_FEATURE_COLUMNS, "accounts"),
        (TRANSACTION_FEATURE_COLUMNS, "transactions"),
    ):
        bad = set(colset) & GROUND_TRUTH_FORBIDDEN_COLUMNS
        if bad:
            result.fail(f"Feature table {name} contains ground-truth columns: {bad}")


def assert_valid(world: WorldState) -> None:
    res = validate_world(world)
    if not res.ok:
        msg = "Validation failed:\n" + "\n".join(f"  - {e}" for e in res.errors[:40])
        if len(res.errors) > 40:
            msg += f"\n  ... and {len(res.errors) - 40} more"
        raise ValueError(msg)
