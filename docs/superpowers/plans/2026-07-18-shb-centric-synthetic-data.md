# SHB-Centric Synthetic Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the deterministic synthetic generator so SHB is the only home-bank ledger and every non-SHB account is a limited external counterparty observation.

**Architecture:** Keep internal `Account` records, balances, KYC, devices, and entity ownership in the SHB boundary. Add a separate `ExternalAccount` collection without balances or owners, and make every transaction carry typed endpoint references whose topology determines `INTERNAL`, `INBOUND`, or `OUTBOUND`. Adapt scenario injection, ground truth, validation, writers, and checked-in data to this boundary.

**Tech Stack:** Python 3.11, Pydantic 2, pytest, CSV, JSONL, SHA-256 manifests.

## Global Constraints

- `BANK-SHB-001` is the only home bank.
- `accounts.csv` contains only SHB-managed accounts.
- External counterparties never receive SHB owner IDs, KYC, device/IP history, balances, or off-SHB transaction history.
- Every transaction touches at least one SHB account.
- Normal transaction count remains exact and generation remains deterministic by seed.
- The main rapid fan-in scenario uses six SHB sources and four external sources.
- Existing detector, agent, API, frontend, and orchestration code stays unchanged.
- Do not commit unless the user explicitly asks for a commit.

---

### Task 1: Define the SHB Data Boundary in Models and State

**Files:**
- Modify: `backend/synthetic_data/config.py`
- Modify: `backend/synthetic_data/models.py`
- Modify: `backend/synthetic_data/id_factory.py`
- Modify: `backend/synthetic_data/world.py`
- Test: `backend/tests/unit/synthetic_data/test_generator.py`

**Interfaces:**
- Consumes: existing `StrictModel`, `GeneratorConfig`, and `WorldState` patterns.
- Produces: `AccountReferenceType`, `TransactionDirection`, `DataVisibility`, `ExternalAccount`, typed `Transaction`, `WorldState.external_accounts`, `IDFactory.external_account()`, and `GeneratorConfig.validate()`.

- [x] **Step 1: Add failing boundary-model tests**

```python
def test_shb_boundary_models(small_world):
    world, _ = small_world
    assert world.config.home_bank_id == "BANK-SHB-001"
    assert len(world.external_accounts) == world.config.n_external_accounts
    assert all(a.bank_id == world.config.home_bank_id for a in world.accounts.values())
    assert not (set(world.external_accounts) & set(world.balances))
    assert all(a.external_account_id.startswith("EXT-ACC-") for a in world.external_accounts.values())


def test_invalid_external_count_rejected():
    with pytest.raises(ValueError, match="n_external_accounts"):
        GeneratorConfig(n_external_accounts=499).validate()
```

- [x] **Step 2: Run the focused tests and confirm the old model fails**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'shb_boundary_models or invalid_external_count' -q`

Expected: failures because SHB/external configuration and collections do not exist.

- [x] **Step 3: Add enums, external model, typed transaction schema, and ground-truth visibility fields**

```python
class AccountReferenceType(str, Enum):
    INTERNAL_SHB = "INTERNAL_SHB"
    EXTERNAL = "EXTERNAL"


class TransactionDirection(str, Enum):
    INTERNAL = "INTERNAL"
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class DataVisibility(str, Enum):
    FULL_INTERNAL = "FULL_INTERNAL"
    PAYMENT_MESSAGE_ONLY = "PAYMENT_MESSAGE_ONLY"
    ENRICHED_EXTERNAL = "ENRICHED_EXTERNAL"


class ExternalAccount(StrictModel):
    external_account_id: str
    masked_account_number: str
    bank_id: str
    country_code: str
    counterparty_name: str
    counterparty_type: Literal["INDIVIDUAL", "COMPANY", "VASP"]
    available_identifier_type: str
    available_identifier_value: Optional[str]
    risk_score: float
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    metadata_source: str = "PAYMENT_MESSAGE"
    data_visibility: DataVisibility = DataVisibility.PAYMENT_MESSAGE_ONLY
```

Change `Transaction` to use `source_account_ref`, `source_account_type`, `destination_account_ref`, `destination_account_type`, `direction`, two countries, visibility, evidence source, and payment reference. Extend `GroundTruthScenario` with list fields for internal/external account IDs and observable/hidden facts. Update feature-column tuples to exactly match the design spec.

- [x] **Step 4: Add validated SHB configuration and separate world collections**

```python
home_bank_id: str = "BANK-SHB-001"
n_external_accounts: int = 1000
internal_transaction_ratio: float = 0.45
inbound_transaction_ratio: float = 0.275
outbound_transaction_ratio: float = 0.275
cross_border_ratio: float = 0.05

def validate(self) -> None:
    if not 500 <= self.n_external_accounts <= 1500:
        raise ValueError("n_external_accounts must be between 500 and 1500")
    ratios = self.internal_transaction_ratio + self.inbound_transaction_ratio + self.outbound_transaction_ratio
    if abs(ratios - 1.0) > 1e-9:
        raise ValueError("transaction direction ratios must sum to 1.0")
    if not 0.0 <= self.cross_border_ratio <= self.inbound_transaction_ratio + self.outbound_transaction_ratio:
        raise ValueError("cross_border_ratio must fit within external traffic")
```

Replace `demo_accounts` with `external_accounts: dict[str, ExternalAccount]`; keep `balances` and device/IP maps internal-only. `get_account()` returns only internal accounts and add `get_external_account()` plus `get_account_reference()`.

- [x] **Step 5: Run the focused tests**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'shb_boundary_models or invalid_external_count' -q`

Expected: pass.

### Task 2: Generate the Bank Directory, SHB Accounts, and External Counterparties

**Files:**
- Modify: `backend/synthetic_data/entity_generator.py`
- Modify: `backend/synthetic_data/pipeline.py`
- Test: `backend/tests/unit/synthetic_data/test_generator.py`

**Interfaces:**
- Consumes: `ExternalAccount`, `WorldState.external_accounts`, `home_bank_id`, and `IDFactory.external_account()` from Task 1.
- Produces: `create_banks_catalog()`, `generate_external_accounts()`, and an internal-account population containing only home-bank accounts.

- [x] **Step 1: Add failing entity-boundary tests**

```python
def test_single_home_bank_and_external_directory(small_world):
    world, _ = small_world
    home = [b for b in world.banks.values() if b.is_home_bank]
    assert [b.bank_id for b in home] == ["BANK-SHB-001"]
    assert all(a.bank_id == "BANK-SHB-001" for a in world.accounts.values())
    assert all(e.bank_id != "BANK-SHB-001" for e in world.external_accounts.values())


def test_external_accounts_have_no_internal_artifacts(small_world):
    world, _ = small_world
    external_ids = set(world.external_accounts)
    assert not (external_ids & set(world.entity_accounts))
    assert not (external_ids & set(world.entity_devices))
    assert not (external_ids & set(world.entity_ips))
    assert not (external_ids & set(world.kyc_profiles))
```

- [x] **Step 2: Run the focused tests and confirm failure**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'single_home_bank or external_accounts_have_no_internal' -q`

Expected: fail against the current multi-bank account generator.

- [x] **Step 3: Replace demo-ledger generation**

Make `generate_account()` always set `bank_id=cfg.home_bank_id` and produce `ACCT-SHB-...` IDs. Build one SHB bank row and external directory rows with `bank_name`, `bank_type`, `country_code`, `is_home_bank`, `risk_score`, and `swift_code`. Generate exactly `n_external_accounts` limited records, reserving stable IDs for crypto, high-risk foreign, domestic scenario, normal domestic, and normal foreign roles.

For every external record, leave `first_seen_at` and `last_seen_at` empty until transactions are created. Do not register it through `WorldState.register_account()`.

- [x] **Step 4: Update pipeline quota checks**

Call `config.validate()` before creating the world. Remove demo-account slots from the internal account quota because external counterparties are counted separately. Preserve exactly `min_accounts..max_accounts` internal SHB accounts.

- [x] **Step 5: Run focused entity tests**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'single_home_bank or external_accounts_have_no_internal or exact_quotas' -q`

Expected: pass.

### Task 3: Generate Typed SHB-Centric Transactions and Replay Only the SHB Ledger

**Files:**
- Modify: `backend/synthetic_data/normal_transaction_generator.py`
- Modify: `backend/synthetic_data/ledger.py`
- Test: `backend/tests/unit/synthetic_data/test_generator.py`

**Interfaces:**
- Consumes: internal and external account collections and typed transaction enums.
- Produces: `create_transaction()` supporting internal/external endpoints, exact direction quotas, external seen-bound updates, and SHB-only replay.

- [x] **Step 1: Add failing topology and visibility tests**

```python
def test_transaction_topologies_and_visibility(small_world):
    world, _ = small_world
    allowed = {
        ("INTERNAL_SHB", "INTERNAL_SHB", "INTERNAL"),
        ("EXTERNAL", "INTERNAL_SHB", "INBOUND"),
        ("INTERNAL_SHB", "EXTERNAL", "OUTBOUND"),
    }
    assert {
        (t.source_account_type.value, t.destination_account_type.value, t.direction.value)
        for t in world.transactions.values()
    } <= allowed
    for t in world.transactions.values():
        if t.direction.value == "INBOUND":
            assert t.source_ip is None and t.device_id is None
        if t.direction.value == "INTERNAL":
            assert t.data_visibility.value == "FULL_INTERNAL"


def test_exact_normal_direction_quotas(small_world):
    world, _ = small_world
    normal = [world.transactions[tid] for tid in world.normal_transaction_ids]
    counts = Counter(t.direction.value for t in normal)
    assert counts == {"INTERNAL": 540, "INBOUND": 330, "OUTBOUND": 330}
```

- [x] **Step 2: Run focused tests and confirm failure**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'transaction_topologies or exact_normal_direction' -q`

Expected: fail because current transactions assume every endpoint is a full `Account`.

- [x] **Step 3: Implement typed transaction creation**

Use a common endpoint resolver to derive reference ID, type, bank, and country. Derive direction from endpoint types and reject external-to-external calls. Apply balances only to internal endpoints. Assign device/IP only when the source is internal. Update an external endpoint's `first_seen_at` and `last_seen_at` with `min`/`max` of observed transaction timestamps.

Generate an exact shuffled direction schedule using largest-remainder allocation so totals always equal `n_transactions`. Allocate an exact cross-border subset from inbound/outbound slots. Cycle through every external account before random reuse so every exported normal external record is observed.

- [x] **Step 4: Replace ledger deficit and replay logic**

Replay only internal accounts. For inbound transactions credit only the internal destination; for outbound transactions debit only the internal source; for internal transfers do both. If an outbound/internal source lacks funds, insert a visible inbound payment-message transaction from a designated external settlement counterparty before the debit, without creating or validating an external balance.

- [x] **Step 5: Run focused transaction and ledger tests**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'transaction_topologies or exact_normal_direction or negative_balance or external' -q`

Expected: pass.

### Task 4: Adapt Scenarios and Ground Truth to the Hybrid Visibility Model

**Files:**
- Modify: `backend/synthetic_data/scenario_injector.py`
- Modify: `backend/synthetic_data/ground_truth.py`
- Modify: `backend/synthetic_data/watchlist_generator.py`
- Test: `backend/tests/unit/synthetic_data/test_generator.py`

**Interfaces:**
- Consumes: typed `create_transaction()` and reserved internal/external records.
- Produces: hybrid rapid fan-in invariants and explicit observable/hidden ground truth.

- [x] **Step 1: Add failing hybrid scenario tests**

```python
def test_hybrid_rapid_fan_in(small_world):
    world, _ = small_world
    scenario = next(s for s in world.scenarios.values() if s.notes["scenario_key"] == "RAPID_FAN_IN_PASS_THROUGH")
    assert len(scenario.internal_account_ids) == 7  # six people plus SHB company
    assert len(scenario.external_account_ids) == 6  # four senders, crypto, beneficiary
    fan_in = [world.transactions[tid] for tid in scenario.suspicious_transaction_ids if world.transactions[tid].purpose_code == "FAN_IN"]
    assert sum(t.source_account_type.value == "INTERNAL_SHB" for t in fan_in) == 6
    assert sum(t.source_account_type.value == "EXTERNAL" for t in fan_in) == 4
    assert max(t.occurred_at for t in fan_in) - min(t.occurred_at for t in fan_in) <= timedelta(minutes=5)
    outbound = next(world.transactions[tid] for tid in scenario.suspicious_transaction_ids if world.transactions[tid].purpose_code == "PASS_THROUGH")
    assert outbound.occurred_at - max(t.occurred_at for t in fan_in) == timedelta(seconds=121)
    assert outbound.amount == int(sum(t.amount for t in fan_in) * 0.992)


def test_ground_truth_visibility_isolated(small_world):
    world, _ = small_world
    assert all(s.observable_internal_facts for s in world.scenarios.values())
    forbidden = {"observable_internal_facts", "observable_external_facts", "hidden_world_facts"}
    assert not (forbidden & set(TRANSACTION_FEATURE_COLUMNS))
```

- [x] **Step 2: Run focused tests and confirm failure**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'hybrid_rapid_fan_in or ground_truth_visibility' -q`

Expected: fail because current rapid fan-in has ten internal sources and untyped ground truth.

- [x] **Step 3: Implement the hybrid scenario**

Reserve six SHB personal sources, four domestic external sources, the SHB company, crypto external source, and foreign high-risk external beneficiary. Create crypto inbound funding only for the six internal people. Create six internal and four inbound fan-in transfers, then the 99.2-percent outbound after exactly 121 seconds. Shared device/IP evidence may be assigned only to internal source entities.

Adapt every remaining scenario to typed endpoints. Preserve scenario counts and dispositions, but remove assumptions that external counterparties have balances, SHB owners, KYC, devices, or full ledgers.

- [x] **Step 4: Export visibility-aware ground truth**

Populate internal/external account lists independently, keep `involved_account_ids` as their ordered union, and add concrete observable internal facts, observable external facts, and evaluation-only hidden facts per scenario. Keep external account references out of `involved_entity_ids`.

- [x] **Step 5: Run scenario tests**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'scenario or hybrid or ground_truth or screening' -q`

Expected: pass.

### Task 5: Enforce and Export the New Contract

**Files:**
- Modify: `backend/synthetic_data/validators.py`
- Modify: `backend/synthetic_data/io_writer.py`
- Test: `backend/tests/unit/synthetic_data/test_generator.py`

**Interfaces:**
- Consumes: completed SHB-centric world and scenario structures.
- Produces: strict validation, `external_accounts.csv`, updated `banks.csv`, updated manifest counts/checksums, and deterministic artifacts.

- [x] **Step 1: Add failing exported-contract tests**

```python
def test_shb_centric_files_and_manifest(small_world):
    world, out = small_world
    external_header = (out / "external_accounts.csv").read_text().splitlines()[0]
    transaction_header = (out / "transactions.csv").read_text().splitlines()[0]
    assert "external_account_id" in external_header
    assert "source_account_type" in transaction_header
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["counts"]["external_accounts"] == len(world.external_accounts)
    assert "external_accounts.csv" in manifest["checksums_sha256"]


def test_all_external_seen_bounds_match_transactions(small_world):
    world, _ = small_world
    for external in world.external_accounts.values():
        observed = [t.occurred_at for t in world.transactions.values() if external.external_account_id in (t.source_account_ref, t.destination_account_ref)]
        assert observed
        assert external.first_seen_at == min(observed)
        assert external.last_seen_at == max(observed)
```

- [x] **Step 2: Run focused export tests and confirm failure**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data/test_generator.py -k 'shb_centric_files or external_seen_bounds' -q`

Expected: fail because the new file and manifest contract do not exist.

- [x] **Step 3: Replace multi-bank validators with SHB-boundary validators**

Validate exactly one home bank, internal ownership, external isolation, typed topology/direction, endpoint and bank references, country/cross-border consistency, visibility/evidence-source compatibility, external seen bounds, SHB-only ledger replay, scenario invariants, and absence of ground-truth fields from feature columns.

- [x] **Step 4: Write deterministic SHB-centric artifacts**

Write internal accounts only to `accounts.csv`, external observations to `external_accounts.csv`, the new bank directory schema to `banks.csv`, and typed transactions to `transactions.csv`. Add `external_accounts` to manifest counts and its checksum to `checksums_sha256`. Sort every artifact by stable ID.

- [x] **Step 5: Run the complete unit suite**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data -q`

Expected: all tests pass.

### Task 6: Update Operations Documentation and Regenerate Checked-In Data

**Files:**
- Modify: `backend/synthetic_data/config.example.yaml`
- Modify: `backend/synthetic_data/README.md`
- Modify: `backend/data/generated/*`

**Interfaces:**
- Consumes: final generator and writer.
- Produces: documented config, fresh default seed-42 dataset, checksums, and verification evidence.

- [x] **Step 1: Update generator documentation and sample configuration**

Document `home_bank_id`, `n_external_accounts`, the three direction ratios, cross-border ratio, visibility semantics, the hybrid scenario, output schemas, and the statement: `Synthetic demo distribution, not calibrated to SHB production traffic.`

- [x] **Step 2: Run the default generator**

Run: `cd backend && PYTHONPATH=. python -m synthetic_data.cli --seed 42 --customers 2000 --companies 50 --transactions 40000 --min-accounts 2500 --max-accounts 3000 --output ./data/generated`

Expected: generation and validation complete with 2,000 customers, 50 companies, 2,500–3,000 internal SHB accounts, 1,000 external accounts, and 40,000 normal transactions plus scenarios.

- [x] **Step 3: Run fresh full verification**

Run: `cd backend && PYTHONPATH=. pytest tests/unit/synthetic_data -q`

Expected: all tests pass.

Run: `cd backend && python -m compileall -q synthetic_data tests/unit/synthetic_data`

Expected: exit code 0.

Run: `git diff --check`

Expected: exit code 0 with no whitespace errors.

- [x] **Step 4: Verify manifest and data boundary directly**

Run: `cd backend && python -c "import csv,json,pathlib; p=pathlib.Path('data/generated'); a=list(csv.DictReader((p/'accounts.csv').open())); e=list(csv.DictReader((p/'external_accounts.csv').open())); t=list(csv.DictReader((p/'transactions.csv').open())); m=json.loads((p/'manifest.json').read_text()); assert {r['bank_id'] for r in a}=={'BANK-SHB-001'}; assert all(r['direction'] in {'INTERNAL','INBOUND','OUTBOUND'} for r in t); assert not any(r['source_account_type']=='EXTERNAL' and r['destination_account_type']=='EXTERNAL' for r in t); assert m['counts']['external_accounts']==len(e); print(m['counts'])"`

Expected: assertions pass and the manifest count summary is printed.

- [x] **Step 5: Review final scope**

Run: `git status --short && git diff --stat`

Expected: changes are limited to the design/plan, synthetic generator, generator tests/docs, and generated artifacts. Do not include `DataRepository` or business-agent changes in this implementation.
