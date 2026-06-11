"use client";

import { DECISIONS, riskGrade, VERDICT_LABELS, verdictBadgeTone, type DecisionKey } from "@/lib/labels";
import type { ReviewOutput, StreamEvent } from "@/lib/types";
import { Badge } from "../ui";

interface Props {
  status: "idle" | "running" | "done" | "error";
  result: ReviewOutput | null;
  reviewTitle: string;
  events: StreamEvent[];
  decision: DecisionKey | null;
  onDecide: (decision: DecisionKey | null) => void;
}

export function ContextBar({ status, result, reviewTitle, events, decision, onDecide }: Props) {
  const last = events.at(-1);
  const misleading = Number(result?.overall_impression_judgment?.misleading_risk_score ?? 0);
  const grade = riskGrade(misleading);
  const [aiLabel] = result ? (VERDICT_LABELS[result.final_verdict] ?? [result.final_verdict]) : [""];

  return (
    <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-extrabold tracking-tight whitespace-nowrap">
            {reviewTitle || "심사 대기"}
          </span>
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-2.5 text-[11.5px] text-ink-3">
          <span className="font-mono">{result?.review_run_id ?? "run 없음"}</span>
          {status === "running" && (
            <span className="font-semibold text-brand">
              실행 중 · {last?.step ?? "시작"} ({events.length} events)
            </span>
          )}
        </div>
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-3.5">
        {result && (
          <div className="text-right">
            <div className="flex items-center justify-end gap-2">
              <span className="text-[10.5px] font-bold tracking-wider text-ink-4">AI 판정</span>
              <Badge tone={verdictBadgeTone(result.final_verdict)}>{aiLabel}</Badge>
            </div>
            <div className="mt-1 flex items-center justify-end gap-1.5 text-[11px] text-ink-3">
              <span>오인 위험</span>
              <span
                title={`misleading_risk_score ${misleading.toFixed(2)}`}
                className={`font-bold ${grade.tone === "reject" ? "text-reject" : grade.tone === "review" ? "text-revise" : "text-pass"}`}
              >
                {grade.label}
              </span>
            </div>
          </div>
        )}

        <div className="h-9 w-px bg-line" />

        {decision ? (
          <div
            className="flex items-center gap-2 rounded-lg py-1 pr-1.5 pl-3"
            style={{ background: DECISIONS[decision].bg }}
          >
            <div>
              <div className="text-[10px] font-bold text-ink-4">심사자 확정</div>
              <div className="text-[13.5px] font-extrabold" style={{ color: DECISIONS[decision].color }}>
                {DECISIONS[decision].label}
              </div>
            </div>
            <button
              type="button"
              onClick={() => onDecide(null)}
              title="결정 취소"
              className="grid h-6 w-6 place-items-center rounded-md bg-white/70 text-ink-3"
            >
              ✕
            </button>
          </div>
        ) : (
          <div className="flex gap-1.5">
            {(Object.keys(DECISIONS) as DecisionKey[]).map((key) => {
              const item = DECISIONS[key];
              const primary = key === "reject";
              return (
                <button
                  key={key}
                  type="button"
                  disabled={!result}
                  onClick={() => onDecide(key)}
                  className="rounded-lg px-3.5 py-2 text-[13px] font-bold whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-40"
                  style={
                    primary
                      ? { background: item.color, color: "#fff", boxShadow: "0 3px 10px rgba(214,69,58,.28)" }
                      : { background: item.bg, color: item.color, border: `1px solid ${item.color}40` }
                  }
                >
                  {item.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </header>
  );
}
