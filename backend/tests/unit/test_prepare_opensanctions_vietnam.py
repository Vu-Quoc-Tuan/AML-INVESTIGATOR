import csv
from pathlib import Path

from scripts.prepare_opensanctions_vietnam import (
    COMMON_COLUMNS,
    simple_person_rows,
    write_csv,
)


def test_simple_person_rows_keeps_only_vietnam_people(tmp_path: Path) -> None:
    source = tmp_path / "peps.csv"
    source.write_text(
        "id,schema,name,countries,dataset\n"
        "a,Person,Nguyen A,vn;fr,source-a\n"
        "b,Organization,Not a person,vn,source-b\n"
        "c,Person,Not Vietnamese,us,source-c\n"
        "d,Person,,vn,source-d\n"
        "a,Person,Duplicate,vn,source-a\n",
        encoding="utf-8",
    )

    rows = list(simple_person_rows(source))

    assert rows == [
        {
            "id": "a",
            "name": "Nguyen A",
            "aliases": "",
            "birth_date": "",
            "countries": "vn;fr",
            "addresses": "",
            "identifiers": "",
            "phones": "",
            "emails": "",
            "source_datasets": "source-a",
            "first_seen": "",
            "last_seen": "",
            "last_change": "",
        }
    ]

def test_write_csv_writes_utf8_headers(tmp_path: Path) -> None:
    output = tmp_path / "output.csv"
    count = write_csv(output, COMMON_COLUMNS, [{"id": "1", "name": "Đặng"}])

    with output.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    assert count == 1
    assert tuple(rows[0]) == COMMON_COLUMNS
    assert rows[0]["name"] == "Đặng"
