import type { NextConfig } from "next";

const API_BASE = process.env.CCG_API_BASE ?? "http://localhost:8770";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_BASE}/api/:path*` },
      { source: "/health", destination: `${API_BASE}/health` },
    ];
  },
};

export default nextConfig;
