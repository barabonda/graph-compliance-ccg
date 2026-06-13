"use client";

import { JUDGMENT_STATUS, judgmentBadgeTone, riskGrade } from "@/lib/labels";
import {
  aggregationForAnchor,
  buildIssueCards,
  buildOverallImpressionGraph,
  claimQualifiers,
  clauseEvidenceForAnchor,
  delegationByPrinciple,
  disclosureDocCrossRef,
  disclosureSignals,
  effectiveJudgmentsForAnchor,
  planItemsForAnchor,
  productClaimFactsForAnchor,
  productComparisonsForClaimFact,
  safeAlternative,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { Badge, Expandable, KeyValueText, Meter, Tag } from "../ui";
import { DelegationChain } from "./DelegationChain";
import { OverallImpressionGraph } from "./OverallImpressionGraph";
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
  const graph = buildOverallImpressionGraph(result);
  const syn = trackB.synthesized_evidence;
  const ROLE_KO: Record<string, string> = {
    benefit_claim: "혜택",
    condition_disclosure: "조건 고지",
    risk_disclosure: "위험 고지",
    protection_disclosure: "보호 고지",
  };
  return (
    <div className="flex h-full flex-col">
      <PaneHeader icon="target" title="판정 상세" sub="소비자 오인 · 종합 심사" />
      <div className="flex-1 overflow-y-auto px-4.5 pt-4 pb-6" style={{ animation: "nodeIn .3s" }}>
        {/* 헤더 등급 (수치는 hover) */}
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-[13px] font-bold" style={{ color }}>
            <span className="h-2 w-2 rounded-full" style={{ background: color }} />
            전체 인상 판단
          </span>
          <span className="text-[12px] font-bold" style={{ color }} title={`misleading_risk_score ${score.toFixed(2)}`}>
            오인 위험 {grade.label}
          </span>
        </div>
        {/* 종합 결론 한 단락 */}
        {trackB.representative_consumer_impression && (
          <div
            className="rounded-[10px] p-3.5 text-[13.5px] leading-relaxed break-keep text-ink"
            style={{ background: "var(--surface-2)", border: "1px solid var(--line)" }}
          >
            {trackB.representative_consumer_impression}
          </div>
        )}
        {/* 근거 그래프 (혜택 주장 ← 완화/강화) */}
        <div className="mt-3">
          <div className="mb-1.5 text-[10.5px] font-bold tracking-wider text-ink-4">근거 · 혜택 주장과 완화/강화</div>
          <OverallImpressionGraph graph={graph} />
        </div>
        {/* 점진적 공개 — 문장별 상세는 펼쳐야 보인다 */}
        <div className="mt-3">
          <Expandable header={<span className="text-[12px] font-bold text-ink-2">문장별 상세 · 근거 더보기</span>}>
            <div className="space-y-3 px-3 py-2.5">
              {trackB.why && (
                <div>
                  <div className="mb-1 text-[10.5px] font-bold tracking-wider text-ink-4">판단 이유</div>
                  <p className="m-0 text-[12.5px] leading-relaxed text-ink-2">{trackB.why}</p>
                </div>
              )}
              {(trackB.misleading_factors?.length ?? 0) > 0 && (
                <div>
                  <div className="mb-1 text-[10.5px] font-bold tracking-wider text-ink-4">오인 요인</div>
                  <ul className="m-0 list-disc space-y-1 pl-4 text-[12px] leading-relaxed text-ink-2">
                    {trackB.misleading_factors!.map((factor, index) => (
                      <li key={index}>{factor}</li>
                    ))}
                  </ul>
                </div>
              )}
              {(syn?.sentence_layers?.length ?? 0) > 0 && (
                <div>
                  <div className="mb-1 text-[10.5px] font-bold tracking-wider text-ink-4">문장 위계</div>
                  <div className="space-y-1">
                    {syn!.sentence_layers!.map((layer, index) => (
                      <div key={index} className="flex items-start gap-2 text-[12px]">
                        <span className="shrink-0 rounded bg-surface-3 px-1.5 py-0.5 text-[10px] font-bold text-ink-3">
                          {ROLE_KO[layer.role ?? ""] ?? layer.role}
                        </span>
                        <span className="min-w-0 text-ink-2">{layer.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Expandable>
        </div>
        <p className="mt-3 text-[11px] text-ink-4">대법원 ‘전체적·궁극적 인상’ 기준(2017두60109)에 대응하는 판단입니다.</p>
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
          {(() => {
            const checkId = card.id.replace(/^disclosure_/, "");
            const crossRef = disclosureDocCrossRef(result, checkId, card.quote);
            if (crossRef.status === "no_doc") return null;
            const inDoc = crossRef.status === "in_doc";
            return (
              <DetailRow icon="layers" label="상품설명서 대조">
                <div
                  className="rounded-[10px] p-3"
                  style={{
                    background: inDoc ? "var(--revise-bg)" : "var(--surface-2)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <div
                    className="mb-1 text-[12.5px] font-bold"
                    style={{ color: inDoc ? "var(--revise)" : "var(--ink-2)" }}
                  >
                    {inDoc
                      ? "상품설명서에는 명시되어 있으나 광고 문안에 없습니다"
                      : "광고와 상품설명서 모두에서 확인되지 않았습니다"}
                  </div>
                  <p className="m-0 mb-2 text-[12px] leading-relaxed text-ink-3">
                    {inDoc
                      ? "상품설명서·약관에 근거가 있으므로 해당 내용을 광고 문안에 함께 표시하면 누락이 해소됩니다."
                      : "상품설명서에서도 근거를 찾지 못했습니다. 표시 가능 여부를 상품 부서와 확인하세요."}
                  </p>
                  {crossRef.facts.map((fact) => (
                    <div
                      key={fact.fact_id}
                      className="mt-1 flex items-baseline gap-2 text-[12px] leading-relaxed"
                    >
                      <span className="shrink-0 font-semibold text-ink-2">{fact.fact_type}</span>
                      <span className="min-w-0 text-ink-3">
                        {fact.value}
                        {fact.page_or_chunk ? (
                          <span className="ml-1.5 font-mono text-[10.5px] text-ink-4">· {fact.page_or_chunk}</span>
                        ) : null}
                      </span>
                    </div>
                  ))}
                </div>
              </DetailRow>
            );
          })()}
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
  // 법령 위임 사슬 (법률→시행령→감독규정→심의기준) — 여러 chain의 단계를 병합.
  const delegationGroups = delegationByPrinciple(result, anchor.anchor_id).filter((g) => g.steps.length > 0);
  const clauseEvidence = clauseEvidenceForAnchor(result, anchor.anchor_id);
  const aggregationRows = aggregationForAnchor(result, anchor);
  const suggestion = (result.revision_suggestions ?? []).find((item) => item.anchor_id === anchor.anchor_id);
  const qualifiers = claimQualifiers(result, anchor.claim_id);
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const missingChecks = checks.filter((check) => !check.present);
  const comparisons = productClaimFactsForAnchor(result, anchor).flatMap((fact) =>
    productComparisonsForClaimFact(result, fact.claim_fact_id),
  );
  const principles = [...new Set(plans.map((item) => item.principle).filter(Boolean))];

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
              <span className="font-semibold text-ink-3">위반 가능성</span>
              <span className="font-bold" style={{ color: headColor }}>
                {grade.label}
              </span>
            </div>
            <Meter value={score * 100} color={headColor} title={`score ${score.toFixed(2)}`} />
          </div>
        </div>

        {/* 판정 사유 — 금감원 답변식: 정의 → 요건별 사실 적용 → 결론 → 유보 */}
        <DetailRow icon="alert" label="판정 사유">
          {topJudgment?.legal_basis || (topJudgment?.criteria_findings?.length ?? 0) > 0 ? (
            <div className="space-y-2.5">
              {topJudgment?.legal_basis && (
                <div className="rounded-md border border-line bg-surface-2 px-3 py-2">
                  <span className="text-[10.5px] font-bold tracking-wider text-ink-4">적용 법리</span>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-ink-2">{topJudgment.legal_basis}</p>
                </div>
              )}
              {(topJudgment?.criteria_findings?.length ?? 0) > 0 && (
                <div>
                  <span className="text-[10.5px] font-bold tracking-wider text-ink-4">판단 기준별 적용</span>
                  <ol className="mt-1 space-y-1.5">
                    {topJudgment!.criteria_findings!.map((cf, i) => (
                      <li key={i} className="flex gap-2 rounded-md border border-line px-2.5 py-1.5">
                        <span
                          className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded text-[10px] font-bold"
                          style={{
                            background: cf.satisfied ? "var(--reject-bg)" : "var(--surface-3)",
                            color: cf.satisfied ? "var(--reject)" : "var(--ink-4)",
                          }}
                        >
                          {cf.satisfied ? "●" : "○"}
                        </span>
                        <div className="min-w-0">
                          <span className="text-[12.5px] font-bold text-ink">{cf.criterion}</span>
                          <span className={`ml-1.5 text-[11px] ${cf.satisfied ? "text-reject" : "text-ink-4"}`}>
                            {cf.satisfied ? "충족" : "불충족"}
                          </span>
                          <p className="mt-0.5 text-[12px] leading-relaxed text-ink-2">{cf.finding}</p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {topJudgment?.conclusion && (
                <div className="rounded-md border-l-2 border-reject bg-reject-bg/40 px-3 py-2">
                  <span className="text-[10.5px] font-bold tracking-wider text-reject">결론</span>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-ink-2">{topJudgment.conclusion}</p>
                </div>
              )}
              {topJudgment?.reservation && (
                <div className="flex gap-1.5 px-1 text-[11.5px] leading-relaxed text-ink-3">
                  <span className="font-bold text-ink-4">유보</span>
                  <span>{topJudgment.reservation}</span>
                </div>
              )}
            </div>
          ) : (
            <p className="m-0 text-[13.5px] leading-relaxed text-ink-2">
              {card.rationale || topJudgment?.why || "이 표현은 정책 매칭 결과 확인이 필요합니다."}
            </p>
          )}
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

        {/* 연결된 심의 기준 (CU) — 클릭하면 전체 조건/근거 펼침 */}
        {topPlan && (
          <DetailRow icon="layers" label="연결된 심의 기준">
            <Expandable
              header={
                <div className="flex items-start gap-2.5">
                  <span className="shrink-0 rounded-md bg-brand px-1.5 py-0.5 font-mono text-[11px] font-bold text-white">
                    CU
                  </span>
                  <div className="min-w-0">
                    <div className="text-[13.5px] font-bold text-ink">{topPlan.risk_title || topPlan.principle}</div>
                    <div className="mt-0.5 line-clamp-1 text-[12px] text-ink-3">
                      {topPlan.constraint || topPlan.context}
                    </div>
                  </div>
                </div>
              }
            >
              <KeyValueText
                items={[
                  ["원칙", topPlan.principle || "-"],
                  ["대상", topPlan.subject || "-"],
                  ["요건/제약", topPlan.constraint || topPlan.context || "-"],
                  ["맥락", topPlan.context || "-"],
                ]}
              />
            </Expandable>
          </DetailRow>
        )}

        {/* 근거 조문 — 판매원칙별 법령 위임 사슬(법률→시행령→감독규정→심의기준) */}
        {delegationGroups.length > 0 && (
          <DetailRow icon="clause" label="근거 조문 · 법령 위임 사슬">
            <div className="space-y-2.5">
              {delegationGroups.map((group) => (
                <div key={group.principle} className="rounded-[10px] border border-line bg-surface-2 p-3">
                  <div className="mb-2 flex items-center gap-1.5">
                    <Tag tone="danger">{group.principle}</Tag>
                    <span className="text-[10.5px] text-ink-4">원칙 기준 위임 사슬</span>
                  </div>
                  <DelegationChain steps={group.steps} />
                </div>
              ))}
              {/* 조문 원문은 별도 드릴다운(평면 중복 제거, 난수 id 비노출) */}
              {clauseEvidence.some((c) => c.texts.length || c.constraint) && (
                <Expandable
                  header={<span className="text-[12px] font-bold text-ink-2">조문·근거 원문 보기</span>}
                >
                  <div className="space-y-2.5">
                    {clauseEvidence.map((c) => (
                      <div key={c.article}>
                        <div className="font-mono text-[11.5px] font-bold text-brand-2">{c.article}</div>
                        {c.constraint && <p className="mt-0.5 text-[12px] leading-relaxed text-ink-2">{c.constraint}</p>}
                        {c.texts.slice(0, 3).map((t, i) => (
                          <div key={i} className="mt-1 border-l-2 border-line-2 pl-2.5 text-[12px] leading-relaxed text-ink-3">
                            “{t}”
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                </Expandable>
              )}
            </div>
          </DetailRow>
        )}

        {/* 조항별 / 원칙별 영향 집계 — 심사 보고서 단위 */}
        {aggregationRows.length > 0 && (
          <DetailRow icon="layers" label="조항·원칙별 영향">
            <div className="space-y-1.5">
              {aggregationRows.map((row, i) => (
                <div
                  key={`${row.axis}_${row.key}_${i}`}
                  className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-1.5"
                >
                  <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] font-bold text-ink-3">
                    {row.axis === "article" ? "조항" : "원칙"}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink" title={row.key}>
                    {row.key}
                  </span>
                  <span className="text-[11px] text-ink-4">CU {Number(row.cu_count ?? 0)}</span>
                  <Badge tone={judgmentBadgeTone(String(row.effective_verdict ?? ""))}>
                    {JUDGMENT_STATUS[String(row.effective_verdict ?? "")] ?? row.effective_verdict}
                  </Badge>
                </div>
              ))}
            </div>
          </DetailRow>
        )}

        {/* 예외 · 고지 검토 — 완화 사유 클릭 펼침 */}
        <DetailRow icon="shield" label="예외 · 고지 검토">
          {exceptions.length ? (
            <div className="space-y-2">
              {exceptions.map((review) => (
                <Expandable
                  key={review.exception_review_id}
                  tone={review.applies ? "#e7d3a6" : "var(--line)"}
                  header={
                    <div className="flex items-center gap-2">
                      <span
                        className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold whitespace-nowrap"
                        style={{
                          color: review.applies ? "var(--revise)" : "var(--ink-3)",
                          background: review.applies ? "var(--revise-bg)" : "var(--surface-3)",
                        }}
                      >
                        {review.applies ? `완화 가능 · ${review.effect}` : "완화 불가"}
                      </span>
                      <span className="line-clamp-1 text-[12px] text-ink-3">{review.why}</span>
                    </div>
                  }
                >
                  <p className="m-0 text-[12.5px] leading-relaxed text-ink-2">{review.why}</p>
                  {(review.closure_evidence_ids ?? []).length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {review.closure_evidence_ids.map((id) => (
                        <span key={id} className="font-mono text-[10px] text-ink-4">
                          {id}
                        </span>
                      ))}
                    </div>
                  )}
                </Expandable>
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

        {/* 상품 사실 대조 — 수치 클레임이 있을 때만, 클릭 시 근거 펼침 */}
        {comparisons.length > 0 && (
          <DetailRow icon="layers" label="상품 사실 대조">
            <div className="space-y-2">
              {comparisons.slice(0, 4).map((item) => {
                const statusColor =
                  item.status === "SUPPORTED"
                    ? "text-pass"
                    : item.status === "CONTRADICTED"
                      ? "text-reject"
                      : "text-revise";
                return (
                  <Expandable
                    key={item.comparison_id}
                    disabled={!item.evidence_text && !item.rationale}
                    header={
                      <div className="flex items-center gap-2">
                        <b className={`shrink-0 text-[12px] ${statusColor}`}>{item.status}</b>
                        <span className="line-clamp-1 text-[12.5px] text-ink-2">{item.rationale ?? ""}</span>
                      </div>
                    }
                  >
                    <KeyValueText
                      items={[
                        ["판단", item.rationale || "-"],
                        ["근거", item.evidence_text || "-"],
                      ]}
                    />
                  </Expandable>
                );
              })}
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
