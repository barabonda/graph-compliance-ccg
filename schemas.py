"""Typed contracts for the GraphCompliance CCG review workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Verdict = Literal["COMPLIANT", "NON_COMPLIANT", "INSUFFICIENT", "NOT_APPLICABLE"]
FinalVerdict = Literal["pass_candidate", "revise", "reject", "needs_review"]
SupportLevel = Literal["STRONG", "WEAK"]
ProminenceTier = Literal["headline", "subcopy", "body", "footnote", "unknown"]


@dataclass(frozen=True)
class AnchorFeatureSet:
    feature_set_id: str
    anchor_id: str
    action_types: list[str]
    positive_features: list[str]
    missing_context: list[str]
    evidence: list[str]


@dataclass(frozen=True)
class CULegalElementProfile:
    profile_id: str
    cu_id: str
    action_type: str
    required_positive_features: list[str]
    applicability_scope: list[str]
    risk_title: str
    exception_eligible: bool
    rationale: str = ""


@dataclass(frozen=True)
class ReviewInput:
    content_text: str
    workspace_id: str = "graphcompliance_mvp_jb_20260530"
    dataset_item_id: str = ""
    title: str = ""
    channel: str = "bank_event_page_text"
    source_type: str = ""
    product_group: str = "auto"
    selected_product_id: str = ""
    selected_product_name: str = ""
    # 광고 원문 언어(메타데이터). 데이터 라우팅은 workspace_id가 담당하고 추출·정규화는
    # 언어 분기 없이 동작하므로, 이 필드는 run 기록·향후 확장(번역 표시 등)용이다.
    language: str = "ko"


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ContextEntity:
    entity_id: str
    name: str
    entity_type: str
    span: Span


@dataclass(frozen=True)
class ContextRelation:
    source_id: str
    predicate: str
    target_id: str
    evidence: str


@dataclass(frozen=True)
class ContextTriple:
    triple_id: str
    claim_id: str
    subject: str
    predicate: str
    object: str
    evidence: str
    subject_type: str = ""
    object_type: str = ""


@dataclass(frozen=True)
class ContextFrame:
    frame_id: str
    summary: str
    primary_message: str
    product_purpose: str
    tone: str
    representative_consumer_impression: str
    risk_axes: list[str]
    overall_risk_level: str


@dataclass(frozen=True)
class SentenceUnit:
    sentence_id: str
    index: int
    text: str
    span: Span
    role: str
    local_meaning: str
    context_effect: str
    risk_level: str
    prominence_tier: ProminenceTier = "unknown"


@dataclass(frozen=True)
class InterSentenceRelation:
    relation_id: str
    source_sentence_id: str
    target_sentence_id: str
    relation_type: Literal[
        "REINFORCES",
        "QUALIFIES",
        "CONTRADICTS",
        "MITIGATES",
        "AMPLIFIES_RISK",
        "SEQUENCES",
        "OTHER",
    ]
    explanation: str
    evidence: str


@dataclass(frozen=True)
class ContextInfluence:
    influence_id: str
    source_id: str
    source_type: str
    target_id: str
    target_type: str
    influence_type: str
    effect: str
    risk_delta: str
    confidence: float


@dataclass(frozen=True)
class ClaimQualifier:
    qualifier_id: str
    text: str
    role: str
    span: Span
    meaning: str
    risk_reason: str
    confidence: float
    prominence_tier: ProminenceTier = "unknown"


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    span: Span
    meaning: str
    implicature: str
    consumer_effect: str
    risk_hypernym: str
    risk_severity: str
    sentence_id: str = ""
    entities: list[ContextEntity] = field(default_factory=list)
    relations: list[ContextRelation] = field(default_factory=list)
    qualifiers: list[ClaimQualifier] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyHypernymProposal:
    proposal_id: str
    source_id: str
    hypernym_id: str
    hypernym: str
    support: SupportLevel
    confidence: float
    normalized_score: float
    evidence_ids: list[str] = field(default_factory=list)
    why: str = ""


@dataclass(frozen=True)
class ContextAnchor:
    anchor_id: str
    anchor_type: str
    claim_id: str
    span: Span
    facts: list[str]
    hypernyms: list[PolicyHypernymProposal]
    feature_set: AnchorFeatureSet | None = None


@dataclass(frozen=True)
class PolicyCandidate:
    cu_id: str
    principle: str
    subject: str
    condition: str
    constraint: str
    context: str
    cu_type: str
    source_article: str
    active_for_gate: bool
    matched_hypernym_ids: list[str]
    legal_evidence_ids: list[str]
    evidence_texts: list[str]
    retrieval_scores: dict[str, Any]
    retrieval_basis: str = "hypernym_profile"
    gate_status: str = "active"
    reference_paths: list[dict[str, Any]] = field(default_factory=list)
    legal_element_profile: CULegalElementProfile | None = None
    matched_required_features: list[str] = field(default_factory=list)
    missing_required_features: list[str] = field(default_factory=list)
    legal_element_match: bool = False
    risk_title: str = ""


@dataclass(frozen=True)
class CUPlanItem:
    plan_item_id: str
    anchor_id: str
    cu_id: str
    principle: str
    source_article: str
    subject: str
    condition: str
    constraint: str
    context: str
    legal_evidence_ids: list[str]
    evidence_texts: list[str]
    retrieval_scores: dict[str, Any]
    rerank_score: float
    selection_reason: str
    retrieval_basis: str = "hypernym_profile"
    gate_status: str = "active"
    reference_paths: list[dict[str, Any]] = field(default_factory=list)
    legal_element_profile: CULegalElementProfile | None = None
    matched_required_features: list[str] = field(default_factory=list)
    missing_required_features: list[str] = field(default_factory=list)
    legal_element_match: bool = False
    risk_title: str = ""


@dataclass(frozen=True)
class EvidenceWindow:
    evidence_window_id: str
    plan_item_id: str
    anchor_id: str
    facts: list[str]
    legal_evidence_ids: list[str]
    legal_evidence_texts: list[str]
    context_frame: dict[str, Any] = field(default_factory=dict)
    sentence_unit: dict[str, Any] = field(default_factory=dict)
    # 이 anchor 문장을 한정/완화하는 다른 문장(QUALIFIES/MITIGATES). 혜택 주장이
    # 별도 문장의 조건으로 한정되는데 anchor만 보면 과도하게 단정으로 보이는 것 방지.
    related_sentences: list[dict[str, Any]] = field(default_factory=list)
    context_influences: list[dict[str, Any]] = field(default_factory=list)
    policy_evidence_chains: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMJudgment:
    judgment_id: str
    plan_item_id: str
    anchor_id: str
    cu_id: str
    verdict: Verdict
    score: float
    why: str
    evidence_span: str
    used_policy_evidence: list[str]
    # 금감원 답변식 설명가능 추론: 정의 → 요건별 사실 적용 → 결론 → 유보.
    legal_basis: str = ""
    criteria_findings: list[dict[str, Any]] = field(default_factory=list)
    conclusion: str = ""
    reservation: str = ""


@dataclass(frozen=True)
class ExceptionReview:
    exception_review_id: str
    judgment_id: str
    cu_id: str
    applies: bool
    effect: Literal["NONE", "DOWNGRADE_TO_REVIEW", "OVERRIDE_TO_COMPLIANT"]
    why: str
    closure_evidence_ids: list[str]


@dataclass(frozen=True)
class ProductFact:
    fact_id: str
    fact_type: str
    value: str
    unit: str
    condition: str
    source_document_id: str
    page_or_chunk: str
    evidence_text: str
    confidence: float


@dataclass(frozen=True)
class ClaimFact:
    claim_fact_id: str
    claim_id: str
    fact_type: str
    value: str
    unit: str
    qualifier: str
    evidence_text: str
    confidence: float
    prominence_tier: ProminenceTier = "unknown"


@dataclass(frozen=True)
class ComparisonResult:
    comparison_id: str
    claim_fact_id: str
    product_fact_id: str
    status: Literal[
        "SUPPORTED",
        "CONTRADICTED",
        "CONDITION_MISSING",
        "PROMINENCE_INSUFFICIENT",
        "NO_PRODUCT_FACT",
        "NEEDS_PRODUCT_SELECTION",
    ]
    rationale: str
    evidence_text: str
    confidence: float


@dataclass
class ReviewGraph:
    review_run_id: str
    ad_draft_id: str
    content_hash: str
    context_frame: dict[str, Any] = field(default_factory=dict)
    sentence_units: list[SentenceUnit] = field(default_factory=list)
    inter_sentence_relations: list[InterSentenceRelation] = field(default_factory=list)
    context_influences: list[ContextInfluence] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    context_triples: list[ContextTriple] = field(default_factory=list)
    anchors: list[ContextAnchor] = field(default_factory=list)
    anchor_feature_sets: list[AnchorFeatureSet] = field(default_factory=list)
    cu_plan: list[CUPlanItem] = field(default_factory=list)
    evidence_windows: list[EvidenceWindow] = field(default_factory=list)
    judgments: list[LLMJudgment] = field(default_factory=list)
    exception_reviews: list[ExceptionReview] = field(default_factory=list)
    graph_paths: list[dict[str, Any]] = field(default_factory=list)
    retrieval_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)
    product_context: dict[str, Any] = field(default_factory=dict)
    product_fact_context: dict[str, Any] = field(default_factory=dict)
    applicability_gate: dict[str, Any] = field(default_factory=dict)
    prominence_analysis: dict[str, Any] = field(default_factory=dict)
    disclosure_links: list[dict[str, Any]] = field(default_factory=list)
    prominence_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    disclosure_requirements: list[dict[str, Any]] = field(default_factory=list)
    policy_evidence_chains: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    overall_impression_judgment: dict[str, Any] = field(default_factory=dict)
    track_c_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewOutput:
    dataset_item_id: str
    final_verdict: FinalVerdict
    routing: dict[str, Any]
    detected_issues: list[dict[str, Any]]
    post_approval_required_actions: list[str]
    rationale: str
    review_run_id: str
    context_frame: dict[str, Any]
    sentence_units: list[dict[str, Any]]
    inter_sentence_relations: list[dict[str, Any]]
    context_influences: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    context_triples: list[dict[str, Any]]
    context_anchors: list[dict[str, Any]]
    anchor_feature_sets: list[dict[str, Any]]
    cu_plan: list[dict[str, Any]]
    judgments: list[dict[str, Any]]
    effective_judgments: list[dict[str, Any]]
    exception_reviews: list[dict[str, Any]]
    anchor_display: list[dict[str, Any]]
    system_review_items: list[dict[str, Any]]
    revision_suggestions: list[dict[str, Any]]
    product_context: dict[str, Any]
    product_fact_context: dict[str, Any]
    applicability_gate: dict[str, Any]
    prominence_analysis: dict[str, Any]
    disclosure_links: list[dict[str, Any]]
    prominence_diagnostics: list[dict[str, Any]]
    disclosure_requirements: list[dict[str, Any]]
    policy_evidence_chains: dict[str, list[dict[str, Any]]]
    overall_impression_judgment: dict[str, Any]
    track_c_summary: dict[str, Any]
    article_aggregation: list[dict[str, Any]]
    principle_aggregation: list[dict[str, Any]]
    reference_paths_summary: list[dict[str, Any]]
    graph_paths: list[dict[str, Any]]
    highlight_spans: list[dict[str, Any]]
    # 참고용 번역(표시 전용) — 비-KR workspace에서만 채워진다({en, ko, note}).
    # 판정 파이프라인에는 절대 개입하지 않는다. KR 응답은 None(기존과 동일).
    ad_translations: dict[str, Any] | None = None
