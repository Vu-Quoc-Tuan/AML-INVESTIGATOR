# KYC Security, Correctness, and Safe Cleanup Design

## Goal

Fix the five confirmed KYC/orchestrator defects without broad architectural
churn, add regression coverage for each defect, and remove only code or
`.gitkeep` files that are demonstrably redundant in the current repository.

## Scope

This change will:

- reject caller-supplied ownership graphs unless an identical backend-created
  graph already exists in the bound Shared Case File;
- prevent external identity records from being classified as full internal
  identities or marked UBO-eligible;
- report incomplete ownership coverage for every company in the bounded
  ownership graph, not only the root company;
- inspect unresolved ownership relationships for intermediate companies;
- return repository lifecycle errors separately from case revision conflicts;
- return `ENTITY_NOT_FOUND` when KYC documents are requested for an unknown
  internal entity;
- add regression tests for all confirmed cases;
- remove four unused private functions, four unused constants, eight unused
  production imports, one unused test import, and twenty-one redundant
  `.gitkeep` files.

This change will not:

- remove the 82 roadmap/scaffold placeholder files;
- remove empty `__init__.py` package markers;
- remove checked-in generated data;
- remove public helpers whose external use cannot be disproved;
- change the public tool names or replace the ownership-graph payload with a
  new graph-ID-only API;
- add a web framework, CI workflow, frontend, Docker implementation, or other
  unrelated scaffold work.

## Ownership Graph Trust Boundary

`build_ownership_graph` remains the only operation that constructs an
appendable ownership graph from repository evidence. It appends the graph to
the case before returning it.

`calculate_ubo` and `find_ownership_gaps` continue to accept the current graph
payload for compatibility, but the registry must resolve `graph_id` in the
bound case and require exact model equality with the stored graph. A missing
graph or any payload difference raises `EvidenceContractError` and leaves the
case unchanged. The domain UBO service will additionally reject a verified
edge that has no evidence IDs so direct non-registry callers cannot create an
evidence-free verified UBO.

## Identity Scope Boundary

Identity scope is derived by backend rules, never elevated by a caller-provided
`identity_scope` value.

Any record carrying an external account ID, masked external account marker, or
an `EXT-` entity/account identifier is classified as
`LIMITED_EXTERNAL_IDENTITY`. Such a record is never UBO-eligible. Existing
internal customer/company candidates retain `FULL_INTERNAL` only when they do
not carry an external marker. The current deterministic scoring and external
record matching decisions remain unchanged.

## Ownership Completeness

The UBO service computes direct ownership totals per company from graph edges.
Every reachable company with known ownership below 99.99 percent produces an
`INCOMPLETE_OWNERSHIP_COVERAGE` gap whose stable ID contains the graph and
company IDs. The existing root-level gap remains idempotent and is not emitted
twice.

When building the bounded graph, unresolved UBO relationships are collected
for every company node in the result, then deduplicated by relationship ID.
Cycles, depth cutoffs, broken chains, unverified edges, and missing supporting
documents keep their existing behavior.

## Error Handling

The case store will raise a dedicated case revision conflict exception instead
of a generic `RuntimeError`. The tool registry will map:

- repository-not-initialized failures to `DATA_REPOSITORY_NOT_INITIALIZED`;
- other repository failures to `DATA_REPOSITORY_ERROR`;
- stale case writes to `CASE_REVISION_CONFLICT`;
- KYC domain errors to their existing stable codes.

`get_kyc_documents` validates that a non-external entity exists before
returning its documents. Unknown IDs raise `EntityNotFoundError`; external IDs
continue to raise `EntityScopeViolationError`.

## Safe Cleanup

Cleanup is limited to symbols proven to have no reference in production,
tests, documentation, entrypoints, or framework hooks:

- `_utc`, `_sample_hour`, `_ownership_sum`, `_entity_start_customer`;
- `PURPOSE_CODES`, `CHANNELS`, `ACCOUNT_TYPES`, `DOCUMENT_TYPES`;
- the previously reported unused imports;
- redundant `.gitkeep` files in directories already containing tracked files.

Public utilities such as `checksum_for_seed`, `IDFactory.reset`, and
`WorldState.all_account_ids` remain unchanged in this pass because external
callers cannot be ruled out from repository evidence alone.

## Testing

Regression tests must prove:

1. A fabricated or modified graph cannot be used by `calculate_ubo` or
   `find_ownership_gaps`, and the case remains unchanged.
2. A stored graph returned by `build_ownership_graph` can still be passed to
   the downstream tools.
3. A verified ownership edge without evidence is rejected by the domain
   service.
4. An external record cannot override its scope to `FULL_INTERNAL` and cannot
   become UBO-eligible.
5. A 100-percent root owned by a company with only 50-percent upstream
   coverage produces an intermediate coverage gap.
6. An unresolved relationship on an intermediate company appears in the
   bounded graph result.
7. Repository startup failures and case revision conflicts return distinct
   error codes.
8. Unknown internal entity document lookup returns `ENTITY_NOT_FOUND`, while
   external lookup retains the scope error.

After targeted red-green verification, run the complete backend test suite,
AST parsing, `git diff --check`, the repository boundary scans, and a final
diff/status review. No test or cleanup step may modify generated data.
