import type { NextRequest } from "next/server";

const API_BASE = process.env.CCG_API_BASE ?? "http://localhost:8770";

/**
 * 이미지 수정안 생성 프록시.
 *
 * 이미지 생성은 45~60초가 걸리는데 Next 의 rewrite 프록시는 그 전에 소켓을
 * 끊어 ECONNRESET(HTTP 500)이 난다 — review/stream 과 같은 이유로 전용 Route
 * Handler 에서 긴 타임아웃으로 직접 중계한다.
 */
export async function POST(request: NextRequest) {
  const upstream = await fetch(`${API_BASE}/api/revision-image`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    signal: AbortSignal.timeout(300_000),
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export const dynamic = "force-dynamic";
export const maxDuration = 300;
