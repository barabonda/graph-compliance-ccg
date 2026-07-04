"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchEvalReport, fetchEvalReports } from "@/lib/api";
import type { EvalReportDetail, EvalReportSummary } from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState } from "../ui";

function formatTime(ts: number): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function pct(value?: number): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function f1Tone(value?: number): string {
  if (value == null) return "var(--ink-4)";
  if (value >= 0.7) return "var(--pass)";
  if (value >= 0.45) return "var(--revise)";
  return "var(--reject)";
}

function MetricCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="rounded-[10px] border border-line bg-surface p-3">
      <div className="text-[11px] font-bold tracking-wider text-ink-4">{label}</div>
      <div className="mt-0.5 text-[20px] font-extrabold tracking-tight" style={{ color: accent ?? "var(--ink)" }}>
        {value}
      </div>
      {sub ? <div className="text-[11px] text-ink-4">{sub}</div> : null}
    </div>
  );
}

/** JSON metrics 리포트 상세 — 핵심 지표 카드 + 조문별 정밀도/재현율 표. */
function MetricsDetail({ content }: { content: Record<string, unknown> }) {
  const recordCount = content.record_count as number | undefined;
  const metrics = (content.article_metrics as Record<string, unknown> | undefined) ?? undefined;
  const ccg = (content.ccg_metrics as Record<string, unknown> | undefined) ?? undefined;
  const counts = (metrics?.counts as Record<string, number> | undefined) ?? undefined;
  const perArticle = (metrics?.per_article as Record<string, Record<string, number>> | undefined) ?? undefined;
  const num = (v: unknown) => (typeof v === "number" ? v : undefined);

  if (!metrics && !ccg) {
    // metrics-shape 가 아닌 JSON — 원문 그대로.
    return (
      <pre className="max-h-[60vh] overflow-auto rounded-[10px] border border-line bg-surface-2 p-3 text-[11.5px] leading-relaxed text-ink-2">
        {JSON.stringify(content, null, 2)}
      </pre>
    );
  }

  const articleRows = perArticle
    ? Object.entries(perArticle)
        .map(([article, m]) => ({
          article,
          tp: m.tp ?? 0,
          fp: m.fp ?? 0,
          fn: m.fn ?? 0,
          f1: m.f1,
          f2: m.f2,
        }))
        .sort((a, b) => b.tp + b.fn - (a.tp + a.fn))
    : [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="레코드" value={String(recordCount ?? "—")} sub="평가 케이스" />
        <MetricCard label="Micro F1" value={pct(num(metrics?.micro_f1))} accent={f1Tone(num(metrics?.micro_f1))} />
        <MetricCard label="Macro F1" value={pct(num(metrics?.macro_f1))} accent={f1Tone(num(metrics?.macro_f1))} />
        <MetricCard label="Micro F2" value={pct(num(metrics?.micro_f2))} sub="재현율 가중" />
        <MetricCard label="Macro F2" value={pct(num(metrics?.macro_f2))} sub="재현율 가중" />
        <MetricCard
          label="MCC"
          value={num(metrics?.mcc) != null ? num(metrics?.mcc)!.toFixed(3) : "—"}
          sub="상관계수"
        />
      </div>

      {counts ? (
        <div className="flex flex-wrap gap-2 text-[12px]">
          {(
            [
              ["TP", counts.tp, "var(--pass)"],
              ["FP", counts.fp, "var(--reject)"],
              ["FN", counts.fn, "var(--revise)"],
              ["TN", counts.tn, "var(--ink-4)"],
            ] as const
          ).map(([label, value, color]) => (
            <span key={label} className="rounded-md border border-line bg-surface px-2.5 py-1 font-bold">
              <span style={{ color }}>{label}</span> <span className="font-mono text-ink-2">{value ?? 0}</span>
            </span>
          ))}
        </div>
      ) : null}

      {ccg ? (
        <div className="rounded-[10px] border border-line bg-surface-2 p-3">
          <div className="mb-1.5 text-[11px] font-bold tracking-wider text-ink-4">CCG 지표</div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
            {Object.entries(ccg)
              .filter(([, v]) => typeof v === "number")
              .map(([k, v]) => (
                <span key={k}>
                  <span className="text-ink-4">{k}</span>{" "}
                  <b className="font-mono">{(v as number) <= 1 ? pct(v as number) : (v as number).toFixed(2)}</b>
                </span>
              ))}
          </div>
        </div>
      ) : null}

      {articleRows.length ? (
        <div className="overflow-hidden rounded-[10px] border border-line">
          <div className="border-b border-line bg-surface-2 px-3 py-2 text-[12px] font-bold text-ink-2">
            조문별 정밀도/재현율 ({articleRows.length})
          </div>
          <div className="max-h-[40vh] overflow-auto">
            <table className="w-full border-collapse text-[12px]">
              <thead className="sticky top-0 bg-surface">
                <tr className="text-[11px] text-ink-4">
                  <th className="px-3 py-1.5 text-left font-bold">조문</th>
                  <th className="px-2 py-1.5 text-right font-bold">TP</th>
                  <th className="px-2 py-1.5 text-right font-bold">FP</th>
                  <th className="px-2 py-1.5 text-right font-bold">FN</th>
                  <th className="px-2 py-1.5 text-right font-bold">F1</th>
                  <th className="px-2 py-1.5 text-right font-bold">F2</th>
                </tr>
              </thead>
              <tbody>
                {articleRows.map((row) => (
                  <tr key={row.article} className="border-t border-line">
                    <td className="max-w-[280px] px-3 py-1.5 break-keep text-ink-2" title={row.article}>
                      {row.article}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-pass">{row.tp ?? 0}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-reject">{row.fp ?? 0}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-revise">{row.fn ?? 0}</td>
                    <td className="px-2 py-1.5 text-right font-mono font-bold" style={{ color: f1Tone(row.f1) }}>
                      {pct(row.f1)}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-ink-3">{pct(row.f2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** 운영 대시보드 '평가 로그' 서브탭 — eval/ 리포트 목록 + 지표 상세. */
export function EvalPanel() {
  const [reports, setReports] = useState<EvalReportSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvalReportDetail | null>(null);
  const [error, setError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const items = await fetchEvalReports();
      setReports(items);
      setSelected((prev) => prev ?? items[0]?.name ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "평가 리포트를 불러오지 못했습니다.");
      setReports([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    fetchEvalReport(selected)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "리포트 상세를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  if (reports === null) return <EmptyState>평가 리포트를 불러오는 중…</EmptyState>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-ink-3">
          <b className="text-ink-2">eval/</b> 디렉토리의 평가 리포트 — 합성 데이터셋 심사 결과의 유형별·조문별 정밀도/재현율
          로그입니다.
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-bold text-ink-3 hover:border-brand hover:text-brand"
        >
          <Icon name="clock" size={13} /> 새로고침
        </button>
      </div>

      {error ? (
        <div className="rounded-md border border-reject/40 bg-reject-bg px-3 py-2 text-[12.5px] text-reject">{error}</div>
      ) : null}

      {reports.length === 0 ? (
        <div className="rounded-[10px] border border-line bg-surface px-4 py-6 text-[12.5px] text-ink-4">
          아직 평가 리포트가 없습니다. 평가 스윕을 실행하면 eval/ 에 리포트가 쌓이고 여기에 표시됩니다.
        </div>
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: "300px minmax(0,1fr)" }}>
          {/* 좌: 리포트 목록 */}
          <div className="flex max-h-[calc(100vh-260px)] flex-col gap-1.5 overflow-y-auto">
            {reports.map((report) => {
              const isSelected = report.name === selected;
              return (
                <button
                  key={report.name}
                  type="button"
                  onClick={() => setSelected(report.name)}
                  className="rounded-[10px] border px-3 py-2.5 text-left transition"
                  style={{
                    borderColor: isSelected ? "var(--brand)" : "var(--line)",
                    background: isSelected ? "var(--brand-tint)" : "var(--surface)",
                  }}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="rounded bg-surface-3 px-1.5 py-px text-[10px] font-bold text-ink-3 uppercase">
                      {report.kind}
                    </span>
                    <span className="truncate text-[12.5px] font-bold text-ink" title={report.name}>
                      {report.name}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-4">
                    <span>{formatTime(report.mtime)}</span>
                    <span>·</span>
                    <span>{formatSize(report.size)}</span>
                    {report.record_count != null ? (
                      <>
                        <span>·</span>
                        <span>{report.record_count}건</span>
                      </>
                    ) : null}
                  </div>
                  {report.metrics?.micro_f1 != null ? (
                    <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] font-bold">
                      <span style={{ color: f1Tone(report.metrics.micro_f1) }}>F1 {pct(report.metrics.micro_f1)}</span>
                      {report.metrics.mcc != null ? (
                        <span className="text-ink-4">MCC {report.metrics.mcc.toFixed(2)}</span>
                      ) : null}
                    </div>
                  ) : null}
                </button>
              );
            })}
          </div>

          {/* 우: 선택 리포트 상세 */}
          <div className="min-h-0 overflow-y-auto rounded-[12px] border border-line bg-surface p-4 shadow-card">
            {detailLoading ? (
              <div className="py-6 text-[12.5px] text-ink-4">불러오는 중…</div>
            ) : detail?.kind === "md" ? (
              <pre className="max-h-[60vh] overflow-auto rounded-[10px] border border-line bg-surface-2 p-3 text-[12px] leading-relaxed whitespace-pre-wrap break-keep text-ink-2">
                {detail.text}
              </pre>
            ) : detail?.content ? (
              <MetricsDetail content={detail.content} />
            ) : (
              <div className="py-6 text-[12.5px] text-ink-4">왼쪽에서 리포트를 선택하세요.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
