from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import TransactionDirection

HOME_BANK_ID = "BANK-SHB-001"
DataVisibility = Literal["FULL_INTERNAL", "PAYMENT_MESSAGE_ONLY", "ENRICHED_EXTERNAL"]


class TransactionEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    occurred_at: datetime
    ingested_at: datetime
    source_account_ref: str = Field(min_length=1)
    destination_account_ref: str = Field(min_length=1)
    source_bank_id: str = Field(min_length=1)
    destination_bank_id: str = Field(min_length=1)
    amount: float = Field(gt=0, allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    direction: TransactionDirection
    data_visibility: DataVisibility

    @field_validator("occurred_at", "ingested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_bank_boundary(self) -> "TransactionEventV1":
        source_is_home = self.source_bank_id == HOME_BANK_ID
        destination_is_home = self.destination_bank_id == HOME_BANK_ID
        if self.direction is TransactionDirection.INTERNAL:
            if not source_is_home or not destination_is_home:
                raise ValueError("INTERNAL requires both accounts at the home bank")
            if self.data_visibility != "FULL_INTERNAL":
                raise ValueError("INTERNAL requires FULL_INTERNAL visibility")
        elif self.direction is TransactionDirection.INBOUND:
            if source_is_home or not destination_is_home:
                raise ValueError("INBOUND requires external source and home-bank destination")
            if self.data_visibility == "FULL_INTERNAL":
                raise ValueError("cross-bank events cannot use FULL_INTERNAL visibility")
        elif self.direction is TransactionDirection.OUTBOUND:
            if not source_is_home or destination_is_home:
                raise ValueError("OUTBOUND requires home-bank source and external destination")
            if self.data_visibility == "FULL_INTERNAL":
                raise ValueError("cross-bank events cannot use FULL_INTERNAL visibility")
        return self


class DeadLetterEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    error_code: Literal["EMPTY_VALUE", "MALFORMED_JSON", "SCHEMA_VALIDATION_FAILED"]
    error_message: str = Field(min_length=1, max_length=160)
    source_topic: str = Field(min_length=1)
    source_partition: int = Field(ge=0)
    source_offset: int = Field(ge=0)
    failed_at: datetime
    event_id: str | None = Field(default=None, min_length=1)

    @field_validator("failed_at")
    @classmethod
    def require_failed_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("failed_at must include a timezone")
        return value


def canonical_json_bytes(model: BaseModel) -> bytes:
    return model.model_dump_json(exclude_none=True).encode("utf-8")
