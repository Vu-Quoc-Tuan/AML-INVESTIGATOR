from app.detection.agent_adapter import case_id_for, to_investigation_input
from app.detection.contracts import (
    CandidateRecord, CandidateStatus, DecisionKind, DetectionDecision, RuleHit,
)


def candidate() -> CandidateRecord:
    return CandidateRecord(
        candidate_id="candidate-1", event_id="evt-1",
        transaction_snapshot={"transaction_id": "tx-1", "amount": 100},
        decision=DetectionDecision(
            DecisionKind.QUEUED, 0.72, "m1", (RuleHit("R1", "reason"),),
            ("source_owner_age",),
        ),
        status=CandidateStatus.PROCESSING, attempts=1,
    )


def test_adapter_builds_minimal_existing_workflow_input() -> None:
    item = candidate()
    state = to_investigation_input(item)
    assert state["case_id"] == case_id_for(item) == "AML-candidate-1"
    assert state["alert"]["transaction"]["transaction_id"] == "tx-1"
    assert state["alert"]["detection"]["ml_confidence"] == 0.72
    assert state["alert"]["detection"]["rule_hits"][0]["rule_id"] == "R1"

