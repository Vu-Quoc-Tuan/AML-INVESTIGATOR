from datetime import datetime, timedelta
import pandas as pd
from typing import Any

# pyrefly: ignore [missing-import]
from app.data.provider import get_initialized_data_repository
from app.schemas.common import TransactionDirection, CounterpartySummary
from app.schemas.tools import GetAccountTransactionsOutput

def get_account_transactions(
    account_id: str,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    direction: TransactionDirection | str | None = None,
) -> GetAccountTransactionsOutput:
    repo = get_initialized_data_repository()
    
    # Ensure direction is string if provided
    dir_str = direction.value if isinstance(direction, TransactionDirection) else direction
    
    # Query repository
    frame = repo.transactions_for_account(
        account_id,
        start_time=start_time,
        end_time=end_time,
        direction=dir_str,
    )
    
    if frame.empty:
        return GetAccountTransactionsOutput(
            transactions=[],
            counterparty_summary=[],
            total_inbound_amount=0.0,
            total_outbound_amount=0.0,
            net_flow=0.0,
            count=0
        )

    # Sort by occurred_at
    frame = frame.sort_values(by="occurred_at")
    
    # Calculate summaries
    total_inbound = 0.0
    total_outbound = 0.0
    
    counterparties = {}
    transactions = []
    
    for _, row in frame.iterrows():
        amt = float(row["amount"])
        row_dir = str(row["direction"])
        
        # Resolve actual direction relative to the queried account
        if row_dir == "INTERNAL":
            # Determine if this account is source or destination
            is_source = str(row["source_account_ref"]) == account_id
            effective_dir = "OUTBOUND" if is_source else "INBOUND"
            cp_id = str(row["destination_account_ref"]) if is_source else str(row["source_account_ref"])
        else:
            effective_dir = row_dir
            cp_id = str(row["destination_account_ref"]) if effective_dir == "OUTBOUND" else str(row["source_account_ref"])

        if effective_dir == "INBOUND":
            total_inbound += amt
        else:
            total_outbound += amt
            
        cp_key = (cp_id, effective_dir)
        if cp_key not in counterparties:
            counterparties[cp_key] = {
                "account_id": cp_id,
                "total_amount": 0.0,
                "txn_count": 0,
                "direction": TransactionDirection(effective_dir)
            }
            
        counterparties[cp_key]["total_amount"] += amt
        counterparties[cp_key]["txn_count"] += 1
        
        # Create dict representation and convert timestamps to iso format
        txn_dict = row.to_dict()
        txn_dict["effective_direction"] = effective_dir
        for k, v in txn_dict.items():
            if isinstance(v, pd.Timestamp) or isinstance(v, datetime):
                txn_dict[k] = v.isoformat()
            elif pd.isna(v):
                txn_dict[k] = None
        transactions.append(txn_dict)
        
    summary_list = [
        CounterpartySummary(**data)
        for data in counterparties.values()
    ]
    
    return GetAccountTransactionsOutput(
        transactions=transactions,
        counterparty_summary=summary_list,
        total_inbound_amount=total_inbound,
        total_outbound_amount=total_outbound,
        net_flow=total_inbound - total_outbound,
        count=len(transactions)
    )

def get_transactions_around_alert(
    account_id: str,
    alert_time: str | datetime,
    window_before_hours: float = 24.0,
    window_after_hours: float = 12.0
) -> GetAccountTransactionsOutput:
    if isinstance(alert_time, str):
        alert_time = pd.to_datetime(alert_time, utc=True)
        
    start_time = alert_time - timedelta(hours=window_before_hours)
    end_time = alert_time + timedelta(hours=window_after_hours)
    
    return get_account_transactions(
        account_id=account_id,
        start_time=start_time,
        end_time=end_time
    )
