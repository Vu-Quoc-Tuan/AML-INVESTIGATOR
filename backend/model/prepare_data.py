import os
import json
import pandas as pd
import numpy as np
from collections import defaultdict, deque

def make_naive(val):
    if pd.isna(val):
        return val
    dt = pd.to_datetime(val)
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.tz_localize(None)
    return dt

def main():
    # Define directories
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "../data/generated"))
    OUTPUT_PATH = os.path.join(CURRENT_DIR, "training_data.csv")

    print(f"Data directory: {DATA_DIR}")
    print(f"Output path: {OUTPUT_PATH}")

    print("Loading datasets...")
    # Load CSVs
    tx_df = pd.read_csv(os.path.join(DATA_DIR, "transactions.csv"))
    ac_df = pd.read_csv(os.path.join(DATA_DIR, "accounts.csv"))
    cust_df = pd.read_csv(os.path.join(DATA_DIR, "customers.csv"))
    comp_df = pd.read_csv(os.path.join(DATA_DIR, "companies.csv"))
    bank_df = pd.read_csv(os.path.join(DATA_DIR, "banks.csv"))
    addr_df = pd.read_csv(os.path.join(DATA_DIR, "addresses.csv"))
    own_df = pd.read_csv(os.path.join(DATA_DIR, "company_ownership.csv"))
    rel_df = pd.read_csv(os.path.join(DATA_DIR, "entity_relationships.csv"))
    ext_df = pd.read_csv(os.path.join(DATA_DIR, "external_accounts.csv"))

    # Load JSON/JSONL
    def load_jsonl(path):
        if not os.path.exists(path):
            return pd.DataFrame()
        with open(path, "r", encoding="utf-8") as f:
            return pd.DataFrame([json.loads(line) for line in f])

    kyc_prof_df = load_jsonl(os.path.join(DATA_DIR, "kyc_profiles.jsonl"))
    kyc_doc_df = load_jsonl(os.path.join(DATA_DIR, "kyc_documents.jsonl"))
    wl_df = load_jsonl(os.path.join(DATA_DIR, "watchlist_entries.jsonl"))

    with open(os.path.join(DATA_DIR, "ground_truth_scenarios.json"), "r", encoding="utf-8") as f:
        gt_scenarios = json.load(f)

    # 1. Label the target variable (is_suspicious)
    print("Labeling target variable...")
    suspicious_txns = set()
    for scenario in gt_scenarios:
        # Check if the scenario is suspicious or disposition is escalate
        is_susp = (
            scenario.get("scenario_type") == "SUSPICIOUS" or
            scenario.get("expected_case_disposition") == "ESCALATE_FOR_SAR_REVIEW"
        )
        if is_susp:
            for txn_id in scenario.get("suspicious_transaction_ids", []):
                suspicious_txns.add(txn_id)

    tx_df["is_suspicious"] = tx_df["transaction_id"].apply(lambda x: 1 if x in suspicious_txns else 0)
    print(f"Total transactions: {len(tx_df)}, Suspicious: {tx_df['is_suspicious'].sum()}")

    # 2. Build quick lookup maps for Banks
    bank_risk_map = bank_df.set_index("bank_id")["risk_score"].to_dict()
    bank_country_map = bank_df.set_index("bank_id")["country_code"].to_dict()

    # 3. Build lookup maps for Entities (Customers & Companies)
    # Risk Level Mapper
    risk_mapper = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

    print("Building entity lookup maps...")
    entity_info = {}
    
    # Process customers
    for _, r in cust_df.iterrows():
        entity_info[r["customer_id"]] = {
            "type": 0, # CUSTOMER
            "name": r["full_name"],
            "dob": make_naive(r["date_of_birth"]),
            "nationality": r["nationality"],
            "income": float(r["annual_income"]),
            "risk_level": risk_mapper.get(r["customer_risk_level"], 0),
            "address_id": r["address_id"],
            "created_at": make_naive(r["created_at"])
        }

    # Process companies
    for _, r in comp_df.iterrows():
        entity_info[r["company_id"]] = {
            "type": 1, # COMPANY
            "name": r["legal_name"],
            "dob": make_naive(r["incorporation_date"]), # Use incorporation date as dob for age calc
            "nationality": "VN", # Companies are VN registered here
            "income": float(r["expected_monthly_turnover"]),
            "risk_level": risk_mapper.get(r["kyc_risk_level"], 0),
            "address_id": r["registered_address_id"],
            "created_at": make_naive(r["incorporation_date"])
        }

    # Process external accounts
    for _, r in ext_df.iterrows():
        ext_id = r["external_account_id"]
        c_type = 0 if r["counterparty_type"] == "INDIVIDUAL" else 1
        r_score = float(r.get("risk_score", 0.0))
        r_level = 2 if r_score > 0.5 else (1 if r_score > 0.15 else 0)
        entity_info[ext_id] = {
            "type": c_type,
            "name": r["counterparty_name"],
            "dob": pd.NaT,
            "nationality": r["country_code"],
            "income": 0.0,
            "risk_level": r_level,
            "address_id": None,
            "created_at": make_naive(r["first_seen_at"])
        }

    # 4. Build KYC Profile lookup map
    kyc_profile_map = {}
    if not kyc_prof_df.empty:
        for _, r in kyc_prof_df.iterrows():
            kyc_profile_map[r["entity_id"]] = {
                "expected_monthly_inflow": float(r.get("expected_monthly_inflow", 0)),
                "expected_monthly_outflow": float(r.get("expected_monthly_outflow", 0)),
                "expected_transaction_count": int(r.get("expected_transaction_count", 0)),
                "expected_cross_border": bool(r.get("expected_cross_border", False)),
                "expected_countries": set(r.get("expected_countries", []))
            }

    # 5. Build KYC Document rejection status
    kyc_doc_status_map = defaultdict(int) # entity_id -> 1 if has expired/rejected/missing, else 0
    if not kyc_doc_df.empty:
        for _, r in kyc_doc_df.iterrows():
            status = r.get("verification_status")
            if status in ["REJECTED", "EXPIRED", "MISSING"]:
                kyc_doc_status_map[r["entity_id"]] = 1

    # 6. Build Watchlist maps
    wl_names = set(wl_df["full_name"].str.strip().str.lower().dropna().unique())
    for aliases in wl_df["aliases"].dropna():
        for alias in aliases:
            wl_names.add(alias.strip().lower())
    wl_related_entity_ids = set(wl_df["related_entity_id"].dropna().unique())

    def check_watchlist(entity_id, name):
        if pd.isna(entity_id):
            return 0
        if entity_id in wl_related_entity_ids:
            return 1
        if not pd.isna(name):
            name_clean = str(name).strip().lower()
            if name_clean in wl_names:
                return 1
        return 0

    # 7. Build Relationships Map
    relationships = set()
    for _, r in rel_df.iterrows():
        relationships.add((r["source_entity_id"], r["target_entity_id"]))
        relationships.add((r["target_entity_id"], r["source_entity_id"]))
    for _, r in own_df.iterrows():
        relationships.add((r["owner_entity_id"], r["owned_company_id"]))
        relationships.add((r["owned_company_id"], r["owner_entity_id"]))

    def has_relation(s_owner, d_owner):
        if pd.isna(s_owner) or pd.isna(d_owner):
            return 0
        return 1 if (s_owner, d_owner) in relationships else 0

    # 8. Build Account Map
    account_map = {}
    for _, r in ac_df.iterrows():
        account_map[r["account_id"]] = {
            "owner_id": r["owner_entity_id"],
            "owner_type": r["owner_entity_type"],
            "account_type": r["account_type"],
            "opened_at": make_naive(r["opened_at"]),
            "status": r["status"],
            "initial_balance": float(r["initial_balance"])
        }
    for _, r in ext_df.iterrows():
        ext_id = r["external_account_id"]
        account_map[ext_id] = {
            "owner_id": ext_id,
            "owner_type": "CUSTOMER" if r["counterparty_type"] == "INDIVIDUAL" else "COMPANY",
            "account_type": "EXTERNAL",
            "opened_at": make_naive(r["first_seen_at"]),
            "status": "ACTIVE",
            "initial_balance": 0.0
        }

    # 9. Compute Dynamic Velocity / Rolling Features
    print("Computing dynamic rolling window features...")
    # Sort transactions chronologically
    tx_df["occurred_at"] = tx_df["occurred_at"].apply(make_naive)
    tx_df = tx_df.sort_values("occurred_at").reset_index(drop=True)

    epochs = tx_df["occurred_at"].astype("int64") // 10**9
    source_ids = tx_df["source_account_ref"].values
    dest_ids = tx_df["destination_account_ref"].values
    amounts = tx_df["amount"].values
    source_ips = tx_df["source_ip"].values
    device_ids = tx_df["device_id"].values

    n = len(tx_df)

    source_count_1h = np.zeros(n, dtype=int)
    source_sum_1h = np.zeros(n, dtype=float)
    source_count_24h = np.zeros(n, dtype=int)
    source_sum_24h = np.zeros(n, dtype=float)

    dest_count_1h = np.zeros(n, dtype=int)
    dest_sum_1h = np.zeros(n, dtype=float)
    dest_count_24h = np.zeros(n, dtype=int)
    dest_sum_24h = np.zeros(n, dtype=float)

    dest_pass_through_ratio_1h = np.zeros(n, dtype=float)
    ip_sharing_count_1h = np.zeros(n, dtype=int)
    device_sharing_count_1h = np.zeros(n, dtype=int)

    # Histories
    source_history = defaultdict(deque)
    dest_history = defaultdict(deque)
    acc_outgoing_history = defaultdict(deque)
    acc_incoming_history = defaultdict(deque)
    ip_history = defaultdict(deque)
    dev_history = defaultdict(deque)

    for i in range(n):
        t = epochs[i]
        s_id = source_ids[i]
        d_id = dest_ids[i]
        amt = amounts[i]
        ip = source_ips[i]
        dev = device_ids[i]

        # Source rolling
        s_hist = source_history[s_id]
        while s_hist and s_hist[0][0] <= t - 86400:
            s_hist.popleft()
        c_1h, s_1h = 0, 0.0
        c_24h, s_24h = 0, 0.0
        for ts, a in s_hist:
            if ts > t - 3600:
                c_1h += 1
                s_1h += a
            c_24h += 1
            s_24h += a
        source_count_1h[i] = c_1h
        source_sum_1h[i] = s_1h
        source_count_24h[i] = c_24h
        source_sum_24h[i] = s_24h

        # Dest rolling
        d_hist = dest_history[d_id]
        while d_hist and d_hist[0][0] <= t - 86400:
            d_hist.popleft()
        c_1h, s_1h = 0, 0.0
        c_24h, s_24h = 0, 0.0
        for ts, a in d_hist:
            if ts > t - 3600:
                c_1h += 1
                s_1h += a
            c_24h += 1
            s_24h += a
        dest_count_1h[i] = c_1h
        dest_sum_1h[i] = s_1h
        dest_count_24h[i] = c_24h
        dest_sum_24h[i] = s_24h

        # Dest pass through ratio
        out_hist = acc_outgoing_history[d_id]
        in_hist = acc_incoming_history[d_id]
        while out_hist and out_hist[0][0] <= t - 3600:
            out_hist.popleft()
        while in_hist and in_hist[0][0] <= t - 3600:
            in_hist.popleft()
        sum_out = sum(a for _, a in out_hist)
        sum_in = sum(a for _, a in in_hist)
        dest_pass_through_ratio_1h[i] = sum_out / (sum_in + 1.0)

        # IP sharing
        if not pd.isna(ip) and ip != "":
            ip_hist = ip_history[ip]
            while ip_hist and ip_hist[0][0] <= t - 3600:
                ip_hist.popleft()
            ip_sharing_count_1h[i] = len({acc for _, acc in ip_hist})
            ip_history[ip].append((t, s_id))
        else:
            ip_sharing_count_1h[i] = 0

        # Device sharing
        if not pd.isna(dev) and dev != "":
            dev_hist = dev_history[dev]
            while dev_hist and dev_hist[0][0] <= t - 3600:
                dev_hist.popleft()
            device_sharing_count_1h[i] = len({acc for _, acc in dev_hist})
            dev_history[dev].append((t, s_id))
        else:
            device_sharing_count_1h[i] = 0

        # Record histories for future steps
        source_history[s_id].append((t, amt))
        dest_history[d_id].append((t, amt))
        acc_outgoing_history[s_id].append((t, amt))
        acc_incoming_history[d_id].append((t, amt))

    # Add dynamic features to DataFrame
    tx_df["source_txn_count_1h"] = source_count_1h
    tx_df["source_txn_amount_1h"] = source_sum_1h
    tx_df["source_txn_count_24h"] = source_count_24h
    tx_df["source_txn_amount_24h"] = source_sum_24h
    tx_df["dest_txn_count_1h"] = dest_count_1h
    tx_df["dest_txn_amount_1h"] = dest_sum_1h
    tx_df["dest_txn_count_24h"] = dest_count_24h
    tx_df["dest_txn_amount_24h"] = dest_sum_24h
    tx_df["dest_pass_through_ratio_1h"] = dest_pass_through_ratio_1h
    tx_df["ip_sharing_count_1h"] = ip_sharing_count_1h
    tx_df["device_sharing_count_1h"] = device_sharing_count_1h

    # 10. Compute Mismatches, KYC, and entity fields
    print("Joining static metadata and computing compliance features...")
    # Pre-allocate feature columns
    source_owner_type = []
    source_owner_age = []
    source_owner_income = []
    source_owner_risk = []
    source_initial_balance = []
    source_account_age_days = []
    source_bank_risk_score = []
    source_doc_rejected_or_missing = []
    source_in_watchlist = []

    dest_owner_type = []
    dest_owner_age = []
    dest_owner_income = []
    dest_owner_risk = []
    dest_initial_balance = []
    dest_account_age_days = []
    dest_bank_risk_score = []
    dest_doc_rejected_or_missing = []
    dest_in_watchlist = []

    has_relationship_list = []
    mismatch_cross_border_source = []
    mismatch_cross_border_dest = []
    mismatch_country_source = []
    mismatch_country_dest = []
    amt_to_expected_outflow_ratio_source = []
    amt_to_expected_inflow_ratio_dest = []

    for idx, row in tx_df.iterrows():
        t_time = row["occurred_at"]
        s_acc = row["source_account_ref"]
        d_acc = row["destination_account_ref"]
        s_bank = row["source_bank_id"]
        d_bank = row["destination_bank_id"]
        amount = float(row["amount"])
        is_cb = bool(row["is_cross_border"])
        dest_country = row["destination_country"]

        # Get Bank Risk Scores
        s_bank_risk = bank_risk_map.get(s_bank, 0.0)
        d_bank_risk = bank_risk_map.get(d_bank, 0.0)
        s_bank_country = bank_country_map.get(s_bank, "VN")
        d_bank_country = bank_country_map.get(d_bank, "VN")

        # Get Accounts
        s_acc_info = account_map.get(s_acc, {})
        d_acc_info = account_map.get(d_acc, {})

        s_owner = s_acc_info.get("owner_id")
        d_owner = d_acc_info.get("owner_id")

        # Source Entity Features
        s_ent = entity_info.get(s_owner, {})
        s_age = (t_time - s_ent["dob"]).days / 365.25 if "dob" in s_ent else 0
        source_owner_type.append(s_ent.get("type", 0))
        source_owner_age.append(s_age)
        source_owner_income.append(s_ent.get("income", 0))
        source_owner_risk.append(s_ent.get("risk_level", 0))
        source_initial_balance.append(s_acc_info.get("initial_balance", 0))
        source_account_age_days.append((t_time - s_acc_info["opened_at"]).days if "opened_at" in s_acc_info else 0)
        source_bank_risk_score.append(s_bank_risk)
        source_doc_rejected_or_missing.append(kyc_doc_status_map[s_owner])
        source_in_watchlist.append(check_watchlist(s_owner, s_ent.get("name")))

        # Dest Entity Features
        d_ent = entity_info.get(d_owner, {})
        d_age = (t_time - d_ent["dob"]).days / 365.25 if "dob" in d_ent else 0
        dest_owner_type.append(d_ent.get("type", 0))
        dest_owner_age.append(d_age)
        dest_owner_income.append(d_ent.get("income", 0))
        dest_owner_risk.append(d_ent.get("risk_level", 0))
        dest_initial_balance.append(d_acc_info.get("initial_balance", 0))
        dest_account_age_days.append((t_time - d_acc_info["opened_at"]).days if "opened_at" in d_acc_info else 0)
        dest_bank_risk_score.append(d_bank_risk)
        dest_doc_rejected_or_missing.append(kyc_doc_status_map[d_owner])
        dest_in_watchlist.append(check_watchlist(d_owner, d_ent.get("name")))

        # Relationship
        has_relationship_list.append(has_relation(s_owner, d_owner))

        # Mismatches (KYC Profiles)
        s_kyc = kyc_profile_map.get(s_owner, {})
        d_kyc = kyc_profile_map.get(d_owner, {})

        # Cross border mismatches
        mismatch_cb_s = 1 if is_cb and not s_kyc.get("expected_cross_border", False) else 0
        mismatch_cb_d = 1 if is_cb and not d_kyc.get("expected_cross_border", False) else 0
        mismatch_cross_border_source.append(mismatch_cb_s)
        mismatch_cross_border_dest.append(mismatch_cb_d)

        # Country list mismatches
        mismatch_c_s = 1 if is_cb and dest_country not in s_kyc.get("expected_countries", set()) else 0
        mismatch_c_d = 1 if is_cb and s_bank_country not in d_kyc.get("expected_countries", set()) else 0
        mismatch_country_source.append(mismatch_c_s)
        mismatch_country_dest.append(mismatch_c_d)

        # Ratios
        outflow_expected = s_kyc.get("expected_monthly_outflow", 0.0)
        inflow_expected = d_kyc.get("expected_monthly_inflow", 0.0)
        amt_to_expected_outflow_ratio_source.append(amount / outflow_expected if outflow_expected > 0 else 0)
        amt_to_expected_inflow_ratio_dest.append(amount / inflow_expected if inflow_expected > 0 else 0)

    # Attach features to DataFrame
    tx_df["source_owner_type"] = source_owner_type
    tx_df["source_owner_age"] = source_owner_age
    tx_df["source_owner_income"] = source_owner_income
    tx_df["source_owner_risk"] = source_owner_risk
    tx_df["source_initial_balance"] = source_initial_balance
    tx_df["source_account_age_days"] = source_account_age_days
    tx_df["source_bank_risk_score"] = source_bank_risk_score
    tx_df["source_doc_rejected_or_missing"] = source_doc_rejected_or_missing
    tx_df["source_in_watchlist"] = source_in_watchlist

    tx_df["dest_owner_type"] = dest_owner_type
    tx_df["dest_owner_age"] = dest_owner_age
    tx_df["dest_owner_income"] = dest_owner_income
    tx_df["dest_owner_risk"] = dest_owner_risk
    tx_df["dest_initial_balance"] = dest_initial_balance
    tx_df["dest_account_age_days"] = dest_account_age_days
    tx_df["dest_bank_risk_score"] = dest_bank_risk_score
    tx_df["dest_doc_rejected_or_missing"] = dest_doc_rejected_or_missing
    tx_df["dest_in_watchlist"] = dest_in_watchlist

    tx_df["has_relationship"] = has_relationship_list
    tx_df["mismatch_cross_border_source"] = mismatch_cross_border_source
    tx_df["mismatch_cross_border_dest"] = mismatch_cross_border_dest
    tx_df["mismatch_country_source"] = mismatch_country_source
    tx_df["mismatch_country_dest"] = mismatch_country_dest
    tx_df["amt_to_expected_outflow_ratio_source"] = amt_to_expected_outflow_ratio_source
    tx_df["amt_to_expected_inflow_ratio_dest"] = amt_to_expected_inflow_ratio_dest

    # Save to CSV
    print(f"Saving merged data to {OUTPUT_PATH}...")
    # Drop raw IDs, timestamps, and unstructured columns to keep it clean for tabular ML training
    # But keep transaction_id for matching, is_suspicious as label
    columns_to_keep = [
        "transaction_id", "amount", "is_cross_border", "is_suspicious",
        "source_txn_count_1h", "source_txn_amount_1h", "source_txn_count_24h", "source_txn_amount_24h",
        "dest_txn_count_1h", "dest_txn_amount_1h", "dest_txn_count_24h", "dest_txn_amount_24h",
        "dest_pass_through_ratio_1h", "ip_sharing_count_1h", "device_sharing_count_1h",
        "source_owner_type", "source_owner_age", "source_owner_income", "source_owner_risk",
        "source_initial_balance", "source_account_age_days", "source_bank_risk_score",
        "source_doc_rejected_or_missing", "source_in_watchlist",
        "dest_owner_type", "dest_owner_age", "dest_owner_income", "dest_owner_risk",
        "dest_initial_balance", "dest_account_age_days", "dest_bank_risk_score",
        "dest_doc_rejected_or_missing", "dest_in_watchlist",
        "has_relationship", "mismatch_cross_border_source", "mismatch_cross_border_dest",
        "mismatch_country_source", "mismatch_country_dest",
        "amt_to_expected_outflow_ratio_source", "amt_to_expected_inflow_ratio_dest"
    ]
    
    tx_df[columns_to_keep].to_csv(OUTPUT_PATH, index=False)
    print("Data preparation complete!")

if __name__ == "__main__":
    main()
