import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.detection.contracts import (
    CandidateStatus, DecisionKind, DetectionDecision, RunMode, RunTrigger,
)
from app.detection.repository import (
    CandidateBusyError,
    ConflictingOutcomeError,
    DetectionRepository,
    ModeMismatchError,
)
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


NOW = datetime(2026, 7, 19, tzinfo=UTC)


def event(event_id="evt-1") -> TransactionEventV1:
    return TransactionEventV1.model_validate({
        "event_id": event_id, "transaction_id": f"tx-{event_id}",
        "occurred_at": NOW, "ingested_at": NOW,
        "source_account_ref": "src", "destination_account_ref": "dst",
        "source_bank_id": HOME_BANK_ID, "destination_bank_id": HOME_BANK_ID,
        "amount": 100, "currency": "VND", "direction": "INTERNAL",
        "data_visibility": "FULL_INTERNAL",
    })


def decision(kind: DecisionKind) -> DetectionDecision:
    return DetectionDecision(kind, 0.7 if kind is DecisionKind.QUEUED else 0.999, "m1")


def repo(tmp_path: Path, **kwargs) -> DetectionRepository:
    return DetectionRepository(tmp_path / "queue.db", **kwargs)


def test_stores_blocked_and_queued_separately_and_idempotently(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    blocked_id = repository.record_blocked(event("b"), decision(DecisionKind.BLOCKED))
    assert repository.record_blocked(event("b"), decision(DecisionKind.BLOCKED)) == blocked_id
    candidate_id = repository.enqueue_candidate(event("q"), decision(DecisionKind.QUEUED))
    assert repository.enqueue_candidate(event("q"), decision(DecisionKind.QUEUED)) == candidate_id
    assert repository.count("blocked_transactions") == 1
    assert repository.count("investigation_candidates") == 1


def test_replay_cannot_change_durable_outcome(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    repository.record_blocked(event(), decision(DecisionKind.BLOCKED))
    with pytest.raises(ConflictingOutcomeError):
        repository.enqueue_candidate(event(), decision(DecisionKind.QUEUED))


def test_manual_cannot_claim_in_auto_and_auto_is_noop_in_manual(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    repository.enqueue_candidate(event(), decision(DecisionKind.QUEUED))
    assert repository.claim_next(RunTrigger.AUTO, now=NOW) is None
    repository.set_mode(RunMode.AUTO)
    with pytest.raises(ModeMismatchError):
        repository.claim_next(RunTrigger.MANUAL, now=NOW)
    assert repository.claim_next(RunTrigger.AUTO, now=NOW).status is CandidateStatus.PROCESSING


def test_claim_is_fifo_and_attempts_increment(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    first_id = repository.enqueue_candidate(event("1"), decision(DecisionKind.QUEUED))
    repository.enqueue_candidate(event("2"), decision(DecisionKind.QUEUED))
    claimed = repository.claim_next(RunTrigger.MANUAL, now=NOW)
    assert claimed.candidate_id == first_id
    assert claimed.attempts == 1


def test_failed_candidate_retries_only_to_limit(tmp_path: Path) -> None:
    repository = repo(tmp_path, max_attempts=2, retry_delay_seconds=5)
    repository.enqueue_candidate(event(), decision(DecisionKind.QUEUED))
    first = repository.claim_next(RunTrigger.MANUAL, now=NOW)
    repository.mark_failed(first.candidate_id, "secret\n" + "x" * 800, now=NOW)
    assert repository.claim_next(
        RunTrigger.MANUAL, now=NOW + timedelta(seconds=4)
    ) is None
    second = repository.claim_next(RunTrigger.MANUAL, now=NOW + timedelta(seconds=5))
    assert second.attempts == 2
    repository.mark_failed(second.candidate_id, "again", now=NOW + timedelta(seconds=5))
    assert repository.claim_next(RunTrigger.MANUAL, now=NOW + timedelta(seconds=20)) is None


def test_explicit_manual_retry_does_not_wait_for_auto_retry_delay(tmp_path: Path) -> None:
    repository = repo(tmp_path, max_attempts=2, retry_delay_seconds=300)
    candidate_id = repository.enqueue_candidate(event(), decision(DecisionKind.QUEUED))
    first = repository.claim_candidate(candidate_id, RunTrigger.MANUAL, now=NOW)
    repository.mark_failed(first.candidate_id, "tool failed", now=NOW)

    retried = repository.claim_candidate(
        candidate_id,
        RunTrigger.MANUAL,
        now=NOW + timedelta(seconds=1),
    )

    assert retried.status is CandidateStatus.PROCESSING
    assert retried.attempts == 2


def test_expired_processing_lease_can_be_reclaimed(tmp_path: Path) -> None:
    repository = repo(tmp_path, lease_seconds=5)
    repository.enqueue_candidate(event(), decision(DecisionKind.QUEUED))
    first = repository.claim_next(RunTrigger.MANUAL, now=NOW)
    assert repository.claim_next(RunTrigger.MANUAL, now=NOW + timedelta(seconds=4)) is None
    reclaimed = repository.claim_next(RunTrigger.MANUAL, now=NOW + timedelta(seconds=6))
    assert reclaimed.candidate_id == first.candidate_id
    assert reclaimed.attempts == 2


def test_completion_persists_case_id_and_result(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    repository.enqueue_candidate(event(), decision(DecisionKind.QUEUED))
    claimed = repository.claim_next(RunTrigger.MANUAL, now=NOW)
    repository.mark_completed(
        claimed.candidate_id,
        "case-1",
        result={"case_id": "case-1", "overall_risk_level": "MEDIUM"},
    )
    with sqlite3.connect(repository.db_path) as connection:
        row = connection.execute(
            "SELECT status,case_id,result_json FROM investigation_candidates"
        ).fetchone()
    assert row[0] == "COMPLETED"
    assert row[1] == "case-1"
    assert "MEDIUM" in row[2]
    stored = repository.get_candidate(claimed.candidate_id)
    assert stored is not None
    assert stored.result == {"case_id": "case-1", "overall_risk_level": "MEDIUM"}


def test_list_candidates_filters_by_status(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    first = repository.enqueue_candidate(event("1"), decision(DecisionKind.QUEUED))
    repository.enqueue_candidate(event("2"), decision(DecisionKind.QUEUED))
    claimed = repository.claim_next(RunTrigger.MANUAL, now=NOW)
    repository.mark_completed(claimed.candidate_id, "case-1")
    pending = repository.list_candidates(status=CandidateStatus.PENDING)
    completed = repository.list_candidates(status=CandidateStatus.COMPLETED)
    assert len(pending) == 1
    assert pending[0].event_id == "2"
    assert len(completed) == 1
    assert completed[0].candidate_id == first


def test_schema_uses_wal_and_version_three(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    with sqlite3.connect(repository.db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(investigation_candidates)")
        }
        assert "result_json" in columns


def test_concurrent_claims_never_return_same_candidate(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    repository.enqueue_candidate(event("1"), decision(DecisionKind.QUEUED))
    repository.enqueue_candidate(event("2"), decision(DecisionKind.QUEUED))
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(
            executor.map(
                lambda _: repository.claim_next(RunTrigger.MANUAL, now=NOW),
                range(2),
            )
        )
    assert len({claim.candidate_id for claim in claims}) == 2


def test_single_run_claim_allows_only_one_active_candidate(tmp_path: Path) -> None:
    repository = repo(tmp_path)
    candidate_ids = [
        repository.enqueue_candidate(event(str(index)), decision(DecisionKind.QUEUED))
        for index in range(2)
    ]

    def claim(candidate_id: str):
        try:
            return repository.claim_candidate(
                candidate_id,
                RunTrigger.MANUAL,
                now=NOW,
                require_idle=True,
            )
        except (CandidateBusyError, RuntimeError) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, candidate_ids))

    claimed = [item for item in results if not isinstance(item, Exception)]
    rejected = [item for item in results if isinstance(item, Exception)]
    assert len(claimed) == 1
    assert len(rejected) == 1
    assert len(repository.list_candidates(status=CandidateStatus.PROCESSING)) == 1
