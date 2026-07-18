import pandas as pd

from app.data.repository import DataRepository


def test_typed_queries_return_defensive_copies(generated_data_path):
    repository = DataRepository(generated_data_path).load()
    first = repository.account_by_id("ACCT-SHB-000001")
    assert first is not None
    first["status"] = "MUTATED"

    assert repository.account_by_id("ACCT-SHB-000001")["status"] != "MUTATED"

    profile = repository.kyc_profile_by_entity("CUST-000001")
    assert profile is not None
    profile["expected_countries"].append("MUTATED")
    assert "MUTATED" not in repository.kyc_profile_by_entity("CUST-000001")["expected_countries"]


def test_transaction_filters_validate_direction_and_time(generated_data_path):
    repository = DataRepository(generated_data_path).load()
    result = repository.transactions_for_account("ACCT-SHB-000001")
    assert not result.empty
    assert ((result["source_account_ref"] == "ACCT-SHB-000001") | (result["destination_account_ref"] == "ACCT-SHB-000001")).all()


def test_watchlist_candidates_are_normalized_and_filtered(generated_data_path):
    repository = DataRepository(generated_data_path).load()
    candidate = pd.read_json(generated_data_path / "watchlist_entries.jsonl", lines=True).iloc[0]
    result = repository.watchlist_candidates(
        normalized_name=str(candidate["full_name"]).lower(),
        entity_type="INDIVIDUAL",
        list_types=[str(candidate["list_type"])],
    )

    assert candidate["watchlist_id"] in set(result["watchlist_id"])


def test_repository_has_no_generic_or_full_watchlist_api(generated_data_path):
    repository = DataRepository(generated_data_path).load()
    for name in ("get_dataframe", "get_graph", "watchlist_entries", "get_transaction_graph"):
        assert not hasattr(repository, name)
