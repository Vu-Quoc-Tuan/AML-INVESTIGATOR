# Synthetic Data Correctness and 2,000-Customer Scale Design

## Goal

Make the synthetic banking generator suitable for AML, KYC, graph, UBO, screening, and human-review evaluation while preserving deterministic seed-based output.

For the default seed-42 delivery, the final exported world must contain:

- exactly 2,000 customers, including every customer used by injected scenarios;
- exactly 50 companies, including every company used by injected scenarios;
- 2,500 to 3,000 accounts, including demo/external accounts;
- exactly 40,000 normal behavioral transactions, followed by additional scenario transactions; suspicious scenario transaction IDs are referenced only from the isolated ground-truth artifact;
- three suspicious scenarios, three legitimate lookalikes, and the required incomplete-evidence scenario.

The generated artifacts remain under `backend/data/generated/`.

## Selected Approach

Use a quota-first world design. Entity and account counts are final-output contracts, not baseline counts before scenario injection.

The generator will reserve deterministic entity roles for scenarios while creating the normal world. Scenario injectors will reuse those reserved entities and accounts instead of creating records outside the configured quotas. This avoids brittle subtraction of hard-coded scenario counts and lets scenario-count configuration remain meaningful.

## Generation Flow

1. Validate configuration, including minimum entity counts needed by enabled scenarios.
2. Build a deterministic roster of exactly the requested customers and companies.
3. Reserve suitable roster members for scenario roles, including source customers, shell companies, event organizers, payroll companies, import/export companies, employees, and ticket buyers.
4. Select company representatives from the existing customer roster.
5. Create the configured account population, including all required scenario accounts and demo accounts, without exceeding the final account cap.
6. Create coherent KYC profiles, documents, ownership, relationships, devices, and addresses.
7. Generate exactly the requested number of normal transactions from behavioral profiles.
8. Inject scenario transactions and scenario-specific evidence using reserved records.
9. Build isolated ground truth, validate the in-memory world, then write deterministic artifacts and checksums.

## Behavioral Transaction Contracts

Each profile controls transaction count, amount distribution, time distribution, counterparty role, cross-border probability, channel distribution, transaction type, purpose, and volatility.

Counterparty roles must resolve to compatible entity pools. For example, an employer is a company, an employee is a customer, a supplier is a company, and peer or family transfers target customers. Unsupported roles must fail configuration validation rather than silently falling back to a random account.

Cross-border sampling must use the profile's configured probability and expected-country set. A foreign transfer must resolve to a valid external account and bank record. Purpose codes must map coherently to transaction types; the normal dataset must not collapse almost entirely to `TRANSFER`.

Normal inflows must not use a visible system-float super-node. Balance-safe generation will process planned events chronologically, select valid funded counterparties, and skip or reduce a transfer when the source cannot legally debit it. Initial balances remain profile-derived and must not be retroactively raised using future transaction knowledge.

## Entity, KYC, and Ownership Contracts

- An account cannot open before its owning customer is created or its owning company is incorporated.
- KYC review dates cannot predate the entity and `next_review_at` must follow `last_reviewed_at`.
- Document issue and expiry dates must be ordered, and verification status must reflect expiry relative to `world_end`.
- `SHARED_ADDRESS` relationships must reference entities that actually share an address.
- Ownership verification requires an appropriate ownership or UBO document; a business license alone cannot verify an ownership edge.
- Active direct ownership must sum to 100 percent, except explicitly incomplete chains recorded as incomplete evidence.
- Company ownership graphs must be acyclic.

## Foreign-Key and External-Entity Design

Add an exported bank/external-entity catalog for every bank-owned demo account and every bank ID referenced by transactions. The high-risk foreign demo bank must have an explicit risk score and country rather than encoding risk only in its ID.

Every exported foreign key must resolve using exported data, including:

- customer and company addresses and representatives;
- account owners;
- transaction source and destination accounts and banks;
- KYC entity IDs;
- ownership owners, companies, and evidence documents;
- relationship endpoints;
- ground-truth involved accounts, entities, and transactions.

The incomplete-evidence screening dependency must be tied to the affected entity or scenario evidence context. It must not create a `NO_MATCH` result.

## Scenario Contracts

`RAPID_FAN_IN_PASS_THROUGH` retains the exact requested amounts, five-minute fan-in window, 121-second delay, 99.2 percent outflow, common crypto source, shared device/IP subset, high-risk foreign bank, low declared turnover, and unresolved final UBO evidence.

`EVENT_COLLECTION` retains a company older than five years, unique ticket/order references, tiered prices, a matching historical wave, no common crypto source, no abnormal shared device, and no rapid near-total foreign outflow.

The incomplete-evidence scenario retains rapid pass-through behavior, expired KYC evidence, unresolved final ownership, unavailable screening dependency, and a disposition of `NEED_MORE_EVIDENCE` or `MANUAL_REVIEW_REQUIRED`.

Scenario features must never contain `scenario_id` or expected detector/disposition labels.

## Validation and Tests

Validation must cover both the in-memory world and exported artifacts:

- final configured counts and account bounds;
- duplicate IDs before dictionary insertion and in exported files;
- all foreign keys, including demo accounts, bank IDs, relationships, and ground truth;
- complete entity, account, KYC, document, ownership, relationship, and scenario timelines;
- ownership bounds, direct totals, evidence type, and graph cycles;
- positive transaction amounts and chronological ledger replay without illegal overdraft;
- behavioral cross-border, counterparty, purpose, type, and channel consistency;
- absence of ground-truth fields from every feature artifact;
- exact scenario invariants;
- same-seed equality for every generated artifact checksum;
- different-seed inequality for behavioral artifacts;
- configured scenario counts and account caps.

Regression tests must reproduce each defect found in the seed-42 review before the corresponding fix is implemented.

## Output Files

The generated dataset will be written to `backend/data/generated/`:

- `customers.csv`
- `companies.csv`
- `accounts.csv`
- `transactions.csv`
- `addresses.csv`
- `banks.csv`
- `kyc_profiles.jsonl`
- `kyc_documents.jsonl`
- `company_ownership.csv`
- `entity_relationships.csv`
- `watchlist_entries.jsonl`
- `ground_truth_scenarios.json`
- `manifest.json`

The final handoff must report the absolute dataset directory, counts, validation results, test results, and reproducibility status.

## Scope Boundaries

This work changes only the synthetic-data package, its generated artifacts, its dependencies/configuration when required, and its unit tests/documentation. It does not modify AML detector logic or hard-code detector outcomes for scenarios.
