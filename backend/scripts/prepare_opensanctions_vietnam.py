#!/usr/bin/env python3
"""Prepare one clean Vietnam-person CSV from a pinned OpenSanctions PEP export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import math
import os
import tempfile
import unicodedata
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
INJECTION_PERCENT_ENV = "PEP_CUSTOMER_INJECTION_PERCENT"
DEFAULT_CUSTOMERS_FILE = Path("backend/data/generated/customers.csv")
DEFAULT_ENV_FILE = Path("backend/.env")

COMMON_COLUMNS = (
    "id",
    "name",
    "aliases",
    "birth_date",
    "countries",
    "source_name",
    "related_entity_id",
)

NAME_NORMALIZATION_VERSION = "v1"
SPECIAL_LATIN_TRANSLATION = str.maketrans(
    {
        "Đ": "D",
        "đ": "d",
        "Ð": "D",
        "ð": "d",
    }
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


def read_env_value(path: Path, key: str) -> str | None:
    """Read one simple KEY=VALUE entry without adding a dotenv dependency."""

    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        candidate, value = line.split("=", 1)
        if candidate.strip() == key:
            return value.strip().strip("\"'")
    return None


def resolve_injection_percent(
    env_file: Path,
    explicit_percent: float | None = None,
) -> float:
    """Resolve CLI, process environment and .env injection configuration."""

    raw_value: object = explicit_percent
    if raw_value is None:
        raw_value = os.environ.get(INJECTION_PERCENT_ENV)
    if raw_value is None:
        raw_value = read_env_value(env_file, INJECTION_PERCENT_ENV)
    if raw_value is None:
        raw_value = 0
    try:
        percent = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{INJECTION_PERCENT_ENV} must be a number between 0 and 100"
        ) from exc
    if not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError(
            f"{INJECTION_PERCENT_ENV} must be between 0 and 100"
        )
    return percent


def remove_latin_diacritics(value: str) -> str:
    """Remove Latin diacritics without transliterating unrelated scripts."""

    translated = unicodedata.normalize("NFC", value.translate(SPECIAL_LATIN_TRANSLATION))
    result: list[str] = []
    previous_base_was_latin = False
    for character in translated:
        if unicodedata.combining(character):
            if not previous_base_was_latin:
                result.append(character)
            continue
        if "LATIN" not in unicodedata.name(character, ""):
            result.append(character)
            previous_base_was_latin = False
            continue
        result.extend(
            item
            for item in unicodedata.normalize("NFKD", character)
            if not unicodedata.combining(item)
        )
        previous_base_was_latin = True
    return "".join(result)


def title_case_name(value: str) -> str:
    """Capitalize each punctuation-delimited name component deterministically."""

    collapsed = " ".join(value.split()).lower()
    output: list[str] = []
    capitalize_next = True
    for character in collapsed:
        if character.isalpha():
            output.append(character.upper() if capitalize_next else character)
            capitalize_next = False
        else:
            output.append(character)
            capitalize_next = not character.isdigit()
    return "".join(output)


def normalize_person_name(value: object) -> str:
    """Return a trimmed, accent-free display name in component title case."""

    if value is None:
        return ""
    return title_case_name(remove_latin_diacritics(str(value).strip()))


def normalize_aliases(value: object, canonical_name: str) -> str:
    """Normalize, de-duplicate and serialize aliases in source order."""

    aliases: list[str] = []
    seen: set[str] = {canonical_name}
    for item in split_values(value):
        normalized = normalize_person_name(item)
        if normalized and normalized not in seen:
            aliases.append(normalized)
            seen.add(normalized)
    return ";".join(aliases)


def normalization_quality(rows: Iterable[Mapping[str, str]]) -> dict[str, int]:
    """Summarize deterministic output-quality counters for the manifest."""

    materialized = list(rows)
    return {
        "rows": len(materialized),
        "canonical_names_with_non_ascii": sum(
            any(ord(character) > 127 for character in row["name"])
            for row in materialized
        ),
        "empty_normalized_names": sum(not row["name"] for row in materialized),
    }


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
            writer = csv.DictWriter(
                output,
                fieldnames=columns,
                extrasaction="ignore",
                lineterminator="\n",
            )
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
            normalized_name = normalize_person_name(name)
            if not normalized_name:
                raise ValueError(
                    f"PEP record {entity_id!r} has an empty normalized name"
                )
            aliases_original = str(row.get("aliases", "") or "").strip()
            yield {
                "id": entity_id,
                "name": normalized_name,
                "aliases": normalize_aliases(aliases_original, normalized_name),
                "birth_date": row.get("birth_date", ""),
                "countries": row.get("countries", ""),
                "source_name": "OPEN_SANCTIONS_PEP",
                "related_entity_id": "",
            }


def injected_customer_rows(
    customers_file: Path,
    percent: float,
) -> tuple[list[dict[str, str]], int]:
    """Select an exact deterministic percentage of customers as synthetic PEPs."""

    with customers_file.open("r", encoding="utf-8", newline="") as input_file:
        customers = list(csv.DictReader(input_file))
    required = {"customer_id", "full_name", "date_of_birth", "nationality"}
    missing = required - set(customers[0] if customers else [])
    if missing:
        raise ValueError(
            "customers CSV is missing required columns: "
            + ", ".join(sorted(missing))
        )

    injection_count = int(len(customers) * percent / 100 + 0.5)
    ranked = sorted(
        customers,
        key=lambda row: (
            hashlib.sha256(str(row["customer_id"]).encode("utf-8")).hexdigest(),
            str(row["customer_id"]),
        ),
    )
    selected = sorted(
        ranked[:injection_count], key=lambda row: str(row["customer_id"])
    )
    rows: list[dict[str, str]] = []
    for customer in selected:
        customer_id = str(customer["customer_id"]).strip()
        name = normalize_person_name(customer["full_name"])
        if not customer_id or not name:
            raise ValueError("selected customer has an empty ID or normalized name")
        rows.append(
            {
                "id": f"SYNTH-PEP-{customer_id}",
                "name": name,
                "aliases": "",
                "birth_date": str(customer.get("date_of_birth", "") or ""),
                "countries": str(customer.get("nationality", "") or "").lower(),
                "source_name": "SYNTHETIC_CUSTOMER_INJECTION",
                "related_entity_id": customer_id,
            }
        )
    return rows, len(customers)


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
    parser.add_argument("--customers-file", type=Path, default=DEFAULT_CUSTOMERS_FILE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--injection-percent",
        type=float,
        help=f"Override {INJECTION_PERCENT_ENV} from the process environment/.env.",
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
    real_pep_rows = list(simple_person_rows(peps_file))
    injection_percent = resolve_injection_percent(
        args.env_file, args.injection_percent
    )
    injected_rows, eligible_customer_rows = injected_customer_rows(
        args.customers_file, injection_percent
    )
    person_rows = [*real_pep_rows, *injected_rows]
    ids = [row["id"] for row in person_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("combined PEP output contains duplicate IDs")
    quality = normalization_quality(person_rows)
    if quality["empty_normalized_names"]:
        raise ValueError("normalized PEP output contains empty canonical names")
    person_count = write_csv(vietnam_people_path, COMMON_COLUMNS, person_rows)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "country_filter": COUNTRY_CODE,
        "outputs": {
            vietnam_people_path.name: {
                "rows": person_count,
                "real_pep_rows": len(real_pep_rows),
                "injected_customer_rows": len(injected_rows),
                "source": peps_resource["url"],
            },
        },
        "normalization": {
            "version": NAME_NORMALIZATION_VERSION,
            "unicode_form": "NFKD",
            "special_character_map": {
                "Đ": "D",
                "đ": "d",
                "Ð": "D",
                "ð": "d",
            },
            "capitalization": "name_component_title_case",
            "normalized_columns": ["name", "aliases"],
            "quality": quality,
        },
        "customer_injection": {
            "environment_variable": INJECTION_PERCENT_ENV,
            "percent": injection_percent,
            "customers_file": str(args.customers_file),
            "eligible_customer_rows": eligible_customer_rows,
            "injected_rows": len(injected_rows),
            "selection": "sha256(customer_id), exact rounded count",
            "source_name": "SYNTHETIC_CUSTOMER_INJECTION",
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
