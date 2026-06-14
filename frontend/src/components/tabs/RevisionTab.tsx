"use client";

import { useMemo, useState } from "react";
import {
  buildCorrectedCopy,
  buildDocumentDiff,
  buildIssueCards,
  correctedDisclosureBlock,
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
import { Icon } from "../Icon";
import { Badge, EmptyState, Tag, type BadgeTone } from "../ui";

const GRADE_TINT: Record<string, { fg: string; bg: string }> = {
  높음: { fg: "var(--reject)", bg: "var(--reject-bg)" },
  중간: { fg: "var(--revise)", bg: "var(--revise-bg)" },
  낮음: { fg: "var(--review)", bg: "var(--review-bg)" },
};

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
  label,
  grade,
  basis,
  rationale,
  resolved,
  onToggleResolve,
}: {
  result: ReviewOutput;
  anchor: ContextAnchor;
  label: string;
  grade: string;
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
  const why = revision.why_problematic || rationale || "";
  const advice = revision.notes_for_reviewer && revision.notes_for_reviewer !== why ? revision.notes_for_reviewer : "";
  const tint = GRADE_TINT[grade] ?? GRADE_TINT["낮음"];

  return (
    <article
      className={`rounded-[18px] border bg-surface p-5 shadow-card ${resolved ? "border-pass/40" : "border-line"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="rounded-full px-2.5 py-0.5 text-[11.5px] font-extrabold"
              style={{ color: tint.fg, background: tint.bg }}
            >
              {label}
            </span>
            {grade && <span className="text-[11.5px] font-bold text-ink-4">위반 가능성 {grade}</span>}
          </div>
          {basis && <p className="mt-1.5 text-[12px] leading-relaxed text-ink-3">{basis}</p>}
        </div>
        <Badge tone={resolved ? "pass" : "neutral"}>{resolved ? "적용됨" : "검토 전"}</Badge>
      </div>

      <div className="mt-4">
        <div className="mb-2 text-[11px] font-extrabold tracking-wide text-ink-4">무엇이 수정되었나</div>
        <div className="grid items-stretch gap-2 sm:grid-cols-[1fr_auto_1fr]">
          <div className="rounded-[14px] border border-reject/15 bg-reject/5 px-4 py-3">
            <div className="mb-1 text-[10.5px] font-extrabold tracking-wider text-reject uppercase">Before</div>
            <p className="text-[13.5px] leading-relaxed font-semibold text-ink">{revision.before}</p>
          </div>
          <div className="flex items-center justify-center py-1 sm:py-0">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-brand/10">
              <Icon name="arrowR" size={16} color="var(--brand)" />
            </span>
          </div>
          <div className="rounded-[14px] border border-pass/20 bg-pass/5 px-4 py-3">
            <div className="mb-1 text-[10.5px] font-extrabold tracking-wider text-pass uppercase">After</div>
            <p className="text-[13.5px] leading-relaxed font-semibold text-ink">{revision.after}</p>
          </div>
        </div>
      </div>

      {why && (
        <div className="mt-4">
          <div className="mb-1.5 text-[11px] font-extrabold tracking-wide text-ink-4">수정 이유</div>
          <p className="rounded-[14px] bg-surface-2 px-4 py-3 text-[13px] leading-relaxed text-ink-2">{why}</p>
        </div>
      )}

      {productEvidence.length > 0 && (
        <div className="mt-4">
          <div className="mb-1.5 text-[11px] font-extrabold tracking-wide text-ink-4">상품 사실 대조</div>
          <div className="flex flex-col gap-1.5">
            {productEvidence.slice(0, 3).map(({ fact, comparison, productFact }) => (
              <div key={comparison.comparison_id} className="rounded-[12px] border border-line bg-surface-2 px-3.5 py-2.5 text-[12px]">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Tag tone={comparison.status === "SUPPORTED" ? "ok" : comparison.status === "CONTRADICTED" ? "danger" : "review"}>
                    {comparison.status}
                  </Tag>
                  <span className="font-semibold text-ink">{fact.value}</span>
                  {productFact?.value && (
                    <span className="text-ink-3">→ 문서: {productFact.value}{productFact.unit ? ` ${productFact.unit}` : ""}</span>
                  )}
                </div>
                {comparison.rationale && <p className="mt-1 leading-relaxed text-ink-3">{comparison.rationale}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {advice && (
        <div className="mt-3 rounded-[12px] border border-line bg-surface px-3.5 py-2.5">
          <div className="text-[10.5px] font-bold tracking-wide text-ink-4">심사자 참고</div>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-3">{advice}</p>
        </div>
      )}

      <button
        type="button"
        onClick={() => onToggleResolve(anchor.anchor_id)}
        className={`mt-4 inline-flex items-center gap-1.5 rounded-[12px] px-4 py-2.5 text-[13.5px] font-extrabold ${
          resolved
            ? "border border-pass/40 bg-pass/10 text-pass"
            : "bg-brand text-white shadow-[0_6px_16px_rgba(47,109,240,.22)]"
        }`}
      >
        <Icon name={resolved ? "x" : "check"} size={15} color={resolved ? "var(--pass)" : "#fff"} />
        {resolved ? "적용 취소" : "수정안 적용"}
      </button>
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
  const disclosureBlock = correctedDisclosureBlock(result);
  const missingSlots = requiredDisclosureSlots(result);
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const satisfiedChecks = checks.filter(disclosureIsSatisfied);
  const productStatus = result.product_fact_context?.extraction_status ?? "UNKNOWN";
  const proposedAnchorIds = new Set(issueCards.map((card) => card.anchorId).filter((id): id is string => Boolean(id)));
  const proposedCorrection = docRevision
    ? buildDocumentDiff(reviewedText, docRevision)
    : buildCorrectedCopy(result, reviewedText, proposedAnchorIds);
  const hasBodyChange = Boolean(docRevision) || proposedCorrection.changedCount > 0;
  const hasFullRevision = hasBodyChange || Boolean(disclosureBlock);

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-extrabold text-ink">수정 문안 워크벤치</h2>
            <p className="mt-1 text-xs leading-relaxed text-ink-3">
              전체 문안이 어떻게 바뀌는지 먼저 확인하고, 아래에서 개별 수정 근거를 검토합니다.
            </p>
          </div>
          <Badge tone={productStatus === "EXTRACTED" ? "pass" : productStatus === "NEEDS_PRODUCT_SELECTION" ? "review" : "neutral"}>
            상품 사실 대조 · {productStatus}
          </Badge>
        </div>

        <div className="mt-4 rounded-[14px] border border-line bg-surface-2 p-3">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-extrabold text-ink">전체 Before → After</h3>
              <p className="mt-1 text-xs leading-relaxed text-ink-3">
                {hasFullRevision
                  ? `변경 후보 ${proposedCorrection.changedCount}곳을 전체 문안 흐름 안에서 표시합니다.`
                  : "아직 문서 단위 수정안이 생성되지 않았습니다."}
              </p>
            </div>
            {docRevision ? <Badge tone="pass">문서 단위 수정안</Badge> : <Badge tone="revise">이슈별 수정안 합성</Badge>}
          </div>
          <div className="grid gap-3 xl:grid-cols-2">
            <section className="min-h-[220px] rounded-[12px] border border-reject/20 bg-reject/5">
              <div className="flex items-center justify-between border-b border-reject/15 px-3 py-2">
                <span className="text-[11px] font-extrabold tracking-wider text-reject uppercase">Before · 원문</span>
                <span className="text-[11px] font-semibold text-ink-4">{reviewedText.length}자</span>
              </div>
              <div className="max-h-[420px] overflow-auto whitespace-pre-wrap p-3 text-[13.5px] leading-7 text-ink">
                {reviewedText || "원문이 없습니다."}
              </div>
            </section>
            <section className="min-h-[220px] rounded-[12px] border border-pass/25 bg-pass/5">
              <div className="flex items-center justify-between border-b border-pass/20 px-3 py-2">
                <span className="text-[11px] font-extrabold tracking-wider text-pass uppercase">After · 수정안</span>
                <span className="text-[11px] font-semibold text-ink-4">초록 표시 = 변경/추가 후보</span>
              </div>
              <div className="max-h-[420px] overflow-auto whitespace-pre-wrap p-3 text-[13.5px] leading-7 text-ink">
                {hasFullRevision ? (
                  <>
                    {hasBodyChange ? (
                      proposedCorrection.segments.map((segment, index) => (
                        <span
                          key={`${index}_${segment.text.slice(0, 10)}`}
                          className={segment.changed ? "rounded bg-pass/15 px-1 font-semibold text-pass" : ""}
                        >
                          {segment.text}
                        </span>
                      ))
                    ) : (
                      <span>{reviewedText}</span>
                    )}
                    {disclosureBlock && (
                      <div className="mt-4 border-t border-pass/20 pt-3">
                        <div className="mb-1.5 text-[12px] font-extrabold text-ink-2">꼭 확인해 주세요!</div>
                        <ul className="m-0 list-none space-y-1 p-0">
                          {disclosureBlock.items.map((item) => (
                            <li key={item.check_id} className="flex gap-1.5 text-[13px] leading-6">
                              <span className={item.status === "add" ? "text-pass" : "text-revise"}>ㆍ</span>
                              <span>
                                {item.status === "add" ? (
                                  <span className="rounded bg-pass/15 px-1 font-semibold text-pass">{item.text}</span>
                                ) : (
                                  <span className="text-ink-3">
                                    {item.label} — <span className="font-semibold text-revise">심사자 보완</span>
                                    <span className="text-ink-4"> (심의필 번호 등 상품별 정보)</span>
                                  </span>
                                )}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                ) : (
                  <span className="text-ink-4">수정 제안이 없습니다.</span>
                )}
              </div>
            </section>
          </div>
        </div>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
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

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-extrabold text-ink">수정 제안</h3>
            <p className="mt-1 text-xs text-ink-3">문구별로 무엇을, 왜 바꿨는지 확인합니다.</p>
          </div>
          {docRevision && (
            <button
              type="button"
              onClick={() => setShowFullRevision((value) => !value)}
              className="rounded-md border border-line px-3 py-1.5 text-xs font-bold text-ink-2 hover:border-brand hover:text-brand"
            >
              {showFullRevision ? "문서 수정안 접기" : "문서 수정안 기준"}
            </button>
          )}
        </div>
        {showFullRevision && docRevision && (
          <div className="rounded-[12px] border border-pass/25 bg-pass/5 p-3 text-[13px] leading-7 text-ink">
            {docRevision}
          </div>
        )}
        {issueCards.length ? (
          issueCards.map((card) => {
            const anchor = anchorById(result, card.anchorId);
            if (!anchor) return null;
            return (
              <RevisionCard
                key={card.id}
                result={result}
                anchor={anchor}
                label={card.label}
                grade={card.grade}
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
