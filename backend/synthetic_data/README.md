# SHB-Centric Synthetic Banking Data Generator

Deterministic, fully fictitious single-bank dataset for AML investigation.
SHB is the only home bank; every other institution is an external reference
counterparty rather than a ledger managed by this generator.

- Alert detection evaluation
- Transaction graph investigation
- KYC profile comparison
- Entity resolution & UBO
- Sanctions / PEP / watchlist screening
- Typology matching
- Human-in-the-loop case review

**No real personal data.** All names, IDs, accounts, companies, and addresses are synthetic.

## Install

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install pydantic pytest
```

## Generate

```bash
cd backend
source .venv/bin/activate

python -m synthetic_data.cli \
  --seed 42 \
  --customers 2000 \
  --companies 50 \
  --transactions 40000 \
  --external-accounts 1000 \
  --min-accounts 2500 \
  --max-accounts 3000 \
  --output ./data/generated
```

Defaults are already 2000 customers / 50 companies / 2500–3000 accounts.
With the default seed and minimum-account setting, the checked-in dataset is in
`backend/data/generated/` and contains 2000 customer rows, 50 company rows,
2500 SHB account rows, 1000 external counterparty observations, and 40000
normal transactions plus scenario transactions.

The normal demo mix is 45% SHB-to-SHB, 27.5% inbound, and 27.5% outbound;
approximately 5% of all normal transactions are cross-border. **Synthetic demo
distribution, not calibrated to SHB production traffic.**

## Output files

| File | Description |
|------|-------------|
| `customers.csv` | SHB individual customers (feature columns only); exact quota |
| `companies.csv` | SHB corporate customers; exact quota |
| `accounts.csv` | SHB-managed accounts only; every row uses `BANK-SHB-001` |
| `external_accounts.csv` | Limited counterparties observed through payment messages |
| `transactions.csv` | Typed `INTERNAL`, `INBOUND`, and `OUTBOUND` SHB ledger events |
| `banks.csv` | One SHB home-bank row plus external bank reference rows |
| `kyc_profiles.jsonl` | Expected activity profiles |
| `kyc_documents.jsonl` | Synthetic identity / corporate docs |
| `company_ownership.csv` | Ownership / UBO edges |
| `entity_relationships.csv` | Broader graph relationships |
| `watchlist_entries.jsonl` | Fictitious sanctions/PEP/watchlist |
| `ground_truth_scenarios.json` | **Labels only** — do not mix into features |
| `addresses.csv` | Synthetic addresses |
| `manifest.json` | Counts + SHA-256 checksums |

Ground-truth columns (`scenario_id`, `is_suspicious`, `expected_*`, …) are **never** written into feature CSVs.

## Design

1. **SHB entities** from behavioral profiles (salary, student, SME, import/export, …)
2. **SHB ownership** chains (optional multi-layer UBO)
3. **External observations** without owner IDs, KYC, balances, devices, or full ledgers
4. **Normal transactions** with typed internal/external endpoints and exact direction quotas
5. **Scenario injection** mutates the world (fan-in, layering, payroll lookalike, …) without hard-coding detector outcomes into features
6. **Watchlist** synthetic entries + screening dependency flags
7. **Ground truth** written only to `ground_truth_scenarios.json`
8. **Validation** (SHB boundary, FK, balances, timestamps, visibility, GT integrity, reproducibility)

Ordinary cross-border traffic uses limited external correspondents (SG, CN, US,
JP, KR, DE). The high-risk foreign bank is reserved for injected AML scenarios.
If planned activity needs extra liquidity, the generator emits a visible
inbound payment-message transaction; it never creates an external balance or
rewrites an SHB profile's opening balance after observing future transactions.

`FULL_INTERNAL` is used only when both endpoints are SHB accounts.
`PAYMENT_MESSAGE_ONLY` is used when a transaction crosses the SHB boundary.
`ENRICHED_EXTERNAL` is valid only when an explicit enrichment source is named.

## Scenarios (default)

| Key | Type | Disposition |
|-----|------|-------------|
| `RAPID_FAN_IN_PASS_THROUGH` | 6 SHB + 4 external fan-in, rapid foreign outbound | `ESCALATE_FOR_SAR_REVIEW` |
| `STRUCTURING_SMURFING` | Suspicious | `ESCALATE_FOR_SAR_REVIEW` |
| `MULE_LAYERING_CHAIN` | Suspicious | `ESCALATE_FOR_SAR_REVIEW` |
| `EVENT_COLLECTION` | Lookalike | `CLEARED_WITH_RATIONALE` |
| `PAYROLL_BATCH` | Lookalike | `CLEARED_WITH_RATIONALE` |
| `TRADE_INVOICE_SETTLEMENT` | Lookalike | `CLEARED_WITH_RATIONALE` |
| `INCOMPLETE_EVIDENCE_PASS_THROUGH` | Incomplete evidence | `NEED_MORE_EVIDENCE` |

## Reproducibility

Same `--seed` and parameters → same file checksums (see `manifest.json`).

## Tests

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest tests/unit/synthetic_data -q
```

## Module map

```
synthetic_data/
  config.py                    # defaults & fake reference lists
  models.py                    # Pydantic models
  id_factory.py                # stable IDs
  profiles.py                  # behavioral profile specs
  world.py                     # in-memory state
  entity_generator.py          # SHB entities/accounts/KYC + external observations
  ownership_generator.py       # UBO & relationships
  normal_transaction_generator.py
  scenario_injector.py
  watchlist_generator.py
  ground_truth.py
  validators.py
  io_writer.py
  pipeline.py                  # orchestration
  cli.py
```
