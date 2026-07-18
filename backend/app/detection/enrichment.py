"""Read-only static enrichment for realtime rule and model features."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.streaming.schemas import TransactionEventV1


_RISK_LEVEL = {"LOW": 0.0, "MEDIUM": 1.0, "HIGH": 2.0}


class StaticEnrichmentProvider:
    """Load generated reference data once, then enrich events without I/O."""

    def __init__(self, data_path: Path) -> None:
        self.data_path = Path(data_path)
        self.accounts = self._csv("accounts.csv", "account_id")
        self.external_accounts = self._csv(
            "external_accounts.csv", "external_account_id"
        )
        self.customers = self._csv("customers.csv", "customer_id")
        self.companies = self._csv("companies.csv", "company_id")
        self.banks = self._csv("banks.csv", "bank_id")
        self.profiles = self._jsonl("kyc_profiles.jsonl", "entity_id")

    def __call__(self, event: TransactionEventV1) -> dict[str, Any]:
        source = self._party(event.source_account_ref, event.occurred_at)
        destination = self._party(event.destination_account_ref, event.occurred_at)
        result: dict[str, Any] = {}
        self._prefix(result, "source", source)
        self._prefix(result, "dest", destination)

        is_cross_border = event.source_bank_id != event.destination_bank_id
        source_profile = self.profiles.get(source.get("owner_id", ""), {})
        destination_profile = self.profiles.get(destination.get("owner_id", ""), {})
        result["mismatch_cross_border_source"] = float(
            is_cross_border and not bool(source_profile.get("expected_cross_border"))
        )
        result["mismatch_cross_border_dest"] = float(
            is_cross_border and not bool(destination_profile.get("expected_cross_border"))
        )
        expected_outflow = _number(source_profile.get("expected_monthly_outflow"))
        expected_inflow = _number(destination_profile.get("expected_monthly_inflow"))
        result["amt_to_expected_outflow_ratio_source"] = (
            event.amount / expected_outflow if expected_outflow > 0 else 0.0
        )
        result["amt_to_expected_inflow_ratio_dest"] = (
            event.amount / expected_inflow if expected_inflow > 0 else 0.0
        )
        return result

    def _party(self, account_ref: str, occurred_at: datetime) -> dict[str, Any]:
        if account := self.accounts.get(account_ref):
            owner_id = account["owner_entity_id"]
            entity = self.customers.get(owner_id) or self.companies.get(owner_id) or {}
            is_company = account.get("owner_entity_type") == "COMPANY"
            born_at = entity.get("incorporation_date" if is_company else "date_of_birth")
            risk = entity.get("kyc_risk_level" if is_company else "customer_risk_level")
            income = entity.get(
                "expected_monthly_turnover" if is_company else "annual_income"
            )
            return {
                "owner_id": owner_id,
                "owner_type": float(is_company),
                "owner_age": _age_years(born_at, occurred_at),
                "owner_income": _number(income),
                "owner_risk": _RISK_LEVEL.get(str(risk).upper(), 0.0),
                "initial_balance": _number(account.get("initial_balance")),
                "account_age_days": _age_days(account.get("opened_at"), occurred_at),
                "bank_risk_score": _number(
                    self.banks.get(account.get("bank_id", ""), {}).get("risk_score")
                ),
            }

        if external := self.external_accounts.get(account_ref):
            raw_risk = _number(external.get("risk_score"))
            return {
                "owner_id": account_ref,
                "owner_type": float(external.get("counterparty_type") != "INDIVIDUAL"),
                "owner_age": 0.0,
                "owner_income": 0.0,
                "owner_risk": 2.0 if raw_risk > 0.5 else (1.0 if raw_risk > 0.15 else 0.0),
                "initial_balance": 0.0,
                "account_age_days": _age_days(external.get("first_seen_at"), occurred_at),
                "bank_risk_score": _number(
                    self.banks.get(external.get("bank_id", ""), {}).get("risk_score")
                ),
            }
        return {}

    @staticmethod
    def _prefix(target: dict[str, Any], prefix: str, party: dict[str, Any]) -> None:
        for name in (
            "owner_type", "owner_age", "owner_income", "owner_risk",
            "initial_balance", "account_age_days", "bank_risk_score",
        ):
            if name in party:
                target[f"{prefix}_{name}"] = party[name]

    def _csv(self, filename: str, key: str) -> dict[str, dict[str, str]]:
        path = self.data_path / filename
        if not path.is_file():
            raise FileNotFoundError(f"enrichment data file not found: {path}")
        with path.open(encoding="utf-8", newline="") as handle:
            return {row[key]: row for row in csv.DictReader(handle)}

    def _jsonl(self, filename: str, key: str) -> dict[str, dict[str, Any]]:
        path = self.data_path / filename
        if not path.is_file():
            raise FileNotFoundError(f"enrichment data file not found: {path}")
        with path.open(encoding="utf-8") as handle:
            rows = (json.loads(line) for line in handle if line.strip())
            return {row[key]: row for row in rows}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _age_days(value: Any, occurred_at: datetime) -> float:
    parsed = _parse_datetime(value)
    return float(max(0, (occurred_at - parsed).days)) if parsed else 0.0


def _age_years(value: Any, occurred_at: datetime) -> float:
    return _age_days(value, occurred_at) / 365.25
