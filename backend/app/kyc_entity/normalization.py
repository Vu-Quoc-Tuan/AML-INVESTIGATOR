"""Pure identity normalization utilities."""

import re
import unicodedata
from datetime import date, datetime
from typing import Any

from app.schemas.kyc_entity import NormalizedIdentity


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def normalize_name(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^A-Za-z0-9 ]+", " ", without_marks).upper().split())


def normalize_identifier(value: Any) -> str | None:
    text = _text(value)
    return None if text is None else "".join(char for char in text.upper() if char.isalnum())


def normalize_phone(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    digits = "".join(char for char in text if char.isdigit())
    if digits.startswith("0") and len(digits) >= 9:
        digits = "84" + digits[1:]
    return digits or None


def normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


def _identity_scope(raw_identity: dict[str, Any]) -> str:
    identifiers = (
        raw_identity.get("entity_id"),
        raw_identity.get("account_id"),
        raw_identity.get("external_account_id"),
    )
    has_external_marker = bool(
        raw_identity.get("external_account_id")
        or raw_identity.get("masked_account_number")
        or any(str(value).startswith("EXT-") for value in identifiers if value)
    )
    if has_external_marker:
        return "LIMITED_EXTERNAL_IDENTITY"
    if raw_identity.get("identity_scope") == "LIMITED_EXTERNAL_IDENTITY":
        return "LIMITED_EXTERNAL_IDENTITY"
    return "FULL_INTERNAL"


def normalize_identity(raw_identity: dict[str, Any]) -> NormalizedIdentity:
    display_name = (
        _text(raw_identity.get("full_name"))
        or _text(raw_identity.get("legal_name"))
        or _text(raw_identity.get("counterparty_name"))
    )
    aliases = raw_identity.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    normalized_aliases = sorted({name for item in aliases if (name := normalize_name(item))})
    addresses = raw_identity.get("addresses") or raw_identity.get("address") or []
    if isinstance(addresses, str):
        addresses = [addresses]
    address_text = " ".join(str(item) for item in addresses)
    address_tokens = sorted(set(normalize_name(address_text).split())) if address_text else []
    scope = _identity_scope(raw_identity)
    return NormalizedIdentity(
        display_name=display_name,
        standardized_name=normalize_name(display_name),
        aliases=normalized_aliases,
        date_of_birth=normalize_date(raw_identity.get("date_of_birth")),
        national_id=normalize_identifier(raw_identity.get("national_id")),
        passport=normalize_identifier(raw_identity.get("passport")),
        registration_number=normalize_identifier(raw_identity.get("registration_number")),
        phone=normalize_phone(raw_identity.get("phone")),
        email=_text(raw_identity.get("email")).lower() if _text(raw_identity.get("email")) else None,
        address_tokens=address_tokens,
        external_account_id=_text(raw_identity.get("external_account_id")),
        masked_account_number=_text(raw_identity.get("masked_account_number")),
        bank_id=_text(raw_identity.get("bank_id")),
        identity_scope=scope,
    )
