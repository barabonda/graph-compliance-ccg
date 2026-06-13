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
  risk_title?: string;
  subject?: string;
  constraint?: string;
  severity?: number;
  problem_span?: string;
  rationale?: string;
  required_action?: string;
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
}

/** 운영 대시보드용 실행(ReviewRun) 요약. `GET /api/runs`. */
export interface RunSummary {
  id: string;
  ts: number;
  title: string;
  channel: string;
  product_group: string;
  model: string;
  content_text: string;
  final_verdict: string;
  misleading_verdict: string;
  issue_count: number;
  missing_disclosures: string[];
  principles: string[];
  cu_ids: string[];
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
  explicit_mitigation_signals?: { id?: string; label?: string; matched_terms?: string }[];
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
  /** 선택 LLM 모델(빈 값=.env 기본). 백엔드가 게이트웨이 모델을 오버라이드. */
  llm_model?: string;
}
