"use client";

import { useEffect, useRef, useState } from "react";
import type { StreamEvent } from "@/lib/types";

// review_events가 내보내는 step_started 단계 수(workflow.py). 단계가 늘면
// 실제 본 수로 보정한다.
const PIPELINE_TOTAL = 18;

export function PipelineProgress({ events }: { events: StreamEvent[] }) {
  const completed = new Set(
    events.filter((e) => e.event === "step_completed" && e.step).map((e) => e.step),
  ).size;
  const startedNames = events.filter((e) => e.event === "step_started" && e.step).map((e) => e.step as string);
  const total = Math.max(PIPELINE_TOTAL, new Set(startedNames).size);
  const finished = events.some((e) => e.event === "result" || e.event === "error");
  const current = !finished ? startedNames[startedNames.length - 1] : null;
  const pct = finished ? 100 : Math.min(99, Math.round((completed / total) * 100));

  const startRef = useRef<number>(Date.now());
  const [now, setNow] = useState<number>(Date.now());
  useEffect(() => {
    if (finished) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [finished]);

  const elapsed = Math.max(0, Math.round((now - startRef.current) / 1000));
  const eta = !finished && completed > 0 ? Math.round((elapsed * (total - completed)) / completed) : null;
  const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

  return (
    <div className="mb-3 rounded-[10px] border border-line bg-surface-2 px-3.5 py-3">
      <div className="mb-1.5 flex items-center justify-between text-[12px]">
        <span className="font-bold" style={{ color: finished ? "var(--pass)" : "var(--brand-2)" }}>
          {finished ? "분석 완료" : "분석 진행 중"}
        </span>
        <span className="text-ink-3">
          {completed}/{total} 단계 · {pct}%
          {eta != null ? ` · 예상 잔여 ~${mmss(eta)}` : ""}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-3">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: finished ? "var(--pass)" : "var(--brand)" }}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[11px] text-ink-4">
        <span>{current ? `현재 단계: ${current}` : finished ? "모든 단계 완료" : "시작 중…"}</span>
        <span>경과 {mmss(elapsed)}</span>
      </div>
    </div>
  );
}
