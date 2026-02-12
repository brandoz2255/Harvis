import type { NextConfig } from "next";
import path from "path";
import { copyFileSync, existsSync, mkdirSync } from "fs";

const nextConfig: NextConfig & { eslint?: { ignoreDuringBuilds?: boolean } } = {
  output: "standalone", // Required for Docker multi-stage build
  serverExternalPackages: [],
  // Don't set BACKEND_URL here - it gets baked at build time!
  // Let it be read from environment at runtime instead
  env: {},
  typescript: {
    ignoreBuildErrors: true, // Match old frontend pattern
  },
  images: {
    unoptimized: true,
  },
  // Rewrites removed - nginx handles API routing in production
  // This was causing build-time baking of BACKEND_URL
  
  // Use webpack instead of turbopack for compatibility
  turbopack: {
    // Disable turbopack to use webpack
  },
  
  // Copy PDF.js worker to public directory during build
  webpack: (config, { isServer }) => {
    if (!isServer) {
      // Ensure pdfjs worker is copied to public directory
      const pdfjsWorkerSrc = path.join(process.cwd(), "node_modules", "pdfjs-dist", "build", "pdf.worker.min.mjs");
      const publicDir = path.join(process.cwd(), "public", "pdfjs");
      const pdfjsWorkerDest = path.join(publicDir, "pdf.worker.min.mjs");
      
      if (existsSync(pdfjsWorkerSrc)) {
        if (!existsSync(publicDir)) {
          mkdirSync(publicDir, { recursive: true });
        }
        copyFileSync(pdfjsWorkerSrc, pdfjsWorkerDest);
        console.log("✅ Copied PDF.js worker to public/pdfjs/");
      }
    }
    return config;
  },
};

export default nextConfig;
