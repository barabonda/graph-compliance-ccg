"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchEvalReport, fetchEvalReports } from "@/lib/api";
import {
  EVAL_BREAKDOWN_DIMENSION_LABEL,
  PRODUCT_SELECTION_LABEL,
  productSelectionStringLabel,
  recordPassMeta,
  reportKindMeta,
  verdictColor,
  VERDICT_LABELS,
} from "@/lib/labels";
import type {
  EvalBreakdownGroup,
  EvalGoldRecord,
  EvalPerArticleRow,
  EvalProductGroupRow,
  EvalReportCategory,
  EvalReportDetail,
  EvalReportSummary,
  EvalVerdictCounts,
  EvalViolationTypeRow,
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

/**
 * 리포트 분류 폴백 — 계약상 `report_kind`는 summary에 항상 채워지므로(contract_api.md),
 * 정상 경로에선 summary 값을 그대로 쓴다. 이 함수는 summary 조회가 실패한 극히 예외적인
 * 경우(예: 상세만 로드되고 목록 매칭이 안 된 경우)를 위한 최후 폴백이다.
 */
function inferReportKind(report?: { report_kind?: EvalReportCategory; kind?: string; gold_available?: boolean; name?: string }): EvalReportCategory {
  if (report?.report_kind) return report.report_kind;
  if (report?.kind === "jbbank_live_eval" || report?.gold_available === false) return "live";
  const name = (report?.name ?? "").toLowerCase();
  if (name.includes("synth")) return "synthetic";
  if (name.includes("guideline")) return "guideline";
  return "unknown";
}

/** `model` 등 pass-through `unknown` 값을 안전하게 문자열로 — 객체/배열이면 표시 생략. */
function scalarLabel(value: unknown): string | undefined {
  if (value == null) return undefined;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return undefined;
}

/**
 * 상품 선택 provenance 뱃지 텍스트 — 계약상 `product_selection` 타입은 `any`(pass-through)라
 * shape을 가정하지 않고 런타임에 안전하게 narrowing한다. boolean, 문자열 코드(예: JB 실제광고
 * 라이브 리포트의 `"product_group_only"`, `run_jbbank_eval.py` 참조), `{selected, product_name}`
 * 형태의 객체를 모두 허용하고, 그 외 shape(배열 등)은 배지 생략.
 */
function productSelectionInfo(sel?: unknown): { label: string; selected: boolean } | null {
  if (sel == null) return null;
  if (typeof sel === "boolean") {
    return { label: sel ? PRODUCT_SELECTION_LABEL.selected : PRODUCT_SELECTION_LABEL.sweep, selected: sel };
  }
  if (typeof sel === "string") {
    return { label: productSelectionStringLabel(sel), selected: true };
  }
  if (typeof sel === "object") {
    const obj = sel as Record<string, unknown>;
    if (typeof obj.selected === "boolean") {
      const base = obj.selected ? PRODUCT_SELECTION_LABEL.selected : PRODUCT_SELECTION_LABEL.sweep;
      const productName = typeof obj.product_name === "string" ? obj.product_name : undefined;
      return { label: productName ? `${base} · ${productName}` : base, selected: obj.selected };
    }
  }
  return null;
}

function ProductSelectionBadge({ sel }: { sel?: unknown }) {
  const info = productSelectionInfo(sel);
  if (!info) return null;
  return (
    <span
      className="rounded-full border px-2 py-0.5 text-[10.5px] font-bold"
      style={
        info.selected
          ? { borderColor: "var(--brand)", background: "var(--brand-tint)", color: "var(--brand)" }
          : { borderColor: "var(--line)", background: "var(--surface-3)", color: "var(--ink-3)" }
      }
    >
      {info.label}
    </span>
  );
}

function ReportKindBadge({ kind }: { kind: string }) {
  const meta = reportKindMeta(kind);
  return (
    <span
      className="rounded px-1.5 py-px text-[10px] font-bold uppercase"
      style={{ background: meta.bg, color: meta.color }}
    >
      {meta.label}
    </span>
  );
}

/**
 * 카드용 top-N 분해 미리보기 — `EvalReportSummary.breakdown`(계약 확정 필드)의 차원별
 * 1위 항목만 한 줄로. 전체 테이블은 상세 화면(ViolationTypeTable/ProductGroupTable/ArticleTable)에서.
 */
function BreakdownPreview({ groups }: { groups?: EvalBreakdownGroup[] }) {
  if (!groups?.length) return null;
  return (
    <div className="mt-1 space-y-0.5">
      {groups.map((group) => {
        const top = group.top?.[0];
        if (!top) return null;
        const parts: string[] = [];
        if (top.precision != null) parts.push(`정밀도 ${pct(top.precision)}`);
        if (top.recall != null) parts.push(`재현율 ${pct(top.recall)}`);
        return (
          <div key={group.dimension} className="truncate text-[10.5px] text-ink-4">
            <span className="font-bold text-ink-3">{EVAL_BREAKDOWN_DIMENSION_LABEL[group.dimension] ?? group.dimension} Top</span>{" "}
            <span title={top.key}>{top.key}</span>
            {parts.length ? ` · ${parts.join(" · ")}` : ""}
          </div>
        );
      })}
    </div>
  );
}

/** tp/fp/fn에서 정밀도/재현율을 보정 계산(원본에 없을 때만 사용). */
function prf(row: { tp?: number; fp?: number; fn?: number; precision?: number; recall?: number }): {
  precision?: number;
  recall?: number;
} {
  const tp = row.tp ?? 0;
  const fp = row.fp ?? 0;
  const fn = row.fn ?? 0;
  return {
    precision: row.precision ?? (tp + fp ? tp / (tp + fp) : undefined),
    recall: row.recall ?? (tp + fn ? tp / (tp + fn) : undefined),
  };
}

/** 위반유형별 재현율 테이블(합성 v0.2 `per_violation_type_recall`, 있을 때만). */
function ViolationTypeTable({ rows }: { rows?: Record<string, EvalViolationTypeRow> }) {
  const entries = rows ? Object.entries(rows) : [];
  if (!entries.length) return null;
  return (
    <div className="overflow-hidden rounded-[10px] border border-line">
      <div className="border-b border-line bg-surface-2 px-3 py-2 text-[12px] font-bold text-ink-2">
        위반 유형별 재현율 (변이 레코드)
      </div>
      <div className="max-h-[280px] overflow-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-[11px] text-ink-4">
              <th className="px-3 py-1.5 text-left font-bold">유형</th>
              <th className="px-2 py-1.5 text-right font-bold">변이 수</th>
              <th className="px-2 py-1.5 text-right font-bold">검출</th>
              <th className="px-3 py-1.5 text-right font-bold">재현율</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([type, row]) => (
              <tr key={type} className="border-t border-line">
                <td className="px-3 py-1.5 font-medium text-ink">{type}</td>
                <td className="px-2 py-1.5 text-right font-mono text-ink-2">{row.mutations ?? "—"}</td>
                <td className="px-2 py-1.5 text-right font-mono text-ink-2">{row.detected ?? "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono font-bold" style={{ color: f1Tone(row.recall) }}>
                  {pct(row.recall)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** 상품군별 정밀도/재현율 테이블(합성 v0.2 `per_product_group`, 있을 때만). */
function ProductGroupTable({ rows }: { rows?: Record<string, EvalProductGroupRow> }) {
  const entries = rows ? Object.entries(rows) : [];
  if (!entries.length) return null;
  return (
    <div className="overflow-hidden rounded-[10px] border border-line">
      <div className="border-b border-line bg-surface-2 px-3 py-2 text-[12px] font-bold text-ink-2">상품군별 정밀도·재현율</div>
      <div className="max-h-[280px] overflow-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-[11px] text-ink-4">
              <th className="px-3 py-1.5 text-left font-bold">상품군</th>
              <th className="px-2 py-1.5 text-right font-bold">TP/FP/FN/TN</th>
              <th className="px-2 py-1.5 text-right font-bold">정밀도</th>
              <th className="px-2 py-1.5 text-right font-bold">재현율</th>
              <th className="px-3 py-1.5 text-right font-bold">F1</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([group, row]) => (
              <tr key={group} className="border-t border-line">
                <td className="px-3 py-1.5 font-medium text-ink">{group}</td>
                <td className="px-2 py-1.5 text-right font-mono text-ink-3">
                  {row.counts?.tp ?? 0}/{row.counts?.fp ?? 0}/{row.counts?.fn ?? 0}/{row.counts?.tn ?? 0}
                </td>
                <td className="px-2 py-1.5 text-right font-mono font-bold" style={{ color: f1Tone(row.precision) }}>
                  {pct(row.precision)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono font-bold" style={{ color: f1Tone(row.recall) }}>
                  {pct(row.recall)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-ink-2">{row.f1 != null ? row.f1.toFixed(3) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** 조문별 정밀도/재현율 테이블 — gold 리포트 원본 `article_metrics.per_article` 사용.
 * 신호가 있는(TP/FP/FN 중 하나라도 있는) 조문을 위로 정렬, 없으면 전체 생략. */
function ArticleTable({ rows }: { rows?: Record<string, EvalPerArticleRow> }) {
  const entries = rows ? Object.entries(rows) : [];
  if (!entries.length) return null;
  const sorted = [...entries].sort((a, b) => {
    const relevance = (r: EvalPerArticleRow) => (r.tp ?? 0) + (r.fp ?? 0) + (r.fn ?? 0);
    return relevance(b[1]) - relevance(a[1]);
  });
  return (
    <div className="overflow-hidden rounded-[10px] border border-line">
      <div className="border-b border-line bg-surface-2 px-3 py-2 text-[12px] font-bold text-ink-2">
        조문별 정밀도·재현율 ({sorted.length})
      </div>
      <div className="max-h-[320px] overflow-auto">
        <table className="w-full border-collapse text-[12px]">
          <thead className="sticky top-0 bg-surface">
            <tr className="text-[11px] text-ink-4">
              <th className="px-3 py-1.5 text-left font-bold">조문</th>
              <th className="px-2 py-1.5 text-right font-bold">TP/FP/FN/TN</th>
              <th className="px-2 py-1.5 text-right font-bold">정밀도</th>
              <th className="px-2 py-1.5 text-right font-bold">재현율</th>
              <th className="px-3 py-1.5 text-right font-bold">F1</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(([article, row]) => {
              const { precision, recall } = prf(row);
              return (
                <tr key={article} className="border-t border-line">
                  <td className="max-w-[220px] px-3 py-1.5 font-medium text-ink" title={article}>
                    <span className="block truncate">{article}</span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-ink-3">
                    {row.tp ?? 0}/{row.fp ?? 0}/{row.fn ?? 0}/{row.tn ?? 0}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono font-bold" style={{ color: f1Tone(precision) }}>
                    {pct(precision)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono font-bold" style={{ color: f1Tone(recall) }}>
                    {pct(recall)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-ink-2">{row.f1 != null ? row.f1.toFixed(3) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * 합성 gold 레코드 id → 상품명·변이유형 파싱. 실제 산출 규칙은 `syn_{product}_web_page_{variant}`
 * (채널이 `web_page` 고정) — 패턴이 안 맞으면 추측하지 않고 원본 id를 그대로 노출한다.
 */
function parseRecordId(id: string): { product: string; variant: string } {
  const stripped = id.replace(/^syn_/, "");
  const marker = "_web_page_";
  const idx = stripped.indexOf(marker);
  if (idx === -1) return { product: stripped.replace(/_/g, " ").trim() || id, variant: "" };
  const product = stripped.slice(0, idx).replace(/_/g, " ").trim();
  const variantRaw = stripped.slice(idx + marker.length);
  const variant = variantRaw === "clean" ? "정상(위반 없음)" : variantRaw.replace(/_/g, " ").trim();
  return { product: product || id, variant };
}

function PassBadge({ pass }: { pass?: boolean }) {
  const meta = recordPassMeta(pass);
  return (
    <span
      className="shrink-0 rounded-full border px-2 py-0.5 text-[10.5px] font-bold"
      style={{ borderColor: meta.color, background: meta.bg, color: meta.color }}
    >
      {meta.label}
    </span>
  );
}

/** 축별 ✓/✗ — 백엔드 `matches`가 없으면(구버전 리포트) 자체 재계산 없이 "—"만 표시. */
function AxisMark({ ok }: { ok?: boolean }) {
  if (ok == null) return <span className="font-mono text-ink-4">—</span>;
  return ok ? (
    <span className="text-[14px] font-bold" style={{ color: "var(--pass)" }}>✓</span>
  ) : (
    <span className="text-[14px] font-bold" style={{ color: "var(--reject)" }}>✗</span>
  );
}

function listOrDash(items?: string[]): string {
  return items && items.length ? items.join(", ") : "—";
}

/** 레코드 상세의 축 1줄 — gold/pred 값 나란히 + 우측 ✓/✗(있을 때만). */
function AxisRow({
  label,
  ok,
  gold,
  pred,
  extra,
}: {
  label: string;
  ok?: boolean;
  gold: string;
  pred: string;
  extra?: string;
}) {
  return (
    <div className="grid grid-cols-[132px_1fr_1fr_24px] items-start gap-2.5 text-[12px]">
      <div className="pt-0.5 font-bold text-ink-3">{label}</div>
      <div className="min-w-0">
        <div className="text-[10px] font-bold tracking-wide text-ink-4 uppercase">정답(gold)</div>
        <div className="break-words text-ink-2">{gold}</div>
      </div>
      <div className="min-w-0">
        <div className="text-[10px] font-bold tracking-wide text-ink-4 uppercase">예측(pred)</div>
        <div className="break-words text-ink-2">{pred}</div>
        {extra ? <div className="mt-0.5 text-[11px] text-ink-4">{extra}</div> : null}
      </div>
      <div className="pt-0.5 text-center">
        <AxisMark ok={ok} />
      </div>
    </div>
  );
}

/**
 * 레코드 1건의 축별 gold vs prediction 상세 — 위반 여부·조문(정확일치/계열병합)·필수
 * 고지사항 재현율·라우팅 4축. `matches`가 없는 구버전 리포트에서도 gold/pred 원본 값은
 * 그대로 보여주되(정보 자체는 항상 있음), ✓/✗ 판정만 "—"로 비운다.
 */
function RecordAxisDetail({ record }: { record: EvalGoldRecord }) {
  const { gold, prediction, matches } = record;
  const disclosureMatch = matches?.disclosures;
  const routingMatch = matches?.routing;

  return (
    <div className="space-y-2.5 border-t border-line bg-surface-2 px-3 py-3">
      <AxisRow
        label="위반 여부"
        ok={matches?.violation}
        gold={gold.violation ? "위반" : "위반 없음"}
        pred={prediction.predicted_violation ? "위반" : "위반 없음"}
      />
      <AxisRow
        label="조문(정확일치)"
        ok={matches?.article_exact}
        gold={listOrDash(gold.articles)}
        pred={listOrDash(prediction.predicted_articles)}
      />
      <AxisRow
        label="조문(계열병합)"
        ok={matches?.article_family}
        gold={listOrDash(gold.articles)}
        pred={listOrDash(prediction.predicted_articles)}
      />
      <AxisRow
        label="필수 고지사항"
        ok={disclosureMatch?.recall != null ? disclosureMatch.recall >= 1 : undefined}
        gold={gold.required_disclosures ? listOrDash(gold.required_disclosures) : "gold 미제공"}
        pred={listOrDash(prediction.predicted_required_disclosures)}
        extra={
          disclosureMatch
            ? `재현율 ${pct(disclosureMatch.recall)} (${disclosureMatch.matched_n ?? 0}/${disclosureMatch.gold_n ?? 0})`
            : undefined
        }
      />
      <AxisRow
        label="라우팅"
        ok={routingMatch?.exact}
        gold={gold.expected_routing ? verdictLabel(gold.expected_routing) : "—"}
        pred={prediction.predicted_routing ? verdictLabel(prediction.predicted_routing) : "—"}
        extra={
          routingMatch
            ? routingMatch.exact
              ? "정확 일치"
              : routingMatch.adjacent
                ? "인접(±1) 허용 범위"
                : "불일치"
            : undefined
        }
      />
    </div>
  );
}

type RecordPassFilter = "all" | "pass" | "fail";

/**
 * 레코드별 통과 검증 뷰 — 합성 gold 레코드를 열어 gold vs prediction을 축별로 확인한다.
 * `matches`/`overall_pass` 없는 구버전 리포트에서도 크래시 없이 "판정 없음"으로 표시하고
 * (자체 판정 로직 재계산 금지 — 백엔드가 채운 값만 그대로 노출), `records` 필드 자체가
 * 없는 리포트에서는 이 섹션을 아예 렌더링하지 않는다(호출부에서 가드).
 */
function RecordsPanel({
  records,
  overallPassDefinition,
  onOpenRunId,
}: {
  records: EvalGoldRecord[];
  overallPassDefinition?: string;
  onOpenRunId?: (runId: string) => void;
}) {
  const [passFilter, setPassFilter] = useState<RecordPassFilter>("all");
  const [productFilter, setProductFilter] = useState<string>("all");

  const parsed = useMemo(() => records.map((record) => ({ record, ...parseRecordId(record.id) })), [records]);

  const products = useMemo(() => {
    const set = new Set<string>();
    for (const p of parsed) set.add(p.product);
    return Array.from(set).sort((a, b) => a.localeCompare(b, "ko"));
  }, [parsed]);

  const filtered = useMemo(
    () =>
      parsed.filter(({ record, product }) => {
        if (productFilter !== "all" && product !== productFilter) return false;
        if (passFilter === "pass" && record.overall_pass !== true) return false;
        if (passFilter === "fail" && record.overall_pass !== false) return false;
        return true;
      }),
    [parsed, productFilter, passFilter],
  );

  const passCount = records.filter((r) => r.overall_pass === true).length;
  const failCount = records.filter((r) => r.overall_pass === false).length;
  const unknownCount = records.length - passCount - failCount;
  const hasAnyMatches = records.some((r) => r.overall_pass != null);

  return (
    <div className="overflow-hidden rounded-[10px] border border-line">
      <div className="border-b border-line bg-surface-2 px-3 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[12px] font-bold text-ink-2">
            레코드별 통과 검증 ({records.length}건 · 통과 {passCount} · 실패 {failCount}
            {unknownCount ? ` · 판정 없음 ${unknownCount}` : ""})
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {([
              ["all", "전체"],
              ["pass", "통과만"],
              ["fail", "실패만"],
            ] as [RecordPassFilter, string][]).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setPassFilter(key)}
                className="rounded-md border px-2 py-1 text-[11px] font-bold"
                style={
                  passFilter === key
                    ? { borderColor: "var(--brand)", background: "var(--brand-tint)", color: "var(--brand)" }
                    : { borderColor: "var(--line)", background: "var(--surface)", color: "var(--ink-3)" }
                }
              >
                {label}
              </button>
            ))}
            <select
              value={productFilter}
              onChange={(e) => setProductFilter(e.target.value)}
              className="rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-bold text-ink-3"
            >
              <option value="all">상품 전체</option>
              {products.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        </div>
        {overallPassDefinition ? (
          <div className="mt-1.5 text-[11px] text-ink-4">
            <b className="text-ink-3">통과 정의</b> · {overallPassDefinition}
          </div>
        ) : hasAnyMatches ? (
          <div className="mt-1.5 text-[11px] text-ink-4">통과 정의가 리포트에 명시되지 않았습니다.</div>
        ) : (
          <div className="mt-1.5 text-[11px] text-ink-4">
            이 리포트는 레코드별 축 판정(matches/overall_pass) 이전 버전입니다 — gold·예측 값은 아래에서 그대로 비교할 수 있습니다.
          </div>
        )}
      </div>

      <div className="max-h-[60vh] overflow-auto">
        {filtered.length === 0 ? (
          <div className="px-3 py-6 text-center text-[12px] text-ink-4">조건에 맞는 레코드가 없습니다.</div>
        ) : (
          filtered.map(({ record, product, variant }) => {
            const runId = record.review_run_id ?? record.prediction?.review_run_id;
            return (
              <details key={record.id} className="border-t border-line first:border-t-0">
                <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 hover:bg-surface-2">
                  <PassBadge pass={record.overall_pass} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] font-bold text-ink" title={record.id}>
                      {product}
                    </span>
                    {variant ? <span className="block truncate text-[11px] text-ink-4">{variant}</span> : null}
                  </span>
                  {runId ? (
                    onOpenRunId ? (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          onOpenRunId(runId);
                        }}
                        className="shrink-0 rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-bold text-ink-3 hover:border-brand hover:text-brand"
                      >
                        콘솔에서 열기
                      </button>
                    ) : (
                      <span className="shrink-0 font-mono text-[10.5px] text-ink-4" title={runId}>
                        {runId.slice(0, 16)}
                      </span>
                    )
                  ) : null}
                </summary>
                <RecordAxisDetail record={record} />
              </details>
            );
          })
        )}
      </div>
    </div>
  );
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
 * 합성 gold 리포트 상세 — 확정 계약 필드(metrics/counts/ccg_metrics)에 더해 있으면
 * 위반유형별·조문별·상품군별 분해 테이블, report_kind/모델/상품선택 뱃지도 표시한다.
 * summary(목록 응답)와 content(원본 JSON) 중 존재하는 쪽에서 값을 읽는다 — 둘 다 없으면
 * 해당 항목은 조용히 생략(옵셔널 처리, undefined 크래시 없음).
 */
function GoldMetricsDetail({
  summary,
  content,
  onOpenRunId,
}: {
  summary?: EvalReportSummary;
  content?: GoldEvalReport;
  onOpenRunId?: (runId: string) => void;
}) {
  const metrics = summary?.metrics ?? content?.metrics ?? content?.article_metrics;
  const counts = summary?.counts ?? content?.counts ?? content?.overall?.counts;
  const ccg = summary?.ccg_metrics ?? content?.ccg_metrics;
  const recordCount = summary?.record_count ?? content?.record_count;
  // report_kind는 summary에만 존재하는 계약 필드(상세 content는 원본 파일 그대로라 없음).
  const reportKind = summary?.report_kind ?? inferReportKind(summary);
  const model = scalarLabel(summary?.model ?? content?.model);
  const productSelection = summary?.product_selection ?? content?.product_selection;
  // synth_v0_2_breakdown.py의 대안 shape(article_metrics 없이 overall{precision,recall,f1}만) 폴백.
  const overall = content?.overall;
  const overallPrecision = ccg?.violation_precision ?? overall?.precision;
  const overallRecall = ccg?.violation_recall ?? overall?.recall;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <ReportKindBadge kind={reportKind} />
        {model ? (
          <span className="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink-3">{model}</span>
        ) : null}
        <ProductSelectionBadge sel={productSelection} />
      </div>

      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
        <MetricCard label="레코드" value={String(recordCount ?? "—")} sub="평가 케이스" />
        <MetricCard label="위반 정밀도" value={pct(overallPrecision)} accent={f1Tone(overallPrecision)} sub="violation precision" />
        <MetricCard label="위반 재현율" value={pct(overallRecall)} accent={f1Tone(overallRecall)} sub="violation recall" />
        <MetricCard
          label="MCC"
          value={metrics?.mcc != null ? metrics.mcc.toFixed(3) : "—"}
          sub="상관계수"
        />
        <MetricCard label="Micro F1" value={pct(metrics?.micro_f1 ?? overall?.f1)} accent={f1Tone(metrics?.micro_f1 ?? overall?.f1)} />
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

      <ViolationTypeTable rows={content?.per_violation_type_recall} />
      <ProductGroupTable rows={content?.per_product_group} />
      <ArticleTable rows={content?.article_metrics?.per_article} />

      {content?.records?.length ? (
        <RecordsPanel
          records={content.records}
          overallPassDefinition={content.overall_pass_definition}
          onOpenRunId={onOpenRunId}
        />
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
  const model = scalarLabel(report.model);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-revise/40 bg-revise-bg px-2.5 py-1 text-[11.5px] font-bold text-revise">
          실제 광고 — 정답 라벨 없음(판정 로그)
        </span>
        {model ? (
          <span className="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink-3">{model}</span>
        ) : null}
        <ProductSelectionBadge sel={report.product_selection} />
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
  /** 중간 산출물(is_report:false) 기본 숨김 — 토글하면 원자료까지 포함해 보여준다. */
  const [showRaw, setShowRaw] = useState(false);

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

  // 중간 산출물(is_report:false) 기본 제외 — 필드가 없는(구버전) 리포트는 true로 취급(무회귀).
  const visibleReports = useMemo(() => {
    if (!reports) return reports;
    return showRaw ? reports : reports.filter((r) => r.is_report !== false);
  }, [reports, showRaw]);
  const hiddenRawCount = reports ? reports.length - (visibleReports?.length ?? reports.length) : 0;

  if (reports === null) return <EmptyState>평가 리포트를 불러오는 중…</EmptyState>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-ink-3">
          <b className="text-ink-2">eval/</b> 디렉토리의 평가 리포트 — 합성 gold셋의 정밀도/재현율과 JB 실제광고 판정 로그를
          리포트별로 확인합니다.
        </p>
        <div className="flex shrink-0 items-center gap-2">
          {hiddenRawCount > 0 || showRaw ? (
            <label className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[11.5px] font-bold text-ink-3">
              <input
                type="checkbox"
                checked={showRaw}
                onChange={(e) => setShowRaw(e.target.checked)}
                className="accent-brand"
              />
              원자료 포함{hiddenRawCount > 0 && !showRaw ? ` (${hiddenRawCount})` : ""}
            </label>
          ) : null}
          <button
            type="button"
            onClick={() => void load()}
            className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-[12px] font-bold text-ink-3 hover:border-brand hover:text-brand"
          >
            <Icon name="clock" size={13} /> 새로고침
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-md border border-reject/40 bg-reject-bg px-3 py-2 text-[12.5px] text-reject">{error}</div>
      ) : null}

      {reports.length === 0 ? (
        <div className="rounded-[10px] border border-line bg-surface px-4 py-6 text-[12.5px] text-ink-4">
          아직 평가 리포트가 없습니다. 평가 스윕을 실행하면 eval/ 에 리포트가 쌓이고 여기에 표시됩니다.
        </div>
      ) : !visibleReports || visibleReports.length === 0 ? (
        <div className="rounded-[10px] border border-line bg-surface px-4 py-6 text-[12.5px] text-ink-4">
          중간 산출물만 있습니다. &quot;원자료 포함&quot;을 켜면 확인할 수 있습니다.
        </div>
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: "300px minmax(0,1fr)" }}>
          {/* 좌: 리포트 목록 */}
          <div className="flex max-h-[calc(100vh-260px)] flex-col gap-1.5 overflow-y-auto">
            {visibleReports.map((report) => {
              const isSelected = report.name === selected;
              const live = isLiveSummary(report);
              const isRaw = report.is_report === false;
              const kind = report.report_kind ?? inferReportKind(report);
              const productSel = productSelectionInfo(report.product_selection);
              const modelLabel = scalarLabel(report.model);
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
                    opacity: isRaw && !isSelected ? 0.65 : 1,
                  }}
                >
                  <div className="flex items-center gap-1.5">
                    <ReportKindBadge kind={kind} />
                    {isRaw ? (
                      <span className="rounded px-1.5 py-px text-[10px] font-bold uppercase" style={{ background: "var(--surface-3)", color: "var(--ink-4)" }}>
                        원자료
                      </span>
                    ) : null}
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

                  {modelLabel || productSel ? (
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      {modelLabel ? (
                        <span className="rounded border border-line bg-surface-2 px-1.5 py-px font-mono text-[10.5px] text-ink-3">
                          {modelLabel}
                        </span>
                      ) : null}
                      {productSel ? (
                        <span
                          className="rounded-full px-1.5 py-px text-[10px] font-bold"
                          style={
                            productSel.selected
                              ? { background: "var(--brand-tint)", color: "var(--brand)" }
                              : { background: "var(--surface-3)", color: "var(--ink-3)" }
                          }
                        >
                          {productSel.label}
                        </span>
                      ) : null}
                    </div>
                  ) : null}

                  <BreakdownPreview groups={report.breakdown} />

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
                <GoldMetricsDetail
                  summary={selectedSummary}
                  content={detail.content as GoldEvalReport}
                  onOpenRunId={onOpenRunId}
                />
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
