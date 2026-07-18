"""KYC evidence is committed and validated only by the orchestrator."""

from copy import deepcopy

from app.investigation_orchestrator.evidence_validator import validate_evidence
from app.investigation_orchestrator.nodes import merge_and_validate_node
from app.investigation_orchestrator.state import initial_state


def parallel_state(kyc_evidence_ids: list[str]) -> dict:
    return {
        **initial_state("CASE-KYC-MERGE", {}),
        "agent_outputs": {
            "transaction": {
                "agent": "transaction_agent",
                "status": "COMPLETED",
                "findings": [],
                "evidence": [],
            },
            "kyc": {
                "agent": "kyc_agent",
                "status": "COMPLETED",
                "findings": [
                    {
                        "finding_id": "F-KYC-1",
                        "finding_type": "KYC_PROFILE",
                        "summary": "Verified internal KYC profile",
                        "evidence_ids": kyc_evidence_ids,
                        "entity_scope": "SHB_INTERNAL",
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "EV-KYC-1",
                        "source_system": "SHB_KYC_PROFILE",
                        "source_record_id": "KYC-1",
                        "visibility_level": "FULL_INTERNAL",
                    }
                ],
            },
        },
    }


def test_exact_retry_builds_the_same_case_file_without_mutating_input() -> None:
    state = parallel_state(["EV-KYC-1"])
    before = deepcopy(state)

    first = merge_and_validate_node(state).update["case_file"]
    second = merge_and_validate_node(state).update["case_file"]

    assert first == second
    assert state == before


def test_invalid_kyc_reference_is_excluded_by_deterministic_validation() -> None:
    state = parallel_state(["EV-KYC-MISSING"])
    case_file = merge_and_validate_node(state).update["case_file"]

    validation, validated_case = validate_evidence(case_file)

    assert validation["status"] == "FAILED"
    assert validated_case["findings"] == []
    assert case_file["findings"]
