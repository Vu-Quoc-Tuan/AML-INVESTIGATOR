"""Unit tests for synthetic banking data generator."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import timedelta
import pytest

from synthetic_data.config import GROUND_TRUTH_FORBIDDEN_COLUMNS, GeneratorConfig
from synthetic_data.io_writer import write_world
from synthetic_data.models import (
    ACCOUNT_FEATURE_COLUMNS,
    COMPANY_FEATURE_COLUMNS,
    CUSTOMER_FEATURE_COLUMNS,
    TRANSACTION_FEATURE_COLUMNS,
    VerificationStatus,
)
from synthetic_data.pipeline import generate_world
from synthetic_data.profiles import PROFILE_SPECS
from synthetic_data.validators import validate_world


@pytest.fixture(scope="module")
def small_world(tmp_path_factory):
    out = tmp_path_factory.mktemp("syn")
    cfg = GeneratorConfig(
        random_seed=42,
        n_customers=80,
        n_companies=12,
        n_transactions=1200,
        n_external_accounts=500,
        min_accounts=100,
        max_accounts=220,
        output_dir=out,
        run_validation=True,
    )
    world = generate_world(cfg, write=True)
    return world, out


def test_exact_quotas(small_world):
    world, _ = small_world
    assert len(world.customers) == 80
    assert len(world.companies) == 12
    total_accounts = len(world.accounts)
    assert 100 <= total_accounts <= 220


def test_shb_boundary_models(small_world):
    world, _ = small_world
    assert world.config.home_bank_id == "BANK-SHB-001"
    assert len(world.external_accounts) == world.config.n_external_accounts
    assert all(
        account.bank_id == world.config.home_bank_id
        for account in world.accounts.values()
    )
    assert not (set(world.external_accounts) & set(world.balances))
    assert all(
        account.external_account_id.startswith("EXT-ACC-")
        for account in world.external_accounts.values()
    )


def test_invalid_external_count_rejected():
    with pytest.raises(ValueError, match="n_external_accounts"):
        GeneratorConfig(n_external_accounts=499).validate()


def test_single_normal_transaction_uses_consistent_quota_rounding(tmp_path):
    config = GeneratorConfig(
        random_seed=3,
        n_customers=20,
        n_companies=5,
        n_transactions=1,
        n_external_accounts=500,
        min_accounts=25,
        max_accounts=60,
        n_suspicious_scenarios=0,
        n_lookalike_scenarios=0,
        inject_incomplete_evidence=False,
        output_dir=tmp_path,
    )
    world = generate_world(config, write=False)
    transaction = world.transactions[next(iter(world.normal_transaction_ids))]
    assert transaction.direction.value == "INTERNAL"


def test_validation_passes(small_world):
    world, _ = small_world
    res = validate_world(world)
    assert res.ok, res.errors


def test_no_duplicate_ids(small_world):
    world, _ = small_world
    assert len(world.customers) == len(set(world.customers))
    assert len(world.transactions) == len(set(world.transactions))


def test_transaction_amounts_positive(small_world):
    world, _ = small_world
    assert all(t.amount > 0 for t in world.transactions.values())


def test_no_negative_balance_without_overdraft(small_world):
    world, _ = small_world
    for aid, bal in world.balances.items():
        acc = world.get_account(aid)
        if acc and not acc.allow_overdraft:
            assert bal >= 0, (aid, bal)


def test_no_system_float(small_world):
    world, _ = small_world
    assert "ACCT-SYSTEM-FLOAT-001" not in world.external_accounts
    assert "ACCT-SYSTEM-FLOAT-001" not in world.accounts
    assert all("SYSTEM-FLOAT" not in t.description for t in world.transactions.values())


def test_banks_catalog_exported(small_world):
    world, out = small_world
    assert world.banks
    assert (out / "banks.csv").exists()
    text = (out / "banks.csv").read_text(encoding="utf-8")
    assert "BANK-FOREIGN-HR-88" in text
    assert "risk_score" in text


def test_single_home_bank_and_external_directory(small_world):
    world, _ = small_world
    home = [bank for bank in world.banks.values() if bank.is_home_bank]
    assert [bank.bank_id for bank in home] == ["BANK-SHB-001"]
    assert all(account.bank_id == "BANK-SHB-001" for account in world.accounts.values())
    assert all(
        account.bank_id != "BANK-SHB-001"
        for account in world.external_accounts.values()
    )


def test_external_accounts_have_no_internal_artifacts(small_world):
    world, _ = small_world
    external_ids = set(world.external_accounts)
    assert not (external_ids & set(world.entity_accounts))
    assert not (external_ids & set(world.entity_devices))
    assert not (external_ids & set(world.entity_ips))
    assert not (external_ids & set(world.balances))
    assert all(
        profile.entity_id not in external_ids
        for profile in world.kyc_profiles.values()
    )


def test_bank_account_and_transaction_fks_resolve(small_world):
    world, out = small_world
    bank_ids = set(world.banks)
    all_accounts = {**world.accounts, **world.external_accounts}

    assert "bank_id" in ACCOUNT_FEATURE_COLUMNS
    assert "bank_id" in (out / "accounts.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "is_home_bank" in (out / "banks.csv").read_text(encoding="utf-8").splitlines()[0]

    for account in world.accounts.values():
        assert account.bank_id in bank_ids
        assert account.owner_entity_id in world.customers or account.owner_entity_id in world.companies

    for txn in world.transactions.values():
        assert txn.source_bank_id == all_accounts[txn.source_account_ref].bank_id
        assert txn.destination_bank_id == all_accounts[txn.destination_account_ref].bank_id


def test_transaction_topologies_and_visibility(small_world):
    world, _ = small_world
    allowed = {
        ("INTERNAL_SHB", "INTERNAL_SHB", "INTERNAL"),
        ("EXTERNAL", "INTERNAL_SHB", "INBOUND"),
        ("INTERNAL_SHB", "EXTERNAL", "OUTBOUND"),
    }
    assert {
        (
            transaction.source_account_type.value,
            transaction.destination_account_type.value,
            transaction.direction.value,
        )
        for transaction in world.transactions.values()
    } <= allowed
    for transaction in world.transactions.values():
        if transaction.direction.value == "INBOUND":
            assert transaction.source_ip is None
            assert transaction.device_id is None
        if transaction.direction.value == "INTERNAL":
            assert transaction.data_visibility.value == "FULL_INTERNAL"


def test_exact_normal_direction_quotas(small_world):
    world, _ = small_world
    normal = [world.transactions[transaction_id] for transaction_id in world.normal_transaction_ids]
    assert Counter(transaction.direction.value for transaction in normal) == {
        "INTERNAL": 540,
        "INBOUND": 330,
        "OUTBOUND": 330,
    }


def test_normal_cross_border_uses_normal_foreign_counterparties(small_world):
    world, _ = small_world
    normal_xb = [
        world.transactions[tid]
        for tid in world.normal_transaction_ids
        if world.transactions[tid].is_cross_border
    ]
    assert normal_xb
    countries = {txn.destination_country for txn in normal_xb}
    assert countries & {"SG", "US", "JP", "KR", "CN", "DE"}
    high_risk = sum(
        txn.destination_bank_id == world.config.high_risk_foreign_bank_id
        for txn in normal_xb
    )
    assert high_risk / len(normal_xb) < 0.10


def test_unavailable_screening_is_linked_to_incomplete_entity(small_world):
    world, _ = small_world
    incomplete = next(
        scenario
        for scenario in world.scenarios.values()
        if scenario.notes.get("scenario_key") == "INCOMPLETE_EVIDENCE_PASS_THROUGH"
    )
    unavailable = [
        entry
        for entry in world.watchlist.values()
        if entry.screening_dependency == "unavailable"
    ]
    assert unavailable
    assert all(entry.related_entity_id in incomplete.involved_entity_ids for entry in unavailable)


def test_initial_balances_stay_within_behavioral_profile(small_world):
    world, _ = small_world
    for account in world.accounts.values():
        spec = PROFILE_SPECS[account.behavioral_profile]
        assert account.initial_balance <= spec.initial_balance_max, account.account_id


def test_ground_truth_tx_ids_exist(small_world):
    world, _ = small_world
    tx = set(world.transactions)
    for sc in world.scenarios.values():
        for tid in sc.suspicious_transaction_ids:
            assert tid in tx


def test_feature_columns_exclude_ground_truth():
    for cols in (
        CUSTOMER_FEATURE_COLUMNS,
        COMPANY_FEATURE_COLUMNS,
        ACCOUNT_FEATURE_COLUMNS,
        TRANSACTION_FEATURE_COLUMNS,
    ):
        assert not (set(cols) & GROUND_TRUTH_FORBIDDEN_COLUMNS)


def test_feature_files_have_no_label_columns(small_world):
    _, out = small_world
    import csv

    for name in ("customers.csv", "companies.csv", "accounts.csv", "transactions.csv"):
        with (out / name).open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fields = set(reader.fieldnames or [])
            assert not (fields & GROUND_TRUTH_FORBIDDEN_COLUMNS), name


def test_ownership_percentage_bounds(small_world):
    world, _ = small_world
    for o in world.ownerships.values():
        assert 0 < o.ownership_percentage <= 100


def test_document_validity_and_status(small_world):
    world, _ = small_world
    world_end = world.config.world_end.date()
    for d in world.kyc_documents.values():
        if d.expires_at is not None:
            assert d.expires_at >= d.issued_at
            if d.expires_at < world_end:
                status = (
                    d.verification_status.value
                    if hasattr(d.verification_status, "value")
                    else d.verification_status
                )
                assert status != VerificationStatus.VERIFIED.value


def test_account_not_before_owner(small_world):
    world, _ = small_world
    for a in world.accounts.values():
        otype = a.owner_entity_type.value if hasattr(a.owner_entity_type, "value") else a.owner_entity_type
        if otype == "CUSTOMER":
            assert a.opened_at >= world.customers[a.owner_entity_id].created_at
        elif otype == "COMPANY":
            assert a.opened_at.date() >= world.companies[a.owner_entity_id].incorporation_date


def test_shared_address_real(small_world):
    world, _ = small_world
    addr = {c.customer_id: c.address_id for c in world.customers.values()}
    for rel in world.relationships.values():
        if rel.relationship_type != "SHARED_ADDRESS":
            continue
        assert addr[rel.source_entity_id] == addr[rel.target_entity_id]


def test_fk_account_owner(small_world):
    world, _ = small_world
    for a in world.accounts.values():
        if a.owner_entity_type.value == "CUSTOMER":
            assert a.owner_entity_id in world.customers
        elif a.owner_entity_type.value == "COMPANY":
            assert a.owner_entity_id in world.companies


def test_rapid_fan_in_scenario_present(small_world):
    world, _ = small_world
    keys = [sc.notes.get("scenario_key") for sc in world.scenarios.values()]
    assert "RAPID_FAN_IN_PASS_THROUGH" in keys
    assert "EVENT_COLLECTION" in keys
    assert "INCOMPLETE_EVIDENCE_PASS_THROUGH" in keys


def test_hybrid_rapid_fan_in(small_world):
    world, _ = small_world
    scenario = next(
        item
        for item in world.scenarios.values()
        if item.notes["scenario_key"] == "RAPID_FAN_IN_PASS_THROUGH"
    )
    assert len(scenario.internal_account_ids) == 7
    assert len(scenario.external_account_ids) == 6
    fan_in = [
        world.transactions[transaction_id]
        for transaction_id in scenario.suspicious_transaction_ids
        if world.transactions[transaction_id].purpose_code == "FAN_IN"
    ]
    assert sum(
        transaction.source_account_type.value == "INTERNAL_SHB"
        for transaction in fan_in
    ) == 6
    assert sum(
        transaction.source_account_type.value == "EXTERNAL"
        for transaction in fan_in
    ) == 4
    assert max(item.occurred_at for item in fan_in) - min(
        item.occurred_at for item in fan_in
    ) <= timedelta(minutes=5)
    outbound = next(
        world.transactions[transaction_id]
        for transaction_id in scenario.suspicious_transaction_ids
        if world.transactions[transaction_id].purpose_code == "PASS_THROUGH"
    )
    assert outbound.occurred_at - max(
        item.occurred_at for item in fan_in
    ) == timedelta(seconds=121)
    assert outbound.amount == int(sum(item.amount for item in fan_in) * 0.992)


def test_rapid_fan_in_company_has_full_verified_kyc_and_ubo(small_world):
    world, _ = small_world
    scenario = next(
        item
        for item in world.scenarios.values()
        if item.notes["scenario_key"] == "RAPID_FAN_IN_PASS_THROUGH"
    )
    company_account = next(
        world.accounts[account_id]
        for account_id in scenario.internal_account_ids
        if world.accounts[account_id].owner_entity_type.value == "COMPANY"
    )
    company_id = company_account.owner_entity_id
    assert any(
        profile.entity_id == company_id
        for profile in world.kyc_profiles.values()
    )
    company_documents = [
        document
        for document in world.kyc_documents.values()
        if document.entity_id == company_id
    ]
    for required_type in ("BUSINESS_LICENSE", "UBO_DECLARATION"):
        matching = [
            document
            for document in company_documents
            if document.document_type == required_type
        ]
        assert matching
        assert any(
            document.verification_status.value == "VERIFIED"
            for document in matching
        )
    ownerships = [
        ownership
        for ownership in world.ownerships.values()
        if ownership.owned_company_id == company_id
    ]
    assert ownerships
    assert round(sum(item.ownership_percentage for item in ownerships), 2) == 100.0
    assert all(
        item.verified
        and item.source_document_id in world.kyc_documents
        for item in ownerships
    )
    assert not any(
        relationship.target_entity_id == company_id
        and relationship.relationship_type == "UNRESOLVED_UBO_CHAIN"
        for relationship in world.relationships.values()
    )
    assert any(
        company_account.account_id
        in (transaction.source_account_ref, transaction.destination_account_ref)
        and transaction.transaction_id not in scenario.suspicious_transaction_ids
        for transaction in world.transactions.values()
    )


def test_ground_truth_visibility_isolated(small_world):
    world, _ = small_world
    assert all(scenario.observable_internal_facts for scenario in world.scenarios.values())
    forbidden = {
        "observable_internal_facts",
        "observable_external_facts",
        "hidden_world_facts",
    }
    assert not (forbidden & set(TRANSACTION_FEATURE_COLUMNS))


def test_shb_centric_files_and_manifest(small_world):
    world, out = small_world
    external_header = (out / "external_accounts.csv").read_text().splitlines()[0]
    transaction_header = (out / "transactions.csv").read_text().splitlines()[0]
    assert "external_account_id" in external_header
    assert "source_account_type" in transaction_header
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["counts"]["external_accounts"] == len(world.external_accounts)
    assert "external_accounts.csv" in manifest["checksums_sha256"]


def test_all_external_seen_bounds_match_transactions(small_world):
    world, _ = small_world
    for external in world.external_accounts.values():
        observed = [
            transaction.occurred_at
            for transaction in world.transactions.values()
            if external.external_account_id
            in (transaction.source_account_ref, transaction.destination_account_ref)
        ]
        assert observed, external.external_account_id
        assert external.first_seen_at == min(observed)
        assert external.last_seen_at == max(observed)


def test_incomplete_evidence_not_no_match(small_world):
    world, _ = small_world
    for sc in world.scenarios.values():
        if sc.notes.get("scenario_key") == "INCOMPLETE_EVIDENCE_PASS_THROUGH":
            assert sc.expected_case_disposition.value != "NO_MATCH"
            assert sc.expected_case_disposition.value in (
                "NEED_MORE_EVIDENCE",
                "MANUAL_REVIEW_REQUIRED",
            )
            assert sc.notes.get("forbid_disposition") == "NO_MATCH"


def test_scenario_count_config_respected(tmp_path):
    cfg = GeneratorConfig(
        random_seed=7,
        n_customers=60,
        n_companies=10,
        n_transactions=400,
        min_accounts=80,
        max_accounts=160,
        n_suspicious_scenarios=1,
        n_lookalike_scenarios=1,
        inject_incomplete_evidence=False,
        output_dir=tmp_path,
        run_validation=True,
    )
    world = generate_world(cfg, write=False)
    assert len(world.scenarios) == 2


def test_transaction_type_diversity(small_world):
    world, _ = small_world
    types = {t.transaction_type for t in world.transactions.values()}
    # Must not collapse almost entirely to a single type in code paths
    assert len(types) >= 2


def test_seed_reproducibility(tmp_path):
    cfg1 = GeneratorConfig(
        random_seed=99,
        n_customers=40,
        n_companies=8,
        n_transactions=400,
        min_accounts=55,
        max_accounts=120,
        output_dir=tmp_path / "a",
    )
    cfg2 = GeneratorConfig(
        random_seed=99,
        n_customers=40,
        n_companies=8,
        n_transactions=400,
        min_accounts=55,
        max_accounts=120,
        output_dir=tmp_path / "b",
    )
    w1 = generate_world(cfg1, write=True)
    w2 = generate_world(cfg2, write=True)
    c1 = write_world(w1, tmp_path / "a")
    c2 = write_world(w2, tmp_path / "b")
    for key in (
        "customers.csv",
        "companies.csv",
        "accounts.csv",
        "external_accounts.csv",
        "transactions.csv",
        "banks.csv",
        "ground_truth_scenarios.json",
    ):
        assert c1[key] == c2[key], key


def test_different_seed_different_output(tmp_path):
    cfg1 = GeneratorConfig(
        random_seed=1,
        n_customers=30,
        n_companies=6,
        n_transactions=250,
        min_accounts=40,
        max_accounts=90,
        output_dir=tmp_path / "s1",
    )
    cfg2 = GeneratorConfig(
        random_seed=2,
        n_customers=30,
        n_companies=6,
        n_transactions=250,
        min_accounts=40,
        max_accounts=90,
        output_dir=tmp_path / "s2",
    )
    generate_world(cfg1, write=True)
    generate_world(cfg2, write=True)
    c1 = (tmp_path / "s1" / "customers.csv").read_bytes()
    c2 = (tmp_path / "s2" / "customers.csv").read_bytes()
    assert hashlib.sha256(c1).hexdigest() != hashlib.sha256(c2).hexdigest()
