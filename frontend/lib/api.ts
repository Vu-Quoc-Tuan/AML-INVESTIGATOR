/**
 * Public API base URL.
 *
 * Flow:
 *   Browser (FE on Vercel) --HTTPS:443--> https://aml-api.vutuan.indevs.in
 *   Cloudflare Tunnel ------------------> 127.0.0.1:8000 (BE Docker)
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "https://aml-api.vutuan.indevs.in";

export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE_URL}${normalized}`;
}
