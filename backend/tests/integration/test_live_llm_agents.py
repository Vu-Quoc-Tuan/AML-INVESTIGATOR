"""Live contract tests for the configured investigation agents."""

import json

import pytest
from langchain_core.tools import tool

from app.investigation_orchestrator.agents import (
    build_kyc_agent,
    build_planner_agent,
    build_report_agent,
    build_screening_agent,
    build_transaction_agent,
    invoke_planner,
    invoke_report,
    invoke_worker,
)
from app.investigation_orchestrator.model import build_chat_model
from app.investigation_orchestrator.tool_registry import ToolResult
from app.screening import ScreeningFacade, build_screening_tools
from app.transaction_investigation import build_transaction_tools
from app.kyc_entity import build_kyc_tools
from app.schemas.evidence import KycEvidence
from app.schemas.kyc_entity import CompanyProfileSnapshot


pytestmark = pytest.mark.live_llm


class StaticScreeningProvider:
    def candidates(self, *args, **kwargs):
        return [
            {
                "watchlist_id": "WL-LIVE-001",
                "list_type": "SANCTIONS",
                "full_name": "Nguyen Van An",
                "aliases": [],
                "date_of_birth": "1980-05-05",
                "nationalities": ["VN"],
                "document_numbers": ["P12345"],
                "company_registration_number": None,
                "source_name": "DEMO-SANCTIONS-LIST",
                "effective_from": "2020-01-01",
                "effective_to": None,
                "status": "ACTIVE",
                "screening_dependency": "available",
            }
        ]


class StaticTransactionService:
    """Production-adapter dependency with one deterministic internal record."""

    def get_account_transactions(self, *args, **kwargs):
        return {
            "transactions": [
                {
                    "transaction_id": "TX-LIVE-PRODUCTION-1",
                    "source_account_ref": "ACCT-SHB-LIVE-001",
                    "destination_account_ref": "ACCT-SHB-LIVE-002",
                    "amount": 1250000.0,
                    "occurred_at": "2026-01-01T10:00:00+00:00",
                    "evidence_source": "SHB_TRANSACTION_LEDGER",
                    "data_visibility": "FULL_INTERNAL",
                }
            ],
            "counterparty_summary": [],
            "total_inbound_amount": 0.0,
            "total_outbound_amount": 1250000.0,
            "net_flow": -1250000.0,
            "count": 1,
        }


class StaticKycFacade:
    """Production-adapter dependency with one deterministic internal profile."""

    def get_company_profile(self, company_id, as_of_date):
        return CompanyProfileSnapshot(
            entity={"company_id": company_id, "legal_name": "Live Test Company"},
            address=None,
            accounts=[],
            kyc_profile=None,
            documents=[],
            representative=None,
            direct_owners=[],
            ownership_coverage_percentage=100.0,
            ownership_status="COMPLETE",
            evidence=[
                KycEvidence(
                    evidence_id="EV-LIVE-KYC-COMPANY",
                    source_type="SHB_COMPANY_MASTER",
                    source_record_id=company_id,
                    statement=f"SHB company master record {company_id}",
                    visibility_level="FULL_INTERNAL",
                )
            ],
        )


def test_live_planner_returns_the_mandatory_plan() -> None:
    plan, error_type = invoke_planner(
        build_planner_agent(build_chat_model()),
        '{"case_id":"CASE-LIVE-PLAN","alert":{"type":"rapid_movement"}}',
    )
    assert error_type is None
    assert len(plan["steps"]) == 6
    assert plan["steps"][-1]["stage"] == "human_review"


def test_live_transaction_agent_uses_tool_derived_evidence() -> None:
    @tool
    def get_account_transactions(case_id: str) -> dict:
        """Return one deterministic internal transaction for a live agent test."""

        return ToolResult(
            status="SUCCESS",
            data={"case_id": case_id, "amount": 1000},
            evidence=[
                {
                    "evidence_id": "E-LIVE-TX",
                    "source_system": "SHB_TRANSACTION_LEDGER",
                    "source_record_id": "TX-LIVE-1",
                    "visibility_level": "FULL_INTERNAL",
                }
            ],
        ).model_dump()

    tools = [get_account_transactions]
    output = invoke_worker(
        "transaction",
        build_transaction_agent(build_chat_model(), tools),
        tools,
        '{"case_id":"CASE-LIVE-TX","alert":{"data_visibility":"FULL_INTERNAL"}}',
    )
    assert output["available"] is True, output["metadata"]
    assert {item["evidence_id"] for item in output["evidence"]} == {"E-LIVE-TX"}
    assert all(
        set(finding["evidence_ids"]) <= {"E-LIVE-TX"}
        for finding in output["findings"]
    )


def test_live_transaction_agent_selects_the_registered_production_tool() -> None:
    tools = build_transaction_tools(StaticTransactionService())
    context = json.dumps(
        {
            "case_id": "CASE-LIVE-PRODUCTION-TX",
            "instruction": (
                "Call get_account_transactions exactly once for the account_id "
                "below. Do not call another tool. Report only tool-derived evidence."
            ),
            "account_id": "ACCT-SHB-LIVE-001",
            "alert": {"data_visibility": "FULL_INTERNAL"},
        }
    )

    output = invoke_worker(
        "transaction",
        build_transaction_agent(build_chat_model(), tools),
        tools,
        context,
    )

    assert output["status"] != "ERROR", output["metadata"]
    assert output["available"] is True, output["metadata"]
    assert {item["evidence_id"] for item in output["evidence"]} == {
        "TX-LIVE-PRODUCTION-1"
    }
    assert output["evidence"][0]["source_system"] == "SHB_TRANSACTION_LEDGER"
    assert output["evidence"][0]["visibility_level"] == "FULL_INTERNAL"


def test_live_kyc_agent_selects_the_registered_production_tool() -> None:
    tools = build_kyc_tools(StaticKycFacade())
    context = json.dumps(
        {
            "case_id": "CASE-LIVE-PRODUCTION-KYC",
            "instruction": (
                "Call get_company_profile exactly once using the company_id and "
                "as_of_date below. Do not call another tool. Report only "
                "tool-derived internal evidence."
            ),
            "company_id": "COMP-LIVE-001",
            "as_of_date": "2025-12-20",
        }
    )

    output = invoke_worker(
        "kyc",
        build_kyc_agent(build_chat_model(), tools),
        tools,
        context,
    )

    assert output["status"] != "ERROR", output["metadata"]
    assert output["available"] is True, output["metadata"]
    assert {item["evidence_id"] for item in output["evidence"]} == {
        "EV-LIVE-KYC-COMPANY"
    }
    assert output["evidence"][0]["source_system"] == "SHB_COMPANY_MASTER"


def test_live_screening_agent_cannot_confirm_external_name_only_match() -> None:
    @tool
    def screen_internal_watchlist(case_id: str) -> dict:
        """Return a deterministic external name-only candidate for a live test."""

        return ToolResult(
            status="SUCCESS",
            data={"case_id": case_id, "entity_scope": "EXTERNAL", "match_basis": "NAME"},
            evidence=[
                {
                    "evidence_id": "E-LIVE-SCREEN",
                    "source_system": "INTERNAL_SCREENING_SERVICE",
                    "source_record_id": "SCREEN-LIVE-1",
                }
            ],
        ).model_dump()

    tools = [screen_internal_watchlist]
    output = invoke_worker(
        "screening",
        build_screening_agent(build_chat_model(), tools),
        tools,
        '{"case_id":"CASE-LIVE-SCREEN","instruction":"Assess the external name-only candidate."}',
    )
    assert output["status"] != "ERROR", output["metadata"]
    assert output["available"] is True
    assert {item["evidence_id"] for item in output["evidence"]} == {"E-LIVE-SCREEN"}
    assert output["status"] != "CONFIRMED_MATCH"


def test_live_screening_agent_uses_the_merged_screening_tool() -> None:
    tools = build_screening_tools(ScreeningFacade(StaticScreeningProvider()))
    context = json.dumps(
        {
            "case_id": "CASE-LIVE-MERGED-SCREENING",
            "instruction": (
                "Call screen_subject_against_watchlists exactly once with the "
                "screening_request below, then report the tool-derived result."
            ),
            "screening_request": {
                "request_id": "REQ-LIVE-001",
                "subject": {
                    "subject_id": "CUST-LIVE-001",
                    "entity_scope": "SHB_INTERNAL",
                    "entity_type": "INDIVIDUAL",
                    "name": "Nguyen Van An",
                    "date_of_birth": "1980-05-05",
                    "nationalities": ["VN"],
                    "passport_number": "P-12345",
                },
                "screening_types": ["SANCTIONS"],
                "as_of_date": "2026-01-01",
            },
        }
    )

    output = invoke_worker(
        "screening",
        build_screening_agent(build_chat_model(), tools),
        tools,
        context,
    )

    assert output["status"] != "ERROR", output["metadata"]
    assert output["available"] is True, output["metadata"]
    assert {item["evidence_id"] for item in output["evidence"]} == {
        "EV-SCREENING-WL-LIVE-001"
    }
    assert output["status"] == "CONFIRMED_MATCH", output["metadata"]


def test_live_report_preserves_human_review_safety_fields() -> None:
    case_file = {"findings": [], "evidence": [], "screening": {"status": "NO_MATCH"}}
    report = invoke_report(
        build_report_agent(build_chat_model()),
        '{"case_id":"CASE-LIVE-REPORT","case_file":{"findings":[],"evidence":[]}}',
        "CASE-LIVE-REPORT",
        case_file=case_file,
        validation={"status": "PASSED"},
        workflow_error=None,
    )
    assert report["recommended_action"] == "HUMAN_REVIEW_REQUIRED"
    assert report["automated_compliance_decision"] is False
    assert report["workflow_error"] is None
