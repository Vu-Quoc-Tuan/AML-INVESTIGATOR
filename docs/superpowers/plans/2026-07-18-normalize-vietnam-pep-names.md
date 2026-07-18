# Vietnam PEP Blacklist Preparation

## Implemented goal

Prepare a minimal blacklist-style Vietnam PEP CSV from the pinned
OpenSanctions raw export and deterministically inject a configurable percentage
of synthetic customers for end-to-end screening tests.

## Output contract

`backend/data/opensanctions/processed/vietnam_persons.csv` contains only:

```text
id
name
aliases
birth_date
countries
source_name
related_entity_id
```

Real OpenSanctions rows use:

```text
source_name = OPEN_SANCTIONS_PEP
related_entity_id = empty
```

Injected customer rows use:

```text
id = SYNTH-PEP-{customer_id}
source_name = SYNTHETIC_CUSTOMER_INJECTION
related_entity_id = customer_id
```

`name` and `aliases` are normalized without Vietnamese/Latin diacritics and
use component title case. `Đ/đ/Ð/ð` are explicitly converted to `D/d`.

## Injection configuration

The percentage is read from `backend/.env`:

```text
PEP_CUSTOMER_INJECTION_PERCENT=5
```

Resolution precedence is:

1. `--injection-percent` CLI override;
2. process environment variable;
3. value in `--env-file` (default `backend/.env`);
4. zero when no value is configured.

The value must be finite and between 0 and 100. Selection ranks customers by
`SHA-256(customer_id)`, takes the exact rounded target count, then writes them
in customer-ID order. The same input and percentage therefore always produce
the same injected set.

At the configured 5 percent, the current dataset produces:

```text
1,601 OpenSanctions PEP rows
  100 injected customer rows
1,701 total blacklist rows
```

## Source and audit metadata

`manifest.json` records:

- pinned OpenSanctions URL, version and SHA-1;
- real and injected row counts;
- configured injection percentage;
- eligible customer count;
- deterministic selection method;
- name-normalization policy and output-quality counts.

The raw OpenSanctions file remains checksum-verified and gitignored.

## Verification

The implementation is covered by tests for:

- Vietnam `Person` filtering and source-ID deduplication;
- Vietnamese, decomposed Unicode and `Đ/Ð` normalization;
- alias normalization/deduplication;
- `.env`, process environment and CLI percentage precedence;
- invalid percentage rejection;
- exact deterministic injection count and row contract;
- atomic CSV output and stable column order.

Regeneration command for the pinned local raw file:

```text
python3 backend/scripts/prepare_opensanctions_vietnam.py \
  --skip-download \
  --peps-sha1 69c2d73d2c3d9a3b16413c3b0f5d0ccd5f829af7
```
