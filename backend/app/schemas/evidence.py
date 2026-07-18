from datetime import datetime
from typing import Any
from pydantic import BaseModel

class EvidenceItem(BaseModel):
    evidence_id: str
    source_system: str
    source_record_ids: list[str]
    evidence_type: str
    content: dict[str, Any]
    created_at: datetime
