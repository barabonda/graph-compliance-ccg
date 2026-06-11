"use client";

import { riskGrade } from "@/lib/labels";
import {
  anchorDisplay,
  buildIssueCards,
  chainNodeLabel,
  chainsForAnchor,
  claimQualifiers,
  disclosureSignals,
  effectiveJudgmentsForAnchor,
  humanAnchorLabel,
  planItemsForAnchor,
  productClaimFactsForAnchor,
  productComparisonsForClaimFact,
  safeAlternative,
  shorten,
  verdictTone,
  type HighlightTone,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Tag } from "../ui";
import { DetailRow, PaneHeader } from "./common";

interface Props {
  result: ReviewOutput;
  selectedAnchorId: string;
  resolved: Set<string>;
  onToggleResolve: (id: string) => void;
  onGotoGraph: () => void;
}

const TONE_COLOR: Record<HighlightTone, string> = {
  risk: "var(--reject)",
  review: "var(--revise)",
  "keep-warning": "var(--revise)",
  keep: "var(--pass)",
  scope: "var(--ink-4)",
};

const TONE_BG: Record<HighlightTone, string> = {
  risk: "var(--reject-bg)",
  review: "var(--revise-bg)",
  "keep-warning": "var(--revise-bg)",
  keep: "var(--pass-bg)",
  scope: "var(--surface-3)",
};

function TrackBDetail({ result }: { result: ReviewOutput }) {
  const trackB = result.overall_impression_judgment ?? {};
  const grade = riskGrade(Number(trackB.misleading_risk_score ?? 0));
  return (
    <div className="flex-1 overflow-y-auto px-4.5 pt-4 pb-6" style={{ animation: "nodeIn .3s" }}>
      <div className="mb-2 flex items-center gap-2">
        <span className="h-2 w-2 rounded-full" style={{ background: grade.tone === "reject" ? "var(--reject)" : grade.tone === "review" ? "var(--revise)" : "var(--pass)" }} />
        <span className="text-[13px] font-bold">전체 인상 (Track B) · 오인 위험 {grade.label}</span>
      </div>
      <p className="rounded-[10px] border border-line bg-surface-2 p-3 text-[13.5px] leading-relaxed">
        {trackB.representative_consumer_impression}
      </p>
      <DetailRow label="판단 이유">
        <p className="m-0 text-[13px] leading-relaxed text-ink-2">{trackB.why || "-"}</p>
      </DetailRow>
      <DetailRow label="오인 요인">
        <ul className="m-0 list-disc space-y-1 pl-4 text-[12.5px] leading-relaxed text-ink-2">
          {(trackB.misleading_factors ?? []).map((factor, index) => (
            <li key={index}>{factor}</li>
          ))}
        </ul>
      </DetailRow>
      <DetailRow label="근거 경로 (Claim → 인상 → 효과)">
        <div className="space-y-2">
          {(trackB.evidence_paths ?? []).map((path, index) => (
            <div key={index} className="rounded-[10px] border border-line p-3 text-[12.5px] leading-relaxed text-ink-2">
              <b className="text-ink">{path.claim}</b>
              <br />
              {path.implicature || path.meaning}
              <br />→ {path.consumer_effect}
            </div>
          ))}
        </div>
      </DetailRow>
      <p className="mt-2 text-[11px] text-ink-4">대법원 ‘전체적·궁극적 인상’ 기준에 대응하는 판단입니다.</p>
    </div>
  );
}

export function DetailPane({ result, selectedAnchorId, resolved, onToggleResolve, onGotoGraph }: Props) {
  if (selectedAnchorId === "trackB") {
    return (
      <div className="flex h-full flex-col">
        <PaneHeader title="판정 상세" sub="소비자 오인 · Track B" />
        <TrackBDetail result={result} />
      </div>
    );
  }

  const anchor = result.context_anchors?.find((item) => item.anchor_id === selectedAnchorId);
  const card = buildIssueCards(result).find((item) => item.id === selectedAnchorId || item.anchorId === selectedAnchorId);

  if (!anchor) {
    return (
      <div className="flex h-full flex-col">
        <PaneHeader title="판정 상세" sub="항목을 선택하세요" />
        <div className="grid flex-1 place-items-center p-6 text-center text-[13px] text-ink-4">
          좌측 광고의 위험 표현 또는
          <br />
          중앙 위험 카드를 선택하면
          <br />
          판정 근거가 여기에 표시됩니다.
        </div>
      </div>
    );
  }

  const display = anchorDisplay(result, anchor.anchor_id);
  const tone = verdictTone(display?.display_verdict ?? "ANCHOR");
  const color = TONE_COLOR[tone];
  const isResolved = resolved.has(card?.id ?? anchor.anchor_id);
  const effective = effectiveJudgmentsForAnchor(result, anchor.anchor_id);
  const risky = effective.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
  const topJudgment = risky[0] ?? effective[0];
  const plans = planItemsForAnchor(result, anchor.anchor_id);
  const topPlan = plans.find((item) => item.plan_item_id === topJudgment?.plan_item_id) ?? plans[0];
  const grade = riskGrade(Number(topJudgment?.score ?? 0));
  const exceptions = (result.exception_reviews ?? []).filter((review) =>
    effective.some((judgment) => judgment.judgment_id === review.judgment_id),
  );
  const legalChains = chainsForAnchor(result.policy_evidence_chains?.legal_basis_chains, anchor.anchor_id).filter(
    (chain) => chain.status === "FOUND",
  );
  const suggestion = (result.revision_suggestions ?? []).find((item) => item.anchor_id === anchor.anchor_id);
  const qualifiers = claimQualifiers(result, anchor.claim_id);
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const missingChecks = checks.filter((check) => !check.present);
  const claimFacts = productClaimFactsForAnchor(result, anchor);
  const comparisons = claimFacts.flatMap((fact) => productComparisonsForClaimFact(result, fact.claim_fact_id));
  const label = humanAnchorLabel(result, anchor) || "검토 대상";

  return (
    <div className="flex h-full flex-col">
      <PaneHeader
        title="판정 상세"
        sub={label}
        right={
          isResolved ? (
            <Tag tone="ok">✓ 해소됨</Tag>
          ) : (
            <span className="text-[11.5px] font-bold" style={{ color }}>
              {tone === "risk" ? "위반 의심" : tone === "review" ? "검토 필요" : "검토됨"}
            </span>
          )
        }
      />
      <div key={anchor.anchor_id} className="flex-1 overflow-y-auto px-4.5 pt-4 pb-6" style={{ animation: "nodeIn .3s" }}>
        <div className="mb-2 flex items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: isResolved ? "var(--pass)" : color }} />
          <span className="text-[13px] font-bold" style={{ color: isResolved ? "var(--pass)" : color }}>
            {isResolved ? "수정안 적용 · 해소" : `${tone === "risk" ? "위반 의심" : "검토 필요"} — ${label}`}
          </span>
        </div>
        <div
          className="rounded-[10px] p-3.5 text-[16px] leading-normal font-bold break-keep"
          style={{ background: isResolved ? "var(--pass-bg)" : TONE_BG[tone], border: `1px solid ${(isResolved ? "var(--pass)" : color)}22` }}
        >
          “{anchor.span.text}”
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {[...new Set(plans.map((item) => item.principle).filter(Boolean))].map((principle) => (
            <Tag key={principle}>{principle}</Tag>
          ))}
          <span
            className="ml-auto text-[11.5px] font-bold"
            title={topJudgment ? `score ${Number(topJudgment.score ?? 0).toFixed(2)}` : undefined}
          >
            위반 신뢰도{" "}
            <span className={grade.tone === "reject" ? "text-reject" : grade.tone === "review" ? "text-revise" : "text-pass"}>
              {grade.label}
            </span>
          </span>
        </div>

        <DetailRow label="판정 사유">
          <p className="m-0 text-[13px] leading-relaxed text-ink-2">
            {card?.rationale || topJudgment?.why || "이 표현은 정책 매칭 결과 확인이 필요합니다."}
          </p>
        </DetailRow>

        {qualifiers.length > 0 && (
          <DetailRow label="문제 표현">
            <div className="flex flex-wrap gap-1.5">
              {qualifiers.map((item) => (
                <Tag key={item.qualifier_id || item.text} tone="review">
                  {item.text}
                </Tag>
              ))}
            </div>
          </DetailRow>
        )}

        {topPlan && (
          <DetailRow label="연결된 심의 기준">
            <div className="flex items-start gap-2.5 rounded-[10px] border border-line bg-surface-2 p-3">
              <div className="min-w-0">
                <div className="text-[13px] font-bold text-ink">{topPlan.risk_title || topPlan.principle}</div>
                <div className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
                  {shorten(topPlan.constraint || topPlan.context, 200)}
                </div>
              </div>
            </div>
          </DetailRow>
        )}

        <DetailRow label="근거 조문">
          <div className="space-y-2">
            {[...new Set(plans.map((item) => item.source_article).filter(Boolean))].slice(0, 3).map((article) => (
              <div key={article} className="rounded-[10px] border border-line p-3">
                <div className="font-mono text-[11.5px] font-bold text-brand-2">{article}</div>
              </div>
            ))}
            {legalChains.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {legalChains.flatMap((chain) => chain.basis_nodes ?? []).slice(0, 5).map((node, index) => (
                  <Tag key={index}>{chainNodeLabel(node)}</Tag>
                ))}
              </div>
            )}
            {topPlan?.evidence_texts?.[0] && (
              <div className="border-l-2 border-line-2 pl-2.5 text-[12px] leading-relaxed text-ink-2">
                “{shorten(topPlan.evidence_texts[0], 220)}”
              </div>
            )}
          </div>
        </DetailRow>

        <DetailRow label="예외 · 고지 검토">
          <div className="space-y-2">
            {exceptions.length ? (
              exceptions.map((review) => (
                <div
                  key={review.exception_review_id}
                  className="flex items-start gap-2.5 rounded-[10px] border p-3"
                  style={{
                    borderColor: review.applies ? "#e7d3a6" : "var(--line)",
                    background: review.applies ? "var(--revise-bg)" : "var(--surface-2)",
                  }}
                >
                  <Tag tone={review.applies ? "review" : undefined}>
                    {review.applies ? `완화 가능 · ${review.effect}` : "완화 불가"}
                  </Tag>
                  <p className="m-0 text-[12.5px] leading-relaxed text-ink-2">{review.why}</p>
                </div>
              ))
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {disclosureSignals(anchor).map((signal) => (
                  <Tag key={signal} tone="ok">
                    {signal}
                  </Tag>
                ))}
              </div>
            )}
          </div>
        </DetailRow>

        {comparisons.length > 0 && (
          <DetailRow label="상품 사실 대조">
            <div className="space-y-1.5">
              {comparisons.slice(0, 3).map((item) => (
                <div key={item.comparison_id} className="text-[12.5px] leading-relaxed text-ink-2">
                  <b
                    className={
                      item.status === "SUPPORTED" ? "text-pass" : item.status === "CONTRADICTED" ? "text-reject" : "text-revise"
                    }
                  >
                    {item.status}
                  </b>{" "}
                  · {shorten(item.rationale ?? "", 140)}
                </div>
              ))}
            </div>
          </DetailRow>
        )}

        <DetailRow label="필요한 고지">
          <div className="space-y-1.5">
            {(suggestion?.required_disclosures ?? []).map((item, index) => (
              <div key={`s_${index}`} className="flex items-center gap-2 text-[13px] text-ink-2">
                <span className="grid h-4.5 w-4.5 shrink-0 place-items-center rounded bg-reject-bg text-[11px] text-reject">✕</span>
                {item}
              </div>
            ))}
            {missingChecks.map((check) => (
              <div key={check.check_id} className="flex items-center gap-2 text-[13px] text-ink-2">
                <span className="grid h-4.5 w-4.5 shrink-0 place-items-center rounded bg-reject-bg text-[11px] text-reject">✕</span>
                {check.label}
              </div>
            ))}
            {!missingChecks.length && !(suggestion?.required_disclosures ?? []).length && (
              <span className="text-[12.5px] text-ink-3">추가로 요구되는 고지가 없습니다.</span>
            )}
          </div>
        </DetailRow>

        <DetailRow label="안전한 대체 문안">
          <div className="overflow-hidden rounded-[10px] border border-line">
            <div className="border-b border-[#f3d3cf] bg-reject-bg px-3 py-2.5">
              <div className="mb-1 text-[10.5px] font-bold tracking-wider text-reject">BEFORE · 현재 문안</div>
              <div className="text-[13px] leading-relaxed text-[#8a2e26] line-through decoration-[#d6453a66]">
                {suggestion?.before ?? anchor.span.text}
              </div>
            </div>
            <div className="bg-pass-bg px-3 py-2.5">
              <div className="mb-1 text-[10.5px] font-bold tracking-wider text-pass">AFTER · 제안 문안 (권고)</div>
              <div className="text-[13px] leading-relaxed font-medium text-[#0c6b4a]">
                {suggestion?.after ?? safeAlternative(anchor.span.text)}
              </div>
            </div>
          </div>
          {suggestion?.notes_for_reviewer && (
            <p className="mt-2 text-[11.5px] leading-relaxed text-ink-3">{suggestion.notes_for_reviewer}</p>
          )}
        </DetailRow>

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => onToggleResolve(card?.id ?? anchor.anchor_id)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2.5 text-[13.5px] font-bold ${
              isResolved ? "bg-surface-3 text-ink-2" : "bg-brand text-white shadow-[0_4px_12px_rgba(47,109,240,.25)]"
            }`}
          >
            {isResolved ? "적용 취소" : "✓ 수정안 적용"}
          </button>
          <button
            type="button"
            onClick={onGotoGraph}
            className="rounded-lg border border-line-2 bg-surface px-3.5 py-2.5 text-[13.5px] font-bold whitespace-nowrap text-ink-2"
          >
            근거 경로
          </button>
        </div>
      </div>
    </div>
  );
}
