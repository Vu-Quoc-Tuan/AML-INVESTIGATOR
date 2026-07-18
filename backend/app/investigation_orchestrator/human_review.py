"""Human-in-the-loop interrupt and resume handling."""

from __future__ import annotations

from typing import Any, Literal, cast

from langgraph.types import Command, interrupt

from .state import InvestigationState, ReviewDecision, ReviewResult


ALLOWED_DECISIONS: set[str] = {
    "APPROVED",
    "REJECTED",
    "MORE_INFORMATION_REQUIRED",
}


def _validate_review(payload: Any) -> ReviewResult:
    if not isinstance(payload, dict):
        raise ValueError("Human review resume payload must be a dictionary")

    decision = payload.get("decision")
    if decision not in ALLOWED_DECISIONS:
        raise ValueError(f"Unsupported human review decision: {decision!r}")
    if decision == "MORE_INFORMATION_REQUIRED" and not payload.get("requested_target"):
        raise ValueError("requested_target is required when more information is requested")

    return {
        "decision": cast(ReviewDecision, decision),
        "reviewer": str(payload.get("reviewer", "unknown")),
        "comments": str(payload.get("comments", "")),
        "requested_target": str(payload.get("requested_target", "")),
    }


def human_review_node(
    state: InvestigationState,
) -> Command[Literal["supervisor"]]:
    """Pause the graph and resume only after a validated human decision."""

    payload = interrupt(
        {
            "case_id": state["case_id"],
            "report": state.get("report", {}),
            "allowed_decisions": sorted(ALLOWED_DECISIONS),
        }
    )
    review = _validate_review(payload)
    return Command(
        update={
            "human_review": review,
            "handoff_log": [
                {
                    "source": "human_review",
                    "target": "supervisor",
                    "reason": f"Reviewer selected {review['decision']}",
                }
            ],
        },
        goto="supervisor",
    )
