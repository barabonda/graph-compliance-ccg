"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchEvalReport, fetchEvalReports } from "@/lib/api";
import { verdictColor, VERDICT_LABELS } from "@/lib/labels";
import type {
  EvalReportDetail,
  EvalReportSummary,
  EvalVerdictCounts,
  FinalVerdict,
  GoldEvalReport,
  JbLiveEvalReport,
} from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState } from "../ui";

const VERDICT_ORDER: FinalVerdict[] = ["reject", "revise", "needs_review", "pass_candidate"];

function verdictLabel(verdict: string): string {
  return VERDICT_LABELS[verdict as FinalVerdict]?.[0] ?? verdict ?? "—";
}

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

/** 요약 카드가 JB 실제광고 로그(정답 라벨 없음)인지. */
function isLiveSummary(report: EvalReportSummary): boolean {
  return report.kind === "jbbank_live_eval" || report.gold_available === false;
}

/** 상세 본문이 JB 실제광고 로그인지. */
function isLiveContent(content: unknown): content is JbLiveEvalReport {
  if (!content || typeof content !== "object") return false;
  const c = content as Record<string, unknown>;
  return c.kind === "jbbank_live_eval" || c.gold_available === false;
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

/** 판정 분포 막대 — 판정 5종 색으로. */
function VerdictBars({ counts }: { counts?: EvalVerdictCounts }) {
  const rows = VERDICT_ORDER.map((key) => ({ key, value: Number(counts?.[key] ?? 0) }));
  const extraKeys = counts
    ? Object.keys(counts).filter((k) => !VERDICT_ORDER.includes(k as FinalVerdict))
    : [];
  for (const key of extraKeys) rows.push({ key: key as FinalVerdict, value: Number(counts?.[key] ?? 0) });
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.key} className="flex items-center gap-2">
          <span className="w-[92px] shrink-0 text-[12px] font-bold" style={{ color: verdictColor(row.key) }}>
            {verdictLabel(row.key)}
          </span>
          <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-surface-3">
            <span
              className="block h-full rounded-full"
              style={{ width: `${(row.value / max) * 100}%`, background: verdictColor(row.key) }}
            />
          </span>
          <span className="w-7 text-right font-mono text-[11.5px] font-bold text-ink-3">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * 합성 gold 리포트 상세 — 확정 계약 필드(metrics/counts/ccg_metrics)만 표시.
 * summary(목록 응답)와 content(원본 JSON) 중 존재하는 쪽에서 값을 읽는다.
 */
function GoldMetricsDetail({ summary, content }: { summary?: EvalReportSummary; content?: GoldEvalReport }) {
  const metrics = summary?.metrics ?? content?.metrics;
  const counts = summary?.counts ?? content?.counts;
  const ccg = summary?.ccg_metrics ?? content?.ccg_metrics;
  const recordCount = summary?.record_count ?? content?.record_count;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
        <MetricCard label="레코드" value={String(recordCount ?? "—")} sub="평가 케이스" />
        <MetricCard label="위반 정밀도" value={pct(ccg?.violation_precision)} accent={f1Tone(ccg?.violation_precision)} sub="violation precision" />
        <MetricCard label="위반 재현율" value={pct(ccg?.violation_recall)} accent={f1Tone(ccg?.violation_recall)} sub="violation recall" />
        <MetricCard
          label="MCC"
          value={metrics?.mcc != null ? metrics.mcc.toFixed(3) : "—"}
          sub="상관계수"
        />
        <MetricCard label="Micro F1" value={pct(metrics?.micro_f1)} accent={f1Tone(metrics?.micro_f1)} />
        <MetricCard label="Macro F1" value={pct(metrics?.macro_f1)} accent={f1Tone(metrics?.macro_f1)} />
        <MetricCard label="Micro F2" value={pct(metrics?.micro_f2)} sub="재현율 가중" />
        <MetricCard label="Macro F2" value={pct(metrics?.macro_f2)} sub="재현율 가중" />
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

      {ccg && (ccg.overblocking_rate != null || ccg.clean_non_pass_rate != null) ? (
        <div className="rounded-[10px] border border-line bg-surface-2 p-3">
          <div className="mb-1.5 text-[11px] font-bold tracking-wider text-ink-4">과차단 지표</div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
            {ccg.overblocking_rate != null ? (
              <span>
                <span className="text-ink-4">과차단율(overblocking)</span> <b className="font-mono">{pct(ccg.overblocking_rate)}</b>
              </span>
            ) : null}
            {ccg.clean_non_pass_rate != null ? (
              <span>
                <span className="text-ink-4">클린 오탐률(clean non-pass)</span> <b className="font-mono">{pct(ccg.clean_non_pass_rate)}</b>
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {content ? (
        <details className="rounded-[10px] border border-line bg-surface-2">
          <summary className="cursor-pointer px-3 py-2 text-[12px] font-bold text-ink-3">원본 JSON 보기</summary>
          <pre className="max-h-[40vh] overflow-auto border-t border-line p-3 text-[11.5px] leading-relaxed text-ink-2">
            {JSON.stringify(content, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

/** JB 실제광고 라이브 로그 상세 — 판정 분포 + 레코드 테이블(run_id 딥링크). */
function JbLiveDetail({ report, onOpenRunId }: { report: JbLiveEvalReport; onOpenRunId?: (runId: string) => void }) {
  const records = report.records ?? [];
  const productGroups = report.product_group_counts
    ? Object.entries(report.product_group_counts).sort((a, b) => b[1] - a[1])
    : [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-revise/40 bg-revise-bg px-2.5 py-1 text-[11.5px] font-bold text-revise">
          실제 광고 — 정답 라벨 없음(판정 로그)
        </span>
        {report.batch ? <span className="font-mono text-[11px] text-ink-4">{report.batch}</span> : null}
        {report.generated_at ? <span className="text-[11px] text-ink-4">{formatTime(report.generated_at)}</span> : null}
      </div>

      {report.note ? (
        <div className="rounded-[10px] border border-line bg-surface-2 px-3 py-2 text-[12px] leading-relaxed text-ink-3">
          {report.note}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2 text-[12px]">
        {report.record_count != null ? (
          <span className="rounded-md border border-line bg-surface px-2.5 py-1 font-bold">
            <span className="text-ink-4">레코드</span> <span className="font-mono text-ink-2">{report.record_count}</span>
          </span>
        ) : null}
        {report.flagged_count != null ? (
          <span className="rounded-md border border-line bg-surface px-2.5 py-1 font-bold">
            <span className="text-ink-4">검출</span> <span className="font-mono text-reject">{report.flagged_count}</span>
          </span>
        ) : null}
        {productGroups.map(([group, value]) => (
          <span key={group} className="rounded-md border border-line bg-surface px-2.5 py-1 font-bold">
            <span className="text-ink-4">{group}</span> <span className="font-mono text-ink-2">{value}</span>
          </span>
        ))}
      </div>

      <div className="rounded-[10px] border border-line bg-surface p-3">
        <div className="mb-2.5 text-[12.5px] font-bold text-ink">판정 분포</div>
        <VerdictBars counts={report.verdict_counts} />
      </div>

      {records.length ? (
        <div className="overflow-hidden rounded-[10px] border border-line">
          <div className="border-b border-line bg-surface-2 px-3 py-2 text-[12px] font-bold text-ink-2">
            심사 레코드 ({records.length})
          </div>
          <div className="max-h-[50vh] overflow-auto">
            <table className="w-full border-collapse text-[12px]">
              <thead className="sticky top-0 bg-surface">
                <tr className="text-[11px] text-ink-4">
                  <th className="px-3 py-1.5 text-left font-bold">제목</th>
                  <th className="px-2 py-1.5 text-left font-bold">상품군</th>
                  <th className="px-2 py-1.5 text-left font-bold">판정</th>
                  <th className="px-2 py-1.5 text-right font-bold">이슈</th>
                  <th className="px-3 py-1.5 text-left font-bold">누락 고지</th>
                  <th className="px-3 py-1.5 text-left font-bold">실행 상세</th>
                </tr>
              </thead>
              <tbody>
                {records.map((row) => {
                  const missing = row.missing_disclosures ?? [];
                  return (
                    <tr key={row.id} className="border-t border-line align-top">
                      <td className="max-w-[260px] px-3 py-1.5 font-medium text-ink" title={row.title}>
                        <span className="block truncate">{row.title || "(제목 없음)"}</span>
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap text-ink-3">{row.product_group || "—"}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        <span className="font-bold" style={{ color: verdictColor(row.final_verdict) }}>
                          {verdictLabel(row.final_verdict)}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono font-bold text-ink-2">{row.issue_count ?? 0}</td>
                      <td className="max-w-[220px] px-3 py-1.5 text-[11.5px] text-ink-3">
                        {missing.length ? (
                          <span className="line-clamp-2" title={missing.join(", ")}>
                            {missing.join(", ")}
                          </span>
                        ) : (
                          <span className="text-ink-4">—</span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 whitespace-nowrap">
                        {row.run_id ? (
                          onOpenRunId ? (
                            <button
                              type="button"
                              onClick={() => onOpenRunId(row.run_id as string)}
                              className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-bold text-ink-3 hover:border-brand hover:text-brand"
                            >
                              콘솔에서 열기
                            </button>
                          ) : (
                            <span className="font-mono text-[11px] text-ink-4" title={row.run_id}>
                              {row.run_id.slice(0, 20)}
                            </span>
                          )
                        ) : (
                          <span className="text-ink-4">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="rounded-[10px] border border-line bg-surface px-3 py-4 text-[12px] text-ink-4">
          레코드가 없습니다.
        </div>
      )}
    </div>
  );
}

interface EvalPanelProps {
  /** 레코드 run_id를 콘솔 실행 상세로 딥링크(있을 때만 '콘솔에서 열기' 버튼 노출). */
  onOpenRunId?: (runId: string) => void;
}

/** 운영 대시보드 '평가 로그' 서브탭 — eval/ 리포트 목록 + 지표/판정 상세. */
export function EvalPanel({ onOpenRunId }: EvalPanelProps) {
  const [reports, setReports] = useState<EvalReportSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvalReportDetail | null>(null);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const items = await fetchEvalReports();
      // 최신순(mtime desc) — 백엔드가 이미 정렬해 주지만 방어적으로 재정렬.
      const sorted = [...items].sort((a, b) => (b.mtime ?? 0) - (a.mtime ?? 0));
      setReports(sorted);
      setSelected((prev) => (prev && sorted.some((r) => r.name === prev) ? prev : sorted[0]?.name ?? null));
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
    setDetailError("");
    fetchEvalReport(selected)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setDetail(null);
          setDetailError(err instanceof Error ? err.message : "리포트 상세를 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const selectedSummary = useMemo(
    () => reports?.find((r) => r.name === selected),
    [reports, selected],
  );

  if (reports === null) return <EmptyState>평가 리포트를 불러오는 중…</EmptyState>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-ink-3">
          <b className="text-ink-2">eval/</b> 디렉토리의 평가 리포트 — 합성 gold셋의 정밀도/재현율과 JB 실제광고 판정 로그를
          리포트별로 확인합니다.
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
              const live = isLiveSummary(report);
              const verdictTotal = report.verdict_counts
                ? Object.values(report.verdict_counts).reduce((sum, v) => sum + Number(v ?? 0), 0)
                : 0;
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
                    <span
                      className="rounded px-1.5 py-px text-[10px] font-bold uppercase"
                      style={
                        live
                          ? { background: "var(--revise-bg)", color: "var(--revise)" }
                          : { background: "var(--surface-3)", color: "var(--ink-3)" }
                      }
                    >
                      {live ? "LIVE" : report.kind}
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

                  {live ? (
                    <div className="mt-1 text-[11px] font-bold text-revise">정답 라벨 없음 · 판정 로그</div>
                  ) : null}
                  {live && verdictTotal ? (
                    <div className="mt-1 flex h-2 overflow-hidden rounded-full">
                      {VERDICT_ORDER.map((key) => {
                        const value = Number(report.verdict_counts?.[key] ?? 0);
                        if (!value) return null;
                        return (
                          <span
                            key={key}
                            style={{ width: `${(value / verdictTotal) * 100}%`, background: verdictColor(key) }}
                            title={`${verdictLabel(key)} ${value}`}
                          />
                        );
                      })}
                    </div>
                  ) : null}

                  {!live && report.metrics?.micro_f1 != null ? (
                    <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] font-bold">
                      <span style={{ color: f1Tone(report.metrics.micro_f1) }}>F1 {pct(report.metrics.micro_f1)}</span>
                      {report.metrics.mcc != null ? (
                        <span className="text-ink-4">MCC {report.metrics.mcc.toFixed(2)}</span>
                      ) : null}
                    </div>
                  ) : null}
                  {!live && report.ccg_metrics ? (
                    <div className="mt-0.5 flex flex-wrap gap-1.5 text-[11px]">
                      <span className="text-ink-4">
                        정밀도 <b style={{ color: f1Tone(report.ccg_metrics.violation_precision) }}>{pct(report.ccg_metrics.violation_precision)}</b>
                      </span>
                      <span className="text-ink-4">
                        재현율 <b style={{ color: f1Tone(report.ccg_metrics.violation_recall) }}>{pct(report.ccg_metrics.violation_recall)}</b>
                      </span>
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
            ) : detailError ? (
              <div className="rounded-md border border-reject/40 bg-reject-bg px-3 py-2 text-[12.5px] text-reject">
                {detailError}
              </div>
            ) : detail?.kind === "md" ? (
              <pre className="max-h-[calc(100vh-300px)] overflow-auto rounded-[10px] border border-line bg-surface-2 p-3 text-[12px] leading-relaxed whitespace-pre-wrap break-keep text-ink-2">
                {detail.text ?? ""}
              </pre>
            ) : detail?.content ? (
              isLiveContent(detail.content) ? (
                <JbLiveDetail report={detail.content} onOpenRunId={onOpenRunId} />
              ) : (
                <GoldMetricsDetail summary={selectedSummary} content={detail.content as GoldEvalReport} />
              )
            ) : (
              <div className="py-6 text-[12.5px] text-ink-4">왼쪽에서 리포트를 선택하세요.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
