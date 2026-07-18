#!/usr/bin/env python3
"""Kafka Consumer — reads transactions, runs XGBoost inference, creates tickets.

Usage:
    python backend/scripts/kafka_consumer.py [--bootstrap localhost:9092]

For each message:
  1. Extract 38 feature columns from the JSON payload.
  2. Run XGBoost predict_proba → confidence (probability of class 1).
  3. Determine is_suspicious (confidence >= 0.60).
  4. Create a ticket if suspicious:
     - DANGEROUS  (confidence >= 0.95)
     - WARNING    (0.60 <= confidence < 0.95)
  5. Store the ticket in SQLite (via TicketRepository) and display on terminal.
"""

import json
import sys
import time
import signal
import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import xgboost as xgb
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

# ── Fix for running as a script with app imports ────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.ticket_repository import TicketRepository  # noqa: E402
from app.schemas.ticket import TicketCreate, TicketStatus  # noqa: E402

# ── Constants ───────────────────────────────────────────────────────────
MODEL_PATH = BACKEND_DIR / "model" / "xgb_model.json"
TOPIC = "transactions"
DB_PATH = BACKEND_DIR / "data" / "tickets.db"

# Feature columns used during training (must match training.py X_cols order)
FEATURE_COLUMNS = [
    "amount", "is_cross_border",
    "source_txn_count_1h", "source_txn_amount_1h",
    "source_txn_count_24h", "source_txn_amount_24h",
    "dest_txn_count_1h", "dest_txn_amount_1h",
    "dest_txn_count_24h", "dest_txn_amount_24h",
    "dest_pass_through_ratio_1h", "ip_sharing_count_1h", "device_sharing_count_1h",
    "source_owner_type", "source_owner_age", "source_owner_income", "source_owner_risk",
    "source_initial_balance", "source_account_age_days", "source_bank_risk_score",
    "source_doc_rejected_or_missing", "source_in_watchlist",
    "dest_owner_type", "dest_owner_age", "dest_owner_income", "dest_owner_risk",
    "dest_initial_balance", "dest_account_age_days", "dest_bank_risk_score",
    "dest_doc_rejected_or_missing", "dest_in_watchlist",
    "has_relationship",
    "mismatch_cross_border_source", "mismatch_cross_border_dest",
    "mismatch_country_source", "mismatch_country_dest",
    "amt_to_expected_outflow_ratio_source", "amt_to_expected_inflow_ratio_dest",
]

# ── Globals ─────────────────────────────────────────────────────────────
_running = True


def _signal_handler(sig, frame):
    global _running
    print("\n⚠️  Shutting down consumer gracefully...")
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ── Helpers ─────────────────────────────────────────────────────────────
def check_rule_based(row: dict) -> Optional[str]:
    """Check transaction against bank-like rule-based fraud detection policies.
    
    Returns the name/reason of the violated rule, or None if no rules are violated.
    """
    try:
        # Helper to convert to float safely
        def safe_float(val, default=0.0):
            if val is None or val == "":
                return default
            try:
                if isinstance(val, str):
                    val = val.strip().lower()
                    if val == "true": return 1.0
                    if val == "false": return 0.0
                return float(val)
            except ValueError:
                return default

        # Extract values
        amount = safe_float(row.get("amount"))
        is_cross_border = safe_float(row.get("is_cross_border"))
        ip_sharing_count = safe_float(row.get("ip_sharing_count_1h"))
        device_sharing_count = safe_float(row.get("device_sharing_count_1h"))
        source_owner_risk = safe_float(row.get("source_owner_risk"))
        dest_owner_risk = safe_float(row.get("dest_owner_risk"))
        source_acc_age = safe_float(row.get("source_account_age_days"))
        source_bank_risk = safe_float(row.get("source_bank_risk_score"))

        # RULE 1: PEP / High Risk Profile policy
        if source_owner_risk == 3.0 or dest_owner_risk == 3.0:
            return "HIGH_RISK_OWNER: Entity has a high risk profile (e.g. PEP or high risk sector)."

        # RULE 2: Velocity & Credential Abuse policy
        if ip_sharing_count > 5.0 or device_sharing_count > 3.0:
            return f"VELOCITY_ABUSE: High device/IP sharing (IP shared: {ip_sharing_count}, Device shared: {device_sharing_count}). Possible account takeover / botnet activity."

        # RULE 3: High Value Cross-Border Risk
        if is_cross_border == 1.0:
            if amount > 500_000_000 and source_bank_risk > 4.0:
                return f"CROSS_BORDER_HIGH_RISK_BANK: Cross-border transaction exceeding 500M VND originating from a high risk rating bank (Risk score: {source_bank_risk})."

        # RULE 4: New Account Anomaly
        if source_acc_age > 0 and source_acc_age < 30.0 and amount > 200_000_000:
            return f"NEW_ACCOUNT_LIMIT_EXCEEDED: Newly opened account (Age: {source_acc_age} days) attempting high-value transaction of {amount:,.0f} VND (Threshold: 200M VND)."

    except Exception as e:
        print(f"Error in rule check: {e}")
        
    return None


def load_model() -> xgb.XGBClassifier:
    """Load the pre-trained XGBoost model."""
    if not MODEL_PATH.exists():
        print(f"❌ Model not found: {MODEL_PATH}")
        sys.exit(1)
    model = xgb.XGBClassifier()
    model.load_model(str(MODEL_PATH))
    print(f"✅ Loaded XGBoost model from {MODEL_PATH}")
    return model


def create_consumer(bootstrap: str, retries: int = 10, delay: float = 3.0) -> KafkaConsumer:
    """Create a KafkaConsumer with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            consumer = KafkaConsumer(
                TOPIC,
                bootstrap_servers=bootstrap,
                group_id="aml-inference-group",
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")) if m is not None else None,
                consumer_timeout_ms=2000,  # poll timeout for graceful shutdown checks
            )
            print(f"✅ Connected to Kafka broker at {bootstrap}, subscribed to '{TOPIC}'")
            return consumer
        except NoBrokersAvailable:
            if attempt < retries:
                print(f"⏳ Kafka broker not ready (attempt {attempt}/{retries}), retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"❌ Failed to connect after {retries} attempts.")
                sys.exit(1)
    sys.exit(1)


def extract_features(row: dict) -> np.ndarray:
    """Extract the 38 feature values from a message dict, returning a 1-D numpy array."""
    values = []
    for col in FEATURE_COLUMNS:
        raw = row.get(col, 0)
        # Handle booleans encoded as strings
        if isinstance(raw, str):
            low = raw.strip().lower()
            if low in ("true", "1"):
                raw = 1.0
            elif low in ("false", "0"):
                raw = 0.0
            else:
                try:
                    raw = float(raw)
                except ValueError:
                    raw = 0.0
        values.append(float(raw))
    return np.array(values, dtype=np.float64)


def print_ticket(ticket_id: str, txn_id: str, status: TicketStatus, confidence: float, amount: str, rule_reason: Optional[str] = None):
    """Pretty-print a ticket to the terminal."""
    if status == TicketStatus.DANGEROUS:
        icon = "🔴"
        color_start = "\033[91m"  # Red
    else:
        icon = "🟡"
        color_start = "\033[93m"  # Yellow
    color_end = "\033[0m"

    print(f"\n{color_start}{'═' * 65}")
    print(f"  {icon}  TICKET: {ticket_id}  |  Status: {status.value}")
    print(f"{'─' * 65}")
    print(f"  Transaction ID : {txn_id}")
    print(f"  Amount         : {amount}")
    if rule_reason:
        print(f"  Detection      : RULE-BASED")
        print(f"  Rule Reason    : {rule_reason}")
    else:
        print(f"  Detection      : ML MODEL")
        print(f"  Confidence     : {confidence * 100:.2f}%")
    print(f"  Is Suspicious  : True")
    if status == TicketStatus.DANGEROUS:
        print(f"  ⚠️  NGUY HIỂM — Cần xử lý ngay lập tức!")
    else:
        print(f"  ⏳ CẢNH BÁO — Cần cho thời gian multi-agent suy nghĩ")
    print(f"{'═' * 65}{color_end}\n")


# ── Main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Kafka consumer with XGBoost ML inference")
    parser.add_argument("--bootstrap", type=str, default="127.0.0.1:9092", help="Kafka bootstrap servers")
    args = parser.parse_args()

    model = load_model()
    consumer = create_consumer(args.bootstrap)
    repo = TicketRepository(db_path=DB_PATH)

    print(f"💾 Tickets DB: {DB_PATH}")
    print(f"🔄 Listening for messages on topic '{TOPIC}'...")
    print("─" * 65)

    processed = 0
    tickets_created = 0
    start_time = time.time()

    try:
        while _running:
            # KafkaConsumer with consumer_timeout_ms will raise StopIteration
            # after the timeout, allowing us to check _running flag
            try:
                for message in consumer:
                    if not _running:
                        break

                    row = message.value
                    if row is None:
                        continue  # skip tombstone / null messages
                    txn_id = row.get("transaction_id", "UNKNOWN")
                    processed += 1

                    # ── Rule-Based Detection ──
                    rule_violation = check_rule_based(row)
                    
                    if rule_violation:
                        confidence = 1.0
                        is_suspicious = True
                        detection_method = "RULE_BASED"
                    else:
                        # ── ML Inference ──
                        features = extract_features(row)
                        proba = model.predict_proba(features.reshape(1, -1))[0]
                        confidence = float(proba[1])  # P(class=1 = suspicious)
                        is_suspicious = confidence >= 0.60
                        detection_method = "ML_MODEL"

                    # ── Build enriched data (original + new fields) ──
                    enriched = dict(row)
                    # Remove original ground-truth label; replace with inference results
                    enriched.pop("is_suspicious", None)
                    enriched["confidence"] = round(confidence, 6)
                    enriched["is_suspicious"] = is_suspicious
                    enriched["detection_method"] = detection_method
                    if rule_violation:
                        enriched["rule_violation_reason"] = rule_violation

                    # ── Ticket creation ──
                    if is_suspicious:
                        status = TicketStatus.DANGEROUS if (rule_violation or confidence >= 0.95) else TicketStatus.WARNING

                        ticket_data = TicketCreate(
                            transaction_id=txn_id,
                            confidence=round(confidence, 6),
                            is_suspicious=True,
                            status=status,
                            transaction_data=enriched,
                        )
                        ticket = repo.create_ticket(ticket_data)
                        tickets_created += 1

                        # Terminal display
                        print_ticket(
                            ticket.ticket_id,
                            txn_id,
                            status,
                            confidence,
                            str(row.get("amount", "N/A")),
                            rule_reason=rule_violation,
                        )
                    else:
                        # Legitimate — brief log every 50 messages
                        if processed % 50 == 0:
                            elapsed = time.time() - start_time
                            tps = processed / elapsed if elapsed > 0 else 0
                            print(
                                f"  ✅ Processed {processed:>6} | "
                                f"Tickets: {tickets_created} | "
                                f"TPS: {tps:.1f} | "
                                f"Last: {txn_id} (conf={confidence:.4f})"
                            )

            except StopIteration:
                # consumer_timeout_ms expired, loop back to check _running
                continue

    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.time() - start_time
        consumer.close()
        print("─" * 65)
        print(f"📊 Summary: processed {processed} messages in {elapsed:.1f}s")
        print(f"   Tickets created: {tickets_created} (DB: {DB_PATH})")
        print("👋 Consumer shut down.")


if __name__ == "__main__":
    main()
