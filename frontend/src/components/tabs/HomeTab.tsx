"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchRuns } from "@/lib/api";
import { CHANNELS, EXAMPLES, PRODUCT_GROUPS, VERDICT_LABELS } from "@/lib/labels";
import type { FinalVerdict, ReviewOutput, ReviewRequest, RunSummary, StreamEvent } from "@/lib/types";
import { Icon } from "../Icon";

interface Props {
  status: "idle" | "running" | "done" | "error";
  result: ReviewOutput | null;
  events: StreamEvent[];
  onNewReview: () => void;
  onDashboard: () => void;
  onOpenRun: (run: RunSummary) => void;
  onEditRun: (run: RunSummary) => void;
  onUsePreset: (preset: Partial<ReviewRequest>) => void;
}

const VERDICT_TONE: Record<string, string> = {
  reject: "var(--reject)",
  revise: "var(--revise)",
  needs_review: "var(--revise)",
  pass_candidate: "var(--pass)",
};

function verdictLabel(verdict: string): string {
  return VERDICT_LABELS[verdict as FinalVerdict]?.[0] ?? verdict ?? "—";
}

function formatTime(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function groupLabel(value: string): string {
  return PRODUCT_GROUPS.find((item) => item.value === value)?.label ?? value;
}

function channelLabel(value: string): string {
  return CHANNELS.find((item) => item.value === value)?.label ?? value;
}

export function HomeTab({
  status,
  result,
  events,
  onNewReview,
  onDashboard,
  onOpenRun,
  onEditRun,
  onUsePreset,
}: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      setRuns((await fetchRuns()).filter((run) => !run.seed).slice(0, 5));
    } catch (err) {
      setError(err instanceof Error ? err.message : "최근 실행 기록을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchRuns()
      .then((items) => {
        if (!cancelled) setRuns(items.filter((run) => !run.seed).slice(0, 5));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "최근 실행 기록을 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const lastStep = events.at(-1)?.step ?? "대기 중";
  const running = status === "running";

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <section className="rounded-[18px] border border-line bg-surface p-6 shadow-card">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-brand-tint px-3 py-1 text-[12px] font-extrabold text-brand-2">
              <Icon name="shield" size={14} /> JB Compliance Agent
            </div>
            <h1 className="text-[28px] font-extrabold tracking-tight text-ink">금융광고 사전심의 홈</h1>
            <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-ink-3">
              새 초안을 접수하고, 진행 중인 심사 상태를 확인하고, 완료된 실행 조건을 다시 불러와 수정 후 재심사합니다.
              여러 초안은 새 심사에서 대기열로 쌓아 순차 처리할 수 있습니다.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onNewReview}
              className="rounded-md bg-brand px-4 py-2.5 text-sm font-bold text-white shadow-sm hover:bg-brand/90"
            >
              새 심사 하러가기
            </button>
            <button
              type="button"
              onClick={onDashboard}
              className="rounded-md border border-line bg-surface px-4 py-2.5 text-sm font-bold text-ink-2 hover:border-brand hover:text-brand"
            >
              실행 기록 보기
            </button>
          </div>
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-[1.05fr_.95fr]">
        <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[15px] font-extrabold text-ink">심사 상태</h2>
            <span
              className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${
                running ? "bg-revise-bg text-revise" : "bg-surface-3 text-ink-3"
              }`}
            >
              {running ? "심사 중" : status === "done" ? "최근 심사 완료" : "대기"}
            </span>
          </div>
          {running ? (
            <div className="rounded-[12px] border border-revise/30 bg-revise-bg p-4">
              <div className="text-[13px] font-bold text-ink">현재 단계: {lastStep}</div>
              <div className="mt-1 text-[12px] text-ink-3">완료되면 심사 콘솔에서 결과를 열 수 있습니다.</div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-surface">
                <span className="block h-full w-2/3 animate-pulse rounded-full bg-revise" />
              </div>
            </div>
          ) : result ? (
            <div className="rounded-[12px] border border-line bg-surface-2 p-4">
              <div className="text-[12px] font-bold text-ink-4">최근 결과</div>
              <div className="mt-1 flex items-center gap-2">
                <span className="text-[18px] font-extrabold" style={{ color: VERDICT_TONE[result.final_verdict] ?? "var(--ink)" }}>
                  {verdictLabel(result.final_verdict)}
                </span>
                <span className="font-mono text-[11px] text-ink-4">{result.review_run_id}</span>
              </div>
              <button
                type="button"
                onClick={() => onDashboard()}
                className="mt-3 rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-bold text-ink-3 hover:border-brand hover:text-brand"
              >
                기록에서 확인
              </button>
            </div>
          ) : (
            <div className="rounded-[12px] border border-dashed border-line bg-surface-2 p-4 text-[12.5px] text-ink-3">
              아직 진행 중인 심사가 없습니다. 새 심사에서 초안을 넣거나 대기열에 여러 초안을 추가하세요.
            </div>
          )}
        </section>

        <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
          <div className="mb-3">
            <h2 className="text-[15px] font-extrabold text-ink">빠른 시나리오</h2>
            <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink-4">
              데모용 초안을 불러와 바로 심사를 시작합니다.
            </p>
          </div>

          <div className="grid gap-2">
            {EXAMPLES.map((example) => (
              <button
                key={example.label}
                type="button"
                onClick={() =>
                  onUsePreset({
                    title: example.title,
                    content_text: example.text,
                    channel: example.channel,
                    product_group: example.product,
                    selected_product_name: example.selectedProduct || undefined,
                    image_url: example.imageUrl,
                  })
                }
                className="rounded-[11px] border border-line bg-surface-2 p-3 text-left hover:border-brand hover:bg-brand-tint"
              >
                <span className="block text-[13px] font-extrabold text-ink">{example.label}</span>
                <span className="mt-1 block text-[11px] text-ink-4">
                  {groupLabel(example.product)} · {channelLabel(example.channel)}
                  {example.selectedProduct ? ` · ${example.selectedProduct}` : ""}
                </span>
                <span className="mt-1 line-clamp-2 block text-[11.5px] leading-relaxed text-ink-3">
                  {example.text || (example.imageUrl ? "배너 이미지 접수 — VLM이 문안·레이아웃을 추출해 심사하고 이미지 수정안까지 생성합니다." : "")}
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-[15px] font-extrabold text-ink">최근 심사</h2>
            <p className="mt-0.5 text-[11.5px] text-ink-4">완료된 실행은 조건을 불러와 바로 수정·재심사할 수 있습니다.</p>
          </div>
          <button type="button" onClick={() => void load()} className="text-[12px] font-bold text-ink-4 hover:text-brand">
            새로고침
          </button>
        </div>
        {error ? <div className="rounded-md border border-reject/30 bg-reject-bg px-3 py-2 text-[12px] text-reject">{error}</div> : null}
        {runs.length ? (
          <div className="grid gap-2 lg:grid-cols-2">
            {runs.map((run) => (
              <div key={run.id} className="rounded-[11px] border border-line bg-surface-2 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[13px] font-extrabold text-ink">{run.title || "(제목 없음)"}</div>
                    <div className="mt-1 truncate text-[11px] text-ink-4">
                      {formatTime(run.ts)} · {groupLabel(run.product_group)} · {channelLabel(run.channel)}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-ink-4">
                      {run.selected_product_name ? `상품 ${run.selected_product_name}` : "상품 미선택"}
                    </div>
                  </div>
                  <span className="shrink-0 text-[12px] font-extrabold" style={{ color: VERDICT_TONE[run.final_verdict] ?? "var(--ink)" }}>
                    {verdictLabel(run.final_verdict)}
                  </span>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => onOpenRun(run)}
                    className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] font-bold text-ink-3 hover:border-brand hover:text-brand"
                  >
                    결과 열기
                  </button>
                  <button
                    type="button"
                    onClick={() => onEditRun(run)}
                    className="rounded-md bg-ink px-2.5 py-1.5 text-[12px] font-bold text-white hover:bg-ink/90"
                  >
                    조건 불러오기
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-[12px] border border-dashed border-line bg-surface-2 px-4 py-6 text-center text-[12.5px] text-ink-4">
            아직 완료된 심사 기록이 없습니다.
          </div>
        )}
      </section>
    </div>
  );
}
