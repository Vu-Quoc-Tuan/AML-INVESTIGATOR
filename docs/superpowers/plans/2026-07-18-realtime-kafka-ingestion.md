# Realtime Kafka Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real-time Kafka ingestion boundary and a runnable mock transaction publisher without implementing ML, rules, tickets, or multi-agent execution.

**Architecture:** An upstream producer publishes versioned raw transaction JSON to `aml.transactions.raw.v1`. A small ingestion relay validates each event and publishes canonical JSON to `aml.transactions.validated.v1`, or a redacted error envelope to `aml.transactions.dlq.v1`, then manually commits the source offset. A standalone mock service continuously publishes valid demo events through the same producer contract.

**Tech Stack:** Python 3.11+, Pydantic 2, kafka-python 3.x, pytest, Apache Kafka 4.3.1 official Docker image in KRaft mode, Docker Compose.

## Global Constraints

- Keep existing dirty worktree changes untouched.
- Do not modify the current root `docker-compose.yml` or `backend/Dockerfile`.
- Do not implement feature computation, ML inference, rule evaluation, tickets, or multi-agent invocation.
- Use `localhost:9092` for host clients and `kafka:29092` for Docker-network clients.
- Use topics `aml.transactions.raw.v1`, `aml.transactions.validated.v1`, and `aml.transactions.dlq.v1`.
- Use at-least-once delivery with auto-commit disabled.
- Commit a source offset only after the selected output publish is acknowledged.
- Never log or place a full unredacted invalid transaction payload in the DLQ.
- Keep mock publishing separate from the production ingestion contract.

---

### Task 1: Transaction event and Kafka settings contracts

**Files:**
- Create: `backend/app/streaming/__init__.py`
- Create: `backend/app/streaming/config.py`
- Create: `backend/app/streaming/schemas.py`
- Test: `backend/tests/unit/streaming/test_config.py`
- Test: `backend/tests/unit/streaming/test_schemas.py`

**Interfaces:**
- Produces: `KafkaSettings.from_env() -> KafkaSettings`.
- Produces: `TransactionEventV1`, `DeadLetterEventV1`, `canonical_json_bytes(model) -> bytes`.
- Consumes: existing `TransactionDirection` values from `app.schemas.common`.

- [ ] **Step 1: Write schema tests for valid internal, inbound, and outbound events**

```python
def test_outbound_event_requires_payment_message_visibility():
    event = make_event(
        direction="OUTBOUND",
        source_bank_id="BANK-SHB-001",
        destination_bank_id="BANK-FOREIGN-SG-DEMO",
        data_visibility="PAYMENT_MESSAGE_ONLY",
    )
    assert event.schema_version == "1.0"

def test_cross_boundary_event_rejects_full_internal_visibility():
    with pytest.raises(ValidationError):
        make_event(
            direction="OUTBOUND",
            destination_bank_id="BANK-FOREIGN-SG-DEMO",
            data_visibility="FULL_INTERNAL",
        )
```

- [ ] **Step 2: Run schema tests and confirm missing module failure**

Run: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/streaming/test_schemas.py -q`

Expected: collection fails because `app.streaming.schemas` does not exist.

- [ ] **Step 3: Implement strict versioned models and canonical serialization**

```python
class TransactionEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    occurred_at: datetime
    ingested_at: datetime
    source_account_ref: str = Field(min_length=1)
    destination_account_ref: str = Field(min_length=1)
    source_bank_id: str = Field(min_length=1)
    destination_bank_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    direction: TransactionDirection
    data_visibility: Literal[
        "FULL_INTERNAL", "PAYMENT_MESSAGE_ONLY", "ENRICHED_EXTERNAL"
    ]
```

Add timezone and SHB visibility checks through `model_validator(mode="after")`. Serialize with `model_dump_json(exclude_none=True)` encoded as UTF-8.

- [ ] **Step 4: Write and run environment settings tests**

```python
def test_settings_use_documented_defaults(monkeypatch):
    for name in KafkaSettings.environment_names():
        monkeypatch.delenv(name, raising=False)
    settings = KafkaSettings.from_env()
    assert settings.bootstrap_servers == ("localhost:9092",)
    assert settings.raw_topic == "aml.transactions.raw.v1"
    assert settings.enable_auto_commit is False
```

Run: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/streaming/test_config.py tests/unit/streaming/test_schemas.py -q`

Expected: all contract tests pass.

### Task 2: Pure ingestion routing and acknowledgement boundary

**Files:**
- Create: `backend/app/streaming/relay.py`
- Test: `backend/tests/unit/streaming/test_relay.py`

**Interfaces:**
- Consumes: `TransactionEventV1`, `DeadLetterEventV1`, `KafkaSettings`.
- Produces: `RelayDecision(topic: str, key: bytes, value: bytes, route: Literal["validated", "dlq"])`.
- Produces: `TransactionRelay.route(raw_value: bytes | None, metadata: SourceMetadata) -> RelayDecision`.
- Produces: `process_record(record, producer, consumer, relay, settings) -> RelayDecision`.

- [ ] **Step 1: Write failing routing tests**

```python
def test_valid_event_routes_to_validated_topic():
    decision = relay.route(valid_event_bytes(), source_metadata())
    assert decision.route == "validated"
    assert decision.topic == "aml.transactions.validated.v1"
    assert decision.key == b"EVENT-1"

def test_malformed_json_routes_to_redacted_dlq():
    decision = relay.route(b'{"account":"secret"', source_metadata())
    assert decision.route == "dlq"
    assert b"secret" not in decision.value
```

- [ ] **Step 2: Run relay tests and confirm they fail before implementation**

Run: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/streaming/test_relay.py -q`

Expected: collection fails because `app.streaming.relay` does not exist.

- [ ] **Step 3: Implement pure routing**

Decode JSON, validate `TransactionEventV1`, emit canonical event bytes for valid messages, and emit `DeadLetterEventV1` with source topic/partition/offset, safe error code, safe error message, optional event ID, and failure timestamp for invalid messages.

```python
@dataclass(frozen=True)
class RelayDecision:
    topic: str
    key: bytes
    value: bytes
    route: Literal["validated", "dlq"]
```

- [ ] **Step 4: Write acknowledgement-order tests**

```python
def test_commit_happens_only_after_publish_acknowledgement():
    order = []
    producer = FakeProducer(order)
    consumer = FakeConsumer(order)
    process_record(record, producer, consumer, relay, settings)
    assert order == ["send", "ack", "commit"]

def test_publish_failure_does_not_commit():
    producer = FailingProducer()
    consumer = FakeConsumer([])
    with pytest.raises(PublishFailed):
        process_record(record, producer, consumer, relay, settings)
    assert consumer.commits == []
```

- [ ] **Step 5: Run the relay suite**

Run: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/streaming/test_relay.py -q`

Expected: routing, redaction, and acknowledgement ordering tests pass.

### Task 3: Kafka clients and runtime ingestion process

**Files:**
- Create: `backend/app/streaming/clients.py`
- Create: `backend/app/streaming/runtime.py`
- Create: `backend/scripts/run_kafka_ingestion.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/requirements.txt`
- Modify: `backend/.env.example`
- Test: `backend/tests/unit/streaming/test_clients.py`
- Test: `backend/tests/unit/streaming/test_runtime.py`

**Interfaces:**
- Produces: `build_producer(settings) -> KafkaProducer`.
- Produces: `build_consumer(settings) -> KafkaConsumer` with `enable_auto_commit=False`.
- Produces: `run_ingestion(settings, stop_requested) -> None`.
- Consumes: `process_record` from Task 2.

- [ ] **Step 1: Add client configuration tests using patched Kafka constructors**

```python
def test_consumer_disables_auto_commit(monkeypatch):
    captured = {}
    monkeypatch.setattr(clients, "KafkaConsumer", fake_constructor(captured))
    clients.build_consumer(KafkaSettings.from_env())
    assert captured["enable_auto_commit"] is False
    assert captured["group_id"] == "aml-ingestion-v1"
```

- [ ] **Step 2: Add kafka-python 3.x dependency**

Add `kafka-python>=3.0,<4.0` to both dependency manifests. Do not add ML or ticket dependencies.

- [ ] **Step 3: Implement producer, consumer, and long-running runtime**

The consumer subscribes only to the raw topic, polls in bounded intervals, skips no records silently, delegates each record to `process_record`, and closes without an auto-commit. The producer uses JSON bytes supplied by the relay and waits for send acknowledgement before returning.

- [ ] **Step 4: Add signal-aware CLI**

```python
def main() -> int:
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    run_ingestion(KafkaSettings.from_env(), stop.is_set)
    return 0
```

- [ ] **Step 5: Run client/runtime unit tests**

Run: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/streaming/test_clients.py tests/unit/streaming/test_runtime.py -q`

Expected: tests pass without requiring a live Kafka broker.

### Task 4: Mock realtime transaction service

**Files:**
- Create: `backend/app/streaming/mock_service.py`
- Create: `backend/scripts/run_mock_transaction_service.py`
- Test: `backend/tests/unit/streaming/test_mock_service.py`

**Interfaces:**
- Produces: `MockTransactionFactory.next_event() -> TransactionEventV1`.
- Produces: `run_mock_publisher(settings, interval_seconds, limit, stop_requested) -> int`.
- Consumes: `build_producer` and canonical serialization.

- [ ] **Step 1: Write deterministic mock-event tests**

```python
def test_mock_factory_emits_unique_valid_events():
    clock = FixedClock("2026-07-18T10:00:00Z")
    factory = MockTransactionFactory(seed=42, clock=clock)
    first = factory.next_event()
    second = factory.next_event()
    assert first.event_id != second.event_id
    assert first.amount > 0
    TransactionEventV1.model_validate(first.model_dump())
```

- [ ] **Step 2: Implement a minimal continuous publisher**

The service publishes one valid event per interval, uses the event ID as Kafka key, supports `--interval`, `--limit`, and `--seed`, waits for broker acknowledgement, logs only IDs and delivery metadata, and exits cleanly on SIGINT/SIGTERM.

- [ ] **Step 3: Test publisher acknowledgement and limit behavior**

```python
def test_mock_publisher_waits_for_ack_and_honors_limit():
    producer = FakeProducer()
    count = run_mock_publisher(settings, 0, 3, lambda: False, producer=producer)
    assert count == 3
    assert producer.ack_count == 3
```

- [ ] **Step 4: Run mock-service tests**

Run: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/streaming/test_mock_service.py -q`

Expected: deterministic factory and real-time loop tests pass.

### Task 5: Kafka deployment, topic initialization, and operator guide

**Files:**
- Create: `docker-compose.kafka.yml`
- Create: `backend/scripts/create_kafka_topics.py`
- Create: `backend/README-KAFKA.md`
- Test: `backend/tests/unit/streaming/test_topic_admin.py`

**Interfaces:**
- Produces: a single-node Apache Kafka 4.3.1 KRaft broker reachable at `localhost:9092` from the host and `kafka:29092` inside its Docker network.
- Produces: `ensure_topics(settings, partitions=1, replication_factor=1)`.
- Consumes: settings from Task 1 and kafka-python admin client.

- [ ] **Step 1: Implement idempotent topic creation with tests**

```python
def test_ensure_topics_creates_only_missing_topics():
    admin = FakeAdmin(existing={"aml.transactions.raw.v1"})
    ensure_topics(settings, admin=admin)
    assert {topic.name for topic in admin.created} == {
        "aml.transactions.validated.v1",
        "aml.transactions.dlq.v1",
    }
```

- [ ] **Step 2: Add isolated Kafka Compose**

Use `apache/kafka:4.3.1`, KRaft combined mode, explicit internal and host listeners, replication factor 1 for local internal topics, a healthcheck, and a named data volume. Do not edit root Compose.

- [ ] **Step 3: Document exact demo commands**

Document:

```bash
docker compose -f docker-compose.kafka.yml up -d
cd backend
.venv/bin/python scripts/create_kafka_topics.py
.venv/bin/python scripts/run_kafka_ingestion.py
.venv/bin/python scripts/run_mock_transaction_service.py --interval 1 --limit 10
```

State explicitly that real upstream services publish to `localhost:9092` / `aml.transactions.raw.v1`, or `kafka:29092` when sharing the Docker network.

- [ ] **Step 4: Run all focused tests and static checks**

Run: `cd backend && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/streaming -q`

Expected: all streaming unit tests pass.

Run: `backend/.venv/bin/ruff check backend/app/streaming backend/scripts/run_kafka_ingestion.py backend/scripts/run_mock_transaction_service.py backend/scripts/create_kafka_topics.py backend/tests/unit/streaming`

Expected: no Ruff findings in the new Kafka surface.

- [ ] **Step 5: Run live smoke verification when Docker is available**

Start Kafka, create topics, start ingestion, publish valid mock events, consume the validated topic, then send one invalid JSON event and consume the DLQ topic. Verify event IDs match and the DLQ does not contain the original full payload.

- [ ] **Step 6: Inspect the final diff without touching unrelated work**

Run: `git status --short` and `git diff --check -- <Kafka paths>`.

Expected: only Kafka paths created or modified by this plan are attributable to this task; all pre-existing dirty files remain unchanged.
