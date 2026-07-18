"""SQLite persistence for blocked outcomes and deferred investigations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

from app.streaming.schemas import TransactionEventV1

from .contracts import (
    CandidateRecord,
    CandidateStatus,
    DecisionKind,
    DetectionDecision,
    RuleHit,
    RunMode,
    RunTrigger,
)


class ModeMismatchError(RuntimeError):
    """Raised when a manual run is attempted while AUTO mode is active."""


class ConflictingOutcomeError(RuntimeError):
    """Raised if a replay tries to change a durable event outcome."""


class DetectionRepository:
    def __init__(
        self,
        db_path: Path,
        *,
        initial_mode: RunMode = RunMode.MANUAL,
        lease_seconds: int = 1_800,
        retry_delay_seconds: int = 300,
        max_attempts: int = 3,
    ) -> None:
        self.db_path = Path(db_path)
        self.initial_mode = initial_mode
        self.lease_seconds = lease_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self.max_attempts = max_attempts
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE IF NOT EXISTS detection_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS blocked_transactions (
                    blocked_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    transaction_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    response_status TEXT NOT NULL CHECK(response_status = 'DELIVERED'),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS investigation_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    transaction_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_until TEXT,
                    last_error TEXT,
                    case_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_claim
                    ON investigation_candidates(status, created_at);
                PRAGMA user_version = 1;
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO detection_settings(key, value) VALUES('run_mode', ?)",
                (self.initial_mode.value,),
            )

    def record_blocked(
        self, event: TransactionEventV1, decision: DetectionDecision
    ) -> str:
        if decision.kind is not DecisionKind.BLOCKED:
            raise ValueError("record_blocked requires a BLOCKED decision")
        return self._record(event, decision, blocked=True)

    def enqueue_candidate(
        self, event: TransactionEventV1, decision: DetectionDecision
    ) -> str:
        if decision.kind is not DecisionKind.QUEUED:
            raise ValueError("enqueue_candidate requires a QUEUED decision")
        return self._record(event, decision, blocked=False)

    def _record(
        self,
        event: TransactionEventV1,
        decision: DetectionDecision,
        *,
        blocked: bool,
    ) -> str:
        expected_table = "blocked_transactions" if blocked else "investigation_candidates"
        expected_id = "blocked_id" if blocked else "candidate_id"
        other_table = "investigation_candidates" if blocked else "blocked_transactions"
        now = _iso(datetime.now(UTC))
        with self._transaction() as connection:
            existing = connection.execute(
                f"SELECT {expected_id} FROM {expected_table} WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing:
                return str(existing[expected_id])
            conflict = connection.execute(
                f"SELECT 1 FROM {other_table} WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if conflict:
                raise ConflictingOutcomeError(
                    f"event {event.event_id} already has a different durable outcome"
                )

            outcome_id = str(uuid.uuid4())
            event_json = event.model_dump_json()
            decision_json = _decision_json(decision)
            if blocked:
                connection.execute(
                    """
                    INSERT INTO blocked_transactions(
                        blocked_id,event_id,transaction_id,event_json,decision_json,
                        response_status,created_at
                    ) VALUES(?,?,?,?,?,'DELIVERED',?)
                    """,
                    (outcome_id, event.event_id, event.transaction_id, event_json,
                     decision_json, now),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO investigation_candidates(
                        candidate_id,event_id,transaction_id,event_json,decision_json,
                        status,attempts,created_at,updated_at
                    ) VALUES(?,?,?,?,?,'PENDING',0,?,?)
                    """,
                    (outcome_id, event.event_id, event.transaction_id, event_json,
                     decision_json, now, now),
                )
            return outcome_id

    def get_mode(self) -> RunMode:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM detection_settings WHERE key = 'run_mode'"
            ).fetchone()
        if row is None:
            raise RuntimeError("detection run mode is not initialized")
        return RunMode(row["value"])

    def set_mode(self, mode: RunMode) -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE detection_settings SET value = ? WHERE key = 'run_mode'",
                (mode.value,),
            )

    def claim_next(
        self, trigger: RunTrigger, *, now: datetime | None = None
    ) -> CandidateRecord | None:
        claimed_at = now or datetime.now(UTC)
        if claimed_at.tzinfo is None:
            raise ValueError("claim time must be timezone-aware")
        now_text = _iso(claimed_at)
        lease_until = _iso(claimed_at + timedelta(seconds=self.lease_seconds))
        with self._transaction() as connection:
            mode = RunMode(
                connection.execute(
                    "SELECT value FROM detection_settings WHERE key = 'run_mode'"
                ).fetchone()["value"]
            )
            if trigger is RunTrigger.MANUAL and mode is RunMode.AUTO:
                raise ModeMismatchError("manual run is disabled while AUTO mode is active")
            if trigger is RunTrigger.AUTO and mode is RunMode.MANUAL:
                return None

            row = connection.execute(
                """
                SELECT * FROM investigation_candidates
                WHERE attempts < ? AND (
                    status = 'PENDING' OR
                    (status = 'FAILED' AND (lease_until IS NULL OR lease_until <= ?)) OR
                    (status = 'PROCESSING' AND lease_until <= ?)
                )
                ORDER BY created_at, candidate_id
                LIMIT 1
                """,
                (self.max_attempts, now_text, now_text),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE investigation_candidates
                SET status='PROCESSING', attempts=attempts+1, lease_until=?,
                    last_error=NULL, updated_at=?
                WHERE candidate_id=?
                """,
                (lease_until, now_text, row["candidate_id"]),
            )
            return self._candidate_from_row(
                connection.execute(
                    "SELECT * FROM investigation_candidates WHERE candidate_id=?",
                    (row["candidate_id"],),
                ).fetchone()
            )

    def mark_completed(self, candidate_id: str, case_id: str) -> None:
        self._transition(
            candidate_id,
            "status='COMPLETED', case_id=?, lease_until=NULL, last_error=NULL",
            (case_id,),
        )

    def mark_failed(
        self, candidate_id: str, error: str, *, now: datetime | None = None
    ) -> None:
        safe_error = " ".join(str(error).split())[:500] or "investigation failed"
        failed_at = now or datetime.now(UTC)
        retry_at = _iso(failed_at + timedelta(seconds=self.retry_delay_seconds))
        self._transition(
            candidate_id,
            "status='FAILED', lease_until=?, last_error=?",
            (retry_at, safe_error),
        )

    def _transition(self, candidate_id: str, assignment: str, values: tuple) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                f"UPDATE investigation_candidates SET {assignment}, updated_at=? "
                "WHERE candidate_id=? AND status='PROCESSING'",
                (*values, _iso(datetime.now(UTC)), candidate_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("candidate is not currently PROCESSING")

    def count(self, table: str) -> int:
        if table not in {"blocked_transactions", "investigation_candidates"}:
            raise ValueError("unsupported table")
        with self._connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> CandidateRecord:
        return CandidateRecord(
            candidate_id=row["candidate_id"], event_id=row["event_id"],
            transaction_snapshot=json.loads(row["event_json"]),
            decision=_decision_from_json(row["decision_json"]),
            status=CandidateStatus(row["status"]), attempts=row["attempts"],
        )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _decision_json(decision: DetectionDecision) -> str:
    return json.dumps(
        {
            "kind": decision.kind.value,
            "confidence": decision.confidence,
            "model_version": decision.model_version,
            "rule_hits": [
                {"rule_id": hit.rule_id, "reason": hit.reason, "evidence": hit.evidence}
                for hit in decision.rule_hits
            ],
            "imputed_features": list(decision.imputed_features),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _decision_from_json(value: str) -> DetectionDecision:
    data = json.loads(value)
    return DetectionDecision(
        kind=DecisionKind(data["kind"]), confidence=float(data["confidence"]),
        model_version=data["model_version"],
        rule_hits=tuple(RuleHit(**hit) for hit in data["rule_hits"]),
        imputed_features=tuple(data["imputed_features"]),
    )
