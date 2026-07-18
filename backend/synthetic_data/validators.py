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
    EXTERNAL_ACCOUNT_FEATURE_COLUMNS,
    TRANSACTION_FEATURE_COLUMNS,
    AccountReferenceType,
    DataVisibility,
    EntityType,
    TransactionDirection,
    VerificationStatus,
)
from synthetic_data.profiles import PROFILE_SPECS
from synthetic_data.ledger import strict_replay_ok
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
    _check_normal_direction_mix(world, result)
    _check_external_seen_bounds(world, result)
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
    total_accounts = len(world.accounts)
    if total_accounts < cfg.min_accounts:
        result.fail(
            f"Account count {total_accounts} below min_accounts {cfg.min_accounts}"
        )
    if total_accounts > cfg.max_accounts:
        result.fail(
            f"Account count {total_accounts} above max_accounts {cfg.max_accounts}"
        )
    if len(world.external_accounts) != cfg.n_external_accounts:
        result.fail(
            f"External account count {len(world.external_accounts)} != configured "
            f"{cfg.n_external_accounts}"
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
        ("account", world.accounts.keys()),
        ("external_account", world.external_accounts.keys()),
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
    entity_ids = customer_ids | company_ids
    address_ids = set(world.addresses)
    account_ids = set(world.accounts)
    external_account_ids = set(world.external_accounts)
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

    home_banks = [bank.bank_id for bank in world.banks.values() if bank.is_home_bank]
    if home_banks != [world.config.home_bank_id]:
        result.fail(f"Expected one SHB home bank, got {home_banks}")

    for a in world.accounts.values():
        otype = a.owner_entity_type.value if hasattr(a.owner_entity_type, "value") else a.owner_entity_type
        if otype == "CUSTOMER" and a.owner_entity_id not in customer_ids:
            result.fail(f"Account {a.account_id} owner customer missing")
        if otype == "COMPANY" and a.owner_entity_id not in company_ids:
            result.fail(f"Account {a.account_id} owner company missing")
        if a.bank_id not in bank_ids:
            result.fail(f"Account {a.account_id} bank_id not in catalog: {a.bank_id}")
        if a.bank_id != world.config.home_bank_id:
            result.fail(f"Internal account {a.account_id} is not owned by SHB")

    for external in world.external_accounts.values():
        if external.bank_id not in bank_ids:
            result.fail(f"External account {external.account_id} bank_id missing")
        if external.bank_id == world.config.home_bank_id:
            result.fail(f"External account {external.account_id} uses home bank")
        if external.account_id in world.balances:
            result.fail(f"External account {external.account_id} has an internal balance")

    for t in world.transactions.values():
        source_ids = account_ids if t.source_account_type == AccountReferenceType.INTERNAL_SHB else external_account_ids
        destination_ids = account_ids if t.destination_account_type == AccountReferenceType.INTERNAL_SHB else external_account_ids
        if t.source_account_ref not in source_ids:
            result.fail(f"Txn {t.transaction_id} source account missing")
        if t.destination_account_ref not in destination_ids:
            result.fail(f"Txn {t.transaction_id} dest account missing")
        if t.source_bank_id not in bank_ids:
            result.fail(f"Txn {t.transaction_id} source_bank_id missing from catalog")
        if t.destination_bank_id not in bank_ids:
            result.fail(f"Txn {t.transaction_id} destination_bank_id missing from catalog")
        src = world.get_account_reference(t.source_account_ref)
        dst = world.get_account_reference(t.destination_account_ref)
        if src is not None and t.source_bank_id != src.bank_id:
            result.fail(f"Txn {t.transaction_id} source_bank_id mismatches source account")
        if dst is not None and t.destination_bank_id != dst.bank_id:
            result.fail(f"Txn {t.transaction_id} destination_bank_id mismatches destination account")
        if dst is not None and dst.bank_id in world.banks:
            expected_country = world.banks[dst.bank_id].country_code
            if t.destination_country != expected_country:
                result.fail(
                    f"Txn {t.transaction_id} destination_country {t.destination_country} "
                    f"!= destination bank country {expected_country}"
                )
        if src is not None and dst is not None:
            src_country = world.banks[src.bank_id].country_code
            dst_country = world.banks[dst.bank_id].country_code
            if t.is_cross_border != (src_country != dst_country):
                result.fail(
                    f"Txn {t.transaction_id} cross-border flag inconsistent with bank countries"
                )
        topology = (t.source_account_type, t.destination_account_type)
        expected_direction = {
            (AccountReferenceType.INTERNAL_SHB, AccountReferenceType.INTERNAL_SHB): TransactionDirection.INTERNAL,
            (AccountReferenceType.EXTERNAL, AccountReferenceType.INTERNAL_SHB): TransactionDirection.INBOUND,
            (AccountReferenceType.INTERNAL_SHB, AccountReferenceType.EXTERNAL): TransactionDirection.OUTBOUND,
        }.get(topology)
        if expected_direction is None or t.direction != expected_direction:
            result.fail(f"Txn {t.transaction_id} has invalid SHB topology/direction")
        if t.direction == TransactionDirection.INBOUND and (t.source_ip or t.device_id):
            result.fail(f"Inbound txn {t.transaction_id} has external device/IP")
        if t.direction == TransactionDirection.INTERNAL and t.data_visibility != DataVisibility.FULL_INTERNAL:
            result.fail(f"Internal txn {t.transaction_id} lacks full visibility")

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
        src = world.get_account(t.source_account_ref)
        dst = world.get_account(t.destination_account_ref)
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
    if "ACCT-SYSTEM-FLOAT-001" in world.accounts or "ACCT-SYSTEM-FLOAT-001" in world.external_accounts:
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
    errors = strict_replay_ok(world)
    for error in errors[:5]:
        result.fail(f"Replay negative balance for {error}")
    if len(errors) > 5:
        result.fail(f"... and {len(errors) - 5} more ledger negative events")


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


def _check_normal_direction_mix(world: WorldState, result: ValidationResult) -> None:
    ratios = {
        TransactionDirection.INTERNAL: world.config.internal_transaction_ratio,
        TransactionDirection.INBOUND: world.config.inbound_transaction_ratio,
        TransactionDirection.OUTBOUND: world.config.outbound_transaction_ratio,
    }
    raw = {
        direction: world.config.n_transactions * ratio
        for direction, ratio in ratios.items()
    }
    expected = {direction: int(value) for direction, value in raw.items()}
    remainder = world.config.n_transactions - sum(expected.values())
    order = sorted(
        ratios,
        key=lambda direction: (
            raw[direction] - expected[direction],
            direction.value,
        ),
        reverse=True,
    )
    for direction in order[:remainder]:
        expected[direction] += 1
    actual = {direction: 0 for direction in TransactionDirection}
    for transaction_id in world.normal_transaction_ids:
        actual[world.transactions[transaction_id].direction] += 1
    if actual != expected:
        result.fail(f"Normal direction counts {actual} != expected {expected}")


def _check_external_seen_bounds(world: WorldState, result: ValidationResult) -> None:
    observations: dict[str, list[datetime]] = defaultdict(list)
    for transaction in world.transactions.values():
        if transaction.source_account_type == AccountReferenceType.EXTERNAL:
            observations[transaction.source_account_ref].append(transaction.occurred_at)
        if transaction.destination_account_type == AccountReferenceType.EXTERNAL:
            observations[transaction.destination_account_ref].append(transaction.occurred_at)
    external_capacity = round(
        world.config.n_transactions
        * (
            world.config.inbound_transaction_ratio
            + world.config.outbound_transaction_ratio
        )
    )
    require_all_observed = external_capacity >= len(world.external_accounts)
    for account_id, account in world.external_accounts.items():
        timestamps = observations.get(account_id, [])
        if not timestamps:
            if require_all_observed:
                result.fail(f"External account {account_id} is never observed by SHB")
            continue
        if account.first_seen_at != min(timestamps):
            result.fail(f"External account {account_id} first_seen_at mismatch")
        if account.last_seen_at != max(timestamps):
            result.fail(f"External account {account_id} last_seen_at mismatch")


def _check_ground_truth_tx_ids(world: WorldState, result: ValidationResult) -> None:
    tx_ids = set(world.transactions)
    for sc in world.scenarios.values():
        for tid in sc.suspicious_transaction_ids:
            if tid not in tx_ids:
                result.fail(
                    f"Scenario {sc.scenario_id} suspicious_transaction_id missing: {tid}"
                )
        for aid in sc.involved_account_ids:
            if aid not in world.accounts and aid not in world.external_accounts:
                result.fail(
                    f"Scenario {sc.scenario_id} involved_account missing: {aid}"
                )
        if not set(sc.internal_account_ids) <= set(world.accounts):
            result.fail(f"Scenario {sc.scenario_id} has non-SHB internal account IDs")
        if not set(sc.external_account_ids) <= set(world.external_accounts):
            result.fail(f"Scenario {sc.scenario_id} has invalid external account IDs")
        if not sc.observable_internal_facts:
            result.fail(f"Scenario {sc.scenario_id} has no observable internal facts")


def _check_screening_dependencies(world: WorldState, result: ValidationResult) -> None:
    entity_ids = set(world.customers) | set(world.companies)
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
        (EXTERNAL_ACCOUNT_FEATURE_COLUMNS, "external_accounts"),
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
