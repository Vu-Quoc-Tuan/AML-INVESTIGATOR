import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  InvestigationControlApiError,
  investigationControlApi,
} from "./investigation-control";

const BASE_URL = "http://localhost:8000/api/v1";

describe("investigationControlApi", () => {
  beforeEach(() => {
    process.env.NEXT_PUBLIC_API_BASE_URL = BASE_URL;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  });

  it("parses a successful summary and disables read caching", async () => {
    const payload = {
      mode: "MANUAL",
      queue: { pending: 2, processing: 1, completed: 4, failed: 0 },
      active_run: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(investigationControlApi.getSummary()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/investigation-control`,
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("parses a 202 run response", async () => {
    const run = {
      run_id: "run-1",
      trigger: "MANUAL",
      status: "PENDING",
      completed_count: 0,
      failed_count: 0,
      created_at: "2026-07-19T01:00:00Z",
      started_at: null,
      finished_at: null,
      error: null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(run), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(investigationControlApi.createRun("MANUAL")).resolves.toEqual(run);
  });

  it("maps nested conflict details to a typed error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              code: "CONTROL_CONFLICT",
              message: "an active run already exists",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const promise = investigationControlApi.setMode("AUTO");
    await expect(promise).rejects.toMatchObject({
      status: 409,
      code: "CONTROL_CONFLICT",
      message: "an active run already exists",
    });
    await expect(promise).rejects.toBeInstanceOf(InvestigationControlApiError);
  });

  it("uses a safe fallback for a non-json server error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("internal detail", { status: 500 })),
    );

    await expect(investigationControlApi.getConfiguration()).rejects.toMatchObject({
      status: 500,
      code: "HTTP_500",
      message: "Investigation control request failed.",
    });
  });

  it("encodes run ids in detail URLs", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await investigationControlApi.getRun("run/with spaces");

    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE_URL}/investigation-control/runs/run%2Fwith%20spaces`,
      expect.any(Object),
    );
  });

  it("fails clearly when the public API base URL is missing", async () => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;

    await expect(investigationControlApi.getSummary()).rejects.toThrow(
      "NEXT_PUBLIC_API_BASE_URL is not configured",
    );
  });
});
