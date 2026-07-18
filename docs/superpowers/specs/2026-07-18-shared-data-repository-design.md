# Shared Data Repository Design

## Goal

Provide one backend-owned Pandas and NetworkX data layer for the SHB-centric
synthetic dataset. The repository loads and validates agent-safe files once,
builds immutable central graphs once, and serves typed queries to domain
services. Investigation agents must use backend-owned tools built on those
services rather than loading files or accessing the repository directly.

The repository must never load or expose `ground_truth_scenarios.json`.

## Selected Architecture

Use an explicitly initialized cached factory rather than a class-level singleton
or import-time global instance.

```text
backend startup hook
        │
        ▼
initialize_data_repository()
        │
        ▼
cached DataRepository instance
        │
        ├── private Pandas DataFrames
        ├── frozen transaction MultiDiGraph
        ├── frozen entity relationship MultiDiGraph
        └── frozen ownership MultiDiGraph
                  │
                  ▼
           domain data services
                  │
                  ▼
       backend-owned agent tools/API
```

Construction has no import side effect. `app.main.initialize_backend()` is the
framework-neutral startup hook for the current scaffold and calls the explicit
repository initializer. The future FastAPI lifespan must call this same hook.
Because the repository is cached, repeated initialization returns the same
loaded object and does not reread files or rebuild graphs.

## Files and Responsibilities

- `backend/app/data/repository.py`: repository, loaders, schema/data-boundary
  validation, typed DataFrame queries, graph construction, subgraph copies, and
  active ownership graph construction.
- `backend/app/data/config.py`: immutable repository configuration, including
  ownership tolerance and ownership-supporting document types.
- `backend/app/data/provider.py`: cached factory, explicit initializer, loaded
  repository accessor, and test-only cache reset.
- `backend/app/data/exceptions.py`: specific initialization, missing-file,
  schema, and integrity exceptions.
- `backend/app/data/__init__.py`: internal backend exports only; importing it
  does not load data.
- `backend/app/main.py`: framework-neutral `initialize_backend()` warm-up hook;
  no FastAPI application is introduced in this task because the current backend
  entrypoint is empty and FastAPI is not a dependency.
- `backend/app/services/transaction_data_service.py`: transaction queries and
  serialized transaction-subgraph results.
- `backend/app/services/entity_data_service.py`: account, external counterparty,
  customer/company, KYC, document, and relationship queries.
- `backend/app/services/ownership_data_service.py`: ownership records and
  serialized active ownership graph results.
- `backend/app/services/screening_data_service.py`: indexed watchlist candidate
  lookup without exposing the complete watchlist table.
- `backend/tests/unit/data/`: repository, provider, validation, graph, service,
  and startup tests.
- `backend/pyproject.toml` and `backend/requirements.txt`: Pandas and NetworkX
  runtime dependencies.

## Agent-Safe Data Inputs

The repository loads these twelve artifacts from `backend/data/generated/`:

```text
customers.csv
companies.csv
accounts.csv
external_accounts.csv
transactions.csv
addresses.csv
banks.csv
kyc_profiles.jsonl
kyc_documents.jsonl
company_ownership.csv
entity_relationships.csv
watchlist_entries.jsonl
```

It does not load `ground_truth_scenarios.json` or expose a generic filesystem or
table-name loader.

Default data path resolution is relative to the backend package, not the
process working directory. Tests and alternative deployments may pass an
explicit directory to the initializer before the cached instance is created.

## Loading and DataFrame Handling

CSV files use `pandas.read_csv`. JSONL files use `pandas.read_json(...,
lines=True)`. Date and timestamp columns are normalized once during load:

- timestamps use timezone-aware UTC `datetime64` values;
- date-only fields use normalized Pandas timestamps;
- empty end dates remain null rather than becoming strings.

All central DataFrames remain private. There is no `get_dataframe(name)` and no
public property returning a central DataFrame. Repository query methods return
defensive DataFrame or Series copies.

## Required Schema Validation

Every file has a declared required-column set matching the checked-in
SHB-centric artifacts. Initialization fails before graph construction if a
required file or column is missing, a required identifier is null, an amount or
ownership percentage cannot be parsed, or a required timestamp is invalid.

Failures use specific exceptions:

- `DataRepositoryNotInitializedError` when a service requests data before
  startup warm-up;
- `DataFileNotFoundError` for missing artifacts;
- `DataSchemaError` for missing or invalid columns/types;
- `DataIntegrityError` for cross-table or SHB-boundary violations.

Errors include the file/table, affected identifier when available, and violated
contract. Initialization is atomic: a failed load leaves the repository
uninitialized and publishes no partial DataFrame or graph state.

`companies.csv` may optionally contain `ownership_data_complete`. When absent,
it defaults to `false`; the repository does not infer completeness merely from
the current ownership total.

## SHB Data-Boundary Validation

Initialization enforces all of the following:

- `banks.csv` contains exactly one `is_home_bank=true` row and its ID is
  `BANK-SHB-001`;
- every internal account uses `BANK-SHB-001`;
- every internal account owner resolves to the correct customer or company
  table according to `owner_entity_type`;
- every external account uses a non-home bank present in `banks.csv`;
- external account IDs do not appear as internal owners, KYC entities, document
  entities, ownership entities, or entity-relationship endpoints;
- customer/company addresses and company representatives resolve;
- KYC profiles and documents resolve only to internal SHB entities;
- watchlist `related_entity_id`, when present, resolves to an internal entity.

## Transaction Validation

Allowed endpoint topology is exact:

| Source type | Destination type | Direction |
|---|---|---|
| `INTERNAL_SHB` | `INTERNAL_SHB` | `INTERNAL` |
| `EXTERNAL` | `INTERNAL_SHB` | `INBOUND` |
| `INTERNAL_SHB` | `EXTERNAL` | `OUTBOUND` |

External-to-external transactions are invalid. For each endpoint, the account
reference and bank must resolve to the corresponding internal or external
table. Source/destination countries must match the bank/account records and
`is_cross_border` must match the country comparison.

Visibility validation is exact:

- internal transfers require `FULL_INTERNAL` and
  `SHB_TRANSACTION_LEDGER` evidence;
- cross-boundary transfers require `PAYMENT_MESSAGE_ONLY` or
  `ENRICHED_EXTERNAL`;
- `ENRICHED_EXTERNAL` requires a nonempty explicit enrichment evidence source;
- inbound external sources cannot contain an SHB `source_ip` or `device_id`.

Transaction IDs must be unique and amounts must be positive.

## Ownership Validation

Every ownership record must satisfy:

- `owner_entity_id` resolves according to `owner_entity_type`;
- `owned_company_id` resolves to an SHB company;
- percentage is in `(0, 100]`;
- `effective_to` is null or no earlier than `effective_from`;
- verified records have an existing `source_document_id`, the referenced
  document has status `VERIFIED`, and the document either explicitly contains
  `OWNERSHIP` in `document_supports` or its type belongs to the configured
  ownership-supporting type set;
- active direct ownership for a company must not exceed 100 percent outside the
  configured tolerance;
- active direct ownership may total less than 100 percent and still load;
- a company marked `ownership_data_complete=true` must total approximately 100
  percent within the configured tolerance;
- direct 100-percent self-ownership is rejected as an integrity error.

The default ownership-supporting document types are:

```text
UBO_DECLARATION
ARTICLES_OF_ASSOCIATION
SHAREHOLDER_REGISTER
BUSINESS_REGISTRATION
SHARE_TRANSFER_AGREEMENT
CORPORATE_STRUCTURE_DECLARATION
```

For each company and `as_of_date`, the repository derives
`ownership_coverage_percentage` from active direct ownership and sets
`ownership_status` to `COMPLETE` only when coverage is approximately 100
percent; otherwise it is `INCOMPLETE`.

Multi-company cycles such as `A -> B -> C -> A` are retained because they may
be AML evidence rather than malformed input. The ownership graph is published
with `ownership_cycle_detected=true` and cycle members available as graph
metadata. Cycles do not fail startup unless an independent integrity rule is
violated.

## Central Graphs

### Transaction graph

The central transaction graph is a frozen `networkx.MultiDiGraph`. Account IDs
are nodes. Each transaction is a distinct edge keyed by `transaction_id`, so
repeated transfers between the same account pair never overwrite one another.

Node attributes distinguish `INTERNAL_SHB` from `EXTERNAL` and contain only
agent-safe account/bank/country metadata. Edge attributes contain the complete
transaction feature row.

### Entity relationship graph

The central entity relationship graph is a frozen `networkx.MultiDiGraph`.
Entity IDs are nodes and each relationship is keyed by `relationship_id`.
Multiple relationship types between the same entity pair are preserved.

### Ownership graph

The central ownership graph is a frozen `networkx.MultiDiGraph`. Owners point
to owned companies and each edge is keyed by `ownership_id`. Historical or
reissued ownership records between the same pair remain distinct. Graph
metadata records whether a company-ownership cycle was detected and preserves
the detected cycle members for later analysis.

### Active ownership graph

`build_active_ownership_graph(as_of_date)` returns a new mutable
`networkx.DiGraph`, never the shared central graph. It selects records where:

```text
effective_from <= as_of_date
and (effective_to is null or effective_to >= as_of_date)
```

If multiple active records share the same owner/company pair, their percentages
are summed and their ownership IDs are retained as an ordered list. This graph
is suitable for later UBO traversal without losing record provenance. Company
nodes include `ownership_coverage_percentage` and `ownership_status`; graph
metadata includes active ownership-cycle detection results.

## Repository Query Interface

There is no generic DataFrame getter and no raw central graph getter.

Typed repository methods available to backend domain services are:

```python
transactions_for_account(
    account_id: str,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    direction: str | None = None,
) -> pd.DataFrame

account_by_id(account_id: str) -> pd.Series | None
external_account_by_id(external_account_id: str) -> pd.Series | None
entity_by_id(entity_id: str) -> pd.Series | None
kyc_profile_by_entity(entity_id: str) -> pd.Series | None
kyc_documents_by_entity(entity_id: str) -> pd.DataFrame
ownership_records_for_company(company_id: str) -> pd.DataFrame
relationships_for_entity(entity_id: str) -> pd.DataFrame
watchlist_candidates(
    normalized_name: str,
    entity_type: str,
    nationalities: list[str] | None = None,
    date_of_birth: date | None = None,
    list_types: list[str] | None = None,
) -> pd.DataFrame

transaction_subgraph(account_ids: collection[str]) -> nx.MultiDiGraph
entity_subgraph(entity_ids: collection[str]) -> nx.MultiDiGraph
ownership_subgraph(entity_ids: collection[str]) -> nx.MultiDiGraph
build_active_ownership_graph(as_of_date: str | date | datetime) -> nx.DiGraph
```

All returned Series/DataFrames and subgraphs are defensive copies. Unknown IDs
return empty results or `None`; invalid directions and invalid timestamps raise
`ValueError` before querying.

Watchlist data is indexed once during initialization by normalized name,
entity type, list type, and nationality. Candidate lookup requires an exact
normalized-name and entity-type match, then applies the optional nationality,
date-of-birth, and list-type filters. When the current synthetic file does not
contain an explicit entity type, the repository derives `COMPANY` from a
present company registration number and otherwise uses `INDIVIDUAL`; a future
explicit field takes precedence. Neither repository nor service exposes a
method that returns the entire watchlist.

## Domain Service Boundary

The repository is backend infrastructure, not an agent tool API.

- `TransactionDataService` exposes filtered transaction records as serialized
  dictionaries and serializes copied transaction subgraphs into nodes/edges.
- `EntityDataService` exposes account, entity, KYC, document, relationship, and
  relationship data as JSON-safe dictionaries/lists.
- `OwnershipDataService` exposes ownership records and serialized active
  ownership graphs, including coverage, completeness, and cycle metadata.
- `ScreeningDataService` exposes only filtered watchlist candidates as JSON-safe
  dictionaries.

No service returns Pandas objects, NetworkX objects, private repository
collections, or a repository instance. Agent tools and APIs must depend on
these services.

Graph serialization uses:

```json
{
  "nodes": [{"id": "...", "attributes": {}}],
  "edges": [
    {
      "source": "...",
      "target": "...",
      "key": "...",
      "attributes": {}
    }
  ]
}
```

The active ownership `DiGraph` edge omits `key` but retains
`ownership_ids` in its attributes.

## Initialization and Lifecycle

`initialize_data_repository(data_path=None)` calls the cached factory and fully
loads/validates the repository. `get_initialized_data_repository()` raises if
warm-up has not completed; it does not silently initialize during a domain
request.

`app.main.initialize_backend(data_path=None)` is the explicit current startup
hook. Importing `app.main`, `app.data`, provider modules, repository modules, or
domain service modules performs no data I/O.

Tests may call a clearly internal `_reset_data_repository_for_testing()` to
clear the cache between isolated temporary datasets. Production code must not
reset or reload the repository.

## Testing

Tests cover:

- no I/O at import time;
- explicit warm-up and repeated initialization returning the same instance;
- each file being loaded once;
- missing-file, missing-column, invalid timestamp, and atomic failure behavior;
- SHB home-bank and internal/external reference contracts;
- transaction topology, direction, visibility, country, device/IP, uniqueness,
  and positive-amount contracts;
- KYC, document, relationship, watchlist, and ownership integrity;
- incomplete ownership coverage loading successfully, totals over 100 percent
  being rejected, and completeness enforcement only for explicitly complete
  companies;
- ownership-cycle retention and metadata, plus rejection of direct 100-percent
  self-ownership;
- configurable ownership-supporting document types and `document_supports`;
- normalized watchlist candidate filtering without a full-watchlist API;
- `MultiDiGraph` preservation of parallel transactions, relationships, and
  ownership records;
- active ownership filtering, aggregation, and provenance by date;
- defensive DataFrame/subgraph copies;
- domain services returning JSON-safe serialized results only;
- repository refusing to expose or load ground truth;
- startup warm-up using the configured data path.

## Scope Boundaries

This task implements the shared data layer, its internal domain-service boundary,
startup warm-up hook, dependencies, and tests. It does not implement AML
detection, graph analytics, UBO traversal algorithms, agent prompts, APIs,
FastAPI wiring, database persistence, or ground-truth access.
