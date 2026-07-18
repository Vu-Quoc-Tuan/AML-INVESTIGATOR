from app.data.repository import DataRepository


def test_kyc_typed_queries_and_bounded_ownership(generated_data_path):
    repository = DataRepository(generated_data_path).load()
    accounts = repository.accounts_for_entity("COMP-000008")
    document = repository.kyc_document_by_id("DOC-002098")
    graph = repository.build_ownership_neighborhood("COMP-000005", "2025-12-20", 2)

    assert set(accounts["owner_entity_id"]) == {"COMP-000008"}
    assert document["document_type"] == "UBO_DECLARATION"
    assert graph.graph["root_company_id"] == "COMP-000005"
    assert graph.has_edge("COMP-000005", "COMP-000037")
