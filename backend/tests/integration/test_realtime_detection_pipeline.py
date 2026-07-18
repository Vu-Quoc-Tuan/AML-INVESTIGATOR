from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.detection.config import DetectionSettings
from app.detection.contracts import ModelPrediction, RunTrigger
from app.detection.features import RealtimeFeatureExtractor
from app.detection.repository import DetectionRepository
from app.detection.rules import RuleEngine
from app.detection.runner import InvestigationQueueRunner
from app.detection.worker import DetectionWorker
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1, canonical_json_bytes


class Consumer:
    def __init__(self): self.commits = []
    def commit(self, offsets): self.commits.append(offsets)


class Predictor:
    def __init__(self, confidence): self.confidence = confidence
    def predict(self, features):
        return ModelPrediction(self.confidence, "integration-model", features.imputed_features)


class Workflow:
    def __init__(self): self.calls = []
    def invoke(self, state, config): self.calls.append((state, config))


def record(event_id: str, offset: int):
    now = datetime(2026, 7, 19, 12, offset, tzinfo=UTC)
    event = TransactionEventV1.model_validate({
        "event_id": event_id, "transaction_id": f"tx-{event_id}",
        "occurred_at": now, "ingested_at": now, "source_account_ref": f"src-{event_id}",
        "destination_account_ref": f"dst-{event_id}", "source_bank_id": HOME_BANK_ID,
        "destination_bank_id": HOME_BANK_ID, "amount": 100, "currency": "VND",
        "direction": "INTERNAL", "data_visibility": "FULL_INTERNAL",
    })
    return SimpleNamespace(topic="aml.transactions.validated.v1", partition=0,
                           offset=offset, value=canonical_json_bytes(event))


def process(repository, confidence, item):
    consumer = Consumer()
    worker = DetectionWorker(
        consumer=consumer, repository=repository, rule_engine=RuleEngine(),
        feature_extractor=RealtimeFeatureExtractor(), predictor=Predictor(confidence),
        settings=DetectionSettings(),
    )
    try:
        decision = worker.process_record(item)
    finally:
        worker.close()
    return decision, consumer


def test_allowed_queued_blocked_and_deferred_agent_flow(tmp_path: Path) -> None:
    repository = DetectionRepository(tmp_path / "detection.db")

    allowed, allowed_consumer = process(repository, 0.2, record("allowed", 1))
    queued, queued_consumer = process(repository, 0.8, record("queued", 2))
    blocked, blocked_consumer = process(repository, 0.995, record("blocked", 3))

    assert allowed.kind.value == "ALLOWED"
    assert queued.kind.value == "QUEUED"
    assert blocked.kind.value == "BLOCKED"
    assert repository.count("investigation_candidates") == 1
    assert repository.count("blocked_transactions") == 1
    assert [next(iter(c.commits[0].values())).offset for c in
            (allowed_consumer, queued_consumer, blocked_consumer)] == [2, 3, 4]

    workflow = Workflow()
    summary = InvestigationQueueRunner(repository, lambda: workflow).drain(RunTrigger.MANUAL)
    assert summary.completed == 1
    assert len(workflow.calls) == 1
    assert workflow.calls[0][0]["alert"]["event_id"] == "queued"


def test_model_failure_leaves_offset_uncommitted(tmp_path: Path) -> None:
    class BrokenPredictor:
        def predict(self, features): raise RuntimeError("model unavailable")

    consumer = Consumer()
    worker = DetectionWorker(
        consumer=consumer, repository=DetectionRepository(tmp_path / "detection.db"),
        rule_engine=RuleEngine(), feature_extractor=RealtimeFeatureExtractor(),
        predictor=BrokenPredictor(), settings=DetectionSettings(),
    )
    with pytest.raises(RuntimeError, match="model unavailable"):
        worker.process_record(record("failed", 4))
    worker.close()
    assert consumer.commits == []

