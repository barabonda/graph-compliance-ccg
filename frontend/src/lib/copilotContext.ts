/**
 * 심사 코파일럿에 공유하는 심의 결과 컨텍스트 직렬화.
 *
 * Grounding 원칙: 코파일럿은 여기 담긴 판정·근거 안에서만 답한다.
 * ReviewOutput 전체를 넘기면 토큰이 터지고 내부 개발 용어가 새므로,
 * 준법 도메인 언어로 요약한 컴팩트 뷰만 넘긴다.
 */
import { VERDICT_LABELS } from "./labels";
import {
  buildIssueCards,
  disclosureIsSatisfied,
  disclosureStatus,
  effectiveJudgmentsForAnchor,
  principleBreakdown,
} from "./selectors";
import type { ReviewOutput } from "./types";

function clip(text: string, max: number): string {
  const value = text ?? "";
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/** anchor 카드의 판정 상세(요건별 판단·적용 법리·결론) — 사이드챗 심층 질의용. */
function judgmentDetail(result: ReviewOutput, anchorId?: string) {
  if (!anchorId) return undefined;
  const effective = effectiveJudgmentsForAnchor(result, anchorId);
  const top =
    effective.find((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict)) ?? effective[0];
  if (!top) return undefined;
  return {
    적용_법리: clip(top.legal_basis ?? "", 400) || undefined,
    요건별_판단: (top.criteria_findings ?? []).map((cf) => ({
      기준: cf.criterion,
      충족: cf.satisfied ? "충족" : "불충족",
      판단: clip(cf.finding ?? "", 150),
    })),
    결론: clip(top.conclusion ?? "", 300) || undefined,
    유보: clip(top.reservation ?? "", 200) || undefined,
  };
}

export function buildCopilotReviewContext(
  result: ReviewOutput,
  resolved: Set<string>,
  title?: string,
  reviewedText?: string,
): Record<string, unknown> {
  const cards = buildIssueCards(result);
  const [verdictLabel] = VERDICT_LABELS[result.final_verdict] ?? [result.final_verdict];
  const trackB = result.overall_impression_judgment;
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  return {
    안내: "현재 화면에 열려 있는 금융광고 AI 사전심의 결과 요약. 이 범위 안에서만 답변할 것.",
    광고_제목: title || undefined,
    광고_원문: clip(reviewedText ?? "", 2500) || undefined,
    AI_판정_권고: verdictLabel,
    요약_사유: clip(result.rationale ?? "", 500),
    필수_고지_현황: checks
      .filter((check) => disclosureStatus(check) !== "SKIPPED_BY_GATE")
      .map((check) => `${check.label}: ${disclosureIsSatisfied(check) ? "충족" : "누락"}`),
    판매원칙별_현황: principleBreakdown(result, resolved)
      .map((item) => `${item.label} ${item.count}건`)
      .join(" · "),
    종합_심사: trackB?.verdict
      ? {
          오인_위험_점수: trackB.misleading_risk_score,
          대표_소비자_인상: clip(trackB.representative_consumer_impression ?? "", 300),
          판단_이유: clip(trackB.why ?? "", 300),
          오인_요인: (trackB.misleading_factors ?? []).slice(0, 5).map((f) => clip(f, 150)),
        }
      : undefined,
    위험_카드: cards.map((card) => ({
      코드: card.code || (card.track === "B" ? "B" : card.id),
      심사_층: card.track === "B" ? "종합 심사(광고 전체 인상)" : "개별 심사",
      처리_상태: resolved.has(card.id) ? "해소(수정안 적용됨)" : "미해소",
      권위_계층:
        card.track === "B"
          ? undefined
          : card.authorityTier === "law"
            ? "법령 위반 근거"
            : card.authorityTier === "guideline"
              ? "심의기준 미흡(법령 위반 아님 · 자율규제 보완 권고)"
              : "확인 필요(근거 불충분 — 심사자 판단 필요)",
      대상_문구: clip(card.quote, 100),
      위반_유형: card.label,
      위반_가능성: card.grade,
      요건_요약: card.criteriaSummary,
      근거_조문: card.basis,
      병기_근거: card.coBasis,
      판정_사유: clip(card.rationale ?? "", 300),
      판정_상세: judgmentDetail(result, card.anchorId),
    })),
  };
}
