export const INVESTIGATION_EVENT_TYPES = [
  "AGENT_STARTED",
  "TOOL_STARTED",
  "TOOL_SUCCEEDED",
  "TOOL_FAILED",
  "AGENT_COMPLETED",
  "AGENT_FAILED",
  "INVESTIGATION_COMPLETED",
  "INVESTIGATION_FAILED",
  "REVIEW_DECIDED",
] as const;

export type InvestigationEventType = (typeof INVESTIGATION_EVENT_TYPES)[number];
export type AgentRuntimeStatus = "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
export type TechnicalStatus = "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
export type ReviewDecision = "APPROVED" | "REJECTED" | "FALSE";

export interface InvestigationEvent {
  id: number;
  ticket_id: string;
  case_id: string;
  agent_id: string | null;
  event_type: InvestigationEventType;
  status: string;
  summary: string;
  tool_name: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface AgentRuntimeState {
  status: AgentRuntimeStatus;
  events: InvestigationEvent[];
}

export interface InvestigationEventState {
  ticketId: string;
  lastEventId: number;
  agents: Record<string, AgentRuntimeState>;
  /** Chronological log of every SSE event for the ticket. */
  timeline: InvestigationEvent[];
  selectedAgentId: string | null;
  technicalStatus: TechnicalStatus;
  reviewDecision: ReviewDecision | null;
  finalOutput: Record<string, unknown> | null;
  lastErrorSummary: string | null;
}

const eventTypeSet = new Set<string>(INVESTIGATION_EVENT_TYPES);

export function initialInvestigationEventState(ticketId: string): InvestigationEventState {
  return {
    ticketId,
    lastEventId: 0,
    agents: {},
    timeline: [],
    selectedAgentId: null,
    technicalStatus: "IDLE",
    reviewDecision: null,
    finalOutput: null,
    lastErrorSummary: null,
  };
}

export function parseInvestigationEvent(raw: string): InvestigationEvent {
  let value: unknown;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    throw new Error("Invalid SSE event");
  }
  if (!isRecord(value)) throw new Error("Invalid SSE event");
  const eventType = value.event_type;
  const payload = value.payload;
  if (
    typeof value.id !== "number" ||
    !Number.isInteger(value.id) ||
    value.id < 1 ||
    typeof value.ticket_id !== "string" ||
    typeof value.case_id !== "string" ||
    typeof eventType !== "string" ||
    !eventTypeSet.has(eventType) ||
    typeof value.status !== "string" ||
    typeof value.summary !== "string" ||
    typeof value.created_at !== "string" ||
    (value.agent_id !== null && typeof value.agent_id !== "string") ||
    (value.tool_name !== null && typeof value.tool_name !== "string") ||
    (payload !== null && !isRecord(payload))
  ) {
    throw new Error("Invalid SSE event");
  }
  return value as unknown as InvestigationEvent;
}

export function reduceInvestigationEvent(
  current: InvestigationEventState,
  event: InvestigationEvent,
): InvestigationEventState {
  const state = event.ticket_id === current.ticketId
    ? current
    : initialInvestigationEventState(event.ticket_id);
  if (event.id <= state.lastEventId) return state;

  let agents = state.agents;
  let selectedAgentId = state.selectedAgentId;
  let technicalStatus = state.technicalStatus;
  let reviewDecision = state.reviewDecision;
  let finalOutput = state.finalOutput;
  let lastErrorSummary = state.lastErrorSummary;
  const timeline = [...state.timeline, event];

  if (event.agent_id) {
    const previous = agents[event.agent_id] ?? { status: "IDLE" as const, events: [] };
    let status = previous.status;
    if (event.event_type === "AGENT_STARTED" || event.event_type === "TOOL_STARTED") {
      status = "RUNNING";
      selectedAgentId = event.agent_id;
      technicalStatus = "RUNNING";
    } else if (event.event_type === "AGENT_COMPLETED") {
      status = "COMPLETED";
    } else if (event.event_type === "TOOL_FAILED" || event.event_type === "AGENT_FAILED") {
      status = "FAILED";
      selectedAgentId = event.agent_id;
      technicalStatus = "FAILED";
      lastErrorSummary = event.summary || "Agent/tool failed";
    }
    agents = {
      ...agents,
      [event.agent_id]: { status, events: [...previous.events, event] },
    };
  }

  if (event.event_type === "INVESTIGATION_COMPLETED") {
    technicalStatus = "COMPLETED";
    const result = event.payload?.result;
    finalOutput = isRecord(result) ? result : event.payload;
  } else if (event.event_type === "INVESTIGATION_FAILED") {
    technicalStatus = "FAILED";
    finalOutput = event.payload;
    lastErrorSummary = event.summary || "Investigation failed";
  } else if (event.event_type === "REVIEW_DECIDED") {
    const decision = event.payload?.decision;
    if (decision === "APPROVED" || decision === "REJECTED" || decision === "FALSE") {
      reviewDecision = decision;
    }
  }

  return {
    ...state,
    lastEventId: event.id,
    agents,
    timeline,
    selectedAgentId,
    technicalStatus,
    reviewDecision,
    finalOutput,
    lastErrorSummary,
  };
}

export function eventStreamUrl(ticketId: string): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!base) throw new Error("NEXT_PUBLIC_API_BASE_URL is not configured");
  return `${base.replace(/\/$/, "")}/tickets/${encodeURIComponent(ticketId)}/events`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
