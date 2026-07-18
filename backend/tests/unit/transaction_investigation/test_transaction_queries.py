import pytest
import pandas as pd
from datetime import datetime

from app.transaction_investigation.transaction_queries import get_account_transactions
from app.data.provider import initialize_data_repository, get_initialized_data_repository
from app.schemas.common import TransactionDirection

@pytest.fixture(scope="module", autouse=True)
def setup_repository():
    try:
        repo = get_initialized_data_repository()
    except Exception:
        repo = initialize_data_repository()
    yield repo

def test_get_account_transactions(setup_repository):
    # Setup repository should be provided by conftest
    account_id = "ACCT-SHB-002382" # Using SCN-001 target
    
    result = get_account_transactions(account_id)
    
    assert result.count > 0
    assert result.total_inbound_amount > 0
    assert result.total_outbound_amount > 0
    
    # Check that transactions are returned
    assert len(result.transactions) == result.count
    
    # Check that counterparty summary is built
    assert len(result.counterparty_summary) > 0
    
    for summary in result.counterparty_summary:
        assert summary.account_id is not None
        assert summary.total_amount > 0
        assert summary.txn_count > 0
        assert summary.direction in [TransactionDirection.INBOUND, TransactionDirection.OUTBOUND]
