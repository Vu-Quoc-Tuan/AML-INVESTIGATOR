# Synthetic Banking Data Generator

Deterministic, fully fictitious banking world for AML investigation:

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
  --min-accounts 2500 \
  --max-accounts 3000 \
  --output ./data/generated
```

Defaults are already 2000 customers / 50 companies / 2500–3000 accounts.
With the default seed and minimum-account setting, the checked-in dataset is in
`backend/data/generated/` and contains 2000 customer rows, 50 company rows,
2500 account rows, and 40000 normal transactions plus scenario transactions.

## Output files

| File | Description |
|------|-------------|
| `customers.csv` | Individual customers (feature columns only); exact quota |
| `companies.csv` | Corporate customers; exact quota |
| `accounts.csv` | Accounts (incl. demo bank/crypto/foreign accounts and `bank_id`) |
| `transactions.csv` | Baseline + scenario transactions |
| `banks.csv` | Bank catalog with resolvable `bank_entity_id`, country, and risk score |
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

1. **Entities** from behavioral profiles (salary, student, SME, import/export, …)
2. **Ownership** chains (optional multi-layer UBO)
3. **Normal transactions** sampled from each account’s profile (amounts, hours, channels, counterparties)
4. **Scenario injection** mutates the world (fan-in, layering, payroll lookalike, …) without hard-coding detector outcomes into features
5. **Watchlist** synthetic entries + screening dependency flags
6. **Ground truth** written only to `ground_truth_scenarios.json`
7. **Validation** (FK, balances, timestamps, GT integrity, reproducibility)

Ordinary cross-border traffic uses declared-country demo correspondents (SG,
CN, US, JP, KR, DE). The high-risk CY bank is reserved for injected AML
scenarios. If planned activity needs extra liquidity, the generator emits a
visible bank-settlement funding transaction; it never rewrites a profile's
opening balance after observing future transactions.

## Scenarios (default)

| Key | Type | Disposition |
|-----|------|-------------|
| `RAPID_FAN_IN_PASS_THROUGH` | Suspicious | `ESCALATE_FOR_SAR_REVIEW` |
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
  entity_generator.py          # customers / companies / accounts / KYC
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
