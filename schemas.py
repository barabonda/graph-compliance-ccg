"""Typed contracts for the GraphCompliance CCG review workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Verdict = Literal["COMPLIANT", "NON_COMPLIANT", "INSUFFICIENT", "NOT_APPLICABLE"]
FinalVerdict = Literal["pass_candidate", "revise", "reject", "needs_review"]
SupportLevel = Literal["STRONG", "WEAK"]


@dataclass(frozen=True)
class ReviewInput:
    content_text: str
    workspace_id: str = "graphcompliance_mvp_jb_20260530"
    dataset_item_id: str = ""
    title: str = ""
    channel: str = "bank_event_page_text"
    source_type: str = ""
    product_group: str = "auto"


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
class Claim:
    claim_id: str
    text: str
    span: Span
    meaning: str
    implicature: str
    consumer_effect: str
    risk_hypernym: str
    risk_severity: str
    entities: list[ContextEntity] = field(default_factory=list)
    relations: list[ContextRelation] = field(default_factory=list)


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
    retrieval_scores: dict[str, float]
    retrieval_basis: str = "hypernym_profile"
    gate_status: str = "active"
    reference_paths: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CUPlanItem:
    plan_item_id: str
    anchor_id: str
    cu_id: str
    principle: str
    subject: str
    condition: str
    constraint: str
    context: str
    legal_evidence_ids: list[str]
    evidence_texts: list[str]
    retrieval_scores: dict[str, float]
    rerank_score: float
    selection_reason: str
    retrieval_basis: str = "hypernym_profile"
    gate_status: str = "active"
    reference_paths: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceWindow:
    evidence_window_id: str
    plan_item_id: str
    anchor_id: str
    facts: list[str]
    legal_evidence_ids: list[str]
    legal_evidence_texts: list[str]


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


@dataclass(frozen=True)
class ExceptionReview:
    exception_review_id: str
    judgment_id: str
    cu_id: str
    applies: bool
    effect: Literal["NONE", "DOWNGRADE_TO_REVIEW", "OVERRIDE_TO_COMPLIANT"]
    why: str
    closure_evidence_ids: list[str]


@dataclass
class ReviewGraph:
    review_run_id: str
    ad_draft_id: str
    content_hash: str
    claims: list[Claim] = field(default_factory=list)
    context_triples: list[ContextTriple] = field(default_factory=list)
    anchors: list[ContextAnchor] = field(default_factory=list)
    cu_plan: list[CUPlanItem] = field(default_factory=list)
    evidence_windows: list[EvidenceWindow] = field(default_factory=list)
    judgments: list[LLMJudgment] = field(default_factory=list)
    exception_reviews: list[ExceptionReview] = field(default_factory=list)
    graph_paths: list[dict[str, Any]] = field(default_factory=list)
    retrieval_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)
    product_context: dict[str, Any] = field(default_factory=dict)
    disclosure_requirements: list[dict[str, Any]] = field(default_factory=list)
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
    context_triples: list[dict[str, Any]]
    context_anchors: list[dict[str, Any]]
    cu_plan: list[dict[str, Any]]
    judgments: list[dict[str, Any]]
    effective_judgments: list[dict[str, Any]]
    exception_reviews: list[dict[str, Any]]
    anchor_display: list[dict[str, Any]]
    system_review_items: list[dict[str, Any]]
    revision_suggestions: list[dict[str, Any]]
    product_context: dict[str, Any]
    disclosure_requirements: list[dict[str, Any]]
    overall_impression_judgment: dict[str, Any]
    track_c_summary: dict[str, Any]
    graph_paths: list[dict[str, Any]]
    highlight_spans: list[dict[str, Any]]
