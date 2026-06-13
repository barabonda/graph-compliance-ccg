import type { NextRequest } from "next/server";

const API_BASE = process.env.CCG_API_BASE ?? "http://localhost:8770";

/**
 * Stream the review NDJSON straight through from the FastAPI backend.
 *
 * The Next.js dev rewrite proxy buffers large mid-stream chunks (e.g. the
 * hierarchical-context-extraction event for long ads), so the browser stops
 * receiving events even though the backend keeps emitting them. Piping the
 * upstream ReadableStream through an explicit Route Handler preserves
 * incremental delivery for arbitrarily large lines.
 */
export async function POST(request: NextRequest) {
  const upstream = await fetch(`${API_BASE}/api/review/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    // @ts-expect-error — Node fetch duplex flag, required when streaming a body
    duplex: "half",
    signal: request.signal,
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}

export const dynamic = "force-dynamic";
