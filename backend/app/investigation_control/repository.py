"""SQLite repository for control configuration and background run state."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from app.detection.contracts import RunMode, RunTrigger
from app.investigation_orchestrator.agent_config import AgentSettingsBundle

from .contracts import (
    ControlConfiguration,
    ControlSummary,
    InvestigationRun,
    QueueCounts,
    RunStatus,
)


ACTIVE_STATUSES = (RunStatus.PENDING.value, RunStatus.RUNNING.value)


class ControlConflictError(RuntimeError):
    """Requested control transition conflicts with persisted state."""


class InvestigationControlRepository:
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
        now = _iso(datetime.now(UTC))
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS detection_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS investigation_runs (
                    run_id TEXT PRIMARY KEY,
                    trigger TEXT NOT NULL CHECK(trigger IN ('AUTO','MANUAL')),
                    status TEXT NOT NULL CHECK(status IN (
                        'PENDING','RUNNING','COMPLETED',
                        'COMPLETED_WITH_ERRORS','FAILED','INTERRUPTED'
                    )),
                    soft_prompt_snapshot TEXT,
                    agent_settings_snapshot TEXT,
                    completed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_investigation_runs_status_created
                    ON investigation_runs(status, created_at DESC);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO detection_settings(key,value) VALUES('run_mode','MANUAL')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO detection_settings(key,value) VALUES('soft_prompt','')"
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO detection_settings(key,value)
                VALUES('soft_prompt_updated_at',?)
                """,
                (now,),
            )
            connection.execute(
                "INSERT OR IGNORE INTO detection_settings(key,value) VALUES('selected_llm_id','')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO detection_settings(key,value) VALUES('agent_settings','{}')"
            )
            self._ensure_column(
                connection,
                "investigation_runs",
                "agent_settings_snapshot",
                "TEXT",
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, decl: str
    ) -> None:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def get_agent_settings(self) -> AgentSettingsBundle:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM detection_settings WHERE key='agent_settings'"
            ).fetchone()
        raw: dict[str, Any] = {}
        if row and row["value"]:
            try:
                parsed = json.loads(row["value"])
                if isinstance(parsed, dict):
                    raw = parsed
            except json.JSONDecodeError:
                raw = {}
        return AgentSettingsBundle.from_storage(raw)

    def set_agent_settings(self, bundle: AgentSettingsBundle) -> AgentSettingsBundle:
        payload = json.dumps(bundle.to_storage_dict(), separators=(",", ":"), sort_keys=True)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO detection_settings(key,value) VALUES('agent_settings',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (payload,),
            )
        return bundle

    def get_selected_llm_id(self) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM detection_settings WHERE key='selected_llm_id'"
            ).fetchone()
        if row is None:
            return None
        value = (row["value"] or "").strip()
        return value or None

    def set_selected_llm_id(self, profile_id: str) -> str:
        cleaned = (profile_id or "").strip()
        if not cleaned:
            raise ValueError("profile_id must not be empty")
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO detection_settings(key,value) VALUES('selected_llm_id',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (cleaned,),
            )
        return cleaned

    def get_configuration(self) -> ControlConfiguration:
        with self._connect() as connection:
            values = dict(
                connection.execute(
                    """
                    SELECT key,value FROM detection_settings
                    WHERE key IN ('soft_prompt','soft_prompt_updated_at')
                    """
                ).fetchall()
            )
        return ControlConfiguration(
            soft_prompt=values.get("soft_prompt") or None,
            updated_at=_datetime(values["soft_prompt_updated_at"]),
        )

    def set_soft_prompt(
        self, value: str | None, *, now: datetime | None = None
    ) -> ControlConfiguration:
        changed_at = _aware(now or datetime.now(UTC))
        validated = ControlConfiguration(soft_prompt=value, updated_at=changed_at)
        with self._transaction() as connection:
            connection.execute(
                "UPDATE detection_settings SET value=? WHERE key='soft_prompt'",
                (validated.soft_prompt or "",),
            )
            connection.execute(
                """
                UPDATE detection_settings SET value=?
                WHERE key='soft_prompt_updated_at'
                """,
                (_iso(changed_at),),
            )
        return validated

    def get_summary(self) -> ControlSummary:
        with self._connect() as connection:
            mode = RunMode(
                connection.execute(
                    "SELECT value FROM detection_settings WHERE key='run_mode'"
                ).fetchone()["value"]
            )
            counts = {status: 0 for status in ("PENDING", "PROCESSING", "COMPLETED", "FAILED")}
            review_counts = {"APPROVED": 0, "REJECTED": 0, "FALSE": 0}
            table_exists = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='investigation_candidates'
                """
            ).fetchone()
            if table_exists:
                for row in connection.execute(
                    "SELECT status,COUNT(*) AS count FROM investigation_candidates GROUP BY status"
                ):
                    if row["status"] in counts:
                        counts[row["status"]] = int(row["count"])
                # review_decision may be missing on older DBs before migration
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(investigation_candidates)"
                    )
                }
                if "review_decision" in columns:
                    for row in connection.execute(
                        """
                        SELECT review_decision, COUNT(*) AS count
                        FROM investigation_candidates
                        WHERE review_decision IS NOT NULL AND review_decision != ''
                        GROUP BY review_decision
                        """
                    ):
                        key = row["review_decision"]
                        if key in review_counts:
                            review_counts[key] = int(row["count"])
            active = self._active_row(connection)
        return ControlSummary(
            mode=mode,
            queue=QueueCounts(
                pending=counts["PENDING"],
                processing=counts["PROCESSING"],
                completed=counts["COMPLETED"],
                failed=counts["FAILED"],
                approved=review_counts["APPROVED"],
                rejected=review_counts["REJECTED"],
                false_positive=review_counts["FALSE"],
            ),
            active_run=self._run_from_row(active) if active else None,
        )

    def set_mode(self, mode: RunMode) -> RunMode:
        with self._transaction() as connection:
            if self._active_row(connection):
                raise ControlConflictError("cannot change mode while an active run exists")
            connection.execute(
                "UPDATE detection_settings SET value=? WHERE key='run_mode'",
                (mode.value,),
            )
        return mode

    def create_run(
        self, trigger: RunTrigger, *, now: datetime | None = None
    ) -> InvestigationRun:
        created_at = _aware(now or datetime.now(UTC))
        with self._transaction() as connection:
            mode = RunMode(
                connection.execute(
                    "SELECT value FROM detection_settings WHERE key='run_mode'"
                ).fetchone()["value"]
            )
            if mode.value != trigger.value:
                raise ControlConflictError(
                    f"trigger {trigger.value} conflicts with persisted mode {mode.value}"
                )
            if self._active_row(connection):
                raise ControlConflictError("an active run already exists")
            soft_prompt = connection.execute(
                "SELECT value FROM detection_settings WHERE key='soft_prompt'"
            ).fetchone()["value"]
            agent_settings_row = connection.execute(
                "SELECT value FROM detection_settings WHERE key='agent_settings'"
            ).fetchone()
            agent_settings_raw = (
                agent_settings_row["value"] if agent_settings_row else "{}"
            )
            run_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO investigation_runs(
                    run_id,trigger,status,soft_prompt_snapshot,agent_settings_snapshot,
                    completed_count,failed_count,created_at
                ) VALUES(?,?,?,?,?,0,0,?)
                """,
                (
                    run_id,
                    trigger.value,
                    RunStatus.PENDING.value,
                    soft_prompt or None,
                    agent_settings_raw or "{}",
                    _iso(created_at),
                ),
            )
            row = self._get_run_row(connection, run_id)
        return self._run_from_row(row)

    def get_run(self, run_id: str) -> InvestigationRun | None:
        with self._connect() as connection:
            row = self._get_run_row(connection, run_id)
        return self._run_from_row(row) if row else None

    def list_runs(self, limit: int = 20) -> list[InvestigationRun]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM investigation_runs
                ORDER BY created_at DESC,rowid DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def get_active_run(self) -> InvestigationRun | None:
        with self._connect() as connection:
            row = self._active_row(connection)
        return self._run_from_row(row) if row else None

    def start_run(
        self, run_id: str, *, now: datetime | None = None
    ) -> InvestigationRun:
        started_at = _aware(now or datetime.now(UTC))
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE investigation_runs SET status=?,started_at=?
                WHERE run_id=? AND status=?
                """,
                (
                    RunStatus.RUNNING.value,
                    _iso(started_at),
                    run_id,
                    RunStatus.PENDING.value,
                ),
            )
            self._require_transition(cursor, "run is not PENDING")
            row = self._get_run_row(connection, run_id)
        return self._run_from_row(row)

    def increment_progress(
        self, run_id: str, *, completed: int = 0, failed: int = 0
    ) -> None:
        if completed < 0 or failed < 0 or completed + failed <= 0:
            raise ValueError("progress increments must be non-negative and non-zero")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE investigation_runs
                SET completed_count=completed_count+?,failed_count=failed_count+?
                WHERE run_id=? AND status=?
                """,
                (completed, failed, run_id, RunStatus.RUNNING.value),
            )
            self._require_transition(cursor, "run is not RUNNING")

    def complete_run(
        self, run_id: str, *, now: datetime | None = None
    ) -> InvestigationRun:
        finished_at = _aware(now or datetime.now(UTC))
        with self._transaction() as connection:
            row = self._get_run_row(connection, run_id)
            if row is None or row["status"] != RunStatus.RUNNING.value:
                raise ControlConflictError("run is not RUNNING")
            status = (
                RunStatus.COMPLETED_WITH_ERRORS
                if int(row["failed_count"]) > 0
                else RunStatus.COMPLETED
            )
            connection.execute(
                """
                UPDATE investigation_runs SET status=?,finished_at=?
                WHERE run_id=?
                """,
                (status.value, _iso(finished_at), run_id),
            )
            row = self._get_run_row(connection, run_id)
        return self._run_from_row(row)

    def fail_run(
        self,
        run_id: str,
        error_type: str,
        *,
        now: datetime | None = None,
    ) -> InvestigationRun:
        finished_at = _aware(now or datetime.now(UTC))
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE investigation_runs SET status=?,finished_at=?,error=?
                WHERE run_id=? AND status IN (?,?)
                """,
                (
                    RunStatus.FAILED.value,
                    _iso(finished_at),
                    _safe_error_type(error_type),
                    run_id,
                    *ACTIVE_STATUSES,
                ),
            )
            self._require_transition(cursor, "run is not active")
            row = self._get_run_row(connection, run_id)
        return self._run_from_row(row)

    def interrupt_active_runs(self, *, now: datetime | None = None) -> int:
        interrupted_at = _aware(now or datetime.now(UTC))
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE investigation_runs
                SET status=?,finished_at=?,error='BackendRestart'
                WHERE status IN (?,?)
                """,
                (
                    RunStatus.INTERRUPTED.value,
                    _iso(interrupted_at),
                    *ACTIVE_STATUSES,
                ),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _active_row(connection: sqlite3.Connection) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM investigation_runs WHERE status IN (?,?)
            ORDER BY created_at,rowid LIMIT 1
            """,
            ACTIVE_STATUSES,
        ).fetchone()

    @staticmethod
    def _get_run_row(
        connection: sqlite3.Connection, run_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM investigation_runs WHERE run_id=?", (run_id,)
        ).fetchone()

    @staticmethod
    def _require_transition(cursor: sqlite3.Cursor, message: str) -> None:
        if cursor.rowcount != 1:
            raise ControlConflictError(message)

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> InvestigationRun:
        keys = set(row.keys())
        agent_snapshot = None
        if "agent_settings_snapshot" in keys and row["agent_settings_snapshot"]:
            try:
                parsed = json.loads(row["agent_settings_snapshot"])
                if isinstance(parsed, dict):
                    agent_snapshot = parsed
            except json.JSONDecodeError:
                agent_snapshot = None
        return InvestigationRun(
            run_id=row["run_id"],
            trigger=RunTrigger(row["trigger"]),
            status=RunStatus(row["status"]),
            soft_prompt_snapshot=row["soft_prompt_snapshot"],
            agent_settings_snapshot=agent_snapshot,
            completed_count=row["completed_count"],
            failed_count=row["failed_count"],
            created_at=_datetime(row["created_at"]),
            started_at=_datetime(row["started_at"]) if row["started_at"] else None,
            finished_at=_datetime(row["finished_at"]) if row["finished_at"] else None,
            error=row["error"],
        )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat(timespec="microseconds")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _safe_error_type(value: str) -> str:
    candidate = str(value).split(":", 1)[0].strip()
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", candidate)[:80]
    return normalized or "BackgroundRunError"

