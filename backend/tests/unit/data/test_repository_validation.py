import json
from pathlib import Path

import pandas as pd
import pytest

from app.data.exceptions import DataIntegrityError, DataSchemaError
from app.data.config import RepositoryConfig
from app.data.repository import DataRepository


def _rewrite_csv(path: Path, mutate) -> None:
    frame = pd.read_csv(path)
    mutate(frame)
    frame.to_csv(path, index=False)


def test_repository_ignores_ground_truth(copied_data: Path):
    (copied_data / "ground_truth_scenarios.json").write_text("not valid json", encoding="utf-8")
    assert DataRepository(copied_data).load().is_loaded


def test_missing_required_column_fails_before_publish(copied_data: Path):
    _rewrite_csv(copied_data / "transactions.csv", lambda frame: frame.drop(columns=["direction"], inplace=True))
    repository = DataRepository(copied_data)

    with pytest.raises(DataSchemaError, match="direction"):
        repository.load()

    assert not repository.is_loaded


def test_invalid_transaction_direction_is_rejected(copied_data: Path):
    _rewrite_csv(copied_data / "transactions.csv", lambda frame: frame.__setitem__("direction", ["OUTBOUND", *frame["direction"].iloc[1:]]))
    with pytest.raises(DataIntegrityError, match="topology/direction"):
        DataRepository(copied_data).load()


def test_partial_ownership_coverage_is_valid(copied_data: Path):
    def mutate(frame: pd.DataFrame) -> None:
        frame.loc[0, "ownership_percentage"] = 80.0

    _rewrite_csv(copied_data / "company_ownership.csv", mutate)
    repository = DataRepository(copied_data).load()
    company_id = pd.read_csv(copied_data / "company_ownership.csv").loc[0, "owned_company_id"]
    graph = repository.build_active_ownership_graph("2025-12-31")

    assert graph.nodes[company_id]["ownership_coverage_percentage"] == 80.0
    assert graph.nodes[company_id]["ownership_status"] == "INCOMPLETE"


def test_ownership_over_100_is_rejected(copied_data: Path):
    _rewrite_csv(
        copied_data / "company_ownership.csv",
        lambda frame: frame.__setitem__("ownership_percentage", [101.0, *frame["ownership_percentage"].iloc[1:]]),
    )
    with pytest.raises(DataIntegrityError, match="percentage outside"):
        DataRepository(copied_data).load()


def test_explicit_complete_company_requires_full_coverage(copied_data: Path):
    ownership = pd.read_csv(copied_data / "company_ownership.csv")
    company_id = ownership.loc[0, "owned_company_id"]
    ownership.loc[0, "ownership_percentage"] = 80.0
    ownership.to_csv(copied_data / "company_ownership.csv", index=False)
    companies = pd.read_csv(copied_data / "companies.csv")
    companies["ownership_data_complete"] = False
    companies.loc[companies["company_id"] == company_id, "ownership_data_complete"] = True
    companies.to_csv(copied_data / "companies.csv", index=False)

    with pytest.raises(DataIntegrityError, match="complete data"):
        DataRepository(copied_data).load()


def test_company_cycle_is_retained_in_graph_metadata(copied_data: Path):
    ownership = pd.read_csv(copied_data / "company_ownership.csv")
    first_company = ownership.loc[0, "owned_company_id"]
    second_company = ownership.loc[1, "owned_company_id"]
    ownership.loc[0, ["owner_entity_id", "owner_entity_type", "ownership_percentage"]] = [second_company, "COMPANY", 40.0]
    ownership.loc[1, ["owner_entity_id", "owner_entity_type", "ownership_percentage"]] = [first_company, "COMPANY", 40.0]
    ownership.to_csv(copied_data / "company_ownership.csv", index=False)

    repository = DataRepository(copied_data).load()
    graph = repository.ownership_subgraph([first_company, second_company])
    active_graph = repository.build_active_ownership_graph("2025-12-31")

    assert graph.has_edge(first_company, second_company)
    assert graph.has_edge(second_company, first_company)
    assert graph.graph["ownership_cycle_detected"] is True
    assert active_graph.graph["ownership_cycle_detected"] is True


def test_direct_100_percent_self_ownership_is_rejected(copied_data: Path):
    def mutate(frame: pd.DataFrame) -> None:
        frame.loc[0, "owner_entity_type"] = "COMPANY"
        frame.loc[0, "owner_entity_id"] = frame.loc[0, "owned_company_id"]
        frame.loc[0, "ownership_percentage"] = 100.0

    _rewrite_csv(copied_data / "company_ownership.csv", mutate)
    with pytest.raises(DataIntegrityError, match="self-ownership"):
        DataRepository(copied_data).load()


def test_verified_ownership_accepts_configured_document_type(copied_data: Path):
    documents_path = copied_data / "kyc_documents.jsonl"
    documents = [json.loads(line) for line in documents_path.read_text(encoding="utf-8").splitlines()]
    ownership = pd.read_csv(copied_data / "company_ownership.csv")
    evidence_id = ownership.loc[0, "source_document_id"]
    next(item for item in documents if item["document_id"] == evidence_id)["document_type"] = "SHAREHOLDER_REGISTER"
    documents_path.write_text("\n".join(json.dumps(item) for item in documents) + "\n", encoding="utf-8")

    assert DataRepository(copied_data).load().is_loaded


def test_ownership_document_types_can_be_overridden(copied_data: Path):
    documents_path = copied_data / "kyc_documents.jsonl"
    documents = [json.loads(line) for line in documents_path.read_text(encoding="utf-8").splitlines()]
    ownership = pd.read_csv(copied_data / "company_ownership.csv")
    evidence_id = ownership.loc[0, "source_document_id"]
    next(item for item in documents if item["document_id"] == evidence_id)["document_type"] = "CUSTOM_PROOF"
    documents_path.write_text("\n".join(json.dumps(item) for item in documents) + "\n", encoding="utf-8")

    with pytest.raises(DataIntegrityError, match="unsupported ownership evidence"):
        DataRepository(copied_data).load()

    config = RepositoryConfig(allowed_ownership_document_types=frozenset({"CUSTOM_PROOF", "UBO_DECLARATION"}))
    assert DataRepository(copied_data, config=config).load().is_loaded
