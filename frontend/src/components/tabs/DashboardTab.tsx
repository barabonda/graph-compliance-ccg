"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchRuns } from "@/lib/api";
import { principleColor, VERDICT_LABELS } from "@/lib/labels";
import type { FinalVerdict, RunSummary } from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState } from "../ui";

interface Props {
  onOpenRun: (run: RunSummary) => void;
  onEditRun?: (run: RunSummary) => void;
}

const VERDICT_ORDER: FinalVerdict[] = ["reject", "revise", "needs_review", "pass_candidate"];

const VERDICT_TONE: Record<string, string> = {
  reject: "var(--reject)",
  revise: "var(--revise)",
  needs_review: "var(--revise)",
  pass_candidate: "var(--pass)",
};

function verdictLabel(verdict: string): string {
  return VERDICT_LABELS[verdict as FinalVerdict]?.[0] ?? verdict ?? "—";
}

function Stat({ label, value, unit, sub, accent }: { label: string; value: string | number; unit?: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-[12px] border border-line bg-surface p-4 shadow-card">
      <div className="text-[11px] font-bold tracking-wider text-ink-4">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="text-[26px] font-extrabold tracking-tight" style={{ color: accent ?? "var(--ink)" }}>
          {value}
        </span>
        {unit ? <span className="text-[13px] font-bold text-ink-3">{unit}</span> : null}
      </div>
      {sub ? <div className="mt-0.5 text-[11.5px] text-ink-3">{sub}</div> : null}
    </div>
  );
}

function BarList({ title, items, color }: { title: string; items: { key: string; value: number; tint?: string }[]; color: string }) {
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <div className="rounded-[12px] border border-line bg-surface p-4 shadow-card">
      <div className="mb-2.5 text-[12.5px] font-bold text-ink">{title}</div>
      {items.length ? (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.key} className="flex items-center gap-2">
              <span className="w-[44%] truncate text-[12px] text-ink-2" title={item.key}>
                {item.key}
              </span>
              <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                <span
                  className="block h-full rounded-full"
                  style={{ width: `${(item.value / max) * 100}%`, background: item.tint ?? color }}
                />
              </span>
              <span className="w-7 text-right font-mono text-[11.5px] font-bold text-ink-3">{item.value}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="py-3 text-[12px] text-ink-4">데이터 없음</div>
      )}
    </div>
  );
}

function topCounts(runs: RunSummary[], pick: (run: RunSummary) => string[], limit = 6): { key: string; value: number }[] {
  const counts = new Map<string, number>();
  for (const run of runs) {
    for (const key of pick(run)) {
      if (!key) continue;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([key, value]) => ({ key, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, limit);
}

function formatTime(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function DashboardTab({ onOpenRun, onEditRun }: Props) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string>("");

  const load = useCallback(async () => {
    setError("");
    try {
      setRuns(await fetchRuns());
    } catch (err) {
      setError(err instanceof Error ? err.message : "실행 기록을 불러오지 못했습니다.");
      setRuns([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchRuns()
      .then((items) => {
        if (!cancelled) setRuns(items);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "실행 기록을 불러오지 못했습니다.");
          setRuns([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (runs === null) return <EmptyState>실행 기록을 불러오는 중…</EmptyState>;

  // 집계는 실제 실행만(데모 시드 제외). 표에는 데모도 표시하되 '데모' 배지로 구분.
  const realRuns = runs.filter((run) => !run.seed);
  const demoCount = runs.length - realRuns.length;
  const total = realRuns.length;
  const count = (verdict: string) => realRuns.filter((run) => run.final_verdict === verdict).length;
  const rejectRate = total ? Math.round((count("reject") / total) * 100) : 0;
  const passRate = total ? Math.round((count("pass_candidate") / total) * 100) : 0;
  const avgIssues = total
    ? (realRuns.reduce((sum, run) => sum + (run.issue_count || 0), 0) / total).toFixed(1)
    : "0";
  const verdictBars = VERDICT_ORDER.map((key) => ({
    key: VERDICT_LABELS[key][0],
    value: count(key),
    tint: VERDICT_TONE[key],
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[18px] font-extrabold tracking-tight text-ink">운영 대시보드</h2>
          <p className="mt-0.5 text-[12px] text-ink-3">
            실행 기록과 집계 · 행을 클릭하면 시점 데이터를 열고, 조건 불러오기로 수정 후 재실행합니다.
            {demoCount ? ` (집계는 실제 실행 ${total}건만 · 데모 ${demoCount}건 제외)` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-bold text-ink-3 hover:border-brand hover:text-brand"
        >
          <Icon name="clock" size={13} /> 새로고침
        </button>
      </div>

      {error ? <div className="rounded-md border border-reject/40 bg-reject-bg px-3 py-2 text-[12.5px] text-reject">{error}</div> : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="총 심사 건수" value={total} unit="건" sub="기록된 실행" />
        <Stat label="반려 권고율" value={rejectRate} unit="%" sub={`${count("reject")}건`} accent="var(--reject)" />
        <Stat label="통과 후보율" value={passRate} unit="%" sub={`${count("pass_candidate")}건`} accent="var(--pass)" />
        <Stat label="건당 평균 위험" value={avgIssues} unit="개" sub="detected issues" accent="var(--revise)" />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <BarList title="라우팅 분포" items={verdictBars} color="var(--brand)" />
        <BarList title="자주 걸리는 원칙" items={topCounts(realRuns, (r) => r.principles).map((i) => ({ ...i, tint: principleColor(i.key) }))} color="var(--brand)" />
        <BarList title="자주 누락되는 필수 고지" items={topCounts(realRuns, (r) => r.missing_disclosures)} color="var(--revise)" />
        <BarList title="자주 걸리는 심의 항목 (CU)" items={topCounts(realRuns, (r) => r.cu_labels ?? [])} color="var(--brand-2)" />
      </div>

      <div className="overflow-hidden rounded-[12px] border border-line bg-surface shadow-card">
        <div className="flex items-center gap-2 border-b border-line px-4 py-2.5 text-[12.5px] font-bold text-ink">
          <Icon name="audit" size={14} color="var(--ink-3)" /> 실행 기록
          <span className="ml-auto text-[11px] font-normal text-ink-4">행 클릭 → 시점 데이터 · 조건 불러오기 → 새 심사</span>
        </div>
        {runs.length ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[12.5px]">
              <thead>
                <tr className="text-[11px] text-ink-4">
                  <th className="px-4 py-2 text-left font-bold">시각</th>
                  <th className="px-4 py-2 text-left font-bold">제목</th>
                  <th className="px-3 py-2 text-left font-bold">실행 조건</th>
                  <th className="px-3 py-2 text-left font-bold">심사자</th>
                  <th className="px-3 py-2 text-left font-bold">모델</th>
                  <th className="px-3 py-2 text-left font-bold">AI 권고</th>
                  <th className="px-3 py-2 text-right font-bold">위험</th>
                  <th className="px-3 py-2 text-right font-bold">오인</th>
                  <th className="px-3 py-2 text-left font-bold">재실행</th>
                  <th className="px-4 py-2 text-left font-bold">ReviewRun</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.id}
                    onClick={() => onOpenRun(run)}
                    className="cursor-pointer border-t border-line hover:bg-surface-2"
                  >
                    <td className="px-4 py-2 whitespace-nowrap text-ink-3">{formatTime(run.ts)}</td>
                    <td className="max-w-[240px] px-4 py-2 font-medium text-ink">
                      <span className="flex items-center gap-1.5">
                        {run.seed ? (
                          <span className="shrink-0 rounded bg-surface-3 px-1.5 py-0.5 text-[10px] font-bold text-ink-3">
                            데모
                          </span>
                        ) : null}
                        <span className="truncate" title={run.title}>
                          {run.title || "(제목 없음)"}
                        </span>
                      </span>
                    </td>
                    <td className="max-w-[230px] px-3 py-2 text-[11.5px] text-ink-3">
                      <div className="truncate" title={`${run.product_group} · ${run.channel}`}>
                        {run.product_group || "auto"} · {run.channel || "channel"}
                      </div>
                      <div className="truncate text-ink-4" title={run.selected_product_name || ""}>
                        {run.selected_product_name ? `상품: ${run.selected_product_name}` : "상품 미선택"}
                      </div>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-ink-3">{run.actor || "—"}</td>
                    <td className="px-3 py-2 whitespace-nowrap font-mono text-[11px] text-ink-3">{run.model || "GPT-5.4-nano"}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className="font-bold" style={{ color: VERDICT_TONE[run.final_verdict] ?? "var(--ink-2)" }}>
                        {verdictLabel(run.final_verdict)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono font-bold text-ink-2">{run.issue_count}</td>
                    <td className="px-3 py-2 text-right font-mono text-[11px] text-ink-3">{run.misleading_verdict || "—"}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          onEditRun?.(run);
                        }}
                        className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-bold text-ink-3 hover:border-brand hover:text-brand"
                      >
                        조건 불러오기
                      </button>
                    </td>
                    <td className="px-4 py-2 font-mono text-[10.5px] text-ink-4">{run.id.slice(0, 22)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-4 py-6 text-[12.5px] text-ink-4">아직 기록된 실행이 없습니다. 새 심사를 실행하면 여기에 쌓입니다.</div>
        )}
      </div>
    </div>
  );
}
