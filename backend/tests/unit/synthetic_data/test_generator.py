"""Unit tests for synthetic banking data generator."""

from __future__ import annotations

import hashlib
from pathlib import Path

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
    total_accounts = len(world.accounts) + len(world.demo_accounts)
    assert 100 <= total_accounts <= 220


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
    assert "ACCT-SYSTEM-FLOAT-001" not in world.demo_accounts
    assert "ACCT-SYSTEM-FLOAT-001" not in world.accounts
    assert all("SYSTEM-FLOAT" not in t.description for t in world.transactions.values())


def test_banks_catalog_exported(small_world):
    world, out = small_world
    assert world.banks
    assert (out / "banks.csv").exists()
    text = (out / "banks.csv").read_text(encoding="utf-8")
    assert "BANK-FOREIGN-HR-88" in text
    assert "risk_score" in text


def test_bank_account_and_transaction_fks_resolve(small_world):
    world, out = small_world
    bank_entity_ids = {bank.bank_entity_id for bank in world.banks.values()}
    bank_ids = set(world.banks)
    all_accounts = {**world.accounts, **world.demo_accounts}

    assert len(bank_entity_ids) == len(world.banks)
    assert "bank_id" in ACCOUNT_FEATURE_COLUMNS
    assert "bank_id" in (out / "accounts.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "bank_entity_id" in (out / "banks.csv").read_text(encoding="utf-8").splitlines()[0]

    for account in all_accounts.values():
        assert account.bank_id in bank_ids
        if account.owner_entity_type.value == "BANK":
            assert account.owner_entity_id in bank_entity_ids

    for txn in world.transactions.values():
        assert txn.source_bank_id == all_accounts[txn.source_account_id].bank_id
        assert txn.destination_bank_id == all_accounts[txn.destination_account_id].bank_id


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
