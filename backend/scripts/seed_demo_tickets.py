#!/usr/bin/env python3
"""Seed demo investigation tickets for UI review (safe for local/docker)."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.detection.contracts import (
    DecisionKind,
    DetectionDecision,
    ReviewDecision,
    RuleHit,
    RunTrigger,
)
from app.detection.repository import DetectionRepository
from app.streaming.schemas import HOME_BANK_ID, TransactionEventV1


def main() -> None:
    db = Path(os.environ.get("DETECTION_DB_PATH", "data/detection_queue.db"))
    repo = DetectionRepository(db)
    now = datetime.now(UTC)

    def event(eid: str, amount: float = 50_000_000, minutes_ago: int = 0) -> TransactionEventV1:
        t = now - timedelta(minutes=minutes_ago)
        return TransactionEventV1.model_validate(
            {
                "event_id": eid,
                "transaction_id": f"TX-{eid}",
                "occurred_at": t,
                "ingested_at": t,
                "source_account_ref": f"ACC-SRC-{eid[-3:]}",
                "destination_account_ref": f"ACC-DST-{eid[-3:]}",
                "source_bank_id": HOME_BANK_ID,
                "destination_bank_id": HOME_BANK_ID,
                "amount": amount,
                "currency": "VND",
                "direction": "INTERNAL",
                "data_visibility": "FULL_INTERNAL",
            }
        )

    def queued(conf: float = 0.72, rules: tuple[RuleHit, ...] = ()) -> DetectionDecision:
        return DetectionDecision(DecisionKind.QUEUED, conf, "demo-seed-v1", rules)

    seeds: list[tuple] = []

    # 1-2 PENDING → nút Chạy
    for eid, amount, ago, conf, rules in (
        (
            "seed-pending-001",
            120_000_000,
            5,
            0.78,
            (RuleHit("R_VELOCITY", "high velocity fan-in", {"n": 12}),),
        ),
        ("seed-pending-002", 35_000_000, 15, 0.65, ()),
    ):
        cid = repo.enqueue_candidate(event(eid, amount, ago), queued(conf, rules))
        seeds.append(("PENDING", cid, eid))

    # 3 PROCESSING
    cid = repo.enqueue_candidate(
        event("seed-processing-001", 88_000_000, 30),
        queued(0.81, (RuleHit("R_STRUCT", "structuring pattern", {}),)),
    )
    repo.claim_candidate(cid, RunTrigger.MANUAL)
    seeds.append(("PROCESSING", cid, "seed-processing-001"))

    # 4 COMPLETED HIGH → APPROVE/REJECT
    cid = repo.enqueue_candidate(
        event("seed-high-001", 250_000_000, 60),
        queued(0.91, (RuleHit("R_LAYER", "layered transfers", {"hops": 4}),)),
    )
    repo.claim_candidate(cid, RunTrigger.MANUAL)
    repo.mark_completed(
        cid,
        f"AML-{cid}",
        result={
            "case_id": f"AML-{cid}",
            "phase": "complete",
            "overall_risk_level": "HIGH",
            "recommended_action": "ESCALATE_TO_COMPLIANCE",
            "risk_rationale": (
                "Layered transfers and high velocity inflows inconsistent with KYC."
            ),
            "agent_statuses": {
                "planner": "ok",
                "transaction": "ok",
                "kyc": "ok",
                "report": "ok",
            },
            "errors": [],
            "is_laundering_suspect": True,
        },
    )
    seeds.append(
        (
            "COMPLETED_HIGH",
            cid,
            "seed-high-001",
            repo.get_candidate(cid).review_decision,
        )
    )

    # 5 COMPLETED LOW → auto FALSE
    cid = repo.enqueue_candidate(
        event("seed-low-001", 2_500_000, 90),
        queued(0.61),
    )
    repo.claim_candidate(cid, RunTrigger.MANUAL)
    repo.mark_completed(
        cid,
        f"AML-{cid}",
        result={
            "case_id": f"AML-{cid}",
            "phase": "complete",
            "overall_risk_level": "LOW",
            "recommended_action": "NO_FURTHER_ACTION",
            "risk_rationale": "Payroll-like pattern with verified counterparties.",
            "agent_statuses": {"report": "ok"},
            "errors": [],
            "is_laundering_suspect": False,
        },
    )
    seeds.append(
        (
            "COMPLETED_LOW",
            cid,
            "seed-low-001",
            repo.get_candidate(cid).review_decision,
        )
    )

    # 6 APPROVED
    cid = repo.enqueue_candidate(
        event("seed-approved-001", 175_000_000, 120),
        queued(0.88),
    )
    repo.claim_candidate(cid, RunTrigger.MANUAL)
    repo.mark_completed(
        cid,
        f"AML-{cid}",
        result={
            "case_id": f"AML-{cid}",
            "phase": "complete",
            "overall_risk_level": "CRITICAL",
            "recommended_action": "CONSIDER_SAR",
            "risk_rationale": "Rapid pass-through to external accounts.",
            "agent_statuses": {"transaction": "ok", "report": "ok"},
            "errors": [],
            "is_laundering_suspect": True,
        },
    )
    repo.set_review_decision(cid, ReviewDecision.APPROVED)
    seeds.append(("APPROVED", cid, "seed-approved-001"))

    # 7 REJECTED
    cid = repo.enqueue_candidate(
        event("seed-rejected-001", 99_000_000, 150),
        queued(0.84),
    )
    repo.claim_candidate(cid, RunTrigger.MANUAL)
    repo.mark_completed(
        cid,
        f"AML-{cid}",
        result={
            "case_id": f"AML-{cid}",
            "phase": "complete",
            "overall_risk_level": "HIGH",
            "recommended_action": "ESCALATE",
            "risk_rationale": "Shared device cluster with shell-like entities.",
            "agent_statuses": {"kyc": "ok", "screening": "ok", "report": "ok"},
            "errors": [],
            "is_laundering_suspect": True,
        },
    )
    repo.set_review_decision(cid, ReviewDecision.REJECTED)
    seeds.append(("REJECTED", cid, "seed-rejected-001"))

    # 8 FAILED
    cid = repo.enqueue_candidate(
        event("seed-failed-001", 40_000_000, 180),
        queued(0.70),
    )
    repo.claim_candidate(cid, RunTrigger.MANUAL)
    repo.mark_failed(cid, "RuntimeError: investigation execution failed")
    seeds.append(("FAILED", cid, "seed-failed-001"))

    print(f"DB: {db.resolve()}")
    print("Seeded tickets:")
    for row in seeds:
        print(" ", row)

    con = sqlite3.connect(db)
    print("Counts by status:")
    for status, count in con.execute(
        "SELECT status, COUNT(*) FROM investigation_candidates GROUP BY status"
    ):
        print(f"  {status}: {count}")
    print("Counts by review_decision:")
    for decision, count in con.execute(
        "SELECT COALESCE(review_decision,'(null)'), COUNT(*) "
        "FROM investigation_candidates GROUP BY review_decision"
    ):
        print(f"  {decision}: {count}")
    print("total:", con.execute("SELECT COUNT(*) FROM investigation_candidates").fetchone()[0])


if __name__ == "__main__":
    main()
