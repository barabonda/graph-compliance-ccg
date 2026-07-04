"use client";

/**
 * 콘솔 UI 로케일 — 워크스페이스 관할이 결정한다.
 *
 * KH(PPCBank 등 비-KR) 심사를 열면 화면의 모든 UI 문자열이 영어로 바뀐다
 * ("KH일 때는 한글이 아예 없어야 해"). KR 심사는 기존 한국어 그대로.
 *
 * 판별 신호(둘 중 하나면 en):
 *  1. result.workspace_id — 백엔드가 ReviewOutput에 싣는 관할 키(신규 run).
 *  2. result.ad_translations 존재 — 참고 번역은 비-KR에서만 채워진다(구 run 폴백).
 *
 * 사용 규칙:
 *  - 컴포넌트: `const locale = useLocale();` + `tr(locale, "한국어", "English")`
 *  - 비-React 모듈(selectors 등): locale 파라미터를 받아 tr 사용.
 *  - 라벨 맵(판정·원칙 등)은 이 파일의 *_EN 맵/헬퍼를 사용해 분기한다.
 */

import { createContext, useContext, type ReactNode } from "react";
import type { FinalVerdict, ReviewOutput } from "./types";
import { KH_WORKSPACE_ID, WORKSPACE_ID } from "./labels";

export type Locale = "ko" | "en";

export function localeForWorkspace(workspaceId?: string | null): Locale {
  if (!workspaceId || workspaceId === WORKSPACE_ID) return "ko";
  return workspaceId === KH_WORKSPACE_ID ? "en" : "ko";
}

export function localeForResult(result?: Partial<ReviewOutput> | null): Locale {
  if (!result) return "ko";
  if (result.workspace_id) return localeForWorkspace(result.workspace_id);
  // 구버전 run 폴백 — 참고 번역은 비-KR 관할에서만 생성된다.
  return result.ad_translations ? "en" : "ko";
}

/** 인라인 이중언어 선택 — ko 원문은 바이트 그대로 유지된다(KR 무회귀). */
export function tr(locale: Locale, ko: string, en: string): string {
  return locale === "en" ? en : ko;
}

const LocaleContext = createContext<Locale>("ko");

export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

export function useLocale(): Locale {
  return useContext(LocaleContext);
}

// ---------------------------------------------------------------------------
// 공용 라벨 맵 — labels.ts 의 한국어 맵과 짝을 이루는 영어판.
// ---------------------------------------------------------------------------

/** AI 판정 어휘(권고형) — labels.VERDICT_LABELS 의 EN. */
export const VERDICT_LABELS_EN: Record<FinalVerdict, [string, string]> = {
  pass_candidate: ["Pass candidate", "No material violation signals in the current copy"],
  needs_review: ["Review required", "Evidence or policy matching needs confirmation"],
  revise: ["Revision recommended", "Some expressions or disclosures need fixing"],
  reject: ["Rejection recommended", "Clear violation risk — revise before publication"],
};

export function verdictLabel(locale: Locale, verdict: FinalVerdict, koMap: Record<FinalVerdict, [string, string]>): [string, string] {
  return locale === "en" ? (VERDICT_LABELS_EN[verdict] ?? koMap[verdict]) : koMap[verdict];
}

/** 판정 상태 배지 — labels.JUDGMENT_STATUS 의 EN. */
export const JUDGMENT_STATUS_EN: Record<string, string> = {
  NON_COMPLIANT: "Possible violation",
  RETRIEVAL_FAILURE: "Policy matching failed",
  INSUFFICIENT: "Review required",
  COMPLIANT: "No issue",
  NOT_APPLICABLE: "Not applicable",
  SCOPE: "Scope info",
  ANCHOR: "Reviewed",
};

/** 위반 유형 라벨 — labels.HUMAN_ACTION_LABELS 의 EN. */
export const HUMAN_ACTION_LABELS_EN: Record<string, string> = {
  guarantee_or_return_misleading: "Definitive/guarantee wording",
  condition_or_scope_missing: "Condition disclosure",
  required_disclosure_missing: "Missing required disclosure",
  past_performance_or_future_return: "Past-performance confusion",
  comparison_ad: "Comparative wording",
  unfair_superior_position_sales: "Unfair sales practice",
};

/** 표현 요소 라벨 — labels.HUMAN_FEATURE_LABELS 의 EN. */
export const HUMAN_FEATURE_LABELS_EN: Record<string, string> = {
  guarantee_expression: "Guarantee wording",
  certainty_expression: "Definitive wording",
  unconditional_expression: "No-conditions wording",
  universal_scope_expression: "Audience scope",
  comparison_target: "Comparison basis",
  coercion_or_tie_in_context: "Coercion / tie-in",
};

/** 한정어 역할 라벨 — labels.QUALIFIER_LABELS 의 EN. */
export const QUALIFIER_LABELS_EN: Record<string, string> = {
  target_scope: "Audience scope",
  condition_scope: "Condition scope",
  certainty: "Definitive wording",
  guarantee: "Guarantee wording",
  benefit_scope: "Benefit scope",
  risk_downplay: "Risk downplaying",
  urgency: "Urgency",
  comparison: "Comparative wording",
  disclosure_qualifier: "Disclosure wording",
  other: "Expression",
};

/** 심사 층 명칭 — labels.REVIEW_LAYER 의 EN. */
export const REVIEW_LAYER_EN = {
  individual: { name: "Individual review", sub: "Each expression/disclosure against clauses" },
  holistic: { name: "Holistic review", sub: "Overall impression of the whole ad" },
} as const;

/** 권위 계층 그룹 — labels.AUTHORITY_GROUP 의 EN. */
export const AUTHORITY_GROUP_EN = {
  law: { name: "Legal-basis findings", sub: "" },
  guideline: { name: "Guideline shortfalls", sub: "Not a legal violation · self-regulatory" },
  uncertain: { name: "Needs confirmation", sub: "Insufficient grounds — reviewer judgment required" },
} as const;

/** 위험 등급 — labels.riskGrade 의 EN 라벨. */
export function riskGradeLabelEn(score: number): string {
  if (score >= 0.7) return "High";
  if (score >= 0.4) return "Medium";
  return "Low";
}

/**
 * 판매원칙(분류 좌표) 표시명 — 데이터 키는 한국어(6대 판매원칙)로 유지되지만
 * en 로케일에서는 표시만 영어로 바꾼다. 알 수 없는 값은 원문 그대로.
 */
const PRINCIPLE_DISPLAY_EN: [string, string][] = [
  ["광고규제", "Ad regulation"],
  ["설명의무", "Duty to explain"],
  ["적합성", "Suitability"],
  ["적정성", "Appropriateness"],
  ["불공정영업", "Unfair business practice"],
  ["부당권유", "Improper solicitation"],
  ["허위", "False/misleading"],
  ["과장", "Exaggeration"],
];

export function principleDisplay(locale: Locale, principle: string): string {
  if (locale !== "en") return principle;
  const value = String(principle ?? "");
  for (const [ko, en] of PRINCIPLE_DISPLAY_EN) {
    if (value.includes(ko)) return en;
  }
  return value;
}

/**
 * 데이터 값으로 쓰이는 한국어 등급/상태 유니온의 표시 치환 — 값 자체는 데이터
 * 키(정렬·비교에 사용)라 유지하고, en 로케일에서는 표기만 영어로 바꾼다.
 */
const GRADE_EN: Record<string, string> = { 낮음: "Low", 중간: "Medium", 높음: "High" };

export function gradeDisplay(locale: Locale, grade: string): string {
  return locale === "en" ? (GRADE_EN[grade] ?? grade) : grade;
}

const PRINCIPLE_STATUS_EN: Record<string, string> = {
  "위반 가능성": "Possible violation",
  "수정 필요": "Needs revision",
  "검토 필요": "Review required",
  "문제 없음": "No issue",
  "해당 없음": "Not applicable",
};

export function principleStatusDisplay(locale: Locale, status: string): string {
  return locale === "en" ? (PRINCIPLE_STATUS_EN[status] ?? status) : status;
}

/**
 * 데이터 필드(위반 유형 제목 등)에 남은 알려진 한국어 값의 표시 치환 — KH 정책
 * 그래프가 재컴파일되기 전까지의 표시 폴백. 화면 표기 전용(데이터 원문 불변).
 */
const KNOWN_DATA_TITLES_EN: [string, string][] = [
  ["사업활동의 이익/위험/중요 요소 관련 허위·기만 주장", "False/misleading claims about business profit, risk, or material factors"],
  ["소비자 결정에 영향을 주는 제한정보 누락", "Omission of limiting information affecting consumer decisions"],
  ["절대적·최상급 표현의 사전 서면 확인 없이 사용", "Absolute/superlative claims without prior written confirmation"],
  ["필수고지 현저성 또는 누락", "Required disclosure missing or insufficiently prominent"],
];

export function dataTitleDisplay(locale: Locale, title: string): string {
  if (locale !== "en") return title;
  const value = String(title ?? "");
  for (const [ko, en] of KNOWN_DATA_TITLES_EN) {
    if (value.includes(ko)) return en;
  }
  return value;
}
