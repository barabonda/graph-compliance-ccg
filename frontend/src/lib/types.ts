/** Typed mirror of the FastAPI `ReviewOutput` contract (schemas.py). */

export type FinalVerdict = "pass_candidate" | "revise" | "reject" | "needs_review";

export type JudgmentVerdict =
  | "COMPLIANT"
  | "NON_COMPLIANT"
  | "INSUFFICIENT"
  | "NOT_APPLICABLE";

export type DisplayVerdict = JudgmentVerdict | "RETRIEVAL_FAILURE" | "SCOPE" | "ANCHOR";

export type ProminenceTier = "headline" | "subcopy" | "body" | "footnote" | "unknown";

export type ComparisonStatus =
  | "SUPPORTED"
  | "CONTRADICTED"
  | "CONDITION_MISSING"
  | "PROMINENCE_INSUFFICIENT"
  | "NO_PRODUCT_FACT"
  | "NEEDS_PRODUCT_SELECTION";

export interface Span {
  start: number;
  end: number;
  text: string;
}

export interface ContextFrame {
  frame_id?: string;
  summary?: string;
  primary_message?: string;
  product_purpose?: string;
  tone?: string;
  representative_consumer_impression?: string;
  risk_axes?: string[];
  overall_risk_level?: string;
}

export interface SentenceUnit {
  sentence_id: string;
  index: number;
  text: string;
  span: Span;
  role: string;
  local_meaning: string;
  context_effect: string;
  risk_level: string;
  prominence_tier?: ProminenceTier;
}

export interface InterSentenceRelation {
  relation_id: string;
  source_sentence_id: string;
  target_sentence_id: string;
  relation_type: string;
  explanation: string;
  evidence: string;
}

export interface ContextInfluence {
  influence_id: string;
  source_id: string;
  source_type: string;
  target_id: string;
  target_type: string;
  influence_type: string;
  effect: string;
  risk_delta: string;
  confidence: number;
}

export interface ClaimQualifier {
  qualifier_id: string;
  text: string;
  role: string;
  span: Span;
  meaning: string;
  risk_reason: string;
  confidence: number;
  prominence_tier?: ProminenceTier;
}

export interface ContextEntity {
  entity_id: string;
  name: string;
  entity_type: string;
  span: Span;
}

export interface ContextRelation {
  source_id: string;
  predicate: string;
  target_id: string;
  evidence: string;
}

export interface Claim {
  claim_id: string;
  text: string;
  span: Span;
  meaning: string;
  implicature: string;
  consumer_effect: string;
  risk_hypernym: string;
  risk_severity: string;
  sentence_id?: string;
  entities?: ContextEntity[];
  relations?: ContextRelation[];
  qualifiers?: ClaimQualifier[];
}

export interface ContextTriple {
  triple_id: string;
  claim_id: string;
  subject: string;
  predicate: string;
  object: string;
  evidence: string;
  subject_type?: string;
  object_type?: string;
}

export interface PolicyHypernymProposal {
  proposal_id: string;
  source_id: string;
  hypernym_id: string;
  hypernym: string;
  support: "STRONG" | "WEAK";
  confidence: number;
  normalized_score: number;
  evidence_ids?: string[];
  why?: string;
}

export interface AnchorFeatureSet {
  feature_set_id: string;
  anchor_id: string;
  action_types: string[];
  positive_features: string[];
  missing_context: string[];
  evidence: string[];
}

export interface ContextAnchor {
  anchor_id: string;
  anchor_type: string;
  claim_id: string;
  span: Span;
  facts: string[];
  hypernyms: PolicyHypernymProposal[];
  feature_set?: AnchorFeatureSet | null;
}

export interface CULegalElementProfile {
  profile_id: string;
  cu_id: string;
  action_type: string;
  required_positive_features: string[];
  applicability_scope: string[];
  risk_title: string;
  exception_eligible: boolean;
  rationale?: string;
}

export interface CUPlanItem {
  plan_item_id: string;
  anchor_id: string;
  cu_id: string;
  principle: string;
  source_article: string;
  subject: string;
  condition: string;
  constraint: string;
  context: string;
  legal_evidence_ids: string[];
  evidence_texts: string[];
  retrieval_scores: Record<string, unknown>;
  rerank_score: number;
  selection_reason: string;
  retrieval_basis?: string;
  gate_status?: string;
  reference_paths?: Record<string, unknown>[];
  legal_element_profile?: CULegalElementProfile | null;
  matched_required_features?: string[];
  missing_required_features?: string[];
  legal_element_match?: boolean;
  risk_title?: string;
}

export interface CriterionFinding {
  criterion: string;
  satisfied: boolean;
  finding: string;
}

export interface LLMJudgment {
  judgment_id: string;
  plan_item_id: string;
  anchor_id: string;
  cu_id: string;
  verdict: JudgmentVerdict;
  score: number;
  why: string;
  evidence_span: string;
  used_policy_evidence: string[];
  /** 금감원 답변식 설명가능 추론. */
  legal_basis?: string;
  criteria_findings?: CriterionFinding[];
  conclusion?: string;
  reservation?: string;
}

export interface ExceptionReview {
  exception_review_id: string;
  judgment_id: string;
  cu_id: string;
  applies: boolean;
  effect: "NONE" | "DOWNGRADE_TO_REVIEW" | "OVERRIDE_TO_COMPLIANT";
  why: string;
  closure_evidence_ids: string[];
}

export interface RetrievalDiagnostic {
  anchor_id?: string;
  failure_code?: string;
  candidate_count?: number;
  active_candidate_count?: number;
  hypernym_count?: number;
  top_candidate_ids?: string[];
  top_candidate_principles?: string[];
  anchor_action_types?: string[];
  anchor_positive_features?: string[];
}

export interface AnchorDisplay {
  anchor_id: string;
  anchor_type: string;
  display_role: "actionable" | "scope" | "mitigation" | string;
  is_actionable: boolean;
  display_verdict: DisplayVerdict;
  raw_verdict?: string;
  effective_verdict?: string;
  score?: number;
  cu_count?: number;
  system_review_required?: boolean;
  system_review_reason?: string;
  retrieval_failure_code?: string;
  retrieval_diagnostic?: RetrievalDiagnostic;
}

export interface DetectedIssue {
  risk_code: string;
  principle?: string;
  source_article?: string;
  /** 권위 계층: "law" | "guideline" | 미상. 판정 어휘("위반" vs "미흡")를 가른다. */
  authority_tier?: string;
  /** 병기 근거 (대표 근거와 다른 tier의 조문). */
  co_basis?: string;
  risk_title?: string;
  subject?: string;
  constraint?: string;
  severity?: number;
  problem_span?: string;
  rationale?: string;
  required_action?: string;
}

export interface DisclosureBlockItem {
  check_id: string;
  label: string;
  status: "add" | "reviewer";
  text: string;
}

export interface RevisionSuggestion {
  anchor_id: string;
  severity: string;
  risky_text: string;
  why_problematic: string;
  required_disclosures?: string[];
  before: string;
  after: string;
  notes_for_reviewer?: string;
  /** `__disclosure_block__` 센티넬에만: 하단 '꼭 확인해 주세요' 고지 블록 항목. */
  disclosure_block?: DisclosureBlockItem[];
}

/** 운영 대시보드용 실행(ReviewRun) 요약. `GET /api/runs`. */
export interface RunSummary {
  id: string;
  ts: number;
  title: string;
  channel: string;
  product_group: string;
  selected_product_name?: string;
  selected_product_id?: string;
  source_type?: string;
  workspace_id?: string;
  model: string;
  content_text: string;
  final_verdict: string;
  misleading_verdict: string;
  issue_count: number;
  missing_disclosures: string[];
  principles: string[];
  cu_ids: string[];
  /** 사람이 읽는 CU 라벨(risk_title 등). 해시 cu_id 대체 표시용. */
  cu_labels?: string[];
  /** 실행자 가명. */
  actor?: string;
  /** 실제 실행이 아니라 데모용으로 수동 주입된 기록. */
  seed?: boolean;
}

/** 평가 리포트 종류. `jbbank_live_eval`은 실제 광고 판정 로그(정답 라벨 없음). */
export type EvalReportKind = "json" | "md" | "jbbank_live_eval";

/** 판정 분포(정답 라벨 없는 라이브 로그). */
export type EvalVerdictCounts = Partial<Record<FinalVerdict, number>> & Record<string, number>;

/** 합성 gold 리포트 분류 지표. */
export interface EvalMetrics {
  micro_f1?: number;
  macro_f1?: number;
  micro_f2?: number;
  macro_f2?: number;
  mcc?: number;
}

/** 혼동행렬 카운트(합성 gold). */
export interface EvalConfusionCounts {
  tp?: number;
  fp?: number;
  fn?: number;
  tn?: number;
}

/** CCG 위반 검출 지표(합성 gold). */
export interface EvalCcgMetrics {
  violation_precision?: number;
  violation_recall?: number;
  overblocking_rate?: number;
  clean_non_pass_rate?: number;
  [key: string]: number | undefined;
}

/**
 * 리포트 분류 — 카드 시각 구분용. `_workspace_evallog/contract_api.md` 확정 계약:
 * `report_kind`는 summary에 항상 채워지며(즉시 계산, is_report와 독립적), 값은 이
 * 5종으로 고정된다(서버가 그 외 값을 내려주지 않음).
 */
export type EvalReportCategory = "gold" | "live" | "synthetic" | "guideline" | "unknown";

/** 조문별(article) 분해 행 — gold 리포트 `article_metrics.per_article`(실제 산출 필드). */
export interface EvalPerArticleRow {
  tp?: number;
  fp?: number;
  fn?: number;
  tn?: number;
  f1?: number;
  f2?: number;
  precision?: number;
  recall?: number;
  [key: string]: number | undefined;
}

/** 조문 레벨 분류 지표 — gold 리포트 원본 JSON의 `article_metrics` 필드(요약 `metrics`와 별개). */
export interface EvalArticleMetrics extends EvalMetrics {
  article_universe_size?: number;
  counts?: EvalConfusionCounts;
  per_article?: Record<string, EvalPerArticleRow>;
}

/** 위반유형별 재현율 행 — `synth_v0_2_breakdown.py`의 `per_violation_type_recall` 산출 그대로. */
export interface EvalViolationTypeRow {
  mutations?: number;
  detected?: number;
  recall?: number;
  [key: string]: number | undefined;
}

/** 상품군별 정밀도/재현율 행 — `synth_v0_2_breakdown.py`의 `per_product_group` 산출 그대로. */
export interface EvalProductGroupRow {
  counts?: EvalConfusionCounts;
  precision?: number;
  recall?: number;
  f1?: number;
  [key: string]: unknown;
}

/**
 * 상품 선택 provenance — 합성평가는 상품 선택 상태, 크롤링 스윕은 미선택으로 실행된다.
 * 계약상 타입은 `any`(리포트 JSON 최상위 `product_selection` 키를 그대로 pass-through) —
 * 프론트는 shape을 가정하지 않고 런타임에 안전하게 narrowing한다(`productSelectionInfo`).
 */
export type EvalProductSelection = unknown;

/** `breakdown` 분해 차원 — 계약 고정 3종. */
export type EvalBreakdownDimension = "article" | "violation_type" | "product_group";

/**
 * `breakdown[].top` 행 — 차원별로 존재하는 필드가 다르다(계약 참조):
 * - article/product_group: precision·recall·f1 존재
 * - violation_type: recall·detected만 존재(precision 없음 — gold 위반 레코드만 대상)
 * - support: 정렬 기준(내림차순, tp+fn 또는 mutations 수) — 모든 차원 공통.
 */
export interface EvalBreakdownTopEntry {
  key: string;
  precision?: number;
  recall?: number;
  f1?: number;
  detected?: number;
  support?: number;
  [key: string]: unknown;
}

/** 유형별/조문별/상품군별 top-N(최대 5) 정밀도·재현율 분해 그룹 — `EvalReportSummary.breakdown`. */
export interface EvalBreakdownGroup {
  dimension: EvalBreakdownDimension;
  top: EvalBreakdownTopEntry[];
}

/**
 * 평가 리포트 요약(운영 대시보드 평가 로그 목록). `GET /api/eval/reports`.
 * - 합성 gold 리포트: `metrics`/`counts`/`ccg_metrics` 존재(정밀도·재현율 산출).
 * - JB 실제광고 로그: `kind:"jbbank_live_eval"`, `gold_available:false`, `verdict_counts` 존재.
 */
export interface EvalReportSummary {
  name: string;
  kind: EvalReportKind;
  size: number;
  mtime: number;
  record_count?: number;
  /** 배치 식별자(있을 때). */
  batch?: string;
  /** false면 정답 라벨 없음 — 정밀도/재현율 미산출, 판정 분포만. */
  gold_available?: boolean;
  /** JB 실제광고 로그: 판정 분포. */
  verdict_counts?: EvalVerdictCounts;
  workspace_id?: string;
  /** 합성 gold: 분류 지표(F1/MCC). */
  metrics?: EvalMetrics;
  /** 합성 gold: 혼동행렬 카운트. */
  counts?: EvalConfusionCounts;
  /** 합성 gold: 위반 검출 지표(정밀도/재현율). */
  ccg_metrics?: EvalCcgMetrics;
  /** 리포트 분류(gold|live|synthetic|guideline|unknown) — 항상 채워짐(계약 확정, is_report와 독립적). */
  report_kind: EvalReportCategory;
  /** 실제 "리포트"(카드 노출 대상)인지 — 하드 필터 아닌 플래그, 항상 채워짐. false면
   * 중간 산출물(batch·quality·grounding·metrics 중간본) — 목록 기본 숨김, "원자료 포함"
   * 토글로 노출. 방어적으로 `!== false` 비교 권장(값 자체는 항상 존재). */
  is_report: boolean;
  /** 리포트 JSON 최상위에 `model` 키가 있을 때만 존재(옵셔널, 없으면 키 자체 생략). */
  model?: unknown;
  /** 리포트 JSON 최상위에 `product_selection` 키가 있을 때만 존재(옵셔널). */
  product_selection?: EvalProductSelection;
  /** 알려진 분해 shape(article/violation_type/product_group)이 있을 때만 존재(옵셔널). */
  breakdown?: EvalBreakdownGroup[];
}

/** JB 실제광고 로그의 개별 심사 레코드. `run_id`로 `/api/runs/{run_id}` 상세에 연결. */
export interface JbLiveEvalRecord {
  id: string;
  source_dir?: string;
  title: string;
  product_group?: string;
  /** 전체 ReviewOutput 상세 딥링크 키. */
  run_id?: string;
  final_verdict: string;
  misleading_verdict?: string;
  issue_count?: number;
  missing_disclosures?: string[];
  detected_risk_codes?: string[];
}

/** JB 실제광고 라이브 평가 리포트 본문(`EvalReportDetail.content`). */
export interface JbLiveEvalReport {
  kind: "jbbank_live_eval";
  batch?: string;
  generated_at?: number;
  gold_available?: boolean;
  note?: string;
  workspace_id?: string;
  record_count?: number;
  flagged_count?: number;
  verdict_counts?: EvalVerdictCounts;
  product_group_counts?: Record<string, number>;
  records?: JbLiveEvalRecord[];
  /** 리포트 JSON 최상위에 `model` 키가 있을 때만 존재(옵셔널, 없으면 키 자체 생략). */
  model?: unknown;
  /** 리포트 JSON 최상위에 `product_selection` 키가 있을 때만 존재(옵셔널). */
  product_selection?: EvalProductSelection;
}

/**
 * 합성 gold 레코드의 정답 라벨 — `records[].gold`. `violation_types`·`required_disclosures`는
 * 검증 핵심 축이지만 구버전 리포트엔 없을 수 있어 옵셔널(백엔드 보강 대상, `_workspace_recordview/
 * contract_api.md` 확정 전까지는 없을 수 있다고 가정).
 */
export interface EvalGoldRecordGold {
  violation: boolean;
  articles: string[];
  risk_level?: string;
  expected_routing?: string;
  /** 위반유형 정답(백엔드 보강 예정 — 없으면 레코드 뷰에서 해당 축 "판정 없음"). */
  violation_types?: string[];
  /** 필수 고지사항 정답(백엔드 보강 예정 — 없으면 재현율 계산 불가, "판정 없음" 폴백). */
  required_disclosures?: string[];
  [key: string]: unknown;
}

/** 합성 gold 레코드의 파이프라인 예측 — `records[].prediction`(실제 산출 필드, `predict_*` 접두). */
export interface EvalGoldRecordPrediction {
  record_id?: string;
  predicted_articles?: string[];
  predicted_violation?: boolean;
  predicted_violation_types?: string[];
  predicted_sales_principles?: string[];
  predicted_required_disclosures?: string[];
  predicted_risk_level?: string;
  predicted_routing?: string;
  cu_plan_count?: number;
  context_triple_count?: number;
  has_policy_evidence?: boolean;
  has_cu0_failure?: boolean;
  /** 콘솔 딥링크 키(백엔드 보강 예정 — record 최상위에 실릴 수도 있어 두 위치 모두 확인). */
  review_run_id?: string;
  [key: string]: unknown;
}

/** 고지사항 재현율 축 판정 — `records[].matches.disclosures`(백엔드 보강 예정, 옵셔널). */
export interface EvalRecordDisclosureMatch {
  gold_n?: number;
  matched_n?: number;
  recall?: number;
}

/** 라우팅 축 판정 — `records[].matches.routing`(백엔드 보강 예정, 옵셔널). 인접(±1)까지 포함. */
export interface EvalRecordRoutingMatch {
  gold?: string;
  pred?: string;
  exact?: boolean;
  adjacent?: boolean;
}

/**
 * 레코드별 축별 통과 판정 — `records[].matches`. 백엔드가 집계와 동일 로직(예: `article_family`는
 * `compare_guideline_vlm.article_family`)으로 계산해 채운다. 구버전 리포트엔 필드 자체가 없으므로
 * 전부 옵셔널 — 프론트는 없으면 "판정 없음"으로 폴백하고 자체 로직으로 재계산하지 않는다.
 */
export interface EvalRecordMatches {
  violation?: boolean;
  article_exact?: boolean;
  article_family?: boolean;
  disclosures?: EvalRecordDisclosureMatch;
  routing?: EvalRecordRoutingMatch;
  [key: string]: unknown;
}

/** 합성 gold 레코드(gold vs prediction 병치 + 축별 통과 판정) — `GoldEvalReport.records`. */
export interface EvalGoldRecord {
  id: string;
  gold: EvalGoldRecordGold;
  prediction: EvalGoldRecordPrediction;
  /** 축별 match 판정(백엔드 보강 예정, 옵셔널 — 없으면 레코드 뷰가 "판정 없음"으로 폴백). */
  matches?: EvalRecordMatches;
  /** 종합 통과 여부(백엔드 보강 예정, 옵셔널). 정의는 `GoldEvalReport.overall_pass_definition` 참고. */
  overall_pass?: boolean;
  /** 콘솔 딥링크(백엔드 보강 예정 — 없으면 `prediction.review_run_id`도 확인). */
  review_run_id?: string;
  [key: string]: unknown;
}

/** 합성 gold 리포트 본문(`EvalReportDetail.content`). 확정 필드만 명시, 나머지는 원본 JSON. */
export interface GoldEvalReport {
  record_count?: number;
  metrics?: EvalMetrics;
  counts?: EvalConfusionCounts;
  ccg_metrics?: EvalCcgMetrics;
  /** 조문 레벨 원본 지표 — 실제 리포트(regulator_vlm_full_report.json 등)에 존재하는
   * 필드. 조문별 정밀도/재현율 테이블의 데이터 출처. */
  article_metrics?: EvalArticleMetrics;
  /** 위반유형별 재현율 분해(`synth_v0_2_breakdown.py` 산출, 있을 때). */
  per_violation_type_recall?: Record<string, EvalViolationTypeRow>;
  /** 상품군별 정밀도/재현율 분해(`synth_v0_2_breakdown.py` 산출, 있을 때). */
  per_product_group?: Record<string, EvalProductGroupRow>;
  /** `synth_v0_2_breakdown.py` 산출의 대안 상단 요약(article_metrics 없이 이 shape만 있는
   * 리포트도 있음 — build() 참조). */
  overall?: { counts?: EvalConfusionCounts; precision?: number; recall?: number; f1?: number };
  /** 상품 선택 provenance(리포트 JSON 최상위에 있으면 pass-through, 없으면 생략). */
  product_selection?: EvalProductSelection;
  /** 리포트 JSON 최상위 `model` 키(있으면 pass-through, 없으면 생략). */
  model?: unknown;
  /** 레코드별 gold vs prediction 병치(실제 산출 필드, 34건 등). 없으면 레코드 뷰 자체를 숨긴다. */
  records?: EvalGoldRecord[];
  /** `overall_pass` 판정 기준 한 줄 설명(백엔드 보강 예정, 옵셔널 — 없으면 레코드 뷰에 일반 안내만). */
  overall_pass_definition?: string;
  [key: string]: unknown;
}

/**
 * 단일 평가 리포트 상세 — `GET /api/eval/reports/{name}`.
 * - `.json` → `content`(원본 JSON). 본문 `kind`로 gold/live 분기.
 * - `.md`   → `text`(마크다운 원문).
 */
export interface EvalReportDetail {
  name: string;
  kind: EvalReportKind;
  content?: JbLiveEvalReport | GoldEvalReport | Record<string, unknown>;
  text?: string;
}

export interface SystemReviewItem {
  anchor_id: string;
  risk_code?: string;
  reason?: string;
  [key: string]: unknown;
}

export interface ClaimFact {
  claim_fact_id: string;
  claim_id: string;
  fact_type: string;
  value: string;
  unit?: string;
  qualifier?: string;
  evidence_text?: string;
  confidence?: number;
  prominence_tier?: ProminenceTier;
}

export interface ProductFact {
  fact_id: string;
  fact_type: string;
  value: string;
  unit?: string;
  condition?: string;
  source_document_id?: string;
  page_or_chunk?: string;
  evidence_text?: string;
  confidence?: number;
}

export interface ComparisonResult {
  comparison_id: string;
  claim_fact_id: string;
  product_fact_id: string;
  status: ComparisonStatus | string;
  rationale?: string;
  evidence_text?: string;
  confidence?: number;
}

export interface SelectedDocument {
  document_id?: string;
  label?: string;
  file_name?: string;
  original_name?: string;
  relative_path?: string;
  exists?: boolean;
  [key: string]: unknown;
}

export interface DisclosureCheck {
  check_id: string;
  label: string;
  present: boolean;
  status?: string;
  check_type?: string;
  severity?: number;
  on_missing?: string;
  gate_status?: string;
  gate_reason?: string;
  /** 근거 조문 (그래프 카탈로그 기반). */
  source?: string;
  /** 권위 계층: "law"(법령 위반 근거) | "guideline"(심의기준 미흡) | ""(미상). */
  authority_tier?: string;
  /** tier 규칙으로 고른 대표 근거 조문. */
  representative_basis?: string;
  /** 병기 근거 (다른 tier 쪽 조문). */
  co_basis?: string;
  /** guideline tier 안내 문구 ("법령 위반이 아닌 심의기준 미흡입니다."). */
  tier_note?: string;
  [key: string]: unknown;
}

export interface ProductFactContext {
  extraction_status?: string;
  matched_product?: string;
  reason?: string;
  claim_facts?: ClaimFact[];
  product_facts?: ProductFact[];
  comparison_results?: ComparisonResult[];
  selected_documents?: SelectedDocument[];
  disclosure_checks?: DisclosureCheck[];
  [key: string]: unknown;
}

export interface MatchedProduct {
  product?: string;
  name?: string;
  major?: string;
  subcategory?: string;
  category?: string;
  document_count?: number;
  document_labels?: string[];
  [key: string]: unknown;
}

export interface ProductSearchResult {
  product: string;
  product_group?: string;
  major?: string;
  subcategory?: string;
  category?: string;
  document_count?: number;
  document_labels?: string[];
  source_ids?: string[];
  source?: string;
  score?: number;
  match_basis?: string;
  [key: string]: unknown;
}

export interface ProductContext {
  product_group?: string;
  matched_products?: MatchedProduct[];
  document_count?: number;
  [key: string]: unknown;
}

export interface DisclosureLink {
  check_id?: string;
  status?: string;
  benefit_sentence_id?: string;
  disclosure_sentence_id?: string;
  disclosure_text?: string;
  evidence?: string;
  reason?: string;
  [key: string]: unknown;
}

export interface ProminenceDiagnostic {
  diagnostic_code: string;
  severity?: string;
  message?: string;
  evidence?: string;
  benefit_sentence_id?: string;
  disclosure_sentence_id?: string;
  [key: string]: unknown;
}

export interface DisclosureRequirement {
  label: string;
  source?: string;
  why?: string;
  [key: string]: unknown;
}

export interface ChainNode {
  title?: string;
  name?: string;
  label?: string;
  article?: string;
  id?: string;
  /** ArticleClause | SalesPrinciple | DelegatedStandard … (온톨로지 레이어 구분). */
  node_type?: string;
  /** root_article | principle | delegated_enforcement_decree | delegated_supervisory_standard … */
  role?: string;
  [key: string]: unknown;
}

export interface DelegationEdge {
  relationship_type?: string;
  source_id?: string;
  target_id?: string;
  target_node?: ChainNode;
  why?: string;
}

export interface PolicyEvidenceChain {
  anchor_id: string;
  chain_type?: string;
  status?: string;
  summary?: string;
  basis_nodes?: ChainNode[];
  disclosure_nodes?: ChainNode[];
  exception_nodes?: ChainNode[];
  delegation_edges?: DelegationEdge[];
  provenance_snippets?: { text?: string; summary?: string }[];
  [key: string]: unknown;
}

export interface PolicyEvidenceChains {
  legal_basis_chains?: PolicyEvidenceChain[];
  disclosure_chains?: PolicyEvidenceChain[];
  exception_chains?: PolicyEvidenceChain[];
  chain_diagnostics?: Record<string, unknown>[];
}

export interface TrackBEvidencePath {
  claim_id: string;
  path?: string;
  claim?: string;
  meaning?: string;
  implicature?: string;
  consumer_effect?: string;
}

export interface OverallImpressionJudgment {
  track?: string;
  standard?: string;
  verdict?: string;
  misleading_risk_score?: number;
  representative_consumer_impression?: string;
  why?: string;
  misleading_factors?: string[];
  mitigation_relations?: { id?: string; label?: string; matched_terms?: string }[];
  grounded_claim_ids?: string[];
  evidence_paths?: TrackBEvidencePath[];
  /** 복잡 위반 종합에 연결한 흩어진 증거(위계·위계차·사실모순). */
  synthesized_evidence?: {
    sentence_layers?: { role?: string; tier?: string; text?: string }[];
    prominence_gaps?: { code?: string; message?: string; evidence?: string }[];
    fact_contradictions?: { status?: string; rationale?: string }[];
  };
}

export interface AggregationRow {
  axis?: string;
  key?: string;
  effective_verdict?: string;
  cu_count?: number;
  issue_count?: number;
  max_score?: number;
  principles?: string[];
  anchor_spans?: string[];
  cu_titles?: string[];
  [key: string]: unknown;
}

export interface ReferencePathRow {
  anchor_id?: string;
  cu_id?: string;
  risk_title?: string;
  source_article?: string;
  principle?: string;
  has_disclosure_evidence?: boolean;
  has_exception_path?: boolean;
  path_labels?: string[];
  legal_evidence?: { id?: string; text?: string }[];
  [key: string]: unknown;
}

export interface HighlightSpanRow {
  anchor_id: string;
  judgment_id?: string;
  cu_id?: string;
  verdict?: string;
  start: number;
  end: number;
  text: string;
}

export interface Routing {
  ad_scope?: string;
  preapproval_required_status?: string;
  review_phrase_required_before_publication?: boolean;
  review_phrase_expected_in_input?: boolean;
  review_phrase_input_status?: string;
  [key: string]: unknown;
}

export interface ReviewOutput {
  dataset_item_id: string;
  final_verdict: FinalVerdict;
  routing: Routing;
  detected_issues: DetectedIssue[];
  post_approval_required_actions: string[];
  rationale: string;
  review_run_id: string;
  context_frame: ContextFrame;
  sentence_units: SentenceUnit[];
  inter_sentence_relations: InterSentenceRelation[];
  context_influences: ContextInfluence[];
  claims: Claim[];
  context_triples: ContextTriple[];
  context_anchors: ContextAnchor[];
  anchor_feature_sets: AnchorFeatureSet[];
  cu_plan: CUPlanItem[];
  judgments: LLMJudgment[];
  effective_judgments: LLMJudgment[];
  exception_reviews: ExceptionReview[];
  anchor_display: AnchorDisplay[];
  system_review_items: SystemReviewItem[];
  revision_suggestions: RevisionSuggestion[];
  product_context: ProductContext;
  product_fact_context: ProductFactContext;
  prominence_analysis: Record<string, unknown>;
  disclosure_links: DisclosureLink[];
  prominence_diagnostics: ProminenceDiagnostic[];
  disclosure_requirements: DisclosureRequirement[];
  policy_evidence_chains: PolicyEvidenceChains;
  overall_impression_judgment: OverallImpressionJudgment;
  track_c_summary: Record<string, unknown>;
  article_aggregation: AggregationRow[];
  principle_aggregation: AggregationRow[];
  reference_paths_summary: ReferencePathRow[];
  graph_paths: Record<string, unknown>[];
  highlight_spans: HighlightSpanRow[];
  /** 참고용 번역(표시 전용) — 비-KR workspace 심사에서만 채워짐. KR은 null/미포함. */
  ad_translations?: AdTranslations | null;
  /** 이미지 광고 접수 메타 — 원본은 GET /api/ad-image/{run_id}/original(_N) 로 서빙. */
  ad_image?: { available: boolean; count?: number; layout_notes?: string; extracted_title?: string } | null;
}

/** 비-KR 심사용 참고 번역. 판정 파이프라인에는 개입하지 않는 표시 전용 데이터.
 * 영어(en)가 메인, 크메르어(km)가 서브. ko 는 과거 런 호환용(레거시). */
export interface AdTranslations {
  en: string | null;
  km?: string | null;
  /** @deprecated 과거 런 호환용 — 신규 런은 km 을 사용한다. */
  ko?: string | null;
  /** 문장별 정렬 번역(sentence_units 분할 그대로) — 원문 아래 문장 단위 병기용. */
  sentences?: { original: string; en: string | null; km?: string | null; ko?: string | null }[] | null;
  note?: string;
}

/** NDJSON event emitted by `POST /api/review/stream`. */
export interface StreamEvent {
  event: "step_started" | "step_completed" | "result" | "error" | string;
  step?: string;
  review_run_id?: string;
  summary?: string;
  counts?: Record<string, number>;
  sample?: unknown;
  payload?: unknown;
  result?: ReviewOutput;
  error?: string;
  detail?: { error?: string; message?: string; cause?: string; [key: string]: unknown };
  received_at?: string;
}

export interface ReviewRequest {
  dataset_item_id: string;
  title: string;
  content_text: string;
  channel: string;
  source_type?: string;
  product_group: string;
  selected_product_name?: string;
  workspace_id: string;
  /** 광고 원문 언어(메타데이터). 라우팅은 workspace_id 담당 — 기록·번역 표시용. */
  language?: string;
  /** 선택 LLM 모델(빈 값=.env 기본). 백엔드가 게이트웨이 모델을 오버라이드. */
  llm_model?: string;
  /** 실행자 가명(브라우저별). 실행 기록에 누가 돌렸는지 표시. */
  actor?: string;
  /** 이미지 광고 접수(base64, data: 프리픽스 제외). 문안이 비어 있으면 비전 추출로 채운다. */
  image_base64?: string;
  image_media_type?: string;
  /** 다장 이미지 접수(카드뉴스 등, 최대 5장) — 있으면 image_base64보다 우선. */
  images?: { base64: string; media_type: string }[];
  /** 프리셋 전달용(프론트 전용) — 폼이 이 URL의 이미지를 불러와 첨부한다. 서버로는 안 보냄. */
  image_url?: string;
}
