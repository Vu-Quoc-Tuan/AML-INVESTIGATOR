/** Typed client for existing Investigation Control backend APIs. */

export type RunMode = "AUTO" | "MANUAL";
export type RunTrigger = RunMode;
export type RunStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "COMPLETED_WITH_ERRORS"
  | "FAILED"
  | "INTERRUPTED";

export interface QueueCounts {
  pending: number;
  processing: number;
  completed: number;
  failed: number;
  /** Analyst pressed APPROVE after multi-agent flagged risk */
  approved?: number;
  /** Analyst pressed REJECT after multi-agent flagged risk */
  rejected?: number;
  /** Auto/analyst FALSE — not money laundering (not dashboard Reject) */
  false_positive?: number;
}

export interface InvestigationRun {
  run_id: string;
  trigger: RunTrigger;
  status: RunStatus;
  completed_count: number;
  failed_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface ControlSummary {
  mode: RunMode;
  queue: QueueCounts;
  active_run: InvestigationRun | null;
}

export interface SoftPromptConfiguration {
  soft_prompt: string | null;
  updated_at: string | null;
}

export class InvestigationControlApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "InvestigationControlApiError";
    this.status = status;
    this.code = code;
  }
}

function getBaseUrl(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!base) {
    throw new InvestigationControlApiError(
      0,
      "CONFIG",
      "NEXT_PUBLIC_API_BASE_URL is not configured",
    );
  }
  return base.replace(/\/$/, "");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${getBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new InvestigationControlApiError(0, "NETWORK", "Cannot reach backend API");
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && payload !== null && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : null;

    if (detail && typeof detail === "object" && detail !== null) {
      const nested = detail as { code?: unknown; message?: unknown };
      throw new InvestigationControlApiError(
        response.status,
        typeof nested.code === "string" ? nested.code : `HTTP_${response.status}`,
        typeof nested.message === "string"
          ? nested.message
          : "Investigation control request failed.",
      );
    }

    if (typeof detail === "string") {
      throw new InvestigationControlApiError(
        response.status,
        `HTTP_${response.status}`,
        detail,
      );
    }

    throw new InvestigationControlApiError(
      response.status,
      `HTTP_${response.status}`,
      "Investigation control request failed.",
    );
  }

  return payload as T;
}

export const investigationControlApi = {
  getSummary(): Promise<ControlSummary> {
    return request<ControlSummary>("/investigation-control");
  },

  setMode(mode: RunMode): Promise<{ mode: RunMode }> {
    return request<{ mode: RunMode }>("/investigation-control/mode", {
      method: "PUT",
      body: JSON.stringify({ mode }),
    });
  },

  createRun(trigger: RunTrigger): Promise<InvestigationRun> {
    return request<InvestigationRun>("/investigation-control/runs", {
      method: "POST",
      body: JSON.stringify({ trigger }),
    });
  },

  getRun(runId: string): Promise<InvestigationRun> {
    return request<InvestigationRun>(
      `/investigation-control/runs/${encodeURIComponent(runId)}`,
    );
  },

  listRuns(limit = 20): Promise<{ items: InvestigationRun[] }> {
    return request<{ items: InvestigationRun[] }>(
      `/investigation-control/runs?limit=${limit}`,
    );
  },

  getConfiguration(): Promise<SoftPromptConfiguration> {
    return request<SoftPromptConfiguration>("/investigation-control/configuration");
  },

  saveConfiguration(softPrompt: string | null): Promise<SoftPromptConfiguration> {
    return request<SoftPromptConfiguration>("/investigation-control/configuration", {
      method: "PUT",
      body: JSON.stringify({ soft_prompt: softPrompt }),
    });
  },
};

/** Thin aliases used by existing page wiring. */
export function getControlSummary(): Promise<ControlSummary> {
  return investigationControlApi.getSummary();
}

export function getConfiguration(): Promise<SoftPromptConfiguration> {
  return investigationControlApi.getConfiguration();
}

export function saveConfiguration(
  softPrompt: string | null,
): Promise<SoftPromptConfiguration> {
  return investigationControlApi.saveConfiguration(softPrompt);
}
