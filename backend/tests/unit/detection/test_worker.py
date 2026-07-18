from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.detection.config import DetectionSettings
from app.detection.contracts import (
    DecisionKind, FeatureSnapshot, ModelPrediction, RuleEvaluation, RuleHit,
)
from app.detection.worker import DetectionWorker
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1, canonical_json_bytes


class ImmediateExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, function, *args):
        self.calls.append(function)
        try:
            value, error = function(*args), None
        except Exception as exc:
            value, error = None, exc
        return SimpleNamespace(result=lambda: (_raise(error) if error else value))


def _raise(error):
    raise error


class Consumer:
    def __init__(self): self.commits = []
    def commit(self, offsets): self.commits.append(offsets)


class Repository:
    def __init__(self):
        self.blocked = []
        self.queued = []

    def record_blocked(self, event, decision): self.blocked.append(event.event_id)
    def enqueue_candidate(self, event, decision): self.queued.append(event.event_id)


class Rules:
    def __init__(self, result=None, error=None):
        self.result = result or RuleEvaluation()
        self.error = error

    def evaluate(self, event, enrichment):
        if self.error:
            raise self.error
        return self.result


class Features:
    def __init__(self): self.observed = []
    def extract(self, event, enrichment): return FeatureSnapshot(("x",), (1.0,))
    def observe(self, event): self.observed.append(event.event_id)


class Predictor:
    def __init__(self, confidence=0.1, error=None):
        self.confidence = confidence
        self.error = error

    def predict(self, features):
        if self.error:
            raise self.error
        return ModelPrediction(self.confidence, "test")


def record():
    now = datetime(2026, 7, 19, tzinfo=UTC)
    event = TransactionEventV1.model_validate({
        "event_id": "evt", "transaction_id": "tx", "occurred_at": now,
        "ingested_at": now, "source_account_ref": "src",
        "destination_account_ref": "dst", "source_bank_id": HOME_BANK_ID,
        "destination_bank_id": HOME_BANK_ID, "amount": 100, "currency": "VND",
        "direction": "INTERNAL", "data_visibility": "FULL_INTERNAL",
    })
    return SimpleNamespace(topic="aml.transactions.validated.v1", partition=2,
                           offset=9, value=canonical_json_bytes(event))


def worker(confidence=0.1, rules=None, model_error=None):
    consumer, repository, executor = Consumer(), Repository(), ImmediateExecutor()
    instance = DetectionWorker(
        consumer=consumer, repository=repository, rule_engine=rules or Rules(),
        feature_extractor=Features(), predictor=Predictor(confidence, model_error),
        settings=DetectionSettings(), executor=executor,
    )
    return instance, consumer, repository, executor


@pytest.mark.parametrize(
    ("confidence", "kind", "blocked", "queued"),
    [(0.1, DecisionKind.ALLOWED, [], []),
     (0.7, DecisionKind.QUEUED, [], ["evt"]),
     (0.99, DecisionKind.BLOCKED, ["evt"], [])],
)
def test_decision_persists_exactly_required_outcome_then_commits(
    confidence, kind, blocked, queued
):
    instance, consumer, repository, executor = worker(confidence)
    assert instance.process_record(record()).kind is kind
    assert repository.blocked == blocked
    assert repository.queued == queued
    assert next(iter(consumer.commits[0].values())).offset == 10
    assert len(executor.calls) == 2


def test_rule_hit_queues_low_ml_result() -> None:
    rules = Rules(RuleEvaluation((RuleHit("R1", "hit"),)))
    instance, _, repository, _ = worker(0.1, rules)
    assert instance.process_record(record()).kind is DecisionKind.QUEUED
    assert repository.queued == ["evt"]


@pytest.mark.parametrize("error_source", ["rules", "model"])
def test_scoring_failure_does_not_commit(error_source) -> None:
    rules = Rules(error=RuntimeError("rule failed")) if error_source == "rules" else None
    model_error = RuntimeError("model failed") if error_source == "model" else None
    instance, consumer, repository, _ = worker(0.1, rules, model_error)
    with pytest.raises(RuntimeError):
        instance.process_record(record())
    assert consumer.commits == []
    assert repository.blocked == repository.queued == []
