import json

import pytest

from app.data.exceptions import DataRepositoryNotInitializedError
from app.data.provider import initialize_data_repository
from app.services import EntityDataService, OwnershipDataService, ScreeningDataService, TransactionDataService


def test_services_require_startup_warmup():
    with pytest.raises(DataRepositoryNotInitializedError):
        EntityDataService().account("ACCT-SHB-000001")


def test_services_return_json_safe_results(generated_data_path):
    initialize_data_repository(generated_data_path)
    outputs = [
        EntityDataService().account("ACCT-SHB-000001"),
        TransactionDataService().transactions_for_account("ACCT-SHB-000001"),
        TransactionDataService().transaction_subgraph(["ACCT-SHB-000001"]),
        OwnershipDataService().active_ownership_graph("2025-12-31"),
        ScreeningDataService().candidates("Vu Phong My", "INDIVIDUAL"),
    ]

    for output in outputs:
        json.dumps(output, allow_nan=False)
