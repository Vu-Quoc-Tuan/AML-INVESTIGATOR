#!/usr/bin/env python3
"""Kafka Producer — streams training_data.csv into the 'transactions' topic.

Usage:
    python backend/scripts/kafka_producer.py [--tps 10] [--bootstrap localhost:9092]

Each CSV row is sent as a JSON message with key = transaction_id.
Throughput is throttled to ~TPS (default 10 transactions per second).
"""

import csv
import json
import sys
import time
import argparse
from pathlib import Path

from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable
# ── Paths ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
CSV_PATH = BACKEND_DIR / "model" / "training_data.csv"
TOPIC = "transactions"


def create_producer(bootstrap: str, retries: int = 10, delay: float = 3.0) -> KafkaProducer:
    """Create KafkaProducer with retry logic for broker availability."""
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=bootstrap,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                key_serializer=lambda k: str(k).encode("utf-8") if k else b"",
                acks="all",
                retries=3,
            )
            print(f"✅ Connected to Kafka broker at {bootstrap}")
            return producer
        except NoBrokersAvailable:
            if attempt < retries:
                print(f"⏳ Kafka broker not ready (attempt {attempt}/{retries}), retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"❌ Failed to connect to Kafka broker at {bootstrap} after {retries} attempts.")
                sys.exit(1)
    # Should never reach here
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Kafka producer for AML transaction streaming")
    parser.add_argument("--tps", type=int, default=30, help="Target transactions per second (default: 10)")
    parser.add_argument("--bootstrap", type=str, default="127.0.0.1:9092", help="Kafka bootstrap servers")
    parser.add_argument("--csv", type=str, default=str(BACKEND_DIR / "model" / "testing_data.csv"), help="Path to input CSV data file")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"❌ CSV not found: {csv_path}")
        sys.exit(1)

    producer = create_producer(args.bootstrap)
    interval = 1.0 / args.tps

    print(f"📂 Reading from: {csv_path}")
    print(f"📡 Topic: {TOPIC}")
    print(f"⚡ Target throughput: {args.tps} TPS")
    print("─" * 60)

    sent = 0
    start_time = time.time()

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                txn_id = row.get("transaction_id", f"unknown-{sent}")
                producer.send(TOPIC, key=txn_id, value=row)
                sent += 1

                if sent % 100 == 0:
                    elapsed = time.time() - start_time
                    actual_tps = sent / elapsed if elapsed > 0 else 0
                    print(f"  📤 Sent {sent:>6} messages | Actual TPS: {actual_tps:.1f}")

                time.sleep(interval)

        producer.flush()
        elapsed = time.time() - start_time
        actual_tps = sent / elapsed if elapsed > 0 else 0
        print("─" * 60)
        print(f"✅ Done! Sent {sent} messages in {elapsed:.1f}s (avg {actual_tps:.1f} TPS)")

    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print(f"\n⚠️  Interrupted. Sent {sent} messages in {elapsed:.1f}s")
        producer.flush()
    finally:
        producer.close()


if __name__ == "__main__":
    main()
