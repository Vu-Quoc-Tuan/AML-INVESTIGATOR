"""Regression tests for legal enrichment correctness bugs."""

from app.investigation_orchestrator.agents import (
    _default_risk_level,
    _fallback_behavior_mapping,
    _legal_mappings_from_case_file,
    _sanitize_behavior_mapping,
)
from app.investigation_orchestrator.evidence_validator import validate_evidence
from app.legal_rag.config import LegalRagConfig
from app.legal_rag.hybrid_retriever import LegalHit
from app.legal_rag.tool_adapter import hits_to_boundary


def test_fallback_without_scout_findings_creates_no_legal_queries() -> None:
    mapping = _fallback_behavior_mapping(
        {"case_id": "C", "case_file": {"findings": []}, "agent_outputs": {}}
    )
    assert mapping["rag_queries"] == []


def test_legal_only_does_not_escalate_risk_to_high() -> None:
    hit = LegalHit(
        article="Điều 324",
        article_number=324,
        chapter="X",
        section="Y",
        document="...",
        score=-0.2,
        chunk_id="chunk-324",
    )
    boundary = hits_to_boundary(
        query_id="RQ-1",
        query_text="rửa tiền",
        hits=[hit],
        linked_finding_ids=["F-TX"],  # linked, but scout not in case findings
        config=LegalRagConfig(),
    )
    # No scout findings in case_file -> legal citation fails validation
    validation, case = validate_evidence(
        {"case_id": "C", "findings": [], "evidence": []},
        legal_output={
            "agent": "legal",
            "status": "COMPLETED",
            "available": True,
            "findings": [
                {
                    "finding_id": "L1",
                    "finding_type": "LEGAL_CITATION",
                    "summary": "legal",
                    "evidence_ids": [boundary.evidence[0]["evidence_id"]],
                    "visibility_level": "FULL_INTERNAL",
                }
            ],
            "evidence": boundary.evidence,
        },
    )
    assert validation["status"] == "FAILED"
    assert case["findings"] == []
    assert _default_risk_level(case, validation) == "INCONCLUSIVE"


def test_legal_hit_with_scout_finding_does_not_force_high_risk() -> None:
    scout = {
        "finding_id": "F-TX",
        "finding_type": "TRANSACTION_PATTERN",
        "summary": "pass-through",
        "evidence_ids": ["E-TX"],
        "visibility_level": "FULL_INTERNAL",
    }
    hit = LegalHit(
        article="Điều 324",
        article_number=324,
        chapter="X",
        section="Y",
        document="...",
        score=0.9,
        chunk_id="chunk-324",
    )
    boundary = hits_to_boundary(
        query_id="RQ-1",
        query_text="rửa tiền",
        hits=[hit],
        linked_finding_ids=["F-TX"],
        config=LegalRagConfig(),
    )
    validation, case = validate_evidence(
        {
            "case_id": "C",
            "findings": [scout],
            "evidence": [
                {
                    "evidence_id": "E-TX",
                    "source_system": "SHB_TRANSACTION_LEDGER",
                    "source_record_id": "TX-1",
                    "visibility_level": "FULL_INTERNAL",
                }
            ],
        },
        legal_output={
            "agent": "legal",
            "status": "COMPLETED",
            "available": True,
            "findings": [
                {
                    "finding_id": "L1",
                    "finding_type": "LEGAL_CITATION",
                    "summary": "legal",
                    "evidence_ids": [boundary.evidence[0]["evidence_id"]],
                    "visibility_level": "FULL_INTERNAL",
                }
            ],
            "evidence": boundary.evidence,
        },
    )
    assert validation["status"] == "PASSED"
    assert _default_risk_level(case, validation) == "MEDIUM"


def test_duplicate_evidence_ids_across_queries_are_unique() -> None:
    hit = LegalHit(
        article="Điều 324",
        article_number=324,
        chapter="X",
        section="Y",
        document="...",
        score=0.5,
        chunk_id="chunk-324-demo",
    )
    b1 = hits_to_boundary(
        query_id="Q1",
        query_text="a",
        hits=[hit],
        linked_finding_ids=["F1"],
        config=LegalRagConfig(),
    )
    b2 = hits_to_boundary(
        query_id="Q2",
        query_text="b",
        hits=[hit],
        linked_finding_ids=["F2"],
        config=LegalRagConfig(),
    )
    assert b1.evidence[0]["evidence_id"] != b2.evidence[0]["evidence_id"]
    validation, case = validate_evidence(
        {
            "case_id": "C",
            "findings": [
                {
                    "finding_id": "F1",
                    "finding_type": "TRANSACTION_PATTERN",
                    "summary": "a",
                    "evidence_ids": ["E1"],
                    "visibility_level": "FULL_INTERNAL",
                },
                {
                    "finding_id": "F2",
                    "finding_type": "TRANSACTION_PATTERN",
                    "summary": "b",
                    "evidence_ids": ["E2"],
                    "visibility_level": "FULL_INTERNAL",
                },
            ],
            "evidence": [
                {
                    "evidence_id": "E1",
                    "source_system": "SHB_TRANSACTION_LEDGER",
                    "source_record_id": "T1",
                    "visibility_level": "FULL_INTERNAL",
                },
                {
                    "evidence_id": "E2",
                    "source_system": "SHB_TRANSACTION_LEDGER",
                    "source_record_id": "T2",
                    "visibility_level": "FULL_INTERNAL",
                },
            ],
        },
        legal_output={
            "agent": "legal",
            "status": "COMPLETED",
            "findings": [
                {
                    "finding_id": "L1",
                    "finding_type": "LEGAL_CITATION",
                    "summary": "q1",
                    "evidence_ids": [b1.evidence[0]["evidence_id"]],
                    "visibility_level": "FULL_INTERNAL",
                },
                {
                    "finding_id": "L2",
                    "finding_type": "LEGAL_CITATION",
                    "summary": "q2",
                    "evidence_ids": [b2.evidence[0]["evidence_id"]],
                    "visibility_level": "FULL_INTERNAL",
                },
            ],
            "evidence": b1.evidence + b2.evidence,
        },
    )
    assert validation["status"] == "PASSED"
    legal_ids = [
        item["evidence_id"]
        for item in case["evidence"]
        if item.get("source_system") == "VN_PENAL_CODE_RAG"
    ]
    assert len(legal_ids) == 2
    assert len(set(legal_ids)) == 2


def test_report_mappings_use_scout_finding_ids_not_legal_finding_ids() -> None:
    case = {
        "findings": [
            {
                "finding_id": "F-TX",
                "finding_type": "TRANSACTION_PATTERN",
                "summary": "pass-through",
                "evidence_ids": ["E-TX"],
                "visibility_level": "FULL_INTERNAL",
            },
            {
                "finding_id": "L-LEGAL",
                "finding_type": "LEGAL_CITATION",
                "summary": "Điều 324 may relate",
                "evidence_ids": ["EV-LEGAL"],
            },
        ],
        "evidence": [
            {
                "evidence_id": "E-TX",
                "source_system": "SHB_TRANSACTION_LEDGER",
                "source_record_id": "TX",
                "visibility_level": "FULL_INTERNAL",
            },
            {
                "evidence_id": "EV-LEGAL",
                "source_system": "VN_PENAL_CODE_RAG",
                "source_record_id": "law",
                "payload": {
                    "article": "Điều 324",
                    "linked_finding_ids": ["F-TX"],
                    "query_id": "RQ-1",
                },
            },
        ],
    }
    mappings = _legal_mappings_from_case_file(case)
    assert mappings
    assert mappings[0]["finding_ids"] == ["F-TX"]
    assert "L-LEGAL" not in mappings[0]["finding_ids"]
    assert mappings[0]["article"] == "Điều 324"


def test_sanitize_drops_ungrounded_llm_queries() -> None:
    state = {
        "case_id": "C",
        "case_file": {
            "findings": [
                {
                    "finding_id": "F-REAL",
                    "finding_type": "TRANSACTION_PATTERN",
                    "summary": "real",
                    "evidence_ids": ["E1"],
                    "visibility_level": "FULL_INTERNAL",
                }
            ]
        },
        "agent_outputs": {},
    }
    cleaned = _sanitize_behavior_mapping(
        {
            "behavior_summary": "summary",
            "rag_queries": [
                {
                    "query_id": "RQ-BAD",
                    "query_text": "hallucinated link",
                    "linked_finding_ids": ["F-FAKE"],
                },
                {
                    "query_id": "RQ-GOOD",
                    "query_text": "grounded query",
                    "linked_finding_ids": ["F-REAL"],
                },
            ],
        },
        state,
    )
    assert len(cleaned["rag_queries"]) == 1
    assert cleaned["rag_queries"][0]["query_id"] == "RQ-GOOD"


def test_query_without_linked_findings_yields_no_data_boundary() -> None:
    hit = LegalHit(
        article="Điều 324",
        article_number=324,
        chapter="X",
        section="Y",
        document="...",
        score=1.0,
        chunk_id="c",
    )
    boundary = hits_to_boundary(
        query_id="RQ-1",
        query_text="x",
        hits=[hit],
        linked_finding_ids=[],
        config=LegalRagConfig(),
    )
    assert boundary.status == "NO_DATA"
    assert boundary.evidence == []
