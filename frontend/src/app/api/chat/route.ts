import type { NextRequest } from "next/server";

/**
 * Server-side proxy to the team's Mac mini LLM server (OpenAI-compatible).
 *
 * The browser calls THIS route only — it never sees `LLM_BASE_URL` or
 * `LLM_API_KEY`. The Bearer key stays on the server (Vercel env / .env.local),
 * which avoids key exposure, CORS, and mixed-content problems.
 *
 * Upstream: `POST {LLM_BASE_URL}/v1/chat/completions`, model default
 * `ax-4.0-light` (fast; demo default). `exaone4-32b` is higher quality but slow,
 * and the GPU serves one request at a time so concurrent calls queue.
 *
 * Streaming (`stream: true`) responses are piped through unbuffered.
 */

const DEFAULT_MODEL = "ax-4.0-light";

export async function POST(request: NextRequest) {
  const baseUrl = process.env.LLM_BASE_URL;
  const apiKey = process.env.LLM_API_KEY;
  if (!baseUrl || !apiKey) {
    return Response.json(
      { error: "LLM_BASE_URL / LLM_API_KEY is not configured on the server." },
      { status: 500 },
    );
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Request body must be valid JSON." }, { status: 400 });
  }

  const upstream = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ ...body, model: body.model ?? DEFAULT_MODEL }),
    signal: request.signal,
  });

  // Pass the upstream response straight through (status + body), so a 401 from a
  // bad key, JSON results, and SSE streams all surface unchanged to the client.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") ?? "application/json",
      "Cache-Control": "no-store, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}

export const dynamic = "force-dynamic";
