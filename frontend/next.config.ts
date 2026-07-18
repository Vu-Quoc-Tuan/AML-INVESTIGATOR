import type { NextConfig } from "next";

// Hosted on Vercel (not Docker). Do not set `output: "standalone"` here —
// Vercel builds Next.js natively. API calls go to Cloudflare-tunneled BE:
//   NEXT_PUBLIC_API_BASE_URL=https://aml-api.vutuan.indevs.in
const nextConfig: NextConfig = {
  // Empty for now; extend when adding rewrites/images domains.
};

export default nextConfig;
