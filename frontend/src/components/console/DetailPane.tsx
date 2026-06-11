"use client";

import { riskGrade } from "@/lib/labels";
import {
  buildIssueCards,
  chainNodeLabel,
  chainsForAnchor,
  claimQualifiers,
  disclosureSignals,
  effectiveJudgmentsForAnchor,
  planItemsForAnchor,
  productClaimFactsForAnchor,
  productComparisonsForClaimFact,
  safeAlternative,
  shorten,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { Meter, Tag } from "../ui";
import { DetailRow, PaneHeader } from "./common";
import { TONE_BG, TONE_COLOR, TONE_WORD_SHORT } from "./RiskList";

interface Props {
  result: ReviewOutput;
  selectedAnchorId: string;
  resolved: Set<string>;
  onToggleResolve: (id: string) => void;
  onGotoGraph: () => void;
}

function EmptyDetail() {
  return (
    <div className="flex h-full flex-col">
      <PaneHeader icon="target" title="판정 상세" sub="항목을 선택하세요" />
      <div className="grid flex-1 place-items-center p-6 text-center text-[13px] text-ink-4">
        <div>
          <Icon name="target" size={34} color="var(--line-2)" style={{ margin: "0 auto" }} />
          <div className="mt-3">
            좌측 광고의 위험 표현 또는
            <br />
            중앙 위험 카드를 선택하면
            <br />
            판정 근거가 여기에 표시됩니다.
          </div>
        </div>
      </div>
    </div>
  );
}

function TrackBDetail({ result }: { result: ReviewOutput }) {
  const trackB = result.overall_impression_judgment ?? {};
  const score = Number(trackB.misleading_risk_score ?? 0);
  const grade = riskGrade(score);
  const color = grade.tone === "reject" ? "var(--reject)" : grade.tone === "review" ? "var(--revise)" : "var(--pass)";
  return (
    <div className="flex h-full flex-col">
      <PaneHeader icon="target" title="판정 상세" sub="소비자 오인 · Track B" />
      <div className="flex-1 overflow-y-auto px-4.5 pt-4 pb-6" style={{ animation: "nodeIn .3s" }}>
        <div className="mb-2 flex items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: color }} />
          <span className="text-[13px] font-bold" style={{ color }}>
            전체 인상 판단 · 오인 위험 {grade.label}
          </span>
        </div>
        <div
          className="rounded-[10px] p-3.5 text-[14px] leading-relaxed break-keep"
          style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
        >
          {trackB.representative_consumer_impression}
        </div>
        <div className="mt-3 flex items-center gap-3">
          <span
            className="shrink-0 rounded-md px-2 py-1 font-mono text-[11px] font-extrabold tracking-wide"
            style={{ color, background: grade.tone === "reject" ? "var(--reject-bg)" : grade.tone === "review" ? "var(--revise-bg)" : "var(--pass-bg)" }}
          >
            TRACK B
          </span>
          <div className="flex-1">
            <div className="mb-1 flex justify-between text-[11px]">
              <span className="font-semibold text-ink-3">오인 위험</span>
              <span className="font-bold" style={{ color }}>
                {grade.label}
              </span>
            </div>
            <Meter value={score * 100} color={color} title={`misleading_risk_score ${score.toFixed(2)}`} />
          </div>
        </div>
        <DetailRow icon="alert" label="판단 이유">
          <p className="m-0 text-[13px] leading-relaxed text-ink-2">{trackB.why || "-"}</p>
        </DetailRow>
        <DetailRow icon="layers" label="오인 요인">
          <ul className="m-0 list-disc space-y-1 pl-4 text-[12.5px] leading-relaxed text-ink-2">
            {(trackB.misleading_factors ?? []).map((factor, index) => (
              <li key={index}>{factor}</li>
            ))}
          </ul>
        </DetailRow>
        <DetailRow icon="graph" label="근거 경로 (Claim → 인상 → 효과)">
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
        <p className="mt-2 text-[11px] text-ink-4">대법원 ‘전체적·궁극적 인상’ 기준(2017두60109)에 대응하는 판단입니다.</p>
      </div>
    </div>
  );
}

export function DetailPane({ result, selectedAnchorId, resolved, onToggleResolve, onGotoGraph }: Props) {
  if (selectedAnchorId === "trackB") return <TrackBDetail result={result} />;

  const anchor = result.context_anchors?.find((item) => item.anchor_id === selectedAnchorId);
  const cards = buildIssueCards(result);
  const card = cards.find((item) => item.id === selectedAnchorId || item.anchorId === selectedAnchorId);

  // 고지 누락 카드 (anchor 없음)
  if (!anchor && card?.kind === "disclosure") {
    const isResolved = resolved.has(card.id);
    return (
      <div className="flex h-full flex-col">
        <PaneHeader icon="flag" title="판정 상세" sub={`${card.code} · 필수 고지`} />
        <div className="flex-1 overflow-y-auto px-4.5 pt-4 pb-6" style={{ animation: "nodeIn .3s" }}>
          <div className="mb-2 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full" style={{ background: isResolved ? "var(--pass)" : "var(--revise)" }} />
            <span className="text-[13px] font-bold" style={{ color: isResolved ? "var(--pass)" : "var(--revise)" }}>
              {isResolved ? "고지 반영 · 해소" : "필수 고지 누락"}
            </span>
          </div>
          <div
            className="rounded-[10px] p-3.5 text-[16px] font-bold break-keep"
            style={{ background: isResolved ? "var(--pass-bg)" : "var(--revise-bg)", border: "1px solid var(--line)" }}
          >
            {card.quote}
          </div>
          <DetailRow icon="clause" label="근거">
            <div className="font-mono text-[12px] font-bold text-brand-2">{card.basis}</div>
          </DetailRow>
          <DetailRow icon="alert" label="누락 사유">
            <p className="m-0 text-[13px] leading-relaxed text-ink-2">{card.rationale}</p>
          </DetailRow>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => onToggleResolve(card.id)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2.5 text-[13.5px] font-bold ${
                isResolved ? "bg-surface-3 text-ink-2" : "bg-brand text-white shadow-[0_4px_12px_rgba(47,109,240,.25)]"
              }`}
            >
              <Icon name={isResolved ? "x" : "check"} size={15} />
              {isResolved ? "반영 취소" : "고지 반영 처리"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!anchor || !card) return <EmptyDetail />;

  const tone = card.tone;
  const color = TONE_COLOR[tone];
  const isResolved = resolved.has(card.id);
  const headColor = isResolved ? "var(--pass)" : color;
  const effective = effectiveJudgmentsForAnchor(result, anchor.anchor_id);
  const risky = effective.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
  const topJudgment = risky[0] ?? effective[0];
  const plans = planItemsForAnchor(result, anchor.anchor_id);
  const topPlan = plans.find((item) => item.plan_item_id === topJudgment?.plan_item_id) ?? plans[0];
  const score = Number(topJudgment?.score ?? 0);
  const grade = riskGrade(score);
  const issues = (result.detected_issues ?? []).filter((issue) =>
    effective.some((judgment) => judgment.cu_id === issue.risk_code),
  );
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
  const comparisons = productClaimFactsForAnchor(result, anchor).flatMap((fact) =>
    productComparisonsForClaimFact(result, fact.claim_fact_id),
  );
  const principles = [...new Set(plans.map((item) => item.principle).filter(Boolean))];
  const articles = [...new Set(plans.map((item) => item.source_article).filter(Boolean))];

  return (
    <div className="flex h-full flex-col">
      <PaneHeader
        icon="target"
        title="판정 상세"
        sub={`${card.code} · ${card.label}`}
        right={
          isResolved ? (
            <Tag tone="ok">
              <Icon name="check" size={12} style={{ marginRight: 3 }} /> 해소됨
            </Tag>
          ) : (
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-bold"
              style={{ color, background: TONE_BG[tone] }}
            >
              {TONE_WORD_SHORT[tone]}
            </span>
          )
        }
      />
      <div key={anchor.anchor_id} className="flex-1 overflow-y-auto px-4.5 pt-4 pb-6" style={{ animation: "nodeIn .3s" }}>
        {/* 헤더 */}
        <div className="mb-2 flex items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: headColor }} />
          <span className="text-[13px] font-bold" style={{ color: headColor }}>
            {isResolved ? "수정안 적용 · 해소" : `${TONE_WORD_SHORT[tone]} · ${card.label}`}
          </span>
        </div>
        <div
          className="rounded-[10px] p-3.5 text-[17px] leading-normal font-bold break-keep"
          style={{
            background: isResolved ? "var(--pass-bg)" : TONE_BG[tone],
            border: `1px solid ${headColor}22`,
          }}
        >
          “{anchor.span.text}”
        </div>
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {principles.map((principle) => (
            <Tag key={principle}>{principle}</Tag>
          ))}
        </div>

        {/* 판정 · 신뢰도 */}
        <div className="mt-3 flex items-center gap-3">
          <span
            className="shrink-0 rounded-md px-2 py-1 font-mono text-[11px] font-extrabold tracking-wide"
            style={{
              color: headColor,
              background: isResolved ? "var(--pass-bg)" : TONE_BG[tone],
            }}
          >
            {isResolved ? "RESOLVED" : TONE_WORD_SHORT[tone]}
          </span>
          <div className="flex-1">
            <div className="mb-1 flex justify-between text-[11px]">
              <span className="font-semibold text-ink-3">위반 신뢰도</span>
              <span className="font-bold" style={{ color: headColor }}>
                {grade.label}
              </span>
            </div>
            <Meter value={score * 100} color={headColor} title={`score ${score.toFixed(2)}`} />
          </div>
        </div>

        {/* 판정 사유 */}
        <DetailRow icon="alert" label="판정 사유">
          <p className="m-0 text-[13.5px] leading-relaxed text-ink-2">
            {card.rationale || topJudgment?.why || "이 표현은 정책 매칭 결과 확인이 필요합니다."}
          </p>
        </DetailRow>

        {/* 문제 표현 */}
        {qualifiers.length > 0 && (
          <DetailRow icon="flag" label="문제 표현">
            <div className="flex flex-wrap gap-1.5">
              {qualifiers.map((item) => (
                <Tag key={item.qualifier_id || item.text} tone="review">
                  {item.text}
                </Tag>
              ))}
            </div>
          </DetailRow>
        )}

        {/* 연결된 심의 기준 (CU) */}
        {topPlan && (
          <DetailRow icon="layers" label="연결된 심의 기준">
            <div className="flex items-start gap-2.5 rounded-[10px] border border-line bg-surface-2 p-3">
              <span className="shrink-0 rounded-md bg-brand px-1.5 py-0.5 font-mono text-[11px] font-bold text-white">
                CU
              </span>
              <div className="min-w-0">
                <div className="text-[13.5px] font-bold text-ink">{topPlan.risk_title || topPlan.principle}</div>
                <div className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
                  {shorten(topPlan.constraint || topPlan.context, 220)}
                </div>
              </div>
            </div>
          </DetailRow>
        )}

        {/* 근거 조문 */}
        <DetailRow icon="clause" label="근거 조문">
          <div className="space-y-2">
            {articles.slice(0, 3).map((article, index) => {
              const evidence = plans.find((item) => item.source_article === article)?.evidence_texts?.[0];
              return (
                <div key={article} className="rounded-[10px] border border-line p-3">
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="font-mono text-[11.5px] font-bold text-brand-2">{article}</span>
                  </div>
                  {index === 0 && evidence && (
                    <div className="border-l-2 border-line-2 pl-2.5 text-[12.5px] leading-relaxed text-ink-2">
                      “{shorten(evidence, 220)}”
                    </div>
                  )}
                </div>
              );
            })}
            {legalChains.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {legalChains
                  .flatMap((chain) => chain.basis_nodes ?? [])
                  .slice(0, 5)
                  .map((node, index) => (
                    <Tag key={index}>{chainNodeLabel(node)}</Tag>
                  ))}
              </div>
            )}
          </div>
        </DetailRow>

        {/* 예외 · 고지 검토 */}
        <DetailRow icon="shield" label="예외 · 고지 검토">
          {exceptions.length ? (
            <div className="space-y-2">
              {exceptions.map((review) => (
                <div
                  key={review.exception_review_id}
                  className="flex items-start gap-2.5 rounded-[10px] border p-3"
                  style={{
                    borderColor: review.applies ? "#e7d3a6" : "var(--line)",
                    background: review.applies ? "var(--revise-bg)" : "var(--surface-2)",
                  }}
                >
                  <span
                    className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold whitespace-nowrap"
                    style={{
                      color: review.applies ? "var(--revise)" : "var(--ink-3)",
                      background: review.applies ? "#fff" : "var(--surface-3)",
                    }}
                  >
                    {review.applies ? `완화 가능 · ${review.effect}` : "완화 불가"}
                  </span>
                  <p className="m-0 text-[12.5px] leading-relaxed text-ink-2">{review.why}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {disclosureSignals(anchor).map((signal) => (
                <Tag key={signal} tone="ok">
                  {signal}
                </Tag>
              ))}
            </div>
          )}
        </DetailRow>

        {/* 상품 사실 대조 — 수치 클레임이 있을 때만 */}
        {comparisons.length > 0 && (
          <DetailRow icon="layers" label="상품 사실 대조">
            <div className="space-y-1.5">
              {comparisons.slice(0, 3).map((item) => (
                <div key={item.comparison_id} className="text-[12.5px] leading-relaxed text-ink-2">
                  <b
                    className={
                      item.status === "SUPPORTED"
                        ? "text-pass"
                        : item.status === "CONTRADICTED"
                          ? "text-reject"
                          : "text-revise"
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

        {/* 필요한 고지 */}
        <DetailRow icon="flag" label="필요한 고지">
          <div className="space-y-1.5">
            {[...(suggestion?.required_disclosures ?? []), ...missingChecks.map((check) => check.label)].map(
              (item, index) => (
                <div key={index} className="flex items-center gap-2 text-[13px] text-ink-2">
                  <span
                    className="grid h-[18px] w-[18px] shrink-0 place-items-center rounded"
                    style={{ background: isResolved ? "var(--pass-bg)" : "var(--reject-bg)" }}
                  >
                    <Icon
                      name={isResolved ? "check" : "x"}
                      size={12}
                      stroke={2.4}
                      color={isResolved ? "var(--pass)" : "var(--reject)"}
                    />
                  </span>
                  {item}
                </div>
              ),
            )}
            {!missingChecks.length && !(suggestion?.required_disclosures ?? []).length && (
              <span className="text-[12.5px] text-ink-3">추가로 요구되는 고지가 없습니다.</span>
            )}
          </div>
        </DetailRow>

        {/* 필요한 조치 */}
        {(issues[0]?.required_action || suggestion?.notes_for_reviewer) && (
          <DetailRow icon="target" label="필요한 조치">
            <div className="flex items-start gap-2.5">
              <Icon name="arrowR" size={16} color="var(--brand)" style={{ marginTop: 2, flexShrink: 0 }} />
              <div>
                <div className="text-[13.5px] font-bold text-ink">
                  {issues[0]?.required_action || "표현 수정 및 고지 보완"}
                </div>
                {suggestion?.notes_for_reviewer && (
                  <p className="m-0 mt-1 text-[12.5px] leading-relaxed text-ink-3">{suggestion.notes_for_reviewer}</p>
                )}
              </div>
            </div>
          </DetailRow>
        )}

        {/* 안전한 대체 문안 */}
        <DetailRow icon="spark" label="안전한 대체 문안">
          <div className="overflow-hidden rounded-[10px] border border-line">
            <div className="border-b border-[#f3d3cf] bg-reject-bg px-3 py-2.5">
              <div className="mb-1 flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-reject" />
                <span className="text-[10.5px] font-bold tracking-wider text-reject">BEFORE · 현재 문안</span>
              </div>
              <div className="text-[13px] leading-relaxed text-[#8a2e26] line-through decoration-[#d6453a66]">
                {suggestion?.before ?? anchor.span.text}
              </div>
            </div>
            <div className="bg-pass-bg px-3 py-2.5">
              <div className="mb-1 flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-pass" />
                <span className="text-[10.5px] font-bold tracking-wider text-pass">AFTER · 제안 문안</span>
                <span className="ml-auto font-mono text-[9.5px] font-bold text-ink-4">Revision LLM · 권고</span>
              </div>
              <div className="text-[13px] leading-relaxed font-medium text-[#0c6b4a]">
                {suggestion?.after ?? safeAlternative(anchor.span.text)}
              </div>
            </div>
          </div>
        </DetailRow>

        {/* 액션 */}
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => onToggleResolve(card.id)}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2.5 text-[13.5px] font-bold ${
              isResolved ? "bg-surface-3 text-ink-2" : "bg-brand text-white shadow-[0_4px_12px_rgba(47,109,240,.25)]"
            }`}
          >
            <Icon name={isResolved ? "x" : "check"} size={15} />
            {isResolved ? "적용 취소" : "수정안 적용"}
          </button>
          <button
            type="button"
            onClick={onGotoGraph}
            className="flex items-center gap-1.5 rounded-lg border border-line-2 bg-surface px-3.5 py-2.5 text-[13.5px] font-bold whitespace-nowrap text-ink-2"
          >
            <Icon name="graph" size={15} color="var(--ink-3)" /> 근거 경로
          </button>
        </div>
      </div>
    </div>
  );
}
