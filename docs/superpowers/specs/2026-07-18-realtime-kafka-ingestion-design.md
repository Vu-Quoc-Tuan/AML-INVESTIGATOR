# Realtime Kafka Ingestion Design

**Status:** Proposed for implementation  
**Date:** 2026-07-18  
**Scope:** Kafka transport and ingestion boundary only

## 1. Objective

Add a real-time Kafka entry point for AML transaction events. An upstream
transaction system publishes raw JSON events to Kafka. The AML backend receives
and validates those events, routes invalid events to a dead-letter topic, and
publishes valid events to a stable downstream topic for the future ML and
rule-based detection worker.

This phase must make the Kafka boundary runnable and testable without claiming
that ML inference, rule evaluation, ticket creation, or multi-agent investigation
already exists.

## 2. Scope

### Included

- Local Kafka broker deployment through Docker Compose.
- Environment-driven broker and topic configuration.
- A versioned raw transaction event contract.
- A producer utility for smoke testing with individual JSON events.
- A long-running ingestion consumer that:
  - reads raw events in real time;
  - validates message encoding and schema;
  - preserves the original event identity and event time;
  - publishes valid events to the validated topic;
  - publishes invalid events to the dead-letter topic;
  - commits source offsets only after the output publish succeeds.
- Structured operational logs without transaction PII payload dumps.
- Unit tests for configuration, schema validation, serialization, routing, and
  offset-commit behavior.
- Run instructions showing exactly where an upstream system must publish.

### Excluded

- Feature computation and rolling-window state.
- XGBoost inference or model calibration.
- Rule-based detection and risk aggregation.
- Ticket creation or ticket persistence.
- Invocation of the LangGraph multi-agent workflow.
- Frontend integration.
- Production authentication, TLS, ACL, and managed-Kafka provisioning.

## 3. Approaches Considered

### A. Cherry-pick the old Kafka commit

This is fast but rejected. Commit `33b8a55` mixes Kafka transport with CSV
replay, XGBoost inference, rule evaluation, SQLite tickets, generated logs,
binary database data, and thresholds that do not match the intended routing.
Cherry-picking it would broaden the phase and preserve known design defects.

### B. Clean direct-to-Kafka ingestion boundary

This is the selected approach. The upstream system publishes directly to a raw
Kafka topic. A small AML ingestion consumer validates and relays events to a
validated topic. ML and rule workers can later consume that validated topic
without changing the upstream contract.

### C. HTTP ingestion gateway in front of Kafka

This would help an upstream system that cannot speak Kafka, but it adds an API,
backpressure behavior, authentication, and another runtime service. It is
deferred until a real upstream integration requires HTTP.

## 4. Data Flow

```text
Upstream transaction system
  -> aml.transactions.raw.v1
  -> AML ingestion consumer
       -> schema valid   -> aml.transactions.validated.v1
       -> schema invalid -> aml.transactions.dlq.v1

Future phase:
aml.transactions.validated.v1
  -> feature computation
  -> ML + rule-based detection
  -> routing policy
```

The ingestion consumer does not call ML, rules, ticket APIs, or the multi-agent
workflow.

## 5. Connection Contract

The upstream system points its Kafka producer to:

- From the host machine: `localhost:9092`.
- From another service in the Docker Compose network: `kafka:29092`.
- Topic: `aml.transactions.raw.v1`.
- Message key: `event_id`.
- Message value: UTF-8 JSON matching `TransactionEventV1`.

The addresses and topic names are defaults. Runtime code reads them from
environment variables so staging or production brokers do not require source
changes.

## 6. Transaction Event Contract

`TransactionEventV1` contains transport-level and raw transaction fields only:

```json
{
  "schema_version": "1.0",
  "event_id": "EVENT-20260718-000001",
  "transaction_id": "TX-20260718-000001",
  "occurred_at": "2026-07-18T10:15:30Z",
  "ingested_at": "2026-07-18T10:15:31Z",
  "source_account_ref": "ACCT-SHB-000001",
  "destination_account_ref": "EXT-ACCOUNT-000123",
  "source_bank_id": "BANK-SHB-001",
  "destination_bank_id": "BANK-FOREIGN-SG-DEMO",
  "amount": 1250000.0,
  "currency": "VND",
  "direction": "OUTBOUND",
  "data_visibility": "PAYMENT_MESSAGE_ONLY"
}
```

Validation rules:

- `schema_version` must be `1.0`.
- IDs must be non-empty strings.
- Timestamps must be timezone-aware ISO 8601 values.
- `amount` must be strictly positive.
- `currency` must be a three-letter uppercase code.
- `direction` must be `INTERNAL`, `INBOUND`, or `OUTBOUND`.
- `data_visibility` must be `FULL_INTERNAL`, `PAYMENT_MESSAGE_ONLY`, or
  `ENRICHED_EXTERNAL`.
- Internal transactions require both bank IDs to be the SHB home bank.
- Cross-boundary transactions must not claim `FULL_INTERNAL` visibility.

The contract deliberately excludes the 38 prepared ML features. Those features
must be computed from raw events and reference data in a later phase.

## 7. Components

### Kafka configuration

A typed settings object owns bootstrap servers, consumer group, topic names,
poll timeout, and delivery timeout. Configuration is loaded from environment
variables with development defaults.

### Smoke producer

The producer accepts one JSON file or one JSON line from standard input and
publishes it unchanged to the raw topic with `event_id` as the message key. CSV
replay is not the production contract.

### Ingestion consumer

The consumer owns only transport-boundary responsibilities:

1. Decode the Kafka value as JSON.
2. Validate it as `TransactionEventV1`.
3. Publish a canonical JSON representation to the validated topic.
4. On decoding or validation failure, publish a redacted error envelope to the
   dead-letter topic.
5. Commit the raw-topic offset only after the selected output publish is
   acknowledged.

The DLQ envelope includes the source topic, partition, offset, event ID when
available, error code, error details safe for logs, and failure time. It must not
include secrets or a full unredacted transaction payload.

## 8. Delivery and Failure Semantics

- Delivery is at-least-once.
- Auto-commit is disabled.
- A stable `event_id` is mandatory and used as the Kafka message key.
- Consumers downstream must remain idempotent because a crash after producing
  but before committing can replay an event.
- Transient broker failures are retried with bounded backoff.
- Invalid messages go to the DLQ and then have their raw offsets committed.
- If both normal output and DLQ publication fail, the raw offset is not
  committed.
- SIGINT and SIGTERM stop polling, finish the in-flight message, and close the
  Kafka client cleanly.

Exactly-once processing and a durable cross-service idempotency store are not
claimed in this phase.

## 9. Topic Layout

| Topic | Producer | Consumer | Purpose |
|---|---|---|---|
| `aml.transactions.raw.v1` | Upstream transaction system | AML ingestion consumer | Raw transaction intake |
| `aml.transactions.validated.v1` | AML ingestion consumer | Future detection worker | Validated canonical events |
| `aml.transactions.dlq.v1` | AML ingestion consumer | Operator/replay tooling | Invalid or undecodable events |

Development Compose creates the topics explicitly rather than relying on topic
auto-creation. The raw and validated topics use `event_id` keys. Initial local
deployment may use one broker, while topic and client configuration must not
assume a single partition.

## 10. Configuration

Initial variables:

```dotenv
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_RAW_TOPIC=aml.transactions.raw.v1
KAFKA_VALIDATED_TOPIC=aml.transactions.validated.v1
KAFKA_DLQ_TOPIC=aml.transactions.dlq.v1
KAFKA_INGESTION_GROUP=aml-ingestion-v1
KAFKA_CLIENT_ID=aml-investigator-backend
KAFKA_AUTO_OFFSET_RESET=earliest
```

Docker services override the bootstrap address with `kafka:29092`.

## 11. Testing

Unit tests cover:

- valid internal, inbound, and outbound events;
- invalid timestamps, amount, currency, direction, and visibility;
- malformed JSON and tombstone messages;
- validated-topic routing;
- DLQ routing and redaction;
- no offset commit before output acknowledgement;
- offset commit after successful validated or DLQ publication;
- stable serialization and message key selection;
- environment configuration parsing.

A local smoke procedure covers:

1. Start Kafka and create topics.
2. Start the ingestion consumer.
3. Publish one valid event and observe it on the validated topic.
4. Publish one invalid event and observe it on the DLQ topic.
5. Restart the consumer and verify committed offsets are respected.

The smoke producer is a test utility, not proof of connection to a real banking
transaction source.

## 12. Handoff to the Next Phase

The future detection worker will consume `aml.transactions.validated.v1`. It
will compute realtime features, execute ML and rule-based detection, and apply
the 60/95 routing policy. That worker must not require the upstream producer to
change the `TransactionEventV1` payload.

