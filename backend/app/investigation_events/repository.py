"""Append-only SQLite event log used by SSE replay and reconnect."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .contracts import InvestigationEvent, InvestigationEventType


MAX_EVENT_PAYLOAD_BYTES = 32_768


class InvestigationEventRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS investigation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    agent_id TEXT,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tool_name TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_investigation_events_ticket_id
                    ON investigation_events(ticket_id, id);
                """
            )

    def append(
        self,
        *,
        ticket_id: str,
        case_id: str,
        event_type: InvestigationEventType,
        status: str,
        summary: str,
        agent_id: str | None = None,
        tool_name: str | None = None,
        payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> InvestigationEvent:
        ticket = _required(ticket_id, "ticket_id")
        case = _required(case_id, "case_id")
        normalized_status = _required(status, "status")[:80]
        normalized_summary = _required(summary, "summary")[:1_000]
        normalized_agent = _optional(agent_id, 80)
        normalized_tool = _optional(tool_name, 160)
        payload_json, stored_payload = _serialize_payload(payload)
        created_at = _aware(now or datetime.now(UTC))

        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO investigation_events(
                    ticket_id,case_id,agent_id,event_type,status,summary,
                    tool_name,payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    ticket,
                    case,
                    normalized_agent,
                    event_type.value,
                    normalized_status,
                    normalized_summary,
                    normalized_tool,
                    payload_json,
                    created_at.isoformat(timespec="microseconds"),
                ),
            )
            event_id = int(cursor.lastrowid)
        return InvestigationEvent(
            id=event_id,
            ticket_id=ticket,
            case_id=case,
            agent_id=normalized_agent,
            event_type=event_type,
            status=normalized_status,
            summary=normalized_summary,
            tool_name=normalized_tool,
            payload=stored_payload,
            created_at=created_at,
        )

    def list_after(
        self, ticket_id: str, *, after_id: int = 0, limit: int = 200
    ) -> list[InvestigationEvent]:
        ticket = _required(ticket_id, "ticket_id")
        if after_id < 0:
            raise ValueError("after_id must be non-negative")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM investigation_events
                WHERE ticket_id=? AND id>?
                ORDER BY id ASC LIMIT ?
                """,
                (ticket, after_id, limit),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def latest_for_ticket(self, ticket_id: str) -> InvestigationEvent | None:
        ticket = _required(ticket_id, "ticket_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM investigation_events
                WHERE ticket_id=? ORDER BY id DESC LIMIT 1
                """,
                (ticket,),
            ).fetchone()
        return _from_row(row) if row else None


def _serialize_payload(
    payload: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    if payload is None:
        return None, None
    try:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be JSON serializable") from exc
    size = len(encoded.encode("utf-8"))
    stored = payload
    if size > MAX_EVENT_PAYLOAD_BYTES:
        stored = {"truncated": True, "original_bytes": size}
        encoded = json.dumps(stored, separators=(",", ":"), sort_keys=True)
    return encoded, stored


def _from_row(row: sqlite3.Row) -> InvestigationEvent:
    return InvestigationEvent(
        id=int(row["id"]),
        ticket_id=row["ticket_id"],
        case_id=row["case_id"],
        agent_id=row["agent_id"],
        event_type=InvestigationEventType(row["event_type"]),
        status=row["status"],
        summary=row["summary"],
        tool_name=row["tool_name"],
        payload=json.loads(row["payload_json"]) if row["payload_json"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _required(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _optional(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized[:max_length] or None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
