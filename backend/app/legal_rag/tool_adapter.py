"""LangChain boundary for legal RAG tools owned by the ``legal`` agent."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .config import LegalRagConfig
from .hybrid_retriever import (
    HybridLegalRetriever,
    LegalHit,
    LegalRagUnavailableError,
    LegalRetriever,
)


class LegalToolBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["SUCCESS", "NO_DATA", "INCONCLUSIVE", "ERROR"]
    data: JsonValue = None
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None

    @model_validator(mode="after")
    def enforce_error_code(self) -> "LegalToolBoundary":
        if self.status == "ERROR" and not self.error_code:
            raise ValueError("ERROR tool results require error_code")
        if self.status != "ERROR" and self.error_code:
            raise ValueError("error_code is only valid for ERROR tool results")
        return self


class RetrievePenalCodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)
    linked_finding_ids: list[str] = Field(default_factory=list)


def _evidence_id(hit: LegalHit, query_id: str, config: LegalRagConfig) -> str:
    """Stable id for one (query, article passage) pair.

    Query id is required so two queries that hit the same chunk do not collide
    and overwrite each other's payload/linkage.
    """

    article_key = (
        str(hit.article_number)
        if hit.article_number is not None
        else re.sub(r"\W+", "-", hit.article).strip("-").lower()
    )
    query_key = re.sub(r"\W+", "-", query_id).strip("-").lower() or "query"
    return f"EV-LEGAL-{article_key}-{hit.stable_chunk_id}-{query_key}"


def hits_to_boundary(
    *,
    query_id: str,
    query_text: str,
    hits: list[LegalHit],
    linked_finding_ids: list[str],
    config: LegalRagConfig,
) -> LegalToolBoundary:
    if not hits:
        return LegalToolBoundary(
            status="NO_DATA",
            data={
                "query_id": query_id,
                "query_text": query_text,
                "hits": [],
                "linked_finding_ids": linked_finding_ids,
            },
            warnings=["NO_LEGAL_HITS"],
        )

    evidence: list[dict[str, Any]] = []
    serialized_hits: list[dict[str, Any]] = []
    if not linked_finding_ids:
        return LegalToolBoundary(
            status="NO_DATA",
            data={
                "query_id": query_id,
                "query_text": query_text,
                "hits": [],
                "linked_finding_ids": [],
            },
            warnings=["LEGAL_QUERY_MISSING_SCOUT_LINK"],
        )

    for rank, hit in enumerate(hits, start=1):
        evidence_id = _evidence_id(hit, query_id, config)
        evidence.append(
            {
                "evidence_id": evidence_id,
                "source_system": config.source_system,
                "source_record_id": (
                    f"{config.collection_name}:article:"
                    f"{hit.article_number or hit.article}:{hit.stable_chunk_id}"
                    f":query:{query_id}"
                ),
                "visibility_level": "FULL_INTERNAL",
                "payload": {
                    "query_id": query_id,
                    "article": hit.article,
                    "article_number": hit.article_number,
                    "chapter": hit.chapter,
                    "section": hit.section,
                    "score": hit.score,
                    "hybrid_score": hit.hybrid_score,
                    "retrieval_method": "hybrid_rrf_nvidia_rerank",
                    "snippet": hit.document[:500],
                    "linked_finding_ids": list(linked_finding_ids),
                },
            }
        )
        serialized_hits.append(
            {
                "rank": rank,
                "score": hit.score,
                "hybrid_score": hit.hybrid_score,
                "article": hit.article,
                "article_number": hit.article_number,
                "chapter": hit.chapter,
                "section": hit.section,
                "evidence_id": evidence_id,
                "snippet": hit.document[:500],
            }
        )

    return LegalToolBoundary(
        status="SUCCESS",
        data={
            "query_id": query_id,
            "query_text": query_text,
            "hits": serialized_hits,
            "linked_finding_ids": linked_finding_ids,
        },
        evidence=evidence,
    )


def build_legal_tools(
    retriever: LegalRetriever | None = None,
    config: LegalRagConfig | None = None,
) -> tuple[BaseTool, ...]:
    """Return tools registered under the ``legal`` owner."""

    cfg = config or LegalRagConfig.from_env()
    active_retriever: LegalRetriever = retriever or HybridLegalRetriever(cfg)

    def retrieve_penal_code_passages(
        query_id: str,
        query_text: str,
        top_k: int = 3,
        linked_finding_ids: list[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        linked = list(linked_finding_ids or [])
        try:
            hits = active_retriever.retrieve(query_text, top_k=top_k)
            boundary = hits_to_boundary(
                query_id=query_id,
                query_text=query_text,
                hits=hits,
                linked_finding_ids=linked,
                config=cfg,
            )
        except LegalRagUnavailableError as exc:
            boundary = LegalToolBoundary(
                status="ERROR",
                data={
                    "query_id": query_id,
                    "query_text": query_text,
                    "hits": [],
                    "linked_finding_ids": linked,
                },
                error_code="LEGAL_RAG_UNAVAILABLE",
                warnings=[str(exc)],
            )
        except Exception as exc:  # pragma: no cover - defensive production path
            boundary = LegalToolBoundary(
                status="ERROR",
                data={
                    "query_id": query_id,
                    "query_text": query_text,
                    "hits": [],
                    "linked_finding_ids": linked,
                },
                error_code="LEGAL_RAG_ERROR",
                warnings=[type(exc).__name__],
            )
        artifact = boundary.model_dump(mode="json")
        return json.dumps(artifact, ensure_ascii=False, sort_keys=True), artifact

    tool = StructuredTool.from_function(
        func=retrieve_penal_code_passages,
        name="retrieve_penal_code_passages",
        description=(
            "Retrieve Vietnamese Penal Code passages for one behavior-framed "
            "legal query using hybrid dense+BM25 retrieval with reranking."
        ),
        args_schema=RetrievePenalCodeInput,
        response_format="content_and_artifact",
    )
    return (tool,)
