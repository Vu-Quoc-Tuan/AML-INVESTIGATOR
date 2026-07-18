#!/usr/bin/env python3
"""Prepare one clean Vietnam-person CSV from a pinned OpenSanctions PEP export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen


PEPS_URL = (
    "https://data.opensanctions.org/artifacts/peps/"
    "20260717152701-kci/targets.simple.csv"
)
USER_AGENT = "aml-investigator-opensanctions-prep/1.0"
COUNTRY_CODE = "vn"

COMMON_COLUMNS = (
    "id",
    "name",
    "aliases",
    "birth_date",
    "countries",
    "addresses",
    "identifiers",
    "phones",
    "emails",
    "source_datasets",
    "first_seen",
    "last_seen",
    "last_change",
)


def fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=60) as response:  # nosec B310 - URL is CLI input
        return json.load(response)


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_sha1: str | None = None) -> str:
    """Download atomically and return the verified SHA-1 digest."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        existing_sha1 = sha1_file(destination)
        if expected_sha1 is None or existing_sha1 == expected_sha1:
            logging.info("Reusing verified file: %s", destination)
            return existing_sha1
        logging.warning("Existing file has an unexpected checksum; downloading again")

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    downloaded = 0
    digest = hashlib.sha1()
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with os.fdopen(file_descriptor, "wb") as output, urlopen(  # nosec B310
            request, timeout=120
        ) as response:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if downloaded % (100 * 1024 * 1024) < len(chunk):
                    logging.info("Downloaded %.1f MiB", downloaded / 1024 / 1024)
        actual_sha1 = digest.hexdigest()
        if expected_sha1 and actual_sha1 != expected_sha1:
            raise ValueError(
                f"Checksum mismatch for {url}: expected {expected_sha1}, got {actual_sha1}"
            )
        Path(temporary_name).replace(destination)
        logging.info("Downloaded %.1f MiB to %s", downloaded / 1024 / 1024, destination)
        return actual_sha1
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def split_values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(";") if item.strip()]


def has_country(value: object, country_code: str = COUNTRY_CODE) -> bool:
    return country_code in {item.lower() for item in split_values(value)}


def write_csv(path: Path, columns: tuple[str, ...], rows: Iterable[Mapping[str, str]]) -> int:
    """Write a UTF-8 CSV atomically so a failed extraction leaves no partial output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".part", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
                count += 1
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return count


def simple_person_rows(source: Path) -> Iterator[dict[str, str]]:
    """Yield de-duplicated Person records that explicitly list Vietnam."""
    seen_ids: set[str] = set()
    with source.open("r", encoding="utf-8", newline="") as input_file:
        for row in csv.DictReader(input_file):
            entity_id = row.get("id", "")
            name = row.get("name", "").strip()
            if (
                row.get("schema") != "Person"
                or not entity_id
                or not name
                or entity_id in seen_ids
                or not has_country(row.get("countries"))
            ):
                continue
            seen_ids.add(entity_id)
            yield {
                "id": entity_id,
                "name": name,
                "aliases": row.get("aliases", ""),
                "birth_date": row.get("birth_date", ""),
                "countries": row.get("countries", ""),
                "addresses": row.get("addresses", ""),
                "identifiers": row.get("identifiers", ""),
                "phones": row.get("phones", ""),
                "emails": row.get("emails", ""),
                "source_datasets": row.get("dataset", ""),
                "first_seen": row.get("first_seen", ""),
                "last_seen": row.get("last_seen", ""),
                "last_change": row.get("last_change", ""),
            }


def resource(index: Mapping[str, object], name: str) -> Mapping[str, object]:
    for item in index.get("resources", []):
        if isinstance(item, dict) and item.get("name") == name:
            return item
    raise ValueError(f"Resource {name!r} is absent from collection index")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peps-url", default=PEPS_URL)
    parser.add_argument(
        "--peps-sha1",
        help="Expected SHA-1 for --peps-url when processing a pre-downloaded file.",
    )
    parser.add_argument("--raw-dir", type=Path, default=Path("backend/data/opensanctions/raw"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("backend/data/opensanctions/processed")
    )
    parser.add_argument("--skip-download", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    peps_index_url = args.peps_url.rsplit("/", 1)[0] + "/index.json"
    if args.skip_download:
        peps_index: Mapping[str, object] = {"version": args.peps_url.rsplit("/", 2)[-2]}
        peps_resource: Mapping[str, object] = {
            "url": args.peps_url,
            "checksum": args.peps_sha1 or "not-verified-against-index",
        }
    else:
        peps_index = fetch_json(peps_index_url)
        peps_resource = resource(peps_index, "targets.simple.csv")
    peps_file = args.raw_dir / "peps-targets.simple.csv"

    if not args.skip_download:
        peps_sha1 = download(
            str(peps_resource["url"]), peps_file, str(peps_resource["checksum"])
        )
    else:
        peps_sha1 = sha1_file(peps_file)
        if args.peps_sha1 and peps_sha1 != args.peps_sha1:
            raise ValueError("PEP raw file checksum does not match --peps-sha1")

    vietnam_people_path = args.output_dir / "vietnam_persons.csv"
    person_count = write_csv(vietnam_people_path, COMMON_COLUMNS, simple_person_rows(peps_file))

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "country_filter": COUNTRY_CODE,
        "outputs": {
            vietnam_people_path.name: {"rows": person_count, "source": peps_resource["url"]},
        },
        "sources": {
            "peps": {
                "index_url": peps_index_url,
                "version": peps_index.get("version"),
                "url": peps_resource["url"],
                "sha1": peps_sha1,
            },
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logging.info("Created %s (%s rows)", vietnam_people_path, person_count)


if __name__ == "__main__":
    main()
