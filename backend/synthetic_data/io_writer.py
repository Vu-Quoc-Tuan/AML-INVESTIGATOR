"""Write generated tables to CSV / JSONL / JSON and compute checksums."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from synthetic_data.models import (
    ACCOUNT_FEATURE_COLUMNS,
    COMPANY_FEATURE_COLUMNS,
    CUSTOMER_FEATURE_COLUMNS,
    TRANSACTION_FEATURE_COLUMNS,
    Account,
    Company,
    Customer,
    Transaction,
)
from synthetic_data.world import WorldState


def _serialize_value(v: Any) -> Any:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    return v


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(columns),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _serialize_value(row.get(c)) for c in columns})
    return sha256_file(path)


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, default=str, sort_keys=True))
            f.write("\n")
    return sha256_file(path)


def _write_json(path: Path, data: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str, sort_keys=True)
        f.write("\n")
    return sha256_file(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _model_dump(obj) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return dict(obj)


def customer_feature_row(c: Customer) -> dict[str, Any]:
    d = _model_dump(c)
    return {k: d[k] for k in CUSTOMER_FEATURE_COLUMNS}


def company_feature_row(c: Company) -> dict[str, Any]:
    d = _model_dump(c)
    return {k: d[k] for k in COMPANY_FEATURE_COLUMNS}


def account_feature_row(a: Account) -> dict[str, Any]:
    d = _model_dump(a)
    return {k: d[k] for k in ACCOUNT_FEATURE_COLUMNS}


def transaction_feature_row(t: Transaction) -> dict[str, Any]:
    d = _model_dump(t)
    return {k: d[k] for k in TRANSACTION_FEATURE_COLUMNS}


def write_world(world: WorldState, output_dir: Path | None = None) -> dict[str, str]:
    """Persist all tables. Returns map of filename -> sha256."""
    out = Path(output_dir or world.config.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    checksums: dict[str, str] = {}

    # Deterministic ordering by ID
    customers = [customer_feature_row(world.customers[k]) for k in sorted(world.customers)]
    companies = [company_feature_row(world.companies[k]) for k in sorted(world.companies)]
    accounts = [account_feature_row(world.accounts[k]) for k in sorted(world.accounts)]
    # Include demo accounts in accounts.csv for graph integrity
    for k in sorted(world.demo_accounts):
        accounts.append(account_feature_row(world.demo_accounts[k]))
    transactions = [
        transaction_feature_row(world.transactions[k]) for k in sorted(world.transactions)
    ]

    ownership_cols = (
        "ownership_id", "owner_entity_id", "owner_entity_type", "owned_company_id",
        "ownership_percentage", "effective_from", "effective_to", "source_document_id",
        "verified",
    )
    ownerships = [
        _model_dump(world.ownerships[k]) for k in sorted(world.ownerships)
    ]

    rel_cols = (
        "relationship_id", "source_entity_id", "target_entity_id", "relationship_type",
        "valid_from", "valid_to", "source", "confidence",
    )
    relationships = [
        _model_dump(world.relationships[k]) for k in sorted(world.relationships)
    ]

    checksums["customers.csv"] = _write_csv(
        out / "customers.csv", customers, CUSTOMER_FEATURE_COLUMNS
    )
    checksums["companies.csv"] = _write_csv(
        out / "companies.csv", companies, COMPANY_FEATURE_COLUMNS
    )
    checksums["accounts.csv"] = _write_csv(
        out / "accounts.csv", accounts, ACCOUNT_FEATURE_COLUMNS
    )
    checksums["transactions.csv"] = _write_csv(
        out / "transactions.csv", transactions, TRANSACTION_FEATURE_COLUMNS
    )
    checksums["company_ownership.csv"] = _write_csv(
        out / "company_ownership.csv", ownerships, ownership_cols
    )
    checksums["entity_relationships.csv"] = _write_csv(
        out / "entity_relationships.csv", relationships, rel_cols
    )

    kyc_profiles = [
        _model_dump(world.kyc_profiles[k]) for k in sorted(world.kyc_profiles)
    ]
    kyc_docs = [
        _model_dump(world.kyc_documents[k]) for k in sorted(world.kyc_documents)
    ]
    watchlist = [
        _model_dump(world.watchlist[k]) for k in sorted(world.watchlist)
    ]
    checksums["kyc_profiles.jsonl"] = _write_jsonl(out / "kyc_profiles.jsonl", kyc_profiles)
    checksums["kyc_documents.jsonl"] = _write_jsonl(out / "kyc_documents.jsonl", kyc_docs)
    checksums["watchlist_entries.jsonl"] = _write_jsonl(
        out / "watchlist_entries.jsonl", watchlist
    )

    scenarios = [
        _model_dump(world.scenarios[k]) for k in sorted(world.scenarios)
    ]
    checksums["ground_truth_scenarios.json"] = _write_json(
        out / "ground_truth_scenarios.json", scenarios
    )

    # Addresses helper (optional but useful)
    addresses = [_model_dump(world.addresses[k]) for k in sorted(world.addresses)]
    addr_cols = (
        "address_id", "line1", "ward", "district", "city", "country", "postal_code",
    )
    checksums["addresses.csv"] = _write_csv(out / "addresses.csv", addresses, addr_cols)

    banks = [_model_dump(world.banks[k]) for k in sorted(world.banks)]
    bank_cols = (
        "bank_id", "bank_entity_id", "legal_name", "country", "risk_score",
        "is_demo", "bank_type",
    )
    checksums["banks.csv"] = _write_csv(out / "banks.csv", banks, bank_cols)

    if world.config.write_manifest:
        manifest = {
            "config": world.config.to_dict(),
            "counts": {
                "customers": len(world.customers),
                "companies": len(world.companies),
                "accounts": len(world.accounts) + len(world.demo_accounts),
                "normal_transactions": len(world.normal_transaction_ids),
                "transactions": len(world.transactions),
                "banks": len(world.banks),
                "kyc_profiles": len(world.kyc_profiles),
                "kyc_documents": len(world.kyc_documents),
                "ownerships": len(world.ownerships),
                "relationships": len(world.relationships),
                "watchlist": len(world.watchlist),
                "scenarios": len(world.scenarios),
            },
            "checksums_sha256": checksums,
        }
        checksums["manifest.json"] = _write_json(out / "manifest.json", manifest)

    return checksums
