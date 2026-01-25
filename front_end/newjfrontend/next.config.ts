import type { NextConfig } from "next";

const nextConfig: NextConfig & { eslint?: { ignoreDuringBuilds?: boolean } } = {
  output: "standalone", // Required for Docker multi-stage build
  experimental: {
    serverComponentsExternalPackages: [],
  },
  env: {
    BACKEND_URL: process.env.BACKEND_URL || "http://backend:8000",
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true, // Match old frontend pattern
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.BACKEND_URL || 'http://backend:8000'}/api/:path*`,
      },
    ]
  },
};

export default nextConfig;
