from datetime import datetime

import pytest
from pydantic import ValidationError

from app.streaming.schemas import TransactionEventV1, canonical_json_bytes
from tests.unit.streaming.conftest import make_event


def test_valid_internal_event_is_canonical_json():
    event = make_event()
    decoded = TransactionEventV1.model_validate_json(canonical_json_bytes(event))
    assert decoded == event


def test_outbound_event_requires_payment_message_visibility():
    event = make_event(
        direction="OUTBOUND",
        destination_account_ref="EXT-SG-001",
        destination_bank_id="BANK-FOREIGN-SG-DEMO",
        data_visibility="PAYMENT_MESSAGE_ONLY",
    )
    assert event.schema_version == "1.0"


def test_inbound_event_accepts_enriched_external_visibility():
    event = make_event(
        direction="INBOUND",
        source_account_ref="EXT-US-001",
        source_bank_id="BANK-FOREIGN-US-DEMO",
        data_visibility="ENRICHED_EXTERNAL",
    )
    assert event.direction.value == "INBOUND"


def test_cross_boundary_event_rejects_full_internal_visibility():
    with pytest.raises(ValidationError):
        make_event(
            direction="OUTBOUND",
            destination_bank_id="BANK-FOREIGN-SG-DEMO",
            data_visibility="FULL_INTERNAL",
        )


def test_event_rejects_naive_timestamp():
    with pytest.raises(ValidationError):
        make_event(occurred_at=datetime(2026, 7, 18, 10, 0))


def test_event_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        make_event(card_number="4111111111111111")
