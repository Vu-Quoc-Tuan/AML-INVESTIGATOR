import csv
import unicodedata
from pathlib import Path

import pytest

from scripts.prepare_opensanctions_vietnam import (
    COMMON_COLUMNS,
    injected_customer_rows,
    normalize_aliases,
    normalize_person_name,
    normalization_quality,
    resolve_injection_percent,
    simple_person_rows,
    write_csv,
)


def test_normalize_person_name_removes_vietnamese_diacritics_and_title_cases() -> None:
    examples = {
        "Nguyễn Phú Trọng": "Nguyen Phu Trong",
        "Trần Đức Thuận": "Tran Duc Thuan",
        "Ðào Văn Bình": "Dao Van Binh",
        "đặng văn a": "Dang Van A",
        "AN-MY LÊ": "An-My Le",
        "  võ   văn kim  ": "Vo Van Kim",
        "Rơ Châm H′Phik": "Ro Cham H′Phik",
    }

    assert {
        source: normalize_person_name(source) for source in examples
    } == examples

    decomposed = unicodedata.normalize("NFD", "NGUYỄN VĂN A")
    assert normalize_person_name(decomposed) == "Nguyen Van A"


def test_normalize_person_name_preserves_non_latin_base_characters() -> None:
    assert normalize_person_name("黎永新") == "黎永新"


def test_normalize_aliases_deduplicates_after_normalization() -> None:
    assert normalize_aliases(
        "Nguyen Van A;NGUYỄN VĂN A;;Nguyễn Văn B;nguyen van b",
        "Nguyen Van A",
    ) == "Nguyen Van B"


def test_simple_person_rows_keeps_only_vietnam_people(tmp_path: Path) -> None:
    source = tmp_path / "peps.csv"
    source.write_text(
        "id,schema,name,aliases,countries,dataset\n"
        "a,Person,Nguyễn A,NGUYEN A;Nguyễn B,vn;fr,source-a\n"
        "b,Organization,Not a person,,vn,source-b\n"
        "c,Person,Not Vietnamese,,us,source-c\n"
        "d,Person,,,vn,source-d\n"
        "a,Person,Duplicate,,vn,source-a\n",
        encoding="utf-8",
    )

    rows = list(simple_person_rows(source))

    assert rows == [
        {
            "id": "a",
            "name": "Nguyen A",
            "aliases": "Nguyen B",
            "birth_date": "",
            "countries": "vn;fr",
            "source_name": "OPEN_SANCTIONS_PEP",
            "related_entity_id": "",
        }
    ]


def test_normalization_quality_counts_changes_and_non_ascii() -> None:
    quality = normalization_quality([
        {
            "name": "Nguyen A",
            "aliases": "Nguyen B",
        },
        {
            "name": "黎永新",
            "aliases": "",
        },
    ])

    assert quality == {
        "rows": 2,
        "canonical_names_with_non_ascii": 1,
        "empty_normalized_names": 0,
    }


def test_resolve_injection_percent_uses_env_file_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("PEP_CUSTOMER_INJECTION_PERCENT=12.5\n", encoding="utf-8")
    monkeypatch.delenv("PEP_CUSTOMER_INJECTION_PERCENT", raising=False)

    assert resolve_injection_percent(env_file) == 12.5
    monkeypatch.setenv("PEP_CUSTOMER_INJECTION_PERCENT", "20")
    assert resolve_injection_percent(env_file) == 20
    assert resolve_injection_percent(env_file, 7.5) == 7.5
    with pytest.raises(ValueError):
        resolve_injection_percent(env_file, 101)


def test_injected_customer_rows_selects_exact_deterministic_percentage(
    tmp_path: Path,
) -> None:
    customers = tmp_path / "customers.csv"
    customers.write_text(
        "customer_id,full_name,date_of_birth,nationality\n"
        "CUST-1,Nguyễn Một,1970-01-01,VN\n"
        "CUST-2,Trần Hai,1980-02-02,VN\n"
        "CUST-3,Lê Ba,1990-03-03,US\n"
        "CUST-4,Đỗ Bốn,2000-04-04,VN\n",
        encoding="utf-8",
    )

    first, eligible = injected_customer_rows(customers, 50)
    second, _ = injected_customer_rows(customers, 50)

    assert first == second
    assert eligible == 4
    assert len(first) == 2
    assert all(row["id"] == f"SYNTH-PEP-{row['related_entity_id']}" for row in first)
    assert all(row["source_name"] == "SYNTHETIC_CUSTOMER_INJECTION" for row in first)
    assert all(normalize_person_name(row["name"]) == row["name"] for row in first)


def test_write_csv_writes_utf8_headers(tmp_path: Path) -> None:
    output = tmp_path / "output.csv"
    count = write_csv(output, COMMON_COLUMNS, [{"id": "1", "name": "Đặng"}])

    with output.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    assert count == 1
    assert tuple(rows[0]) == COMMON_COLUMNS
    assert rows[0]["name"] == "Đặng"
