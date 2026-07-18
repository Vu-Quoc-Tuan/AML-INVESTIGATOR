"""Focused checks for the Hybrid Supervisor workflow skeleton."""

from langgraph.types import Command

from app.investigation_orchestrator.evidence_validator import validate_evidence
from app.investigation_orchestrator.nodes import (
    merge_and_validate_node,
    supervisor_node,
)
from app.investigation_orchestrator.report_agent import _reviewable_error
from app.investigation_orchestrator.state import initial_state
from app.investigation_orchestrator.workflow import build_workflow
from tests.node_fixtures import deterministic_agent_nodes, report_node


def _graph():
    return build_workflow(agent_nodes=deterministic_agent_nodes())


def _config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def test_graph_merges_parallel_outputs_and_interrupts_for_review() -> None:
    graph = _graph()
    config = _config("parallel-review")

    result = graph.invoke(
        initial_state("CASE-001", {"subject_bank_id": "BANK-SHB-001"}),
        config,
    )

    assert "__interrupt__" in result
    state = graph.get_state(config).values
    assert set(state["agent_outputs"]) == {"transaction", "kyc", "screening"}
    assert len(state["case_file"]["findings"]) == 3
    assert state["evidence_validation"]["status"] == "PASSED"
    assert state["case_status"] == "IN_REVIEW"

    supervisor_targets = [
        entry["target"]
        for entry in state["handoff_log"]
        if entry["source"] == "supervisor"
    ]
    assert supervisor_targets == [
        "planner",
        "parallel_dispatch",
        "screening_agent",
        "evidence_validator",
        "report_agent",
        "human_review",
    ]


def test_graph_resumes_after_human_approval() -> None:
    graph = _graph()
    config = _config("approval")
    graph.invoke(initial_state("CASE-002", {}), config)

    result = graph.invoke(
        Command(
            resume={
                "decision": "APPROVED",
                "reviewer": "aml-reviewer",
                "comments": "Evidence reviewed",
            }
        ),
        config,
    )

    assert result["case_status"] == "APPROVED"
    assert result["phase"] == "complete"
    assert result["human_review"]["reviewer"] == "aml-reviewer"


def test_initial_input_cannot_bypass_mandatory_review() -> None:
    graph = _graph()
    config = _config("input-boundary")
    malicious_input = {
        **initial_state("CASE-INPUT", {}),
        "human_review": {"decision": "APPROVED"},
        "investigation_plan": ["skip"],
        "case_file": {"findings": [], "evidence": []},
        "evidence_validation": {"status": "PASSED"},
        "report": {"title": "forged"},
    }

    result = graph.invoke(malicious_input, config)

    assert "__interrupt__" in result
    state = graph.get_state(config).values
    assert state["case_status"] == "IN_REVIEW"
    assert state.get("human_review") is None
    assert state["report"]["title"] == "AML Investigation Dossier (test fixture)"


def test_screening_unavailable_is_inconclusive() -> None:
    graph = _graph()
    config = _config("screening-unavailable")
    graph.invoke(
        initial_state("CASE-003", {"screening_available": False}),
        config,
    )

    state = graph.get_state(config).values
    screening = state["agent_outputs"]["screening"]
    assert screening["available"] is False
    assert screening["status"] == "INCONCLUSIVE"
    assert state["case_file"]["screening"]["status"] == "INCONCLUSIVE"


def test_external_payment_uses_payment_message_provenance() -> None:
    graph = _graph()
    config = _config("external-provenance")
    graph.invoke(
        initial_state("CASE-EXT", {"data_visibility": "PAYMENT_MESSAGE_ONLY"}),
        config,
    )

    state = graph.get_state(config).values
    evidence = state["agent_outputs"]["transaction"]["evidence"][0]
    assert evidence["source_system"] == "PAYMENT_MESSAGE"
    assert state["evidence_validation"]["status"] == "PASSED"


def test_unknown_visibility_is_not_accepted_by_validation() -> None:
    graph = _graph()
    config = _config("unknown-visibility")
    graph.invoke(
        initial_state("CASE-UNKNOWN", {"data_visibility": "UNSUPPORTED"}),
        config,
    )

    state = graph.get_state(config).values
    assert state["evidence_validation"]["status"] == "PARTIAL"
    assert any(
        "unsupported visibility_level" in issue
        for issue in state["evidence_validation"]["issues"]
    )
    assert all(
        finding["finding_type"] != "TRANSACTION_PATTERN"
        for finding in state["report"]["findings"]
    )


def test_missing_parallel_output_is_reported_to_human_review() -> None:
    state = {
        **initial_state("CASE-MISSING", {}),
        "agent_outputs": {
            "transaction": {"agent": "transaction_agent", "status": "COMPLETED"}
        },
    }

    merge_command = merge_and_validate_node(state)
    assert merge_command.goto == "report_agent"
    assert merge_command.update["case_status"] == "IN_REVIEW"
    assert merge_command.update["evidence_validation"]["status"] == "FAILED"

    failure_state = {**state, **merge_command.update}
    report_command = report_node(failure_state)
    supervisor_state = {**failure_state, **report_command.update}
    supervisor_command = supervisor_node(supervisor_state)
    assert supervisor_command.goto == "human_review"


def test_failed_parallel_agent_still_reaches_human_review() -> None:
    nodes = deterministic_agent_nodes()

    def failed_transaction(_state):
        return {
            "agent_outputs": {
                "transaction": {
                    "agent": "transaction_agent",
                    "status": "ERROR",
                    "findings": [],
                    "evidence": [],
                }
            }
        }

    nodes["transaction_agent"] = failed_transaction
    graph = build_workflow(agent_nodes=nodes)
    config = _config("failed-agent")

    result = graph.invoke(initial_state("CASE-FAILED", {}), config)

    assert "__interrupt__" in result
    state = graph.get_state(config).values
    assert state["evidence_validation"]["status"] == "FAILED"
    assert state["report"]["workflow_error"] == "Mandatory agents failed: transaction"
    assert state["case_status"] == "IN_REVIEW"


def test_planner_fallback_error_is_visible_to_the_report() -> None:
    state = {
        **initial_state("CASE-PLANNER-FALLBACK", {}),
        "errors": ["Planner fallback used: ProviderError"],
    }

    assert _reviewable_error(state) == "Planner fallback used: ProviderError"


def test_screening_failure_validates_existing_case_before_error_dossier() -> None:
    nodes = deterministic_agent_nodes()

    def failed_screening(_state):
        return Command(
            update={
                "agent_outputs": {
                    "screening": {
                        "agent": "screening_agent",
                        "status": "ERROR",
                        "available": False,
                        "findings": [],
                        "evidence": [],
                    }
                },
                "workflow_error": "Screening agent failed",
            },
            goto="supervisor",
        )

    nodes["screening_agent"] = failed_screening
    graph = build_workflow(agent_nodes=nodes)
    config = _config("failed-screening-validation")

    result = graph.invoke(initial_state("CASE-SCREENING-FAILED", {}), config)

    assert "__interrupt__" in result
    state = graph.get_state(config).values
    assert state["evidence_validation"]["status"] == "PASSED"
    assert state["report"]["workflow_error"] == "Screening agent failed"
    assert state["report"]["findings"] == state["case_file"]["findings"]


def test_more_information_request_ends_without_an_automatic_loop() -> None:
    graph = _graph()
    config = _config("more-information")
    graph.invoke(initial_state("CASE-004", {}), config)

    result = graph.invoke(
        Command(
            resume={
                "decision": "MORE_INFORMATION_REQUIRED",
                "reviewer": "aml-reviewer",
                "requested_target": "transaction_agent",
            }
        ),
        config,
    )

    assert result["case_status"] == "AWAITING_INFORMATION"
    assert result["phase"] == "complete"


def test_malformed_worker_items_are_excluded_instead_of_crashing() -> None:
    validation, validated_case = validate_evidence(
        {
            "case_id": "CASE-MALFORMED",
            "findings": [None, "not-a-finding"],
            "evidence": [None, "not-evidence"],
        }
    )

    assert validation["status"] == "FAILED"
    assert validation["issues"]
    assert validated_case["findings"] == []
    assert validated_case["evidence"] == []


def test_invalid_finding_is_excluded_and_reported() -> None:
    validation, validated_case = validate_evidence(
        {
            "case_id": "CASE-005",
            "findings": [
                {
                    "finding_id": "bad-finding",
                    "finding_type": "TRANSACTION_PATTERN",
                    "summary": "Missing evidence and visibility",
                    "evidence_ids": ["missing-evidence"],
                }
            ],
            "evidence": [],
        }
    )

    assert validation["status"] == "FAILED"
    assert validation["invalid_finding_count"] == 1
    assert validated_case["findings"] == []
    assert any("missing-evidence" in issue for issue in validation["issues"])
