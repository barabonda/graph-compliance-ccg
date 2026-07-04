"use client";

import { useMemo, useState } from "react";
import { claimFactById, productFactById } from "@/lib/selectors";
import type { ComparisonResult, ReviewOutput, SelectedDocument } from "@/lib/types";
import { Badge, EmptyState, type BadgeTone } from "../ui";

/** 상태별 표기·심각도(낮을수록 위험). 위험 우선 정렬·필터의 단일 기준. */
const STATUS_META: Record<string, { label: string; tone: BadgeTone; severity: number; risk: boolean }> = {
  CONTRADICTED: { label: "문서와 충돌", tone: "reject", severity: 0, risk: true },
  PROMINENCE_INSUFFICIENT: { label: "현저성 부족", tone: "revise", severity: 1, risk: true },
  CONDITION_MISSING: { label: "조건 누락", tone: "review", severity: 2, risk: true },
  NO_PRODUCT_FACT: { label: "근거 없음", tone: "review", severity: 3, risk: true },
  NEEDS_PRODUCT_SELECTION: { label: "상품 선택 필요", tone: "neutral", severity: 4, risk: false },
  SUPPORTED: { label: "문서 일치", tone: "pass", severity: 5, risk: false },
};

function meta(status: string) {
  return STATUS_META[status] ?? { label: status, tone: "neutral" as BadgeTone, severity: 9, risk: true };
}

function pageOf(pageOrChunk?: string): number | null {
  const m = (pageOrChunk ?? "").match(/\d+/);
  return m ? Number(m[0]) : null;
}

function openDoc(documentId: string, page: number | null) {
  if (!documentId) return;
  const url = `/api/product-doc/${encodeURIComponent(documentId)}${page ? `#page=${page}` : ""}`;
  window.open(url, "_blank", "noopener");
}

function DocButton({
  doc,
  page,
  fallbackId,
}: {
  doc?: SelectedDocument;
  page: number | null;
  fallbackId?: string;
}) {
  const id = String(doc?.document_id ?? fallbackId ?? "");
  if (!id) return null;
  const label = doc?.label ?? "상품문서";
  return (
    <button
      type="button"
      onClick={() => openDoc(id, page)}
      className="inline-flex items-center gap-1 rounded-md border border-brand-tint2 bg-brand-tint px-2 py-1 text-[11.5px] font-bold text-brand-2 hover:bg-brand-tint2"
    >
      <span aria-hidden>📄</span> {label}
      {page ? ` ${page}p` : ""} 보기
    </button>
  );
}

interface IssueRow {
  comparison: ComparisonResult;
  factType: string;
  claimValue: string;
  claimEvidence: string;
  claimTier: string;
  productValue: string;
  productCondition: string;
  productEvidence: string;
  doc?: SelectedDocument;
  page: number | null;
}

function buildIssues(result: ReviewOutput): IssueRow[] {
  const context = result.product_fact_context ?? {};
  const docs = context.selected_documents ?? [];
  const docById = new Map(docs.map((d) => [String(d.document_id ?? ""), d] as const));
  return (context.comparison_results ?? []).map((comparison) => {
    const cf = claimFactById(result, comparison.claim_fact_id);
    const pf = productFactById(result, comparison.product_fact_id);
    const docId = pf?.source_document_id || (docs.find((d) => d.label === "상품설명서")?.document_id ?? "");
    return {
      comparison,
      factType: cf?.fact_type || pf?.fact_type || "사실 대조",
      claimValue: cf?.value || "",
      claimEvidence: cf?.evidence_text || "",
      claimTier: cf?.prominence_tier || "",
      productValue: pf ? `${pf.value}${pf.unit ? ` ${pf.unit}` : ""}` : "",
      productCondition: pf?.condition || "",
      productEvidence: pf?.evidence_text || comparison.evidence_text || "",
      doc: docById.get(String(docId)),
      page: pageOf(pf?.page_or_chunk),
    };
  });
}

function IssueCard({
  row,
  flagged,
  comment,
  onComment,
  onToggleFlag,
}: {
  row: IssueRow;
  flagged: boolean;
  comment: string;
  onComment: (value: string) => void;
  onToggleFlag: () => void;
}) {
  const [showComment, setShowComment] = useState(false);
  const m = meta(row.comparison.status);
  const accent =
    m.tone === "reject" ? "var(--reject)" : m.tone === "revise" ? "var(--revise)" : m.tone === "review" ? "var(--revise)" : m.tone === "pass" ? "var(--pass)" : "var(--line-2)";

  return (
    <article
      className="overflow-hidden rounded-[12px] border bg-surface"
      style={{ borderColor: flagged ? "var(--brand)" : "var(--line)", borderLeft: `4px solid ${accent}` }}
    >
      {/* 헤더: 상태 + 항목 + 신뢰도 */}
      <div className="flex items-center gap-2 border-b border-line bg-surface-2 px-3.5 py-2">
        <Badge tone={m.tone}>{m.label}</Badge>
        <span className="text-[13px] font-bold text-ink">{row.factType}</span>
        <span className="ml-auto text-[11px] text-ink-3" title={`confidence ${Number(row.comparison.confidence ?? 0).toFixed(2)}`}>
          신뢰도 {Number(row.comparison.confidence ?? 0) >= 0.75 ? "높음" : Number(row.comparison.confidence ?? 0) >= 0.4 ? "중간" : "낮음"}
        </span>
      </div>

      {/* 본문: 광고 주장 → 문서 근거 세로 스택 (시선 이동 없음) */}
      <div className="space-y-0 px-3.5 py-3">
        <div>
          <div className="mb-1 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-reject" />
            <span className="text-[11px] font-bold tracking-wider text-ink-4">광고 주장</span>
            {row.claimTier && row.claimTier !== "unknown" && (
              <span className="rounded bg-surface-3 px-1.5 text-[11px] font-bold text-ink-3">{row.claimTier}</span>
            )}
          </div>
          <p className="text-[13.5px] leading-relaxed font-semibold text-ink">{row.claimValue || "—"}</p>
          {row.claimEvidence && <p className="mt-0.5 text-[12px] leading-relaxed text-ink-3">“{row.claimEvidence}”</p>}
        </div>

        <div className="my-2 flex items-center gap-2 text-[11px] text-ink-4">
          <span className="h-px flex-1 bg-line" />
          <span>대조 ↓</span>
          <span className="h-px flex-1 bg-line" />
        </div>

        <div>
          <div className="mb-1 flex flex-wrap items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-pass" />
            <span className="text-[11px] font-bold tracking-wider text-ink-4">문서 근거</span>
            <span className="ml-auto">
              <DocButton doc={row.doc} page={row.page} fallbackId={row.doc?.document_id as string} />
            </span>
          </div>
          {row.productValue ? (
            <p className="text-[13.5px] leading-relaxed font-semibold text-ink">
              {row.productValue}
              {row.productCondition ? <span className="font-normal text-ink-3"> · {row.productCondition}</span> : null}
            </p>
          ) : (
            <p className="text-[13px] text-ink-3">상품문서에서 대응하는 사실을 찾지 못했습니다.</p>
          )}
          {row.productEvidence && <p className="mt-0.5 text-[12px] leading-relaxed text-ink-3">“{row.productEvidence}”</p>}
        </div>

        {/* 판단 */}
        {row.comparison.rationale && (
          <div className="mt-2.5 rounded-md bg-surface-2 px-3 py-2">
            <span className="text-[11px] font-bold tracking-wider text-ink-4">판단</span>
            <p className="mt-0.5 text-[12.5px] leading-relaxed text-ink-2">{row.comparison.rationale}</p>
          </div>
        )}
      </div>

      {/* 액션: 코멘트 + 보완요청 담기 */}
      <div className="flex items-center gap-2 border-t border-line px-3.5 py-2">
        <button
          type="button"
          onClick={() => setShowComment((v) => !v)}
          className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11.5px] font-semibold text-ink-2 hover:border-brand hover:text-brand"
        >
          💬 {comment ? "코멘트 수정" : "코멘트"}
        </button>
        <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-[12px] font-semibold text-ink-2">
          <input type="checkbox" checked={flagged} onChange={onToggleFlag} className="accent-[var(--brand)]" />
          보완요청 담기
        </label>
      </div>
      {showComment && (
        <div className="border-t border-line px-3.5 py-2">
          <textarea
            value={comment}
            onChange={(e) => onComment(e.target.value)}
            placeholder="마케터에게 전달할 수정 가이드 (예: 헤드라인의 ‘확정’ 표현 삭제, 조건 고지를 동일 크기로 병기)"
            rows={2}
            className="w-full resize-y rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px] outline-none focus:border-brand"
          />
        </div>
      )}
    </article>
  );
}

export function ProductFactsTab({ result }: { result: ReviewOutput | null }) {
  const [riskOnly, setRiskOnly] = useState(true);
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const [showRequest, setShowRequest] = useState(false);
  const [copied, setCopied] = useState(false);

  const issues = useMemo(() => (result ? buildIssues(result) : []), [result]);

  if (!result) return <EmptyState>Review를 실행하면 상품문서 fact 대조가 여기에 표시됩니다.</EmptyState>;

  const context = result.product_fact_context ?? {};
  if (context.extraction_status === "NEEDS_PRODUCT_SELECTION") {
    const candidates = result.product_context?.matched_products ?? [];
    return (
      <div className="rounded-[12px] border border-line bg-surface-2 p-5">
        <h3 className="text-sm font-bold">상품 선택 필요</h3>
        <p className="mt-1.5 text-xs leading-relaxed text-ink-3">
          상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다. 광고 claim과 실제
          상품문서 fact를 대조하려면 리뷰 대상 상품을 먼저 확정해야 합니다.
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {candidates.slice(0, 8).map((item, i) => (
            <span key={i} className="rounded border border-line bg-surface px-2 py-0.5 text-[11px] text-ink-3">
              {item.product || item.name || "상품 후보"}
            </span>
          ))}
        </div>
      </div>
    );
  }

  const sorted = [...issues].sort((a, b) => meta(a.comparison.status).severity - meta(b.comparison.status).severity);
  const visible = riskOnly ? sorted.filter((row) => meta(row.comparison.status).risk) : sorted;
  const riskCount = sorted.filter((row) => meta(row.comparison.status).risk).length;
  const okCount = sorted.length - riskCount;

  const flaggedRows = sorted.filter((row) => flags[row.comparison.comparison_id]);
  const requestText = flaggedRows
    .map((row, i) => {
      const m = meta(row.comparison.status);
      const note = comments[row.comparison.comparison_id]?.trim();
      return [
        `${i + 1}. [${m.label}] ${row.factType}`,
        `   광고 주장: ${row.claimValue || row.claimEvidence}`,
        row.productValue ? `   문서 근거: ${row.productValue}${row.productCondition ? ` (${row.productCondition})` : ""}` : "   문서 근거: 대응 사실 없음",
        `   판단: ${row.comparison.rationale || "-"}`,
        note ? `   수정 요구: ${note}` : "   수정 요구: (가이드 미작성)",
      ].join("\n");
    })
    .join("\n\n");

  const copyRequest = async () => {
    const header = `[보완요청서] ${context.matched_product || "상품"} · ${result.review_run_id}\n대상: 마케팅 담당\n\n`;
    await navigator.clipboard.writeText(header + requestText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="space-y-3">
      {/* 상단 바: 요약 + 위험만 보기 토글 + 보완요청 */}
      <div className="flex flex-wrap items-center gap-3 rounded-[12px] border border-line bg-surface px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold">상품 사실 대조</h3>
          <span className="text-xs text-ink-3">{context.matched_product}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge tone={riskCount ? "reject" : "pass"}>위험 {riskCount}</Badge>
          <Badge tone="pass">일치 {okCount}</Badge>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-[12.5px] font-semibold text-ink-2">
            <input type="checkbox" checked={riskOnly} onChange={() => setRiskOnly((v) => !v)} className="accent-[var(--brand)]" />
            위험/수정 필요만 보기
          </label>
          <button
            type="button"
            onClick={() => setShowRequest((v) => !v)}
            disabled={!flaggedRows.length}
            className="inline-flex items-center gap-1 rounded-md bg-brand px-3 py-1.5 text-[12.5px] font-bold text-white disabled:opacity-40"
          >
            보완요청서 {flaggedRows.length ? `(${flaggedRows.length})` : ""}
          </button>
        </div>
      </div>

      {/* 보완요청서 미리보기 */}
      {showRequest && flaggedRows.length > 0 && (
        <div className="rounded-[12px] border border-brand-tint2 bg-brand-tint p-3.5">
          <div className="mb-2 flex items-center gap-2">
            <strong className="text-[13px] text-brand-2">보완요청서 미리보기 · {flaggedRows.length}건</strong>
            <button
              type="button"
              onClick={copyRequest}
              className="ml-auto rounded-md bg-brand px-2.5 py-1 text-[11.5px] font-bold text-white"
            >
              {copied ? "복사됨 ✓" : "복사"}
            </button>
          </div>
          <pre className="max-h-56 overflow-auto rounded-md bg-surface p-3 font-sans text-[12px] leading-relaxed whitespace-pre-wrap text-ink-2">
            {requestText}
          </pre>
          <p className="mt-1.5 text-[11px] text-ink-4">
            * 데모 단계에서는 복사하여 전달합니다. 발송 워크플로우 연동 시 마케터에게 자동 발송됩니다.
          </p>
        </div>
      )}

      {/* 이슈 카드 (위험 우선 정렬) */}
      {visible.length ? (
        <div className="space-y-2.5">
          {visible.map((row) => (
            <IssueCard
              key={row.comparison.comparison_id}
              row={row}
              flagged={Boolean(flags[row.comparison.comparison_id])}
              comment={comments[row.comparison.comparison_id] ?? ""}
              onComment={(value) => setComments((prev) => ({ ...prev, [row.comparison.comparison_id]: value }))}
              onToggleFlag={() =>
                setFlags((prev) => ({ ...prev, [row.comparison.comparison_id]: !prev[row.comparison.comparison_id] }))
              }
            />
          ))}
        </div>
      ) : (
        <EmptyState>
          {riskOnly ? "위험/수정 필요 항목이 없습니다. 토글을 끄면 일치 항목도 볼 수 있습니다." : "비교 결과가 없습니다."}
        </EmptyState>
      )}

      {/* 검토한 문서 (난수 ID 제거, 버튼화) */}
      {(context.selected_documents ?? []).length > 0 && (
        <div className="rounded-[12px] border border-line bg-surface p-3.5">
          <h4 className="mb-2 text-[13px] font-bold">검토한 상품문서</h4>
          <div className="flex flex-wrap gap-2">
            {(context.selected_documents ?? []).map((doc, i) => (
              <DocButton key={i} doc={doc} page={1} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
