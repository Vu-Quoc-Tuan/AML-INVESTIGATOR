import { describe, expect, it } from "vitest";

import {
  LLM_AGENTS,
  WORKFLOW_EDGES,
  WORKFLOW_NODES,
} from "./workflow-catalog";

describe("workflow catalog", () => {
  it("contains only the six LLM agents shown in the live workflow", () => {
    const agents = WORKFLOW_NODES.filter((node) => node.kind === "agent");

    expect(agents.map((node) => node.id)).toEqual([
      "planner",
      "transaction_agent",
      "kyc_agent",
      "screening_agent",
      "behavior_mapper",
      "report_agent",
    ]);
    expect(LLM_AGENTS).toEqual(agents);
    expect(new Set(WORKFLOW_NODES.map((node) => node.id)).size).toBe(6);
    expect(WORKFLOW_NODES.every((node) => node.role.trim().length > 0)).toBe(true);
  });

  it("contains the mandatory Transaction and KYC parallel fork", () => {
    expect(WORKFLOW_EDGES).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "planner", target: "transaction_agent" }),
        expect.objectContaining({ source: "planner", target: "kyc_agent" }),
        expect.objectContaining({ source: "transaction_agent", target: "screening_agent" }),
        expect.objectContaining({ source: "kyc_agent", target: "screening_agent" }),
        expect.objectContaining({ source: "screening_agent", target: "behavior_mapper" }),
        expect.objectContaining({ source: "behavior_mapper", target: "report_agent" }),
      ]),
    );
  });
});
