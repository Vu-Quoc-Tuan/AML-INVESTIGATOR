"""Pandas/NetworkX data-access layer for the SHB-centric synthetic dataset."""

from __future__ import annotations

import json
import math
import unicodedata
from copy import deepcopy
from collections.abc import Collection, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from .config import RepositoryConfig
from .exceptions import DataFileNotFoundError, DataIntegrityError, DataSchemaError


_FILES: dict[str, tuple[str, str]] = {
    "customers": ("customers.csv", "csv"),
    "companies": ("companies.csv", "csv"),
    "accounts": ("accounts.csv", "csv"),
    "external_accounts": ("external_accounts.csv", "csv"),
    "transactions": ("transactions.csv", "csv"),
    "addresses": ("addresses.csv", "csv"),
    "banks": ("banks.csv", "csv"),
    "kyc_profiles": ("kyc_profiles.jsonl", "jsonl"),
    "kyc_documents": ("kyc_documents.jsonl", "jsonl"),
    "company_ownership": ("company_ownership.csv", "csv"),
    "entity_relationships": ("entity_relationships.csv", "csv"),
    "watchlist_entries": ("watchlist_entries.jsonl", "jsonl"),
}

_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "customers": {
        "customer_id", "full_name", "date_of_birth", "nationality",
        "national_id", "address_id", "created_at",
    },
    "companies": {
        "company_id", "legal_name", "registration_number", "incorporation_date",
        "registered_address_id", "representative_customer_id",
    },
    "accounts": {
        "account_id", "owner_entity_id", "owner_entity_type", "currency",
        "opened_at", "status", "bank_id",
    },
    "external_accounts": {
        "external_account_id", "masked_account_number", "bank_id", "country_code",
        "counterparty_name", "counterparty_type", "first_seen_at", "last_seen_at",
        "metadata_source", "data_visibility",
    },
    "transactions": {
        "transaction_id", "source_account_ref", "source_account_type",
        "source_bank_id", "destination_account_ref", "destination_account_type",
        "destination_bank_id", "amount", "currency", "occurred_at", "direction",
        "source_ip", "device_id", "is_cross_border", "source_country",
        "destination_country", "data_visibility", "evidence_source",
    },
    "addresses": {"address_id", "country"},
    "banks": {
        "bank_id", "bank_name", "bank_type", "country_code", "is_home_bank",
    },
    "kyc_profiles": {"kyc_profile_id", "entity_id", "entity_type"},
    "kyc_documents": {
        "document_id", "document_type", "entity_id", "verification_status",
    },
    "company_ownership": {
        "ownership_id", "owner_entity_id", "owner_entity_type", "owned_company_id",
        "ownership_percentage", "effective_from", "effective_to",
        "source_document_id", "verified",
    },
    "entity_relationships": {
        "relationship_id", "source_entity_id", "target_entity_id",
        "relationship_type", "valid_from", "valid_to",
    },
    "watchlist_entries": {
        "watchlist_id", "full_name", "list_type", "nationalities", "date_of_birth",
        "company_registration_number", "related_entity_id",
    },
}

_ID_COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id",),
    "companies": ("company_id",),
    "accounts": ("account_id",),
    "external_accounts": ("external_account_id",),
    "transactions": ("transaction_id", "source_account_ref", "destination_account_ref"),
    "addresses": ("address_id",),
    "banks": ("bank_id",),
    "kyc_profiles": ("kyc_profile_id", "entity_id"),
    "kyc_documents": ("document_id", "entity_id"),
    "company_ownership": ("ownership_id", "owner_entity_id", "owned_company_id"),
    "entity_relationships": (
        "relationship_id", "source_entity_id", "target_entity_id",
    ),
    "watchlist_entries": ("watchlist_id",),
}

_TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": ("created_at",),
    "accounts": ("opened_at",),
    "external_accounts": ("first_seen_at", "last_seen_at"),
    "transactions": ("occurred_at",),
    "kyc_profiles": ("last_reviewed_at", "next_review_at"),
}

_DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": ("date_of_birth",),
    "companies": ("incorporation_date",),
    "kyc_documents": ("issued_at", "expires_at"),
    "company_ownership": ("effective_from", "effective_to"),
    "entity_relationships": ("valid_from", "valid_to"),
    "watchlist_entries": ("date_of_birth", "effective_from", "effective_to"),
}


def _bool_value(value: Any, *, table: str, column: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not pd.isna(value) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    raise DataSchemaError(f"{table}.{column}: invalid boolean value {value!r}")


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, bool) else False


def _normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value))
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(ascii_text.upper().split())


def _as_list(value: Any) -> list[Any]:
    if _is_missing(value):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


class DataRepository:
    """Single-process, explicitly loaded Data Access Layer.

    Construction is side-effect free. Call :meth:`load` through the provider at
    backend startup. Public queries always return copies.
    """

    def __init__(
        self,
        data_path: str | Path | None = None,
        config: RepositoryConfig | None = None,
    ) -> None:
        self.data_path = self.resolve_data_path(data_path)
        self.config = config or RepositoryConfig()
        self._loaded = False
        self._frames: dict[str, pd.DataFrame] = {}
        self.__transaction_graph: nx.MultiDiGraph | None = None
        self.__entity_graph: nx.MultiDiGraph | None = None
        self.__ownership_graph: nx.MultiDiGraph | None = None
        self._watchlist_indexes: dict[str, dict[Any, frozenset[int]]] = {}

    @staticmethod
    def resolve_data_path(data_path: str | Path | None) -> Path:
        if data_path is None:
            return (Path(__file__).resolve().parents[2] / "data" / "generated").resolve()
        return Path(data_path).expanduser().resolve()

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> DataRepository:
        """Atomically load, validate, index, and build immutable graph state."""

        if self._loaded:
            return self

        frames = self._load_frames()
        self._validate(frames)
        transaction_graph = self._build_transaction_graph(frames)
        entity_graph = self._build_entity_graph(frames)
        ownership_graph = self._build_ownership_graph(frames)
        watchlist_indexes = self._build_watchlist_indexes(frames["watchlist_entries"])

        self._frames = frames
        self.__transaction_graph = nx.freeze(transaction_graph)
        self.__entity_graph = nx.freeze(entity_graph)
        self.__ownership_graph = nx.freeze(ownership_graph)
        self._watchlist_indexes = watchlist_indexes
        self._loaded = True
        return self

    def _load_frames(self) -> dict[str, pd.DataFrame]:
        frames: dict[str, pd.DataFrame] = {}
        for table, (filename, file_type) in _FILES.items():
            path = self.data_path / filename
            if not path.is_file():
                raise DataFileNotFoundError(f"{table}: required file not found: {path}")
            try:
                frame = (
                    pd.read_csv(path)
                    if file_type == "csv"
                    else pd.read_json(path, lines=True)
                )
            except (ValueError, OSError) as exc:
                raise DataSchemaError(f"{table}: cannot parse {path.name}: {exc}") from exc
            frames[table] = frame

        for table, frame in frames.items():
            missing = _REQUIRED_COLUMNS[table] - set(frame.columns)
            if missing:
                raise DataSchemaError(
                    f"{table}: missing required columns: {', '.join(sorted(missing))}"
                )
            for column in _ID_COLUMNS[table]:
                if frame[column].isna().any() or frame[column].astype(str).str.strip().eq("").any():
                    raise DataSchemaError(f"{table}.{column}: required identifier is null/empty")

        companies = frames["companies"]
        if "ownership_data_complete" not in companies.columns:
            companies["ownership_data_complete"] = False
        else:
            companies["ownership_data_complete"] = companies[
                "ownership_data_complete"
            ].map(lambda value: _bool_value(value, table="companies", column="ownership_data_complete"))

        for table, columns in _TIMESTAMP_COLUMNS.items():
            for column in columns:
                if column in frames[table].columns:
                    frames[table][column] = self._parse_datetime_column(
                        frames[table][column], table, column, utc=True
                    )
        for table, columns in _DATE_COLUMNS.items():
            for column in columns:
                if column in frames[table].columns:
                    frames[table][column] = self._parse_datetime_column(
                        frames[table][column], table, column, utc=False
                    )

        for table, column in (
            ("banks", "is_home_bank"),
            ("transactions", "is_cross_border"),
            ("company_ownership", "verified"),
        ):
            frames[table][column] = frames[table][column].map(
                lambda value, t=table, c=column: _bool_value(value, table=t, column=c)
            )

        for table, column in (
            ("transactions", "amount"),
            ("company_ownership", "ownership_percentage"),
        ):
            parsed = pd.to_numeric(frames[table][column], errors="coerce")
            if parsed.isna().any():
                raise DataSchemaError(f"{table}.{column}: contains a non-numeric value")
            frames[table][column] = parsed.astype(float)
        return frames

    @staticmethod
    def _parse_datetime_column(
        series: pd.Series, table: str, column: str, *, utc: bool
    ) -> pd.Series:
        nonempty = series.notna() & series.astype(str).str.strip().ne("")
        parsed = pd.to_datetime(series.where(nonempty), errors="coerce", utc=utc)
        if parsed[nonempty].isna().any():
            bad = series[nonempty & parsed.isna()].iloc[0]
            raise DataSchemaError(f"{table}.{column}: invalid date/timestamp {bad!r}")
        if not utc:
            parsed = parsed.dt.normalize()
        return parsed

    def _validate(self, frames: dict[str, pd.DataFrame]) -> None:
        self._validate_unique_ids(frames)
        self._validate_data_boundary(frames)
        self._validate_transactions(frames)
        self._validate_ownership(frames)

    @staticmethod
    def _validate_unique_ids(frames: dict[str, pd.DataFrame]) -> None:
        primary_ids = {
            "customers": "customer_id", "companies": "company_id",
            "accounts": "account_id", "external_accounts": "external_account_id",
            "transactions": "transaction_id", "addresses": "address_id",
            "banks": "bank_id", "kyc_profiles": "kyc_profile_id",
            "kyc_documents": "document_id", "company_ownership": "ownership_id",
            "entity_relationships": "relationship_id", "watchlist_entries": "watchlist_id",
        }
        for table, column in primary_ids.items():
            duplicated = frames[table][column].duplicated(keep=False)
            if duplicated.any():
                value = frames[table].loc[duplicated, column].iloc[0]
                raise DataIntegrityError(f"{table}.{column}: duplicate identifier {value}")

    def _validate_data_boundary(self, frames: dict[str, pd.DataFrame]) -> None:
        banks = frames["banks"]
        home = banks[banks["is_home_bank"]]
        if len(home) != 1 or str(home.iloc[0]["bank_id"]) != self.config.home_bank_id:
            raise DataIntegrityError(
                f"banks: expected exactly one home bank {self.config.home_bank_id}"
            )

        customer_ids = set(frames["customers"]["customer_id"].astype(str))
        company_ids = set(frames["companies"]["company_id"].astype(str))
        entity_ids = customer_ids | company_ids
        bank_ids = set(banks["bank_id"].astype(str))
        external_ids = set(frames["external_accounts"]["external_account_id"].astype(str))
        address_ids = set(frames["addresses"]["address_id"].astype(str))

        for row in frames["accounts"].itertuples(index=False):
            if str(row.bank_id) != self.config.home_bank_id:
                raise DataIntegrityError(f"accounts[{row.account_id}]: non-SHB internal bank")
            valid = customer_ids if str(row.owner_entity_type) == "CUSTOMER" else company_ids
            if str(row.owner_entity_type) not in {"CUSTOMER", "COMPANY"} or str(row.owner_entity_id) not in valid:
                raise DataIntegrityError(f"accounts[{row.account_id}]: invalid internal owner")

        for row in frames["external_accounts"].itertuples(index=False):
            if str(row.bank_id) not in bank_ids or str(row.bank_id) == self.config.home_bank_id:
                raise DataIntegrityError(
                    f"external_accounts[{row.external_account_id}]: invalid external bank"
                )
            if str(row.data_visibility) not in {"PAYMENT_MESSAGE_ONLY", "ENRICHED_EXTERNAL"}:
                raise DataIntegrityError(
                    f"external_accounts[{row.external_account_id}]: invalid visibility"
                )

        if set(frames["accounts"]["account_id"].astype(str)) & external_ids:
            raise DataIntegrityError("accounts/external_accounts: overlapping identifiers")
        for row in frames["customers"].itertuples(index=False):
            if str(row.address_id) not in address_ids:
                raise DataIntegrityError(f"customers[{row.customer_id}]: address not found")
        for row in frames["companies"].itertuples(index=False):
            if str(row.registered_address_id) not in address_ids:
                raise DataIntegrityError(f"companies[{row.company_id}]: address not found")
            if str(row.representative_customer_id) not in customer_ids:
                raise DataIntegrityError(f"companies[{row.company_id}]: representative not found")

        for table in ("kyc_profiles", "kyc_documents"):
            for row in frames[table].itertuples(index=False):
                if str(row.entity_id) not in entity_ids:
                    raise DataIntegrityError(f"{table}[{row.entity_id}]: non-internal entity")
        for row in frames["entity_relationships"].itertuples(index=False):
            if str(row.source_entity_id) not in entity_ids or str(row.target_entity_id) not in entity_ids:
                raise DataIntegrityError(
                    f"entity_relationships[{row.relationship_id}]: endpoint is not internal"
                )
        for row in frames["watchlist_entries"].itertuples(index=False):
            related = getattr(row, "related_entity_id")
            if not _is_missing(related) and str(related) not in entity_ids:
                raise DataIntegrityError(f"watchlist_entries[{row.watchlist_id}]: invalid related entity")

        forbidden = external_ids & entity_ids
        if forbidden:
            raise DataIntegrityError(f"external entity leaked into internal entity tables: {next(iter(forbidden))}")

    def _validate_transactions(self, frames: dict[str, pd.DataFrame]) -> None:
        tx = frames["transactions"]
        if (tx["amount"] <= 0).any():
            bad = tx.loc[tx["amount"] <= 0, "transaction_id"].iloc[0]
            raise DataIntegrityError(f"transactions[{bad}]: amount must be positive")

        accounts = frames["accounts"].set_index("account_id", drop=False)
        external = frames["external_accounts"].set_index("external_account_id", drop=False)
        banks = frames["banks"].set_index("bank_id", drop=False)
        topology = {
            ("INTERNAL_SHB", "INTERNAL_SHB"): "INTERNAL",
            ("EXTERNAL", "INTERNAL_SHB"): "INBOUND",
            ("INTERNAL_SHB", "EXTERNAL"): "OUTBOUND",
        }
        for row in tx.itertuples(index=False):
            txid = str(row.transaction_id)
            pair = (str(row.source_account_type), str(row.destination_account_type))
            if pair not in topology or str(row.direction) != topology[pair]:
                raise DataIntegrityError(f"transactions[{txid}]: invalid topology/direction")
            self._validate_transaction_endpoint(
                txid, "source", str(row.source_account_ref), pair[0],
                str(row.source_bank_id), str(row.source_country), accounts, external, banks,
            )
            self._validate_transaction_endpoint(
                txid, "destination", str(row.destination_account_ref), pair[1],
                str(row.destination_bank_id), str(row.destination_country), accounts, external, banks,
            )
            cross_border = str(row.source_country) != str(row.destination_country)
            if bool(row.is_cross_border) != cross_border:
                raise DataIntegrityError(f"transactions[{txid}]: is_cross_border mismatch")
            visibility = str(row.data_visibility)
            evidence = "" if _is_missing(row.evidence_source) else str(row.evidence_source).strip()
            if pair == ("INTERNAL_SHB", "INTERNAL_SHB"):
                if visibility != "FULL_INTERNAL" or evidence != "SHB_TRANSACTION_LEDGER":
                    raise DataIntegrityError(f"transactions[{txid}]: invalid internal visibility/evidence")
            else:
                if visibility not in {"PAYMENT_MESSAGE_ONLY", "ENRICHED_EXTERNAL"}:
                    raise DataIntegrityError(f"transactions[{txid}]: invalid external visibility")
                if visibility == "ENRICHED_EXTERNAL" and not evidence:
                    raise DataIntegrityError(f"transactions[{txid}]: enrichment source required")
            if str(row.direction) == "INBOUND":
                if not _is_missing(row.source_ip) or not _is_missing(row.device_id):
                    raise DataIntegrityError(f"transactions[{txid}]: external source has SHB device/IP")

    def _validate_transaction_endpoint(
        self,
        txid: str,
        side: str,
        account_ref: str,
        account_type: str,
        bank_id: str,
        country: str,
        accounts: pd.DataFrame,
        external: pd.DataFrame,
        banks: pd.DataFrame,
    ) -> None:
        if account_type == "INTERNAL_SHB":
            if account_ref not in accounts.index or bank_id != self.config.home_bank_id:
                raise DataIntegrityError(f"transactions[{txid}]: invalid {side} internal reference")
            expected_bank = str(accounts.loc[account_ref, "bank_id"])
        else:
            if account_ref not in external.index:
                raise DataIntegrityError(f"transactions[{txid}]: invalid {side} external reference")
            expected_bank = str(external.loc[account_ref, "bank_id"])
            if str(external.loc[account_ref, "country_code"]) != country:
                raise DataIntegrityError(f"transactions[{txid}]: {side} external country mismatch")
        if bank_id != expected_bank or bank_id not in banks.index:
            raise DataIntegrityError(f"transactions[{txid}]: {side} bank mismatch")
        if str(banks.loc[bank_id, "country_code"]) != country:
            raise DataIntegrityError(f"transactions[{txid}]: {side} bank country mismatch")

    def _validate_ownership(self, frames: dict[str, pd.DataFrame]) -> None:
        ownership = frames["company_ownership"]
        customer_ids = set(frames["customers"]["customer_id"].astype(str))
        company_ids = set(frames["companies"]["company_id"].astype(str))
        documents = frames["kyc_documents"].set_index("document_id", drop=False)
        tolerance = self.config.ownership_percentage_tolerance

        for row in ownership.itertuples(index=False):
            oid = str(row.ownership_id)
            percentage = float(row.ownership_percentage)
            if percentage <= 0 or percentage > 100 + tolerance:
                raise DataIntegrityError(f"company_ownership[{oid}]: percentage outside (0, 100]")
            owner_type = str(row.owner_entity_type)
            valid_owner_ids = customer_ids if owner_type == "CUSTOMER" else company_ids
            if owner_type not in {"CUSTOMER", "COMPANY"} or str(row.owner_entity_id) not in valid_owner_ids:
                raise DataIntegrityError(f"company_ownership[{oid}]: invalid owner")
            if str(row.owned_company_id) not in company_ids:
                raise DataIntegrityError(f"company_ownership[{oid}]: owned company not found")
            if (
                owner_type == "COMPANY"
                and str(row.owner_entity_id) == str(row.owned_company_id)
                and math.isclose(percentage, 100.0, abs_tol=tolerance)
            ):
                raise DataIntegrityError(f"company_ownership[{oid}]: direct 100% self-ownership")
            if not _is_missing(row.effective_to) and row.effective_to < row.effective_from:
                raise DataIntegrityError(f"company_ownership[{oid}]: invalid effective period")
            if bool(row.verified):
                doc_id = "" if _is_missing(row.source_document_id) else str(row.source_document_id)
                if doc_id not in documents.index:
                    raise DataIntegrityError(f"company_ownership[{oid}]: evidence document not found")
                document = documents.loc[doc_id]
                supports = {str(item).upper() for item in _as_list(document.get("document_supports"))}
                supported_type = str(document["document_type"]) in self.config.allowed_ownership_document_types
                if str(document["verification_status"]) != "VERIFIED" or (
                    "OWNERSHIP" not in supports and not supported_type
                ):
                    raise DataIntegrityError(f"company_ownership[{oid}]: unsupported ownership evidence")

        change_dates = ownership["effective_from"].dropna().drop_duplicates().sort_values()
        if change_dates.empty:
            return
        for change_date in change_dates:
            active_at_change = self._active_ownership_records(ownership, change_date)
            active_self_ownership = active_at_change[
                (active_at_change["owner_entity_type"] == "COMPANY")
                & (
                    active_at_change["owner_entity_id"]
                    == active_at_change["owned_company_id"]
                )
            ]
            self_totals = active_self_ownership.groupby("owned_company_id")[
                "ownership_percentage"
            ].sum()
            if any(
                math.isclose(float(total), 100.0, abs_tol=tolerance)
                for total in self_totals
            ):
                company_id = str(
                    next(
                        company
                        for company, total in self_totals.items()
                        if math.isclose(float(total), 100.0, abs_tol=tolerance)
                    )
                )
                raise DataIntegrityError(
                    f"company_ownership[{company_id}]: active direct 100% self-ownership"
                )
            change_coverage = active_at_change.groupby("owned_company_id")[
                "ownership_percentage"
            ].sum()
            if (change_coverage > 100 + tolerance).any():
                company_id = str(change_coverage[change_coverage > 100 + tolerance].index[0])
                raise DataIntegrityError(
                    f"company_ownership[{company_id}]: active coverage exceeds 100% "
                    f"at {pd.Timestamp(change_date).date()}"
                )

        reference_date = frames["transactions"]["occurred_at"].max()
        if pd.isna(reference_date):
            reference_date = change_dates.iloc[-1]
        reference_date = pd.Timestamp(reference_date)
        if reference_date.tzinfo is not None:
            reference_date = reference_date.tz_convert("UTC").tz_localize(None)
        active = self._active_ownership_records(ownership, reference_date)
        coverage = active.groupby("owned_company_id")["ownership_percentage"].sum()
        complete_companies = frames["companies"].loc[
            frames["companies"]["ownership_data_complete"], "company_id"
        ].astype(str)
        for company_id in complete_companies:
            total = float(coverage.get(company_id, 0.0))
            if not math.isclose(total, 100.0, abs_tol=tolerance):
                raise DataIntegrityError(
                    f"company_ownership[{company_id}]: complete data has {total}% coverage"
                )

    @staticmethod
    def _active_ownership_records(frame: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
        moment = pd.Timestamp(as_of).normalize()
        return frame[
            (frame["effective_from"] <= moment)
            & (frame["effective_to"].isna() | (frame["effective_to"] >= moment))
        ].copy()

    @staticmethod
    def _record_attributes(row: pd.Series, excluded: Iterable[str]) -> dict[str, Any]:
        excluded_set = set(excluded)
        return {column: value for column, value in row.items() if column not in excluded_set}

    def _build_transaction_graph(self, frames: dict[str, pd.DataFrame]) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph(graph_type="transaction")
        banks = frames["banks"].set_index("bank_id")
        for row in frames["accounts"].itertuples(index=False):
            graph.add_node(
                str(row.account_id), account_type="INTERNAL_SHB", bank_id=str(row.bank_id),
                country_code=str(banks.loc[row.bank_id, "country_code"]),
                owner_entity_id=str(row.owner_entity_id),
            )
        for row in frames["external_accounts"].itertuples(index=False):
            graph.add_node(
                str(row.external_account_id), account_type="EXTERNAL", bank_id=str(row.bank_id),
                country_code=str(row.country_code), data_visibility=str(row.data_visibility),
            )
        for _, row in frames["transactions"].iterrows():
            graph.add_edge(
                str(row["source_account_ref"]), str(row["destination_account_ref"]),
                key=str(row["transaction_id"]),
                **self._record_attributes(
                    row, {"source_account_ref", "destination_account_ref", "transaction_id"}
                ),
            )
        return graph

    def _build_entity_graph(self, frames: dict[str, pd.DataFrame]) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph(graph_type="entity_relationship")
        for entity_id in frames["customers"]["customer_id"].astype(str):
            graph.add_node(entity_id, entity_type="CUSTOMER")
        for entity_id in frames["companies"]["company_id"].astype(str):
            graph.add_node(entity_id, entity_type="COMPANY")
        for _, row in frames["entity_relationships"].iterrows():
            graph.add_edge(
                str(row["source_entity_id"]), str(row["target_entity_id"]),
                key=str(row["relationship_id"]),
                **self._record_attributes(
                    row, {"source_entity_id", "target_entity_id", "relationship_id"}
                ),
            )
        return graph

    def _build_ownership_graph(self, frames: dict[str, pd.DataFrame]) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph(graph_type="ownership")
        for entity_id in frames["customers"]["customer_id"].astype(str):
            graph.add_node(entity_id, entity_type="CUSTOMER")
        for entity_id in frames["companies"]["company_id"].astype(str):
            graph.add_node(entity_id, entity_type="COMPANY")
        for _, row in frames["company_ownership"].iterrows():
            graph.add_edge(
                str(row["owner_entity_id"]), str(row["owned_company_id"]),
                key=str(row["ownership_id"]),
                **self._record_attributes(
                    row, {"owner_entity_id", "owned_company_id", "ownership_id"}
                ),
            )
        cycles = self._ownership_cycles(frames["company_ownership"])
        graph.graph["ownership_cycle_detected"] = bool(cycles)
        graph.graph["ownership_cycles"] = cycles
        return graph

    @staticmethod
    def _ownership_cycles(frame: pd.DataFrame) -> list[list[str]]:
        company_edges = frame[frame["owner_entity_type"] == "COMPANY"]
        graph = nx.DiGraph()
        graph.add_edges_from(
            zip(
                company_edges["owner_entity_id"].astype(str),
                company_edges["owned_company_id"].astype(str),
                strict=False,
            )
        )
        cycles = [list(map(str, cycle)) for cycle in nx.simple_cycles(graph)]
        return sorted(cycles, key=lambda cycle: (len(cycle), cycle))

    @staticmethod
    def _build_watchlist_indexes(
        frame: pd.DataFrame,
    ) -> dict[str, dict[Any, frozenset[int]]]:
        frame["_normalized_name"] = frame["full_name"].map(_normalize_name)
        if "entity_type" in frame.columns:
            derived = frame["entity_type"].fillna("").astype(str).str.upper()
        else:
            derived = pd.Series("", index=frame.index, dtype="object")
        company_mask = frame["company_registration_number"].notna() & frame[
            "company_registration_number"
        ].astype(str).str.strip().ne("")
        frame["_entity_type"] = derived.where(derived.ne(""), company_mask.map({True: "COMPANY", False: "INDIVIDUAL"}))
        name_entity: dict[tuple[str, str], set[int]] = {}
        list_type: dict[str, set[int]] = {}
        nationality: dict[str, set[int]] = {}
        for index, row in frame.iterrows():
            key = (str(row["_normalized_name"]), str(row["_entity_type"]))
            name_entity.setdefault(key, set()).add(index)
            list_type.setdefault(str(row["list_type"]).upper(), set()).add(index)
            for value in _as_list(row["nationalities"]):
                nationality.setdefault(str(value).upper(), set()).add(index)
        return {
            "name_entity": {key: frozenset(indexes) for key, indexes in name_entity.items()},
            "list_type": {key: frozenset(indexes) for key, indexes in list_type.items()},
            "nationality": {key: frozenset(indexes) for key, indexes in nationality.items()},
        }

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            raise RuntimeError("DataRepository.load() must complete before queries")

    def transactions_for_account(
        self,
        account_id: str,
        start_time: str | datetime | None = None,
        end_time: str | datetime | None = None,
        direction: str | None = None,
    ) -> pd.DataFrame:
        self._ensure_loaded()
        if direction is not None and direction not in {"INTERNAL", "INBOUND", "OUTBOUND"}:
            raise ValueError(f"invalid transaction direction: {direction}")
        start = pd.to_datetime(start_time, utc=True) if start_time is not None else None
        end = pd.to_datetime(end_time, utc=True) if end_time is not None else None
        if start is not None and end is not None and start > end:
            raise ValueError("start_time must be no later than end_time")
        frame = self._frames["transactions"]
        mask = (frame["source_account_ref"] == account_id) | (
            frame["destination_account_ref"] == account_id
        )
        if start is not None:
            mask &= frame["occurred_at"] >= start
        if end is not None:
            mask &= frame["occurred_at"] <= end
        if direction is not None:
            mask &= frame["direction"] == direction
        return self._defensive_frame(frame.loc[mask])

    def account_by_id(self, account_id: str) -> pd.Series | None:
        return self._series_by_id("accounts", "account_id", account_id)

    def external_account_by_id(self, external_account_id: str) -> pd.Series | None:
        return self._series_by_id("external_accounts", "external_account_id", external_account_id)

    def entity_by_id(self, entity_id: str) -> pd.Series | None:
        result = self._series_by_id("customers", "customer_id", entity_id)
        return result if result is not None else self._series_by_id("companies", "company_id", entity_id)

    def kyc_profile_by_entity(self, entity_id: str) -> pd.Series | None:
        return self._series_by_id("kyc_profiles", "entity_id", entity_id)

    def _series_by_id(self, table: str, column: str, value: str) -> pd.Series | None:
        self._ensure_loaded()
        matches = self._frames[table][self._frames[table][column] == value]
        return None if matches.empty else self._defensive_series(matches.iloc[0])

    def kyc_documents_by_entity(self, entity_id: str) -> pd.DataFrame:
        return self._rows_equal("kyc_documents", "entity_id", entity_id)

    def ownership_records_for_company(self, company_id: str) -> pd.DataFrame:
        return self._rows_equal("company_ownership", "owned_company_id", company_id)

    def relationships_for_entity(self, entity_id: str) -> pd.DataFrame:
        self._ensure_loaded()
        frame = self._frames["entity_relationships"]
        return self._defensive_frame(frame.loc[
            (frame["source_entity_id"] == entity_id) | (frame["target_entity_id"] == entity_id)
        ])

    def _rows_equal(self, table: str, column: str, value: str) -> pd.DataFrame:
        self._ensure_loaded()
        frame = self._frames[table]
        return self._defensive_frame(frame.loc[frame[column] == value])

    @staticmethod
    def _defensive_series(series: pd.Series) -> pd.Series:
        copied = series.copy(deep=True)
        for key, value in copied.items():
            copied.at[key] = deepcopy(value)
        return copied

    @staticmethod
    def _defensive_frame(frame: pd.DataFrame) -> pd.DataFrame:
        copied = frame.copy(deep=True)
        for column in copied.select_dtypes(include=["object", "string"]).columns:
            copied[column] = copied[column].map(deepcopy)
        return copied

    def watchlist_candidates(
        self,
        normalized_name: str,
        entity_type: str,
        nationalities: list[str] | None = None,
        date_of_birth: date | None = None,
        list_types: list[str] | None = None,
    ) -> pd.DataFrame:
        self._ensure_loaded()
        normalized_type = entity_type.upper()
        if normalized_type == "CUSTOMER":
            normalized_type = "INDIVIDUAL"
        key = (_normalize_name(normalized_name), normalized_type)
        indexes = set(self._watchlist_indexes["name_entity"].get(key, frozenset()))
        if nationalities:
            nationality_matches: set[int] = set()
            for nationality in nationalities:
                nationality_matches.update(
                    self._watchlist_indexes["nationality"].get(
                        nationality.upper(), frozenset()
                    )
                )
            indexes &= nationality_matches
        if list_types:
            list_matches: set[int] = set()
            for list_type in list_types:
                list_matches.update(
                    self._watchlist_indexes["list_type"].get(
                        list_type.upper(), frozenset()
                    )
                )
            indexes &= list_matches
        frame = self._frames["watchlist_entries"].loc[sorted(indexes)]
        if date_of_birth is not None:
            wanted_dob = pd.Timestamp(date_of_birth).normalize()
            frame = frame[frame["date_of_birth"] == wanted_dob]
        return self._defensive_frame(
            frame.drop(columns=["_normalized_name", "_entity_type"], errors="ignore")
        )

    def transaction_subgraph(self, account_ids: Collection[str]) -> nx.MultiDiGraph:
        self._ensure_loaded()
        assert self.__transaction_graph is not None
        return self._copy_multidigraph_subgraph(self.__transaction_graph, account_ids)

    def entity_subgraph(self, entity_ids: Collection[str]) -> nx.MultiDiGraph:
        self._ensure_loaded()
        assert self.__entity_graph is not None
        return self._copy_multidigraph_subgraph(self.__entity_graph, entity_ids)

    def ownership_subgraph(self, entity_ids: Collection[str]) -> nx.MultiDiGraph:
        self._ensure_loaded()
        assert self.__ownership_graph is not None
        return self._copy_multidigraph_subgraph(self.__ownership_graph, entity_ids)

    @staticmethod
    def _copy_multidigraph_subgraph(
        graph: nx.MultiDiGraph, node_ids: Collection[str]
    ) -> nx.MultiDiGraph:
        copied = nx.MultiDiGraph()
        copied.graph.update(deepcopy(dict(graph.graph)))
        selected = set(node_ids) & set(graph.nodes)
        for node_id in selected:
            copied.add_node(node_id, **deepcopy(dict(graph.nodes[node_id])))
        for source, target, key, attributes in graph.subgraph(selected).edges(
            keys=True, data=True
        ):
            copied.add_edge(source, target, key=key, **deepcopy(dict(attributes)))
        return copied

    def build_active_ownership_graph(
        self, as_of_date: str | date | datetime
    ) -> nx.DiGraph:
        self._ensure_loaded()
        try:
            as_of = pd.Timestamp(as_of_date)
            if as_of.tzinfo is not None:
                as_of = as_of.tz_convert("UTC").tz_localize(None)
            as_of = as_of.normalize()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid as_of_date: {as_of_date!r}") from exc
        active = self._active_ownership_records(self._frames["company_ownership"], as_of)
        graph = nx.DiGraph(graph_type="active_ownership", as_of_date=as_of)
        for entity_id in self._frames["customers"]["customer_id"].astype(str):
            graph.add_node(entity_id, entity_type="CUSTOMER")
        for entity_id in self._frames["companies"]["company_id"].astype(str):
            graph.add_node(entity_id, entity_type="COMPANY")
        grouped = active.groupby(["owner_entity_id", "owned_company_id"], sort=False)
        for (owner_id, company_id), records in grouped:
            graph.add_edge(
                str(owner_id), str(company_id),
                ownership_percentage=float(records["ownership_percentage"].sum()),
                ownership_ids=records["ownership_id"].astype(str).tolist(),
                verified=bool(records["verified"].all()),
            )
        coverage = active.groupby("owned_company_id")["ownership_percentage"].sum()
        tolerance = self.config.ownership_percentage_tolerance
        for company_id in self._frames["companies"]["company_id"].astype(str):
            value = float(coverage.get(company_id, 0.0))
            graph.nodes[company_id]["ownership_coverage_percentage"] = value
            graph.nodes[company_id]["ownership_status"] = (
                "COMPLETE" if math.isclose(value, 100.0, abs_tol=tolerance) else "INCOMPLETE"
            )
        cycles = self._ownership_cycles(active)
        graph.graph["ownership_cycle_detected"] = bool(cycles)
        graph.graph["ownership_cycles"] = cycles
        return graph
