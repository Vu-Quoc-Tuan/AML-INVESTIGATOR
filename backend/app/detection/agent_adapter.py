"""Narrow adapter from a queued detection candidate to workflow input."""

from __future__ import annotations

from app.investigation_orchestrator import initial_state

from .contracts import CandidateRecord


def case_id_for(candidate: CandidateRecord) -> str:
    return f"AML-{candidate.candidate_id}"


def to_investigation_input(candidate: CandidateRecord) -> dict:
    decision = candidate.decision
    alert = {
        "source": "realtime_detection_queue",
        "candidate_id": candidate.candidate_id,
        "event_id": candidate.event_id,
        "transaction": candidate.transaction_snapshot,
        "detection": {
            "decision": decision.kind.value,
            "ml_confidence": decision.confidence,
            "model_version": decision.model_version,
            "rule_hits": [
                {
                    "rule_id": hit.rule_id,
                    "reason": hit.reason,
                    "evidence": hit.evidence,
                }
                for hit in decision.rule_hits
            ],
            "imputed_features": list(decision.imputed_features),
        },
    }
    return initial_state(case_id_for(candidate), alert)

