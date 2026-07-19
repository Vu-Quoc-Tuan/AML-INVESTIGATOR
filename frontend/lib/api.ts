/** Shared browser client for existing backend `/api/v1` endpoints. */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function getApiBaseUrl(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!base) {
    throw new ApiError(
      0,
      "Missing NEXT_PUBLIC_API_BASE_URL (e.g. http://localhost:8000/api/v1)",
    );
  }
  return base.replace(/\/$/, "");
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
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
    throw new ApiError(
      0,
      `Cannot reach backend API at ${getApiBaseUrl()}. Start BE (make up / uvicorn) and check CORS.`,
    );
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
      const message =
        typeof nested.message === "string"
          ? nested.message
          : `Request failed (${response.status})`;
      const code = typeof nested.code === "string" ? nested.code : null;
      throw new ApiError(response.status, message, code);
    }

    if (typeof detail === "string") {
      throw new ApiError(response.status, detail);
    }

    throw new ApiError(response.status, `Request failed (${response.status})`);
  }

  return payload as T;
}
