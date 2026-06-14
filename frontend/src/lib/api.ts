import type { ProductSearchResult, ReviewOutput, ReviewRequest, RunSummary, StreamEvent } from "./types";

export class ReviewApiError extends Error {
  readonly code: string;
  readonly cause?: string;

  constructor(code: string, message: string, cause?: string) {
    super(message);
    this.name = "ReviewApiError";
    this.code = code;
    this.cause = cause;
  }
}

async function parseErrorResponse(response: Response): Promise<ReviewApiError> {
  const fallback = `HTTP ${response.status} ${response.statusText}`;
  const text = await response.text();
  try {
    const payload = JSON.parse(text);
    const detail = payload.detail ?? payload;
    if (typeof detail === "string") return new ReviewApiError("review_failed", `${fallback}: ${detail}`);
    return new ReviewApiError(
      String(detail.error ?? "review_failed"),
      String(detail.message ?? "심사 워크플로우가 완료되지 못했습니다."),
      detail.cause ? String(detail.cause) : undefined,
    );
  } catch {
    return new ReviewApiError("review_failed", text ? `${fallback}: ${text}` : fallback);
  }
}

export function streamErrorToApiError(event: StreamEvent): ReviewApiError {
  const detail = event.detail ?? {};
  return new ReviewApiError(
    String(detail.error ?? event.error ?? "review_failed"),
    String(detail.message ?? event.summary ?? "심사 워크플로우가 완료되지 못했습니다."),
    detail.cause ? String(detail.cause) : undefined,
  );
}

/**
 * Consume `POST /api/review/stream` (NDJSON) and surface each workflow event.
 * Throws `ReviewApiError` on transport errors or in-stream error events.
 */
export async function streamReview(
  payload: ReviewRequest,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/review/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  if (!response.body) {
    throw new ReviewApiError("stream_not_available", "이 브라우저에서 응답 스트림을 읽을 수 없습니다.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line) as StreamEvent;
    onEvent(event);
    if (event.event === "error") {
      throw streamErrorToApiError(event);
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) dispatch(line);
  }
  buffer += decoder.decode();
  dispatch(buffer);
}

/** 운영 대시보드: 최근 실행 요약 목록. */
export async function fetchRuns(): Promise<RunSummary[]> {
  const response = await fetch("/api/runs", { cache: "no-store" });
  if (!response.ok) throw await parseErrorResponse(response);
  const data = (await response.json()) as { runs?: RunSummary[] };
  return data.runs ?? [];
}

/** 저장된 실행의 시점 데이터(전체 ReviewOutput) — 디버깅용. */
export async function fetchRun(id: string): Promise<ReviewOutput> {
  const response = await fetch(`/api/runs/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!response.ok) throw await parseErrorResponse(response);
  return (await response.json()) as ReviewOutput;
}

export async function searchProducts(
  query: string,
  productGroup: string,
  signal?: AbortSignal,
): Promise<ProductSearchResult[]> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (productGroup) params.set("product_group", productGroup);
  params.set("limit", "12");
  const response = await fetch(`/api/products/search?${params.toString()}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw await parseErrorResponse(response);
  const data = (await response.json()) as { products?: ProductSearchResult[] };
  return data.products ?? [];
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}
