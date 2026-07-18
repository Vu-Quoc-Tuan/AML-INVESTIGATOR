"""Concurrency checks for the Transaction/KYC LangGraph fan-out and fan-in."""

from __future__ import annotations

from threading import Barrier, Lock, get_ident

from app.investigation_orchestrator.state import initial_state
from app.investigation_orchestrator.workflow import build_workflow
from app.legal_rag.hybrid_retriever import StaticLegalRetriever
from tests.node_fixtures import deterministic_agent_nodes


def test_transaction_and_kyc_execute_concurrently_before_merge() -> None:
    """Both workers must rendezvous concurrently before either can complete."""

    nodes = deterministic_agent_nodes()
    rendezvous = Barrier(2, timeout=5)
    lock = Lock()
    worker_threads: dict[str, int] = {}

    def concurrent_worker(name, delegate):
        def worker(state):
            with lock:
                worker_threads[name] = get_ident()
            rendezvous.wait()
            return delegate(state)

        return worker

    nodes["transaction_agent"] = concurrent_worker(
        "transaction", nodes["transaction_agent"]
    )
    nodes["kyc_agent"] = concurrent_worker("kyc", nodes["kyc_agent"])

    graph = build_workflow(
        agent_nodes=nodes, legal_retriever=StaticLegalRetriever()
    )
    config = {"configurable": {"thread_id": "parallel-rendezvous"}}
    result = graph.invoke(
        initial_state(
            "CASE-PARALLEL",
            {
                "subject_bank_id": "BANK-SHB-001",
                "data_visibility": "FULL_INTERNAL",
            },
        ),
        config,
    )

    assert "__interrupt__" not in result
    assert result["phase"] == "complete"
    assert set(worker_threads) == {"transaction", "kyc"}
    assert len(set(worker_threads.values())) == 2

    assert set(result["agent_outputs"]) >= {"transaction", "kyc", "screening", "legal"}
    assert {
        evidence["evidence_id"] for evidence in result["case_file"]["evidence"]
    } >= {
        "CASE-PARALLEL:transaction:1",
        "CASE-PARALLEL:kyc:1",
    }
    assert result["evidence_validation"]["status"] in {"PASSED", "PARTIAL"}
    assert "case_status" not in result
