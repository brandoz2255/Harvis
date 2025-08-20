const nextConfig = {
  output: "standalone",
  experimental: {
    serverComponentsExternalPackages: [],
  },
  env: {
    BACKEND_URL: process.env.BACKEND_URL || "http://backend:8000",
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "/api/:path*",
      },
    ]
  },
  eslint: {
    ignoreDuringBuilds: false, // Enable ESLint to catch circular imports
  },
  typescript: {
    ignoreBuildErrors: false, // Enable TypeScript error checking
  },
  images: {
    unoptimized: true,
  },
  // Enable source maps for better debugging
  productionBrowserSourceMaps: true,
  webpack: (config, { dev, isServer }) => {
    if (!dev && !isServer) {
      config.devtool = 'source-map';
    }
    return config;
  },
}

module.exports = nextConfig
