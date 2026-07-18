# Shared Data Repository Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an explicitly initialized, process-cached Pandas/NetworkX repository for the SHB-centric synthetic dataset and expose it only through JSON-safe domain services.

**Architecture:** `DataRepository` loads the twelve agent-safe files atomically, validates the SHB observation boundary, and freezes three central multigraphs. A cached provider owns lifecycle; typed repository queries return defensive copies; backend services serialize results and never expose Pandas, NetworkX, the repository, or ground truth.

**Tech Stack:** Python 3.11+, Pandas, NetworkX, pytest.

## Global Constraints

- Do not perform data I/O while importing any backend module.
- Do not load `ground_truth_scenarios.json`.
- Use `nx.MultiDiGraph` for transactions, entity relationships, and ownership records.
- Use a derived `nx.DiGraph` for active ownership at a requested `as_of_date`.
- Do not expose generic DataFrame getters, raw shared graphs, or the complete watchlist.
- Preserve incomplete and cyclic ownership as investigable data unless an independent integrity rule fails.
- Agents consume backend-owned tools through domain services, never the repository directly.
- Work in the current tree and do not create commits unless the user explicitly requests them.

---

### Task 1: Dependencies, configuration, and lifecycle

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.txt`
- Create: `backend/app/data/config.py`
- Create: `backend/app/data/exceptions.py`
- Create: `backend/app/data/provider.py`
- Create: `backend/app/data/__init__.py`
- Test: `backend/tests/unit/data/test_provider.py`

**Interfaces:**
- Produces: `RepositoryConfig`, `initialize_data_repository(data_path=None, config=None)`, `get_initialized_data_repository()`, `_reset_data_repository_for_testing()`.

- [ ] Add `pandas>=2.0` and `networkx>=3.0` to both runtime dependency declarations.
- [ ] Write provider tests proving imports cause no reads, an accessor fails before warm-up, repeated warm-up returns the same object, and failed initialization is not published.
- [ ] Add a frozen `RepositoryConfig` with `home_bank_id`, ownership tolerance, and the six default ownership-supporting document types.
- [ ] Add specific repository exception classes and an explicit provider protected by a lock and process cache.
- [ ] Run `cd backend && .venv/bin/pytest tests/unit/data/test_provider.py -q`; expect all provider tests to pass.

### Task 2: Atomic loading and validation

**Files:**
- Create: `backend/app/data/repository.py`
- Test: `backend/tests/unit/data/test_repository_validation.py`

**Interfaces:**
- Produces: `DataRepository.load() -> DataRepository`, private tables, `is_loaded`, and validation helpers used before graph publication.

- [ ] Write tests for all twelve required files, missing columns, invalid timestamps, ground-truth exclusion, and atomic failure.
- [ ] Write tests for the home bank, internal/external owners and references, KYC/document/address/relationship boundaries, transaction direction/topology/visibility/country/device contracts, unique transaction IDs, and positive amounts.
- [ ] Write ownership tests proving partial coverage loads, over-100 coverage fails, `ownership_data_complete=true` enforces near-100 coverage, invalid percentages/references fail, 100-percent direct self-ownership fails, and multi-company cycles load.
- [ ] Implement CSV/JSONL loading, date normalization, required schemas, and all cross-table validations against temporary local frames before assigning instance state.
- [ ] Validate verified ownership evidence using either `document_supports` containing `OWNERSHIP` or the configured allowed document type set.
- [ ] Build a private watchlist candidate index after deriving entity type when absent; do not define a full-watchlist method.
- [ ] Run `cd backend && .venv/bin/pytest tests/unit/data/test_repository_validation.py -q`; expect all validation tests to pass.

### Task 3: Typed queries and immutable graph state

**Files:**
- Modify: `backend/app/data/repository.py`
- Test: `backend/tests/unit/data/test_repository_queries.py`
- Test: `backend/tests/unit/data/test_repository_graphs.py`

**Interfaces:**
- Produces: `transactions_for_account`, `account_by_id`, `external_account_by_id`, `entity_by_id`, `kyc_profile_by_entity`, `kyc_documents_by_entity`, `ownership_records_for_company`, `relationships_for_entity`, `watchlist_candidates`, three copied subgraph methods, and `build_active_ownership_graph`.

- [ ] Write query tests for filters, unknown IDs, defensive copies, normalized watchlist candidate matching, and absence of generic/raw getters.
- [ ] Write graph tests proving parallel edge preservation, central graph freezing, copied subgraphs, active-date filtering, pair aggregation, ownership provenance, partial coverage, and cycle metadata.
- [ ] Implement typed DataFrame/Series queries returning copies and validating direction/time inputs.
- [ ] Build and freeze transaction, relationship, and ownership `MultiDiGraph` instances only after validation succeeds.
- [ ] Implement copied induced subgraphs and a fresh active ownership `DiGraph` whose company nodes contain `ownership_coverage_percentage` and `ownership_status` and whose graph metadata contains cycle information.
- [ ] Run both repository query/graph test files; expect all tests to pass.

### Task 4: Domain-service boundary and startup warm-up

**Files:**
- Create: `backend/app/services/serialization.py`
- Create: `backend/app/services/transaction_data_service.py`
- Create: `backend/app/services/entity_data_service.py`
- Create: `backend/app/services/ownership_data_service.py`
- Create: `backend/app/services/screening_data_service.py`
- Modify: `backend/app/services/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/data/test_data_services.py`
- Test: `backend/tests/unit/data/test_startup.py`

**Interfaces:**
- Produces: `initialize_backend(data_path=None)`, `TransactionDataService`, `EntityDataService`, `OwnershipDataService`, and `ScreeningDataService`; all public results are dictionaries/lists/scalars.

- [ ] Write tests proving services fail before warm-up and return JSON-serializable data after warm-up without Pandas/NetworkX/repository objects.
- [ ] Write startup tests proving module imports do no I/O and `initialize_backend()` performs explicit cached warm-up with the supplied path.
- [ ] Implement scalar, DataFrame, Series, and graph serialization that handles Pandas timestamps, nulls, lists, and multigraph keys.
- [ ] Implement thin services that obtain the already-initialized repository internally and expose only domain-shaped serialized results.
- [ ] Implement `ScreeningDataService.candidates(...)` on the filtered repository API; never return the whole watchlist.
- [ ] Add the framework-neutral startup hook to `backend/app/main.py` without introducing FastAPI.
- [ ] Run the service and startup tests; expect all tests to pass.

### Task 5: Full regression verification

**Files:**
- Verify: all files above plus existing synthetic generator tests.

- [ ] Run `cd backend && .venv/bin/pytest -q`; expect the complete backend suite to pass.
- [ ] Run `python3 -m py_compile` for every new/modified backend Python file; expect no output and exit code 0.
- [ ] Run `git diff --check`; expect no whitespace errors.
- [ ] Inspect `git diff --stat` and confirm changes are limited to the repository, services, startup, dependency, test, and design/plan scopes.
