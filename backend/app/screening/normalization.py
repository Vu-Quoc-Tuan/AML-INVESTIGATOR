"""Pure screening normalization helpers."""

import re
import unicodedata
from typing import Any


def normalize_name(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    decomposed = unicodedata.normalize("NFKD", str(value).strip())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^A-Za-z0-9 ]+", " ", without_marks).upper().split())


def normalize_identifier(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return "".join(character for character in str(value).upper() if character.isalnum())


def normalize_country(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    return str(value).strip().upper()
