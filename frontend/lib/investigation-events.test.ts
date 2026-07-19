import { describe, expect, it } from "vitest";

import {
  initialInvestigationEventState,
  parseInvestigationEvent,
  reduceInvestigationEvent,
} from "./investigation-events";

const base = {
  ticket_id: "ticket-1",
  case_id: "case-1",
  tool_name: null,
  payload: null,
  created_at: "2026-07-19T07:00:00+00:00",
};

describe("investigation event reducer", () => {
  it("tracks live agent and tool lifecycle", () => {
    const started = parseInvestigationEvent(JSON.stringify({
      ...base,
      id: 1,
      agent_id: "transaction_agent",
      event_type: "AGENT_STARTED",
      status: "RUNNING",
      summary: "transaction_agent started",
    }));
    const tool = parseInvestigationEvent(JSON.stringify({
      ...base,
      id: 2,
      agent_id: "transaction_agent",
      event_type: "TOOL_STARTED",
      status: "RUNNING",
      summary: "Tool trace_funds started",
      tool_name: "trace_funds",
      payload: { input: { account_id: "ACC-1" } },
    }));
    const completed = parseInvestigationEvent(JSON.stringify({
      ...base,
      id: 3,
      agent_id: "transaction_agent",
      event_type: "AGENT_COMPLETED",
      status: "COMPLETED",
      summary: "transaction_agent completed",
    }));

    const state = [started, tool, completed].reduce(
      reduceInvestigationEvent,
      initialInvestigationEventState("ticket-1"),
    );

    expect(state.agents.transaction_agent.status).toBe("COMPLETED");
    expect(state.agents.transaction_agent.events).toHaveLength(3);
    expect(state.selectedAgentId).toBe("transaction_agent");
    expect(state.lastEventId).toBe(3);
  });

  it("keeps technical failure separate from analyst rejection", () => {
    const failed = parseInvestigationEvent(JSON.stringify({
      ...base,
      id: 4,
      agent_id: "kyc_agent",
      event_type: "TOOL_FAILED",
      status: "FAILED",
      summary: "Tool get_kyc failed",
      tool_name: "get_kyc",
      payload: { error_type: "RuntimeError" },
    }));
    const state = reduceInvestigationEvent(
      initialInvestigationEventState("ticket-1"),
      failed,
    );

    expect(state.agents.kyc_agent.status).toBe("FAILED");
    expect(state.technicalStatus).toBe("FAILED");
    expect(state.reviewDecision).toBeNull();
  });

  it("rejects malformed or unknown events", () => {
    expect(() => parseInvestigationEvent("not-json")).toThrow("Invalid SSE event");
    expect(() => parseInvestigationEvent(JSON.stringify({ ...base, id: 1 }))).toThrow(
      "Invalid SSE event",
    );
  });
});
