#!/usr/bin/env python3
"""Run the autonomous investigation workflow with demo or live agent nodes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.investigation_orchestrator import build_workflow, initial_state  # noqa: E402
from app.investigation_orchestrator.model import (  # noqa: E402
    ModelConfigurationError,
    get_model_settings,
)
from app.legal_rag.config import LegalRagConfig  # noqa: E402
from app.legal_rag.hybrid_retriever import (  # noqa: E402
    HybridLegalRetriever,
    StaticLegalRetriever,
)
from app.main import initialize_backend  # noqa: E402
from tests.node_fixtures import deterministic_agent_nodes  # noqa: E402


def print_header(title: str) -> None:
    print("=" * 60)
    print(f" {title.center(58)} ")
    print("=" * 60)


def print_sub_header(title: str) -> None:
    print("\n" + "-" * 40)
    print(f" {title} ")
    print("-" * 40)


def _select_legal_retriever(*, use_live: bool):
    if not use_live:
        print("Legal RAG: StaticLegalRetriever (offline demo)")
        return StaticLegalRetriever()
    config = LegalRagConfig.from_env()
    if config.is_configured():
        print("Legal RAG: HybridLegalRetriever (Qdrant + NVIDIA from backend/.env)")
        return HybridLegalRetriever(config)
    print(
        "Legal RAG: Hybrid credentials missing; falling back to StaticLegalRetriever. "
        "Set QRANT_URL/QRANT_API and NVIDIA_API for live retrieval."
    )
    return StaticLegalRetriever()


def _build_graph(use_live: bool):
    legal_retriever = _select_legal_retriever(use_live=use_live)
    if not use_live:
        print("Initializing workflow with DETERMINISTIC simulation nodes...")
        return build_workflow(
            agent_nodes=deterministic_agent_nodes(),
            legal_retriever=legal_retriever,
        )

    print("Initializing backend data repository...")
    initialize_backend()
    print("Initializing workflow with LIVE LLM agents...")
    settings = get_model_settings()
    print("LLM settings loaded successfully.")
    print(f"Model: {settings.model_name}")
    print(f"Base URL: {settings.base_url}")
    return build_workflow(legal_retriever=legal_retriever)


def run_workflow(case_id: str, alert: dict[str, Any], use_live: bool) -> int:
    config = {"configurable": {"thread_id": f"investigation-{case_id}"}}

    try:
        graph = _build_graph(use_live)
    except ModelConfigurationError as exc:
        print(f"\n[ERROR] Failed to load LLM settings: {exc}")
        print("Configure backend/.env with API_KEY and BASE_URL.")
        print("Or run without --live to use deterministic simulation mode.")
        return 1
    except Exception as exc:
        print(f"\n[ERROR] Failed to initialize workflow: {exc}")
        return 1

    print("\nInvoking workflow graph...")
    inputs = initial_state(case_id, alert)
    print(f"Input: {json.dumps(inputs, indent=2)}")

    last_phase = "new"
    print_header("Workflow Stream Execution")

    for event in graph.stream(inputs, config, stream_mode="updates"):
        for node_name, update in event.items():
            print(f"\n▶️ [Node Completed: {node_name}]")
            if "phase" in update:
                print(f"   Phase change: {last_phase} -> {update['phase']}")
                last_phase = update["phase"]

            if "investigation_plan" in update:
                plan = update["investigation_plan"]
                print("   Plan Created:")
                print(f"     Summary: {plan.get('case_summary')}")
                print(f"     Steps: {len(plan.get('steps', []))} steps planned.")

            if "agent_outputs" in update:
                for agent_name, agent_out in update["agent_outputs"].items():
                    print(f"   Agent Output [{agent_name}]:")
                    print(f"     Status: {agent_out.get('status')}")
                    print(f"     Findings: {len(agent_out.get('findings', []))}")
                    evidence_count = len(agent_out.get("evidence", []))
                    print(f"     Evidence items collected: {evidence_count}")

            if "case_file" in update:
                print("   Case File Merged:")
                print(f"     Total findings: {len(update['case_file'].get('findings', []))}")
                print(f"     Total evidence: {len(update['case_file'].get('evidence', []))}")

            if "evidence_validation" in update:
                validation = update["evidence_validation"]
                print(f"   Evidence Validation Result: {validation.get('status')}")
                if issues := validation.get("issues", []):
                    print(f"     Issues found: {issues}")

            if "report" in update:
                print("   Dossier Drafted by Report Agent:")
                print(f"     Title: {update['report'].get('title')}")
                print(f"     Summary: {update['report'].get('summary')}")
                print(f"     Findings: {len(update['report'].get('findings', []))}")

    state_info = graph.get_state(config)
    print_sub_header("Handoff Log / Routing Path")
    for index, log in enumerate(state_info.values.get("handoff_log", []), 1):
        print(f" {index}. {log['source']} -> {log['target']} ({log['reason']})")

    if state_info.next:
        print_header("Workflow Unexpectedly Waiting")
        print(f"Next Node in Graph: {state_info.next}")
        print(f"Current Phase: {state_info.values.get('phase')}")
        return 1

    print_header("Workflow Completed")
    print("\nInvestigation Dossier:")
    print(json.dumps(state_info.values.get("report", {}), indent=2))

    final_state = state_info.values
    print_header("Final Case Investigation Status")
    print(f"Case ID: {final_state.get('case_id')}")
    print(f"Phase: {final_state.get('phase')}")
    print(f"Errors: {final_state.get('errors', [])}")
    print(f"Workflow Error: {final_state.get('workflow_error')}")
    print("\nComplete Handoff Trace:")
    for index, log in enumerate(final_state.get("handoff_log", []), 1):
        print(f"  {index}. {log['source']} -> {log['target']} : {log['reason']}")
    print("=" * 60)
    return 0 if final_state.get("phase") == "complete" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the autonomous AML Multi-Agent Investigation Workflow."
    )
    parser.add_argument("--case-id", default="CASE-MOCK-999")
    parser.add_argument("--subject-bank", default="BANK-SHB-001")
    parser.add_argument(
        "--visibility",
        default="FULL_INTERNAL",
        choices=["FULL_INTERNAL", "PAYMENT_MESSAGE_ONLY", "ENRICHED_EXTERNAL"],
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use live LLM agents configured through backend/.env.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    alert = {
        "type": "rapid_movement",
        "subject_bank_id": args.subject_bank,
        "data_visibility": args.visibility,
        "subject_id": "CUST-SHB-7718",
        "transaction_id": "TX-SHB-4819",
        "screening_available": True,
        "screening_status": "NO_MATCH",
    }
    return run_workflow(args.case_id, alert, args.live)


if __name__ == "__main__":
    raise SystemExit(main())
