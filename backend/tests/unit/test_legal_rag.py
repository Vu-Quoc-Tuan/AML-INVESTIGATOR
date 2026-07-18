"""Unit tests for hybrid legal RAG tool boundary (no live Qdrant)."""

import json

from app.legal_rag.config import LegalRagConfig
from app.legal_rag.hybrid_retriever import LegalHit, StaticLegalRetriever
from app.legal_rag.tool_adapter import build_legal_tools, hits_to_boundary
from app.investigation_orchestrator.tool_registry import ToolRegistry, ToolResult


def test_hits_to_boundary_builds_legal_evidence_contract() -> None:
    hit = LegalHit(
        article="Điều 324",
        article_number=324,
        chapter="Chương X",
        section="Mục Y",
        document="Điều 324. Tội rửa tiền...",
        score=0.9,
        hybrid_score=0.1,
        chunk_id="chunk-324",
    )
    boundary = hits_to_boundary(
        query_id="RQ-1",
        query_text="rửa tiền pass-through",
        hits=[hit],
        linked_finding_ids=["F-1"],
        config=LegalRagConfig(),
    )
    assert boundary.status == "SUCCESS"
    assert boundary.evidence[0]["source_system"] == "VN_PENAL_CODE_RAG"
    assert boundary.evidence[0]["payload"]["article"] == "Điều 324"
    assert "rq-1" in boundary.evidence[0]["evidence_id"].lower()
    ToolResult.model_validate(boundary.model_dump(mode="json"))


def test_static_retriever_tool_invokes_successfully() -> None:
    tools = build_legal_tools(retriever=StaticLegalRetriever())
    registry = ToolRegistry()
    registry.register("legal", tools)
    tool = registry.get_tool("legal", "retrieve_penal_code_passages")
    out = tool.invoke(
        {
            "query_id": "RQ-1",
            "query_text": "tội rửa tiền",
            "top_k": 1,
            "linked_finding_ids": ["F-TX-1"],
        }
    )
    payload = json.loads(out) if isinstance(out, str) else out
    if isinstance(payload, tuple):
        payload = payload[1]
    assert payload["status"] == "SUCCESS"
    assert payload["data"]["hits"]
    assert payload["evidence"][0]["source_system"] == "VN_PENAL_CODE_RAG"


def test_empty_hits_are_no_data() -> None:
    class EmptyRetriever:
        def retrieve(self, query_text: str, *, top_k: int = 3):
            return []

    tools = build_legal_tools(retriever=EmptyRetriever())
    out = tools[0].invoke(
        {"query_id": "RQ-EMPTY", "query_text": "no hit expected", "top_k": 3}
    )
    payload = json.loads(out) if isinstance(out, str) else out
    if isinstance(payload, tuple):
        payload = payload[1]
    assert payload["status"] == "NO_DATA"
