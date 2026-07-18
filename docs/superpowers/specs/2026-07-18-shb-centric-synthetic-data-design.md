# SHB-Centric Synthetic Dataset Design

## Goal

Refactor the synthetic AML dataset from a multi-bank ecosystem into a
single-bank-centered ledger where SHB is the only home bank. The dataset must
represent only information that SHB could know from its own customer, KYC, UBO,
account, device, IP, and transaction systems, plus limited external counterparty
details observed through payment messages or explicitly identified enrichment
sources.

The default generated dataset remains deterministic and contains:

- exactly 2,000 SHB customers;
- exactly 50 SHB corporate customers;
- 2,500 to 3,000 SHB-managed accounts;
- exactly 1,000 observed external counterparty accounts by default, configurable
  within the supported range of 500 to 1,500;
- exactly 40,000 normal transactions followed by additional scenario
  transactions;
- one SHB home bank, external domestic banks, external foreign banks, a demo
  crypto platform, and a high-risk foreign bank in the bank directory;
- the existing suspicious, legitimate-lookalike, and incomplete-evidence
  scenario families, adapted to the SHB visibility boundary.

All generated records are fictitious demo data and are not calibrated to SHB
production traffic.

## Selected Approach

Use the hybrid scenario approach: six internal SHB personal accounts and four
external domestic accounts fan in to a newly opened SHB corporate account,
followed by a rapid outbound transfer to a high-risk foreign external
beneficiary.

The generator uses separate models and collections for internal SHB accounts
and external accounts. External accounts are counterparty observations, not
complete ledgers. A transaction can reference either kind of account, but only
SHB account balances are maintained and replayed.

## Data Boundary

The following are internal SHB data:

- customers and companies that have a customer relationship with SHB;
- accounts managed by SHB;
- KYC profiles and KYC documents for SHB entities;
- company ownership and UBO evidence held by SHB;
- entity relationships supported by SHB records;
- devices and IP addresses observed through SHB channels;
- every transaction that passes through an SHB account.

The following are limited external observations:

- counterparty account reference or masked account number;
- counterparty name when supplied by a payment message;
- counterparty bank and country;
- identifier type and value when present in the payment message;
- first and last interaction with an SHB account;
- an explicit external risk tag only when its enrichment source is recorded.

The generator must not create full external customer KYC, external owner entity
foreign keys, external devices or IP history, external balances, or transactions
that do not touch an SHB account.

## Core Models and Output Schemas

### Bank directory

`banks.csv` is a reference directory, not a list of ledgers managed by the
system. Its exported columns are:

```text
bank_id
bank_name
bank_type
country_code
is_home_bank
risk_score
swift_code
```

`BANK-SHB-001` is the single row with `is_home_bank=true`. Other rows are
external reference entities only. They include domestic external banks, normal
foreign banks, `BANK-CRYPTO-DEMO-99`, and `BANK-FOREIGN-HR-88`.

### Internal accounts

`accounts.csv` contains only SHB-managed accounts. It retains the existing
business columns and `bank_id`; every row has `bank_id=BANK-SHB-001`. Internal
IDs use the stable `ACCT-SHB-...` namespace. Every owner resolves to a customer
or company exported by SHB.

Internal accounts retain behavioral profiles and balances in memory for
generation and validation. Runtime-only fields remain excluded from feature
exports.

### External accounts

Add `external_accounts.csv` with these columns:

```text
external_account_id
masked_account_number
bank_id
country_code
counterparty_name
counterparty_type
available_identifier_type
available_identifier_value
risk_score
first_seen_at
last_seen_at
metadata_source
data_visibility
```

An external account has no `owner_entity_id` and does not resolve to
`customers.csv` or `companies.csv`. It has no KYC profile, KYC document,
device/IP history, opening balance, or complete transaction history. All normal
external account rows must be referenced by at least one transaction. Their
`first_seen_at` and `last_seen_at` values are derived from transactions visible
to SHB rather than invented independently.

Default external records use `PAYMENT_MESSAGE` and
`PAYMENT_MESSAGE_ONLY`. `ENRICHED_EXTERNAL` is allowed only when the row names
an explicit enrichment source such as `PAYMENT_ENRICHMENT_DEMO` or
`INTERBANK_AML_DATA_DEMO`.

### Transactions

Replace the internal-only account-ID columns with typed account references:

```text
transaction_id
source_account_ref
source_account_type
source_bank_id
destination_account_ref
destination_account_type
destination_bank_id
amount
currency
transaction_type
channel
purpose_code
description
occurred_at
direction
source_ip
device_id
is_cross_border
source_country
destination_country
data_visibility
evidence_source
payment_reference
```

`source_account_type` and `destination_account_type` accept only
`INTERNAL_SHB` or `EXTERNAL`. `direction` is derived from those values:

| Source | Destination | Direction |
|---|---|---|
| `INTERNAL_SHB` | `INTERNAL_SHB` | `INTERNAL` |
| `EXTERNAL` | `INTERNAL_SHB` | `INBOUND` |
| `INTERNAL_SHB` | `EXTERNAL` | `OUTBOUND` |

`EXTERNAL` to `EXTERNAL` is invalid because SHB cannot observe a transaction
that does not pass through an SHB account.

For an inbound transaction, `source_ip` and `device_id` are empty because the
source is not using an SHB channel. Internal and outbound transactions may use
the source SHB entity's observed device and IP. Internal transactions use
`FULL_INTERNAL`; inbound and outbound transactions use
`PAYMENT_MESSAGE_ONLY`, unless an explicit and named enrichment source justifies
`ENRICHED_EXTERNAL`. Every transaction itself remains an SHB-observed ledger
event; the visibility field describes the available counterparty evidence.

## Generator Flow

1. Validate configuration, including the external account range and transaction
   distribution.
2. Create the bank directory with `BANK-SHB-001` as the only home bank.
3. Generate the configured SHB customer and company rosters.
4. Generate only SHB-managed internal accounts and assign
   `bank_id=BANK-SHB-001`.
5. Generate SHB KYC, documents, ownership, entity relationships, devices, and
   IPs only for internal entities.
6. Generate the configured external counterparty roster without entity owners,
   balances, KYC, devices, or IPs.
7. Generate exactly the configured number of normal transactions using the
   SHB-centric topology and update external first/last-seen timestamps from
   those transactions.
8. Inject scenarios using reserved internal and external records without
   exceeding configured population quotas.
9. Build isolated ground truth with explicit visibility categories.
10. Replay only the SHB side of the ledger, validate the world, and write all
    deterministic outputs and checksums.

The default normal transaction mix is:

- 45 percent `INTERNAL`;
- 27.5 percent `INBOUND`;
- 27.5 percent `OUTBOUND`;
- approximately 5 percent of all normal transactions are cross-border inbound
  or outbound transactions.

The ratios are synthetic demo defaults. The transaction generator assigns exact
direction quotas for a configured run so tests do not depend on random
approximation. Cross-border transactions are a subset of inbound and outbound
transactions, not a fourth direction.

## Balance and Ledger Rules

The balance ledger contains only SHB accounts:

- an internal transfer debits one SHB account and credits another;
- an inbound transfer credits its destination SHB account without checking or
  storing an external source balance;
- an outbound transfer debits its source SHB account without creating an
  external destination balance;
- balance validation enforces non-negative replay only for SHB accounts, except
  where an internal account has an explicitly configured overdraft;
- liquidity support transactions must also pass through an SHB account and
  cannot use a visible external or system-float super-ledger.

The generator must not infer an external account's funds from its observed SHB
interactions.

## Hybrid Rapid Fan-In Scenario

`RAPID_FAN_IN_PASS_THROUGH` uses these roles:

- six SHB personal accounts with full internal customer, account, device/IP,
  and transaction context;
- four external domestic accounts with payment-message-only identity;
- one newly opened SHB corporate account with a low declared turnover, a full
  SHB KYC profile, and verified direct UBO evidence;
- one external crypto-platform account;
- one foreign high-risk external beneficiary.

The scenario proceeds as follows:

1. The crypto-platform external account sends observable inbound transfers to
   the six SHB personal accounts. SHB can confirm those inbound ledger events
   and their payment-message originator, but it does not gain a full crypto
   platform ledger.
2. The six SHB accounts and four external domestic accounts each send an amount
   close to VND 500 million into the SHB corporate account.
3. The ten fan-in transfers occur within five minutes.
4. A subset of the six SHB senders may share SHB-observed device or IP evidence.
   The four external senders never receive synthetic internal device/IP data.
5. Exactly 121 seconds after the last fan-in transfer, the company sends 99.2
   percent of the fan-in total to the high-risk foreign external beneficiary.

Evidence must distinguish confirmed internal facts, payment-message-only
external observations, graph inferences, and unavailable information.

Other suspicious and lookalike scenarios must use the same account boundary.
External parties may participate only as observed counterparties. Existing
scenario semantics should be preserved where compatible; no scenario may
reintroduce an external full ledger.

## Ground Truth

`ground_truth_scenarios.json` retains the existing scenario identity, type,
time range, involved accounts/entities, suspicious transactions, expected alert
type, disposition, explanation, typology tags, and notes. It additionally
exports:

```text
internal_account_ids
external_account_ids
observable_internal_facts
observable_external_facts
hidden_world_facts
```

`involved_account_ids` remains as a compatibility union of internal and
external account IDs. Internal entity IDs remain in `involved_entity_ids`;
external account IDs must not be presented as SHB customer or company entities.

Observable facts describe evidence an investigator is allowed to use.
`hidden_world_facts` contains scenario-generation truth used only for evaluation
and must never appear in a feature CSV, JSONL feature artifact, prompt context,
or evidence returned to an investigator.

## Validation Contracts

Validation must enforce:

- exactly one home bank and its ID is `BANK-SHB-001`;
- every internal account belongs to the home bank and has a valid SHB owner;
- no external account has an internal owner, KYC, device/IP assignment, or
  balance entry;
- every external account and bank reference used by a transaction resolves;
- every transaction has exactly one valid topology and matching direction;
- no external-to-external transaction exists;
- inbound external sources have no SHB source device or IP;
- country, bank, cross-border, visibility, and evidence-source fields are
  consistent;
- all normal external accounts are observed and have first/last-seen bounds
  matching their transactions;
- KYC, ownership, documents, and entity relationships resolve only to SHB
  entities;
- internal ledger replay remains legal without assuming external balances;
- feature files contain no ground-truth or hidden-world labels;
- the hybrid scenario has exactly six internal and four external fan-in sources,
  a five-minute fan-in window, a 121-second delay, and a 99.2 percent outbound;
- same-seed generation produces equal checksums for every artifact, including
  `external_accounts.csv`;
- different seeds produce different behavioral artifacts.

## Files and Responsibilities

- `backend/synthetic_data/config.py`: SHB bank constants, external population,
  and transaction-mix configuration.
- `backend/synthetic_data/models.py`: bank, external account, typed transaction,
  visibility, direction, and ground-truth schemas.
- `backend/synthetic_data/id_factory.py`: stable SHB and external account IDs.
- `backend/synthetic_data/world.py`: separate internal and external account
  collections; internal-only balances and device/IP maps.
- `backend/synthetic_data/entity_generator.py`: SHB customers, companies,
  accounts, KYC, bank directory, and external counterparties.
- `backend/synthetic_data/normal_transaction_generator.py`: typed SHB-centric
  transaction creation and exact normal direction quotas.
- `backend/synthetic_data/ledger.py`: SHB-only balance replay.
- `backend/synthetic_data/scenario_injector.py`: hybrid rapid fan-in and adapted
  remaining scenarios.
- `backend/synthetic_data/ground_truth.py`: observable and hidden fact export.
- `backend/synthetic_data/validators.py`: SHB boundary, reference, topology,
  visibility, scenario, and ledger invariants.
- `backend/synthetic_data/io_writer.py`: new schemas,
  `external_accounts.csv`, counts, checksums, and manifest.
- `backend/synthetic_data/pipeline.py`: phase ordering and quota validation.
- `backend/tests/unit/synthetic_data/test_generator.py`: regression and
  determinism coverage.
- `backend/synthetic_data/README.md` and
  `backend/synthetic_data/config.example.yaml`: operational contract and sample
  configuration.
- `backend/data/generated/`: regenerated SHB-centric artifacts.

## Scope Boundaries

This change is limited to the synthetic data package, its tests and
documentation, and regenerated artifacts. It does not modify AML detector,
investigation agent, screening, API, frontend, or orchestration business logic.
`DataRepository` is deferred until the SHB-centric output schema is stable.
