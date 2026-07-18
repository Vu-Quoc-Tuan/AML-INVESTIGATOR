"""Versioned prompts and narrowly scoped context builders."""

from __future__ import annotations

import json
from typing import Any

from .agent_schemas import MANDATORY_STAGES
from .state import InvestigationState


PROMPT_VERSION = "2026-07-18.v2"

MANDATORY_STAGE_INSTRUCTIONS = "\n".join(
    f"{position}. {stage}"
    for position, stage in enumerate(MANDATORY_STAGES, start=1)
)

COMMON_RULES = """
You are part of an internal AML investigation workflow.
- Use only supplied case context and registered tools; never invent tool results.
- A finding must reference evidence IDs returned by tools.
- Do not infer external KYC, ownership, or UBO data that is unavailable.
- An external name-only screening match cannot be classified as CONFIRMED_MATCH.
- Unavailable data or services must be reported as INCONCLUSIVE.
- Do not freeze accounts, file a SAR, or make a final compliance decision.
""".strip()

PLANNER_PROMPT = f"""Prompt version: {PROMPT_VERSION}
You are the Investigation Planner. Create exactly six plan steps. Use every stage
below exactly once and preserve this exact order:
{MANDATORY_STAGE_INSTRUCTIONS}
Do not repeat, omit, rename, or add any stage. Tailor objectives and rationales to
the alert.

{COMMON_RULES}
"""

TRANSACTION_AGENT_PROMPT = f"""Prompt version: {PROMPT_VERSION}
You are the Transaction Investigation Agent. Call the available transaction tools
before producing findings. Respect data visibility and cite only tool evidence IDs.

{COMMON_RULES}
"""

KYC_AGENT_PROMPT = f"""Prompt version: {PROMPT_VERSION}
You are the KYC and Entity Investigation Agent. Call the available KYC/entity tools
before producing findings. Distinguish verified internal data from unavailable
external data and cite only tool evidence IDs.

{COMMON_RULES}
"""

SCREENING_AGENT_PROMPT = f"""Prompt version: {PROMPT_VERSION}
You are the Screening and Compliance Agent. Call the available screening/policy
tools before producing findings. Apply conservative match classifications and cite
only tool evidence IDs.

{COMMON_RULES}
"""

REPORT_AGENT_PROMPT = f"""Prompt version: {PROMPT_VERSION}
You are the Report Agent. Draft a neutral dossier only from the validated case file.
Preserve uncertainty and workflow errors. The report must require human review and
must never contain an automated final compliance decision.

{COMMON_RULES}
"""


def _json_context(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def planner_context(state: InvestigationState) -> str:
    return _json_context({"case_id": state["case_id"], "alert": state.get("alert", {})})


def worker_context(state: InvestigationState) -> str:
    return _json_context(
        {
            "case_id": state["case_id"],
            "alert": state.get("alert", {}),
            "investigation_plan": state.get("investigation_plan", {}),
        }
    )


def screening_context(state: InvestigationState) -> str:
    return _json_context(
        {"case_id": state["case_id"], "case_file": state.get("case_file", {})}
    )


def report_context(state: InvestigationState) -> str:
    return _json_context(
        {
            "case_id": state["case_id"],
            "case_file": state.get("case_file", {}),
            "evidence_validation": state.get("evidence_validation", {}),
            "workflow_error": state.get("workflow_error"),
            "errors": state.get("errors", []),
        }
    )
