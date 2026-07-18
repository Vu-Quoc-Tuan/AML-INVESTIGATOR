"""Deterministic evidence helpers for Person 3."""

import hashlib
import json
from typing import Any

from app.schemas.evidence import KycEvidence


def evidence_id(prefix: str, record_id: str) -> str:
    return f"EV-{prefix}-{record_id}"


def content_record_id(prefix: str, payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-{digest}"


def source_evidence(
    prefix: str,
    record_id: str,
    source_type: str,
    statement: str,
    attributes: dict[str, Any] | None = None,
    visibility_level: str = "FULL_INTERNAL",
) -> KycEvidence:
    return KycEvidence(
        evidence_id=evidence_id(prefix, record_id),
        source_type=source_type,
        source_record_id=record_id,
        statement=statement,
        visibility_level=visibility_level,
        attributes=attributes or {},
    )
