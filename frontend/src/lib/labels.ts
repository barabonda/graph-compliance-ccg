import type { FinalVerdict } from "./types";

export const WORKSPACE_ID = "graphcompliance_mvp_jb_20260530";

export const PRINCIPLES = [
  { key: "suitability", label: "적합성", match: ["적합성"] },
  { key: "appropriateness", label: "적정성", match: ["적정성"] },
  { key: "explanation", label: "설명의무", match: ["설명", "고지"] },
  { key: "unfair_sales", label: "불공정영업", match: ["불공정"] },
  { key: "unfair_solicitation", label: "부당권유", match: ["부당권유", "단정"] },
  { key: "ad_regulation", label: "광고규제", match: ["광고", "허위", "과장", "오도", "보장"] },
] as const;

export type PrincipleKey = (typeof PRINCIPLES)[number]["key"];

/** AI 판정은 항상 권고형 어미 — 확정형(승인/반려)은 심사자 결정 전용. */
export const VERDICT_LABELS: Record<FinalVerdict, [string, string]> = {
  pass_candidate: ["통과 후보", "현재 문안 기준 중대한 위반 신호 없음"],
  needs_review: ["검토 필요", "근거 또는 정책 매칭 확인 필요"],
  revise: ["수정 권고", "일부 표현 또는 고지 보완 필요"],
  reject: ["반려 권고", "명백한 위반 가능성이 있어 배포 전 수정 필요"],
};

/** 심사자 결정 어휘(확정형) — 로컬 데모 상태로만 기록. */
export const DECISIONS = {
  approve: { label: "승인", color: "var(--pass)", bg: "var(--pass-bg)" },
  revise: { label: "보완요청", color: "var(--revise)", bg: "var(--revise-bg)" },
  reject: { label: "반려", color: "var(--reject)", bg: "var(--reject-bg)" },
} as const;

export type DecisionKey = keyof typeof DECISIONS;

/** 점수 1차 노출 금지 — 등급으로 표기하고 수치는 hover로. */
export function riskGrade(score: number): { label: string; tone: "pass" | "review" | "reject" } {
  if (score >= 0.7) return { label: "높음", tone: "reject" };
  if (score >= 0.4) return { label: "중간", tone: "review" };
  return { label: "낮음", tone: "pass" };
}

export const JUDGMENT_STATUS: Record<string, string> = {
  NON_COMPLIANT: "위반 가능성",
  RETRIEVAL_FAILURE: "정책 매칭 실패",
  INSUFFICIENT: "검토 필요",
  COMPLIANT: "문제 없음",
  NOT_APPLICABLE: "해당 없음",
  SCOPE: "범위 정보",
  ANCHOR: "검토됨",
};

export const HUMAN_ACTION_LABELS: Record<string, string> = {
  guarantee_or_return_misleading: "단정·보장 표현",
  condition_or_scope_missing: "조건 고지",
  required_disclosure_missing: "필수 고지 누락",
  past_performance_or_future_return: "과거성과 오인",
  comparison_ad: "비교 표현",
  unfair_superior_position_sales: "불공정 영업",
};

export const HUMAN_FEATURE_LABELS: Record<string, string> = {
  guarantee_expression: "보장 표현",
  certainty_expression: "확정 표현",
  unconditional_expression: "조건 없음",
  universal_scope_expression: "대상 범위",
  comparison_target: "비교 근거",
  coercion_or_tie_in_context: "강요·끼워팔기",
};

export const QUALIFIER_LABELS: Record<string, string> = {
  target_scope: "대상 범위",
  condition_scope: "조건 범위",
  certainty: "확정 표현",
  guarantee: "보장 표현",
  benefit_scope: "혜택 범위",
  risk_downplay: "위험 축소",
  urgency: "긴급성",
  comparison: "비교 표현",
  disclosure_qualifier: "고지 표현",
  other: "표현",
};

export const DISCLOSURE_LABELS: Record<string, string> = {
  deposit_rate_condition: "최고금리 조건",
  deposit_term: "가입기간",
  deposit_tax_basis: "세전/세후",
  depositor_protection_limit: "예금자보호",
  product_document_notice: "상품설명서",
};

/** 고지 항목별 한 줄 설명 + 필수 여부 (예외·고지 검토 시뮬레이션용). */
export const DISCLOSURE_META: Record<string, { desc: string; required: boolean }> = {
  deposit_rate_condition: {
    desc: "최고금리/우대금리의 적용 조건과 기준을 함께 표시해야 합니다.",
    required: true,
  },
  deposit_term: { desc: "가입기간·만기 조건을 명시해야 합니다.", required: true },
  depositor_protection_limit: {
    desc: "예금자보호법에 따른 보호 한도(부보내용)를 유지 고지해야 합니다.",
    required: true,
  },
  deposit_tax_basis: { desc: "세전/세후 기준을 구분해 오인을 방지합니다.", required: false },
  product_document_notice: {
    desc: "상품설명서·약관 확인 안내를 권장합니다.",
    required: false,
  },
};

export function disclosureMeta(checkId: string): { desc: string; required: boolean } {
  return DISCLOSURE_META[checkId] ?? { desc: "필수 기재 고지 항목입니다.", required: true };
}

export const PRODUCT_GROUPS = [
  { value: "auto", label: "자동" },
  { value: "deposit", label: "예금" },
  { value: "loan", label: "대출" },
  { value: "investment", label: "투자" },
  { value: "insurance", label: "보험" },
] as const;

export const CHANNELS = [
  { value: "web_page", label: "웹페이지" },
  { value: "sns", label: "SNS" },
  { value: "youtube", label: "유튜브" },
  { value: "sms", label: "문자" },
  { value: "banner", label: "배너" },
  { value: "bank_event_page_text", label: "은행 이벤트 페이지" },
] as const;

export interface ExamplePreset {
  label: string;
  product: string;
  channel: string;
  title: string;
  selectedProduct: string;
  text: string;
}

export const EXAMPLES: ExamplePreset[] = [
  {
    label: "예금 · 고지 있음",
    product: "deposit",
    channel: "web_page",
    title: "JB시니어우대예금 특판",
    selectedProduct: "JB시니어우대예금",
    text: "JB시니어우대예금 특판 안내. 최고 연 5.0% 금리를 확정 제공하며 안정적으로 목돈을 관리할 수 있습니다. 기본금리와 우대금리는 가입기간, 우대조건 충족 여부에 따라 달라질 수 있습니다. 이 예금은 예금자보호법에 따라 원금과 이자를 합하여 1인당 최고 1억원까지 보호됩니다.",
  },
  {
    label: "예금 · 보장 위험",
    product: "deposit",
    channel: "web_page",
    title: "고지 없는 특판예금",
    selectedProduct: "",
    text: "JB 특판예금 출시. 누구나 연 5% 확정 보장 수익을 받을 수 있는 절호의 기회입니다. 지금 가입하면 조건 없이 안정적인 고수익을 보장합니다.",
  },
  {
    label: "투자 · ELS",
    product: "investment",
    channel: "web_page",
    title: "ELS 광고 초안",
    selectedProduct: "",
    text: "요즘 같은 변동성 장세에서는 ELS를 이해하는 것이 중요합니다. OO증권의 더블찬스 ELS는 안정성과 수익성을 동시에 고려한 상품입니다. 지난 3년간 유사 구조 상품의 조기상환 성공률이 높았기 때문에, 중위험 투자자에게 좋은 선택이 될 수 있습니다.",
  },
];

export function verdictBadgeTone(verdict: string): "pass" | "review" | "revise" | "reject" {
  const map: Record<string, "pass" | "review" | "revise" | "reject"> = {
    pass_candidate: "pass",
    needs_review: "review",
    revise: "revise",
    reject: "reject",
  };
  return map[verdict] ?? "review";
}

export function judgmentBadgeTone(verdict: string): "pass" | "review" | "reject" {
  const map: Record<string, "pass" | "review" | "reject"> = {
    NON_COMPLIANT: "reject",
    RETRIEVAL_FAILURE: "review",
    INSUFFICIENT: "review",
    COMPLIANT: "pass",
    NOT_APPLICABLE: "pass",
    SCOPE: "pass",
    ANCHOR: "review",
  };
  return map[verdict] ?? "review";
}

export function productFactStatusTone(status?: string): "pass" | "review" | "reject" {
  if (status === "SUPPORTED" || status === "EXTRACTED") return "pass";
  if (status === "CONTRADICTED" || status === "FACT_EXTRACTION_FAILED" || status === "TEXT_EXTRACTION_FAILED") {
    return "reject";
  }
  return "review";
}

export function trackBBadgeTone(verdict?: string, score?: number): "pass" | "review" | "reject" {
  const value = Number(score ?? 0);
  if (verdict === "HIGH" || value >= 0.75) return "reject";
  if (verdict === "MEDIUM" || value >= 0.45) return "review";
  return "pass";
}
