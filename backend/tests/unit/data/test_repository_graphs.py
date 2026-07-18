import networkx as nx

from app.data.repository import DataRepository


def test_transaction_subgraph_preserves_parallel_edges_and_is_mutable(generated_data_path):
    repository = DataRepository(generated_data_path).load()
    transactions = repository.transactions_for_account("ACCT-SHB-000001")
    counterpart = (
        transactions.iloc[0]["destination_account_ref"]
        if transactions.iloc[0]["source_account_ref"] == "ACCT-SHB-000001"
        else transactions.iloc[0]["source_account_ref"]
    )
    graph = repository.transaction_subgraph(["ACCT-SHB-000001", counterpart])

    assert isinstance(graph, nx.MultiDiGraph)
    assert not nx.is_frozen(graph)
    assert graph.number_of_edges() >= 1


def test_active_ownership_is_new_digraph_with_coverage_and_provenance(generated_data_path):
    repository = DataRepository(generated_data_path).load()
    graph = repository.build_active_ownership_graph("2025-12-31")

    assert isinstance(graph, nx.DiGraph)
    assert not graph.is_multigraph()
    company_nodes = [node for node, attrs in graph.nodes(data=True) if attrs["entity_type"] == "COMPANY"]
    assert company_nodes
    assert "ownership_status" in graph.nodes[company_nodes[0]]
    assert all("ownership_ids" in attrs for _, _, attrs in graph.edges(data=True))
