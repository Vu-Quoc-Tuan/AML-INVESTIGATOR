"""Evidence contracts shared by investigation components."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KycEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    visibility_level: str
    attributes: dict[str, Any] = Field(default_factory=dict)
