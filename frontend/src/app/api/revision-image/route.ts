import type { NextRequest } from "next/server";

const API_BASE = process.env.CCG_API_BASE ?? "http://localhost:8770";

/**
 * 이미지 수정안 생성 프록시.
 *
 * gpt-image edit 는 콜아웃이 많으면 수 분이 걸린다. Next 의 rewrite 프록시는
 * 그 전에 소켓을 끊어 ECONNRESET(HTTP 500)이 나므로 전용 Route Handler 에서
 * 긴 타임아웃으로 직접 중계한다. 백엔드 단일 시도 타임아웃(기본 480s)보다
 * 살짝 길게 잡아, 백엔드의 정식 에러/응답이 프록시 중단보다 먼저 오게 한다.
 */
export async function POST(request: NextRequest) {
  const upstream = await fetch(`${API_BASE}/api/revision-image`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    signal: AbortSignal.timeout(540_000),
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

export const dynamic = "force-dynamic";
export const maxDuration = 540;
