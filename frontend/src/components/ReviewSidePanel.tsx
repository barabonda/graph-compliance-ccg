"use client";

import { useEffect, useState } from "react";
import { fetchRuns } from "@/lib/api";
import type { RunSummary } from "@/lib/types";
import { Icon } from "./Icon";

interface Props {
  onOpenRun: (run: RunSummary) => void;
  /** 새 실행이 끝나면 목록을 갱신하기 위한 신호(예: review_run_id). */
  refreshKey?: string;
}

const PIPELINE = [
  { n: 1, title: "문안 구조 분석", sub: "제목·본문·고지 영역 분리" },
  { n: 2, title: "표현(Claim) 추출", sub: "심의 대상 주장 식별" },
  { n: 3, title: "심의 기준 매칭", sub: "정책 그래프에서 후보 기준 검색" },
  { n: 4, title: "판정", sub: "기준 대조 · 위반 여부 판단" },
  { n: 5, title: "예외 · 완화 검토", sub: "조건 고지 · 맥락 완화 평가" },
  { n: 6, title: "수정안 생성", sub: "안전한 대체 문안 작성" },
];

const VERDICT_BADGE: Record<string, { label: string; color: string; bg: string }> = {
  reject: { label: "반려", color: "var(--reject)", bg: "var(--reject-bg)" },
  revise: { label: "수정 요청", color: "var(--revise)", bg: "var(--revise-bg)" },
  needs_review: { label: "검토 필요", color: "var(--brand-2)", bg: "var(--brand-tint)" },
  pass_candidate: { label: "자동 통과", color: "var(--pass)", bg: "var(--pass-bg)" },
};

function relativeTime(ts: number): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "방금 전";
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`;
  return `${Math.floor(diff / 86400)}일 전`;
}

export function ReviewSidePanel({ onOpenRun, refreshKey }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);

  useEffect(() => {
    let alive = true;
    fetchRuns()
      .then((list) => alive && setRuns(list))
      .catch(() => alive && setRuns([]));
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
        <div className="mb-3 flex items-center gap-2 text-[13px] font-bold text-ink">
          <Icon name="layers" size={15} color="var(--ink-3)" /> 분석 파이프라인
        </div>
        <ol className="space-y-2.5">
          {PIPELINE.map((step) => (
            <li key={step.n} className="flex gap-2.5">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-surface-3 text-[11px] font-bold text-ink-3">
                {step.n}
              </span>
              <div className="min-w-0">
                <div className="text-[12.5px] font-bold text-ink">{step.title}</div>
                <div className="text-[11px] text-ink-4">{step.sub}</div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
        <div className="mb-3 flex items-center gap-2 text-[13px] font-bold text-ink">
          <Icon name="review" size={15} color="var(--ink-3)" /> 최근 접수
          <span className="ml-auto text-[11px] font-normal text-ink-4">접수함 {runs.length}건</span>
        </div>
        {runs.length ? (
          <ul className="space-y-1.5">
            {runs.slice(0, 6).map((run) => {
              const badge = VERDICT_BADGE[run.final_verdict] ?? { label: run.final_verdict, color: "var(--ink-3)", bg: "var(--surface-3)" };
              return (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => onOpenRun(run)}
                    className="flex w-full items-center gap-2 rounded-lg border border-transparent px-2 py-2 text-left hover:border-line hover:bg-surface-2"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        {run.seed ? (
                          <span className="shrink-0 rounded bg-surface-3 px-1 text-[9.5px] font-bold text-ink-4">데모</span>
                        ) : null}
                        <span className="truncate text-[12.5px] font-bold text-ink" title={run.title}>
                          {run.title || "(제목 없음)"}
                        </span>
                      </span>
                      <span className="mt-0.5 block truncate text-[11px] text-ink-4">
                        {run.actor ? `${run.actor} · ` : ""}
                        {relativeTime(run.ts)}
                      </span>
                    </span>
                    <span
                      className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold"
                      style={{ color: badge.color, background: badge.bg }}
                    >
                      {badge.label}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="py-3 text-[12px] text-ink-4">아직 접수된 실행이 없습니다.</div>
        )}
      </section>

      <div className="flex items-start gap-2 rounded-[14px] border border-line bg-surface-2 px-4 py-3 text-[11.5px] leading-relaxed text-ink-3">
        <Icon name="shield" size={15} color="var(--ink-4)" style={{ marginTop: 1 }} />
        <span>
          AI 사전심의 결과는 <strong className="text-ink-2">보조 자료</strong>이며, 최종 심의 책임은 심사자에게
          있습니다. 모든 판정은 근거 조항 원문까지 추적할 수 있습니다.
        </span>
      </div>
    </div>
  );
}
