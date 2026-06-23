import type { NextConfig } from "next";

// Vendored into Harvis. Served under basePath /onb by nginx; its /api/* calls are
// rewritten by THIS Next server to the Harvis backend's open-notebook-compat facade
// (prefix /onb-api), so they never collide with Harvis's own /api/* (OWUI) routes.
const nextConfig: NextConfig = {
  output: "standalone",
  basePath: "/onb",
  assetPrefix: "/onb",

  // Vendored fork: don't fail the production build on lint/TS from Harvis edits.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },

  experimental: {
    proxyClientMaxBodySize: '100mb',
  } as NextConfig['experimental'],

  async rewrites() {
    // The Harvis backend. The onb_compat facade is mounted at /onb-api.
    const internalApiUrl = process.env.INTERNAL_API_URL || 'http://backend:8000'
    console.log(`[Next.js Rewrites] Proxying /api/* to ${internalApiUrl}/onb-api/*`)
    return [
      {
        // With basePath, this matches /onb/api/* from the browser and proxies
        // server-side to the Harvis facade.
        source: '/api/:path*',
        destination: `${internalApiUrl}/onb-api/:path*`,
      },
    ]
  },
};

export default nextConfig;
