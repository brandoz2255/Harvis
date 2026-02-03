import type { NextConfig } from "next";

const nextConfig: NextConfig & { eslint?: { ignoreDuringBuilds?: boolean } } = {
  output: "standalone", // Required for Docker multi-stage build
  experimental: {
    serverComponentsExternalPackages: [],
  },
  // Don't set BACKEND_URL here - it gets baked at build time!
  // Let it be read from environment at runtime instead
  env: {},
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true, // Match old frontend pattern
  },
  images: {
    unoptimized: true,
  },
  // Rewrites removed - nginx handles API routing in production
  // This was causing build-time baking of BACKEND_URL
};

export default nextConfig;
