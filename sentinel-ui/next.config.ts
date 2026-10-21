import type { NextConfig } from "next";
import type { Rewrite } from "next/dist/lib/load-custom-routes";

// Deployed (Vercel) origin: CollabUp's API does not CORS-allow anything beyond
// localhost, so /api/* is proxied server-side to the same contract. The UI
// talks to its own origin; nothing upstream changes. Locally (`npm run dev`)
// the UI calls 127.0.0.1:8000 directly, so the rewrite never engages.
const API_PROXY_ORIGIN =
  process.env.API_PROXY_ORIGIN?.replace(/\/$/, "") ?? "https://apihacker.collabup.co.in";

const config: NextConfig = {
  reactStrictMode: true,
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },
  async rewrites(): Promise<Rewrite[] | Array<Rewrite>> {
    return [
      {
        source: "/api/:path*",
        destination: `${API_PROXY_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default config;
