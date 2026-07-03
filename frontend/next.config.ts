import type { NextConfig } from "next";

const API_BASE = process.env.CCG_API_BASE ?? "http://localhost:8770";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      // /api/copilotkit 는 이 앱의 라우트 핸들러(동적 [[...slug]])가 처리한다.
      // afterFiles rewrite 는 동적 라우트보다 먼저 평가되므로 여기서 제외하지
      // 않으면 코파일럿 런타임 요청이 FastAPI 로 프록시되어 404 가 난다.
      { source: "/api/:path((?!copilotkit).*)", destination: `${API_BASE}/api/:path` },
      { source: "/health", destination: `${API_BASE}/health` },
    ];
  },
};

export default nextConfig;
