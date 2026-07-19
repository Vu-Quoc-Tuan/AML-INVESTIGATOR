import { apiRequest } from "./api";

export type TicketStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
export type ReviewDecision = "APPROVED" | "REJECTED" | "FALSE";

export type TicketDisplayStatus =
  | "PENDING"
  | "RUNNING"
  | "AWAITING_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "FALSE"
  | "FAILED"
  | "COMPLETED";

export interface TicketSummary {
  ticket_id: string;
  event_id: string;
  transaction_id: string | null;
  status: TicketStatus;
  /** UI status (e.g. AWAITING_REVIEW when done and waiting APPROVE/REJECT) */
  display_status?: TicketDisplayStatus | string;
  attempts: number;
  case_id: string | null;
  ml_confidence: number;
  overall_risk_level: string | null;
  is_laundering_suspect: boolean;
  review_decision: ReviewDecision | null;
  /** Prefer transaction description / risk rationale / rule reason */
  message?: string | null;
  can_run: boolean;
  can_review: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface TicketDetail extends TicketSummary {
  last_error: string | null;
  transaction: Record<string, unknown> | null;
  detection: {
    decision: string;
    ml_confidence: number;
    model_version: string;
    rule_hits: Array<{
      rule_id: string;
      reason: string;
      evidence: Record<string, unknown>;
    }>;
    imputed_features: string[];
  };
  result: Record<string, unknown> | null;
}

export interface TicketListResponse {
  items: TicketSummary[];
  limit: number;
  offset: number;
  count: number;
}

export function listTickets(params: {
  status?: TicketStatus;
  limit?: number;
  offset?: number;
} = {}): Promise<TicketListResponse> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query}` : "";
  return apiRequest<TicketListResponse>(`/tickets${suffix}`);
}

export function getTicket(ticketId: string): Promise<TicketDetail> {
  return apiRequest<TicketDetail>(`/tickets/${encodeURIComponent(ticketId)}`);
}

export function runTicket(ticketId: string): Promise<{ ticket_id: string; status: string }> {
  return apiRequest(`/tickets/${encodeURIComponent(ticketId)}/run`, {
    method: "POST",
  });
}

export function reviewTicket(
  ticketId: string,
  decision: ReviewDecision,
): Promise<TicketDetail> {
  return apiRequest(`/tickets/${encodeURIComponent(ticketId)}/review`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}
