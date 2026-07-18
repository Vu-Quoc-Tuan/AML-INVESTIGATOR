"""LangChain boundary for backend-owned Transaction investigation tools."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.data.exceptions import DataRepositoryError, DataRepositoryNotInitializedError
from app.schemas.common import TraceDirection, TransactionDirection


NonEmptyId = Annotated[str, Field(min_length=1)]


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountTransactionsInput(StrictToolInput):
    account_id: str = Field(min_length=1)
    start_time: datetime | None = None
    end_time: datetime | None = None
    direction: TransactionDirection | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "AccountTransactionsInput":
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time must be no later than end_time")
        return self


class AccountWindowInput(StrictToolInput):
    account_id: str = Field(min_length=1)
    time_window_hours: float = Field(default=24.0, gt=0, le=720)


class MultiAccountWindowInput(StrictToolInput):
    account_ids: list[NonEmptyId] = Field(min_length=2, max_length=20)
    lookback_period_hours: float = Field(default=24.0, gt=0, le=720)


class SharedIdentifiersInput(StrictToolInput):
    account_ids: list[NonEmptyId] = Field(min_length=2, max_length=20)


class TraceFundsInput(StrictToolInput):
    seed_account_ids: list[NonEmptyId] = Field(min_length=1, max_length=20)
    direction: TraceDirection
    max_depth: int = Field(default=3, ge=1, le=5)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "TraceFundsInput":
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time must be no later than end_time")
        return self


class CaseSubgraphInput(StrictToolInput):
    seed_entity_ids: list[NonEmptyId] = Field(min_length=1, max_length=20)
    max_depth: int = Field(default=2, ge=1, le=5)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "CaseSubgraphInput":
        if self.start_time and self.end_time and self.start_time > self.end_time:
            raise ValueError("start_time must be no later than end_time")
        return self


class TransactionEvidenceBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    visibility_level: str = Field(min_length=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TransactionToolBoundary(BaseModel):
    """Local mirror of the orchestrator's JSON-safe tool result contract."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
    data: JsonValue = None
    evidence: list[TransactionEvidenceBoundary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None

    @model_validator(mode="after")
    def enforce_error_code(self) -> "TransactionToolBoundary":
        if self.status == "ERROR" and not self.error_code:
            raise ValueError("ERROR tool results require error_code")
        if self.status != "ERROR" and self.error_code:
            raise ValueError("error_code is only valid for ERROR tool results")
        return self


def _tool_response(boundary: TransactionToolBoundary) -> tuple[str, dict[str, Any]]:
    artifact = boundary.model_dump(mode="json")
    return json.dumps(artifact, ensure_ascii=False, sort_keys=True), artifact


def _known_error(exc: DataRepositoryError) -> TransactionToolBoundary:
    code = (
        "DATA_REPOSITORY_NOT_INITIALIZED"
        if isinstance(exc, DataRepositoryNotInitializedError)
        else "TRANSACTION_DATA_ERROR"
    )
    return TransactionToolBoundary(status="ERROR", error_code=code, warnings=[code])


def _transaction_records_from_graph(graph_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for edge in graph_snapshot.get("edges", []):
        if edge.get("edge_type") != "TRANSFERRED_TO":
            continue
        transaction_id = edge.get("key")
        attributes = edge.get("attributes")
        if not transaction_id or not isinstance(attributes, dict):
            continue
        records.append(
            {
                **attributes,
                "transaction_id": str(transaction_id),
                "source_account_ref": edge.get("source"),
                "destination_account_ref": edge.get("target"),
            }
        )
    return records


def _finding_evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = {
            str(item)
            for item in value.get("evidence_ids", [])
            if isinstance(item, str) and item
        }
        for child in value.values():
            result.update(_finding_evidence_ids(child))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in value:
            result.update(_finding_evidence_ids(child))
        return result
    return set()


def _evidence_from_records(
    records: list[dict[str, Any]],
    referenced_ids: set[str] | None = None,
) -> tuple[list[TransactionEvidenceBoundary], list[str]]:
    evidence: dict[str, TransactionEvidenceBoundary] = {}
    warnings: list[str] = []
    for record in records:
        transaction_id = record.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id:
            warnings.append("TRANSACTION_RECORD_MISSING_ID")
            continue
        if referenced_ids is not None and transaction_id not in referenced_ids:
            continue
        source_system = record.get("evidence_source")
        visibility = record.get("data_visibility")
        if not isinstance(source_system, str) or not source_system:
            warnings.append(f"MISSING_EVIDENCE_SOURCE:{transaction_id}")
            continue
        if not isinstance(visibility, str) or not visibility:
            warnings.append(f"MISSING_DATA_VISIBILITY:{transaction_id}")
            continue
        evidence[transaction_id] = TransactionEvidenceBoundary(
            evidence_id=transaction_id,
            source_system=source_system,
            source_record_id=transaction_id,
            visibility_level=visibility,
            payload=record,
        )
    if referenced_ids is not None:
        for transaction_id in sorted(referenced_ids - evidence.keys()):
            warnings.append(f"MISSING_TRANSACTION_EVIDENCE:{transaction_id}")
    return list(evidence.values()), warnings


def _boundary(
    data: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    referenced_ids: set[str] | None = None,
    no_data: bool = False,
) -> TransactionToolBoundary:
    evidence, warnings = _evidence_from_records(records, referenced_ids)
    unresolved = bool(warnings)
    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE"]
    if no_data:
        status = "NO_DATA"
    elif unresolved:
        status = "INCONCLUSIVE"
    else:
        status = "SUCCESS"
    return TransactionToolBoundary(
        status=status,
        data=data,
        evidence=evidence,
        warnings=warnings,
    )


def build_transaction_tools(service: Any | None = None) -> tuple[BaseTool, ...]:
    """Return the minimal approved Transaction tool set for owner registration."""

    if service is None:
        from app.services.transaction_data_service import TransactionDataService

        service = TransactionDataService()

    def get_account_transactions(
        account_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        direction: TransactionDirection | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            result = service.get_account_transactions(
                account_id, start_time, end_time, direction
            )
            return _tool_response(
                _boundary(
                    result,
                    result.get("transactions", []),
                    no_data=result.get("count", 0) == 0,
                )
            )
        except DataRepositoryError as exc:
            return _tool_response(_known_error(exc))

    def trace_funds(
        seed_account_ids: list[str],
        direction: TraceDirection,
        max_depth: int = 3,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            result = service.trace_funds(
                seed_account_ids, direction, max_depth, start_time, end_time
            )
            referenced = {
                str(transaction_id)
                for path in result.get("paths", [])
                for transaction_id in path.get("transactions", [])
            }
            records = _transaction_records_from_graph(result.get("graph_snapshot", {}))
            return _tool_response(
                _boundary(
                    result,
                    records,
                    referenced_ids=referenced,
                    no_data=not result.get("paths"),
                )
            )
        except DataRepositoryError as exc:
            return _tool_response(_known_error(exc))

    def detect_rapid_pass_through(
        account_id: str, time_window_hours: float = 24.0
    ) -> tuple[str, dict[str, Any]]:
        try:
            result = service.detect_rapid_pass_through(account_id, time_window_hours)
            transactions = service.get_account_transactions(account_id).get(
                "transactions", []
            )
            return _tool_response(
                _boundary(
                    result,
                    transactions,
                    referenced_ids=_finding_evidence_ids(result),
                )
            )
        except DataRepositoryError as exc:
            return _tool_response(_known_error(exc))

    def detect_fan_in_fan_out(
        account_id: str, time_window_hours: float = 24.0
    ) -> tuple[str, dict[str, Any]]:
        try:
            result = service.detect_fan_in_fan_out(account_id, time_window_hours)
            transactions = service.get_account_transactions(account_id).get(
                "transactions", []
            )
            return _tool_response(
                _boundary(
                    result,
                    transactions,
                    referenced_ids=_finding_evidence_ids(result),
                )
            )
        except DataRepositoryError as exc:
            return _tool_response(_known_error(exc))

    def find_common_funding_sources(
        account_ids: list[str], lookback_period_hours: float = 24.0
    ) -> tuple[str, dict[str, Any]]:
        try:
            result = service.find_common_funding_sources(
                account_ids, lookback_period_hours
            )
            transactions = [
                transaction
                for account_id in account_ids
                for transaction in service.get_account_transactions(account_id).get(
                    "transactions", []
                )
            ]
            return _tool_response(
                _boundary(
                    result,
                    transactions,
                    referenced_ids=_finding_evidence_ids(result),
                )
            )
        except DataRepositoryError as exc:
            return _tool_response(_known_error(exc))

    def find_shared_identifiers(
        account_ids: list[str],
    ) -> tuple[str, dict[str, Any]]:
        try:
            result = service.find_shared_identifiers(account_ids)
            transactions = [
                transaction
                for account_id in account_ids
                for transaction in service.get_account_transactions(account_id).get(
                    "transactions", []
                )
            ]
            return _tool_response(
                _boundary(
                    result,
                    transactions,
                    referenced_ids=_finding_evidence_ids(result),
                )
            )
        except DataRepositoryError as exc:
            return _tool_response(_known_error(exc))

    def build_case_subgraph(
        seed_entity_ids: list[str],
        max_depth: int = 2,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            result = service.build_case_subgraph(
                seed_entity_ids, max_depth, start_time, end_time
            )
            records = _transaction_records_from_graph(result)
            referenced = {
                str(record["transaction_id"])
                for record in records
                if record.get("transaction_id")
            }
            return _tool_response(
                _boundary(
                    result,
                    records,
                    referenced_ids=referenced,
                    no_data=not records,
                )
            )
        except DataRepositoryError as exc:
            return _tool_response(_known_error(exc))

    definitions = (
        (
            get_account_transactions,
            "Retrieve SHB-observable transactions and counterparty summaries for one account.",
            AccountTransactionsInput,
        ),
        (
            trace_funds,
            "Trace evidence-backed fund paths forward or backward from seed accounts.",
            TraceFundsInput,
        ),
        (
            detect_rapid_pass_through,
            "Detect rapid pass-through behavior using deterministic transaction rules.",
            AccountWindowInput,
        ),
        (
            detect_fan_in_fan_out,
            "Detect fan-in and fan-out patterns for one account in a bounded window.",
            AccountWindowInput,
        ),
        (
            find_common_funding_sources,
            "Find transaction-backed common funding sources for multiple accounts.",
            MultiAccountWindowInput,
        ),
        (
            find_shared_identifiers,
            "Find shared device and IP identifiers backed by transaction records.",
            SharedIdentifiersInput,
        ),
        (
            build_case_subgraph,
            "Build a bounded SHB-observable transaction subgraph around seed entities.",
            CaseSubgraphInput,
        ),
    )
    return tuple(
        StructuredTool.from_function(
            func=function,
            name=function.__name__,
            description=description,
            args_schema=args_schema,
            response_format="content_and_artifact",
        )
        for function, description, args_schema in definitions
    )
