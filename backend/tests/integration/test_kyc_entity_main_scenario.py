import json
from datetime import date
from pathlib import Path

from app.data.provider import _reset_data_repository_for_testing, initialize_data_repository
from app.investigation_orchestrator.tool_registry import KycToolRegistry
from app.schemas.evidence import KycEvidence
from app.schemas.tools import KycToolContext


def _tx_evidence(evidence_id: str) -> KycEvidence:
    return KycEvidence(
        evidence_id=evidence_id,
        source_type="SHB_TRANSACTION_LEDGER",
        source_record_id=evidence_id,
        statement="Person 2 observed transaction metric",
        visibility_level="FULL_INTERNAL",
    )


def test_main_company_kyc_ubo_and_turnover_case():
    _reset_data_repository_for_testing()
    initialize_data_repository(Path(__file__).resolve().parents[2] / "data" / "generated")
    registry = KycToolRegistry()
    context = KycToolContext(case_id="CASE-MAIN", as_of_date=date(2025, 12, 20))
    case = registry.case_store.get("CASE-MAIN")
    seeded = case.model_copy(update={"evidence": [
        _tx_evidence("EV-TX-IN-1"),
        _tx_evidence("EV-TX-XB-1"),
    ]})
    registry.case_store.replace("CASE-MAIN", 0, seeded)

    profile = registry.invoke("get_company_profile", {"company_id": "COMP-000008"}, context)
    documents = registry.invoke("compare_kyc_fields", {"entity_id": "COMP-000008"}, context)
    ownership = registry.invoke("build_ownership_graph", {"company_id": "COMP-000008", "max_depth": 3}, context)
    ubo = registry.invoke("calculate_ubo", {
        "ownership_graph": ownership["result"],
        "ownership_threshold": 0.25,
    }, context)
    mismatch = registry.invoke("compare_profile_with_observed_behavior", {
        "entity_id": "COMP-000008",
        "observed_transaction_features": {
            "entity_id": "COMP-000008",
            "window_start": "2025-12-20T10:00:00Z",
            "window_end": "2025-12-20T10:05:00Z",
            "account_ids": ["ACCT-SHB-002382"],
            "metrics": {
                "total_inflow": 5_000_000_000,
                "cross_border_observed": True,
                "observed_countries": ["VN", "SG"],
            },
            "metric_evidence_ids": {
                "total_inflow": ["EV-TX-IN-1"],
                "cross_border_observed": ["EV-TX-XB-1"],
                "observed_countries": ["EV-TX-XB-1"],
            },
        },
    }, context)

    assert profile["status"] == documents["status"] == ownership["status"] == "ok"
    assert ubo["status"] == mismatch["status"] == "ok"
    assert any(item["verified"] for item in ubo["result"]["identified_ubos"])
    assert any(item["type"] == "TURNOVER_DEVIATION" for item in mismatch["result"]["profile_mismatches"])
    assert not any(item["type"] == "CROSS_BORDER_EXPECTATION_MISMATCH" for item in mismatch["result"]["profile_mismatches"])
    case = registry.case_store.get("CASE-MAIN")
    evidence_ids = {item.evidence_id for item in case.evidence}
    assert all(set(item.evidence_ids) <= evidence_ids for item in case.profile_mismatches)
    assert any(item.type == "DOCUMENT_EXPIRED" for item in case.kyc_findings)
    assert not any(item.type == "BUSINESS_LICENSE" for item in case.missing_documents)
    json.dumps(case.model_dump(mode="json"), allow_nan=False)
    _reset_data_repository_for_testing()
