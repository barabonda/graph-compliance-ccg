"use client";

import { useMemo, useState } from "react";
import {
  buildDocumentDiff,
  buildIssueCards,
  correctedDocument,
  disclosureIsSatisfied,
  disclosureStatus,
  disclosureStatusLabel,
  productComparisonsForClaimFact,
  productFactById,
  productClaimFactsForAnchor,
  requiredDisclosureSlots,
  revisionFor,
} from "@/lib/selectors";
import type { ContextAnchor, ReviewOutput } from "@/lib/types";
import { Badge, EmptyState, Tag, type BadgeTone } from "../ui";

function statusTone(status: string): BadgeTone {
  if (status === "PRESENT") return "pass";
  if (status === "PROMINENCE_INSUFFICIENT" || status === "IN_PRODUCT_DOC_ONLY") return "revise";
  if (status === "MISSING" || status === "PRESENT_BUT_NEGATED") return "reject";
  return "neutral";
}

function anchorById(result: ReviewOutput, anchorId?: string): ContextAnchor | undefined {
  if (!anchorId) return undefined;
  return result.context_anchors?.find((anchor) => anchor.anchor_id === anchorId);
}

function RevisionCard({
  result,
  anchor,
  title,
  basis,
  rationale,
  resolved,
  onToggleResolve,
}: {
  result: ReviewOutput;
  anchor: ContextAnchor;
  title: string;
  basis: string;
  rationale: string;
  resolved: boolean;
  onToggleResolve: (id: string) => void;
}) {
  const revision = revisionFor(result, anchor.anchor_id);
  const claimFacts = productClaimFactsForAnchor(result, anchor);
  const productEvidence = claimFacts.flatMap((fact) =>
    productComparisonsForClaimFact(result, fact.claim_fact_id).map((comparison) => ({
      fact,
      comparison,
      productFact: productFactById(result, comparison.product_fact_id),
    })),
  );

  if (!revision) return null;

  return (
    <article className={`overflow-hidden rounded-[12px] border bg-surface ${resolved ? "border-pass/40" : "border-line"}`}>
      <div className="flex flex-wrap items-start gap-2 border-b border-line bg-surface-2 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-extrabold text-ink">{title}</h3>
          {basis && <p className="mt-1 text-xs leading-relaxed text-ink-3">{basis}</p>}
        </div>
        <Badge tone={resolved ? "pass" : "revise"}>{resolved ? "적용됨" : "수정 후보"}</Badge>
      </div>

      <div className="grid gap-3 p-4 lg:grid-cols-2">
        <section className="rounded-[10px] border border-reject/25 bg-reject/5 p-3">
          <div className="mb-1.5 text-[11px] font-extrabold tracking-wider text-reject uppercase">Before</div>
          <p className="text-[13.5px] leading-relaxed font-semibold text-ink">“{revision.before}”</p>
        </section>
        <section className="rounded-[10px] border border-pass/30 bg-pass/5 p-3">
          <div className="mb-1.5 text-[11px] font-extrabold tracking-wider text-pass uppercase">After</div>
          <p className="text-[13.5px] leading-relaxed font-semibold text-ink">“{revision.after}”</p>
        </section>
      </div>

      <div className="space-y-3 border-t border-line px-4 py-3">
        {(rationale || revision.notes_for_reviewer) && (
          <div className="rounded-[10px] bg-surface-2 px-3 py-2">
            <div className="text-[11px] font-bold tracking-wider text-ink-4">검토 메모</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
              {revision.notes_for_reviewer || rationale}
            </p>
          </div>
        )}

        {productEvidence.length > 0 && (
          <div>
            <div className="mb-1.5 text-[11px] font-bold tracking-wider text-ink-4">상품 사실 대조</div>
            <div className="flex flex-col gap-1.5">
              {productEvidence.slice(0, 3).map(({ fact, comparison, productFact }) => (
                <div key={comparison.comparison_id} className="rounded-[9px] border border-line bg-surface-2 px-3 py-2 text-[12px]">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Tag tone={comparison.status === "SUPPORTED" ? "ok" : comparison.status === "CONTRADICTED" ? "danger" : "review"}>
                      {comparison.status}
                    </Tag>
                    <span className="font-semibold text-ink">{fact.value}</span>
                    {productFact?.value && <span className="text-ink-3">→ 문서: {productFact.value}{productFact.unit ? ` ${productFact.unit}` : ""}</span>}
                  </div>
                  {comparison.rationale && <p className="mt-1 leading-relaxed text-ink-3">{comparison.rationale}</p>}
                </div>
              ))}
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={() => onToggleResolve(anchor.anchor_id)}
          className={`inline-flex items-center rounded-md border px-3 py-1.5 text-xs font-extrabold ${
            resolved
              ? "border-pass/40 bg-pass/10 text-pass"
              : "border-brand bg-brand text-white shadow-[0_6px_14px_rgba(47,109,240,.18)]"
          }`}
        >
          {resolved ? "적용 취소" : "수정안 적용"}
        </button>
      </div>
    </article>
  );
}

export function RevisionTab({
  result,
  reviewedText,
  resolved,
  onToggleResolve,
}: {
  result: ReviewOutput | null;
  reviewedText: string;
  resolved: Set<string>;
  onToggleResolve: (id: string) => void;
}) {
  const [showFullRevision, setShowFullRevision] = useState(false);
  const issueCards = useMemo(
    () => (result ? buildIssueCards(result).filter((card) => card.kind === "anchor" && card.anchorId) : []),
    [result],
  );

  if (!result) return <EmptyState>Review를 실행하면 수정 문안 후보가 여기에 표시됩니다.</EmptyState>;

  const docRevision = correctedDocument(result);
  const diff = docRevision ? buildDocumentDiff(reviewedText, docRevision) : null;
  const missingSlots = requiredDisclosureSlots(result);
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const satisfiedChecks = checks.filter(disclosureIsSatisfied);
  const productStatus = result.product_fact_context?.extraction_status ?? "UNKNOWN";

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-extrabold text-ink">수정 문안 워크벤치</h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-3">
              위험 표현은 완화하고, 이미 충족된 고지는 유지하도록 Before/After를 검토합니다.
            </p>
          </div>
          <Badge tone={productStatus === "EXTRACTED" ? "pass" : productStatus === "NEEDS_PRODUCT_SELECTION" ? "review" : "neutral"}>
            상품 사실 대조 · {productStatus}
          </Badge>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <div className="rounded-[12px] border border-line bg-surface-2 p-3">
            <div className="mb-2 text-[11px] font-extrabold tracking-wider text-ink-4 uppercase">유지해야 할 고지</div>
            {satisfiedChecks.length ? (
              <div className="flex flex-wrap gap-1.5">
                {satisfiedChecks.slice(0, 8).map((check) => (
                  <Tag key={check.check_id} tone="ok">
                    {check.label}
                  </Tag>
                ))}
              </div>
            ) : (
              <p className="text-xs text-ink-3">현재 문안에서 명확히 충족된 고지를 찾지 못했습니다.</p>
            )}
          </div>

          <div className="rounded-[12px] border border-line bg-surface-2 p-3">
            <div className="mb-2 text-[11px] font-extrabold tracking-wider text-ink-4 uppercase">추가/보완 고지</div>
            {missingSlots.length ? (
              <div className="flex flex-col gap-1.5">
                {missingSlots.slice(0, 5).map((slot) => (
                  <div key={slot.checkId} className="flex flex-wrap items-center gap-1.5 text-xs">
                    <Badge tone={statusTone(disclosureStatus(checks.find((check) => check.check_id === slot.checkId) ?? {}))}>
                      {disclosureStatusLabel(disclosureStatus(checks.find((check) => check.check_id === slot.checkId) ?? {}))}
                    </Badge>
                    <span className="font-bold text-ink">{slot.label}</span>
                    <span className="text-ink-4">{slot.source}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-ink-3">추가로 보완할 필수 고지가 없습니다.</p>
            )}
          </div>
        </div>
      </section>

      {docRevision && diff && (
        <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-extrabold text-ink">전체 교정본</h3>
              <p className="mt-1 text-xs text-ink-3">원문 흐름을 유지한 문서 단위 수정안입니다.</p>
            </div>
            <button
              type="button"
              onClick={() => setShowFullRevision((value) => !value)}
              className="rounded-md border border-line px-3 py-1.5 text-xs font-bold text-ink-2 hover:border-brand hover:text-brand"
            >
              {showFullRevision ? "접기" : "펼치기"}
            </button>
          </div>
          {showFullRevision && (
            <div className="rounded-[12px] border border-pass/25 bg-pass/5 p-3 text-[13.5px] leading-8 text-ink">
              {diff.segments.map((segment, index) => (
                <span key={`${index}_${segment.text.slice(0, 8)}`} className={segment.changed ? "rounded bg-pass/15 px-1 font-semibold text-pass" : ""}>
                  {segment.text}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="flex flex-col gap-3">
        {issueCards.length ? (
          issueCards.map((card) => {
            const anchor = anchorById(result, card.anchorId);
            if (!anchor) return null;
            return (
              <RevisionCard
                key={card.id}
                result={result}
                anchor={anchor}
                title={card.title}
                basis={card.basis}
                rationale={card.rationale}
                resolved={resolved.has(anchor.anchor_id)}
                onToggleResolve={onToggleResolve}
              />
            );
          })
        ) : (
          <EmptyState>수정이 필요한 표현 이슈가 없습니다.</EmptyState>
        )}
      </section>
    </div>
  );
}
