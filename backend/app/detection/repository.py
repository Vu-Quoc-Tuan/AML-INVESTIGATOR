"""SQLite persistence for blocked outcomes and deferred investigations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from app.streaming.schemas import TransactionEventV1

from .contracts import (
    CandidateRecord,
    CandidateStatus,
    DecisionKind,
    DetectionDecision,
    ReviewDecision,
    RuleHit,
    RunMode,
    RunTrigger,
)


class ModeMismatchError(RuntimeError):
    """Raised when a manual run is attempted while AUTO mode is active."""


class CandidateBusyError(RuntimeError):
    """Raised when a single-run claim would overlap another active candidate."""


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
                    result_json TEXT,
                    review_decision TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_claim
                    ON investigation_candidates(status, created_at);
                """
            )
            self._ensure_candidate_columns(connection)
            connection.execute("PRAGMA user_version = 3")
            connection.execute(
                "INSERT OR IGNORE INTO detection_settings(key, value) VALUES('run_mode', ?)",
                (self.initial_mode.value,),
            )

    @staticmethod
    def _ensure_candidate_columns(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(investigation_candidates)")
        }
        if "result_json" not in columns:
            connection.execute(
                "ALTER TABLE investigation_candidates ADD COLUMN result_json TEXT"
            )
        if "review_decision" not in columns:
            connection.execute(
                "ALTER TABLE investigation_candidates ADD COLUMN review_decision TEXT"
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

    def claim_candidate(
        self,
        candidate_id: str,
        trigger: RunTrigger,
        *,
        now: datetime | None = None,
        require_idle: bool = False,
    ) -> CandidateRecord:
        """Claim one specific candidate for a single-ticket investigation."""

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
                raise ModeMismatchError("auto claim disabled while MANUAL mode is active")

            if require_idle:
                busy = connection.execute(
                    """
                    SELECT candidate_id FROM investigation_candidates
                    WHERE candidate_id != ? AND status = 'PROCESSING'
                        AND lease_until > ?
                    LIMIT 1
                    """,
                    (candidate_id, now_text),
                ).fetchone()
                if busy is not None:
                    raise CandidateBusyError(
                        f"candidate {busy['candidate_id']} is already processing"
                    )

            failed_clause = (
                "status = 'FAILED'"
                if trigger is RunTrigger.MANUAL
                else "(status = 'FAILED' AND (lease_until IS NULL OR lease_until <= ?))"
            )
            parameters: tuple[Any, ...] = (
                (candidate_id, self.max_attempts, now_text)
                if trigger is RunTrigger.MANUAL
                else (candidate_id, self.max_attempts, now_text, now_text)
            )
            row = connection.execute(
                f"""
                SELECT * FROM investigation_candidates
                WHERE candidate_id=? AND attempts < ? AND (
                    status = 'PENDING' OR
                    {failed_clause} OR
                    (status = 'PROCESSING' AND lease_until <= ?)
                )
                """,
                parameters,
            ).fetchone()
            if row is None:
                raise RuntimeError("candidate is not claimable")
            connection.execute(
                """
                UPDATE investigation_candidates
                SET status='PROCESSING', attempts=attempts+1, lease_until=?,
                    last_error=NULL, updated_at=?
                WHERE candidate_id=?
                """,
                (lease_until, now_text, candidate_id),
            )
            return self._candidate_from_row(
                connection.execute(
                    "SELECT * FROM investigation_candidates WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchone()
            )

    def mark_completed(
        self,
        candidate_id: str,
        case_id: str,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        from .agent_adapter import is_laundering_suspect

        result_json = json.dumps(result, separators=(",", ":"), sort_keys=True) if result else None
        review: str | None = None
        if result and not is_laundering_suspect(
            result.get("overall_risk_level"), result.get("recommended_action")
        ):
            # Non-laundering investigations auto-close as FALSE (false positive).
            review = ReviewDecision.FALSE.value
        self._transition(
            candidate_id,
            "status='COMPLETED', case_id=?, result_json=?, review_decision=?, "
            "lease_until=NULL, last_error=NULL",
            (case_id, result_json, review),
        )

    def set_review_decision(
        self, candidate_id: str, decision: ReviewDecision
    ) -> CandidateRecord:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM investigation_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            if row["status"] != CandidateStatus.COMPLETED.value:
                raise RuntimeError("only COMPLETED tickets can be reviewed")
            if row["review_decision"]:
                raise RuntimeError("ticket already has a review decision")
            result_raw = row["result_json"]
            result = json.loads(result_raw) if result_raw else {}
            from .agent_adapter import is_laundering_suspect

            if decision in (ReviewDecision.APPROVED, ReviewDecision.REJECTED):
                if not is_laundering_suspect(
                    result.get("overall_risk_level"), result.get("recommended_action")
                ):
                    raise RuntimeError(
                        "APPROVE/REJECT only allowed when investigation flags laundering risk"
                    )
            connection.execute(
                """
                UPDATE investigation_candidates
                SET review_decision=?, updated_at=?
                WHERE candidate_id=?
                """,
                (decision.value, _iso(datetime.now(UTC)), candidate_id),
            )
            return self._candidate_from_row(
                connection.execute(
                    "SELECT * FROM investigation_candidates WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchone()
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

    def get_candidate(self, candidate_id: str) -> CandidateRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM investigation_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        return self._candidate_from_row(row) if row else None

    def list_candidates(
        self,
        *,
        status: CandidateStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CandidateRecord]:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        query = "SELECT * FROM investigation_candidates"
        params: list[Any] = []
        if status is not None:
            query += " WHERE status=?"
            params.append(status.value)
        query += " ORDER BY created_at DESC, candidate_id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._candidate_from_row(row) for row in rows]

    def flow_trends(self, *, days: int = 7, now: datetime | None = None) -> list[dict[str, Any]]:
        """Daily counts from durable detection outcomes (queued + blocked)."""

        if days < 1 or days > 90:
            raise ValueError("days must be between 1 and 90")
        end = (now or datetime.now(UTC)).astimezone(UTC).date()
        start = end - timedelta(days=days - 1)
        start_text = start.isoformat()
        end_text = (end + timedelta(days=1)).isoformat()

        with self._connect() as connection:
            queued_rows = connection.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
                FROM investigation_candidates
                WHERE created_at >= ? AND created_at < ?
                GROUP BY substr(created_at, 1, 10)
                """,
                (start_text, end_text),
            ).fetchall()
            blocked_rows = connection.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
                FROM blocked_transactions
                WHERE created_at >= ? AND created_at < ?
                GROUP BY substr(created_at, 1, 10)
                """,
                (start_text, end_text),
            ).fetchall()

        queued_map = {row["day"]: int(row["count"]) for row in queued_rows}
        blocked_map = {row["day"]: int(row["count"]) for row in blocked_rows}

        points: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            key = cursor.isoformat()
            queued = queued_map.get(key, 0)
            blocked = blocked_map.get(key, 0)
            points.append(
                {
                    "date": key,
                    "day": cursor.strftime("%a"),
                    "queued": queued,
                    "blocked": blocked,
                    # Chart series used by FE:
                    # volume = all durable detection outcomes that day
                    # flagged = investigation-queue candidates (not blocked)
                    "volume": queued + blocked,
                    "flagged": queued,
                }
            )
            cursor += timedelta(days=1)
        return points

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
        keys = set(row.keys())
        result_raw = row["result_json"] if "result_json" in keys else None
        review_raw = row["review_decision"] if "review_decision" in keys else None
        review = None
        if review_raw:
            try:
                review = ReviewDecision(review_raw)
            except ValueError:
                review = None
        return CandidateRecord(
            candidate_id=row["candidate_id"],
            event_id=row["event_id"],
            transaction_snapshot=json.loads(row["event_json"]),
            decision=_decision_from_json(row["decision_json"]),
            status=CandidateStatus(row["status"]),
            attempts=row["attempts"],
            case_id=row["case_id"],
            last_error=row["last_error"],
            result=json.loads(result_raw) if result_raw else None,
            review_decision=review,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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
