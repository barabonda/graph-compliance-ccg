from __future__ import annotations

import re
from pathlib import Path

import pytest

from context_extractor import LLMContextExtractor
from llm_gateway import LLMGateway
from evaluate import (
    EvaluationLabels,
    EvaluationRecord,
    evaluate_records,
    load_records,
    review_payload_for_record,
    summarize_prediction,
)
from normalizer import PolicyGuidedNormalizer
from policy_compiler import validate_compiler_output
from retriever import PolicyRetriever, candidate_allowed_for_anchor, candidate_from_row
from revision import LLMRevisionSuggester
from schemas import Claim, ContextAnchor, CUPlanItem, LLMJudgment, PolicyCandidate, PolicyHypernymProposal, ReviewGraph, ReviewInput, Span
from vocabulary_governance import validate_governance_output
from workflow import GraphComplianceCCGWorkflow
from server import runtime_error_detail


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.calls: list[str] = []


class FakeLLM(LLMGateway):
    def __init__(self, *, verdict: str = "NON_COMPLIANT") -> None:
        self.client = FakeOpenAIClient()
        self.model = "fake"
        self.verdict = verdict
        self.exception_calls = 0

    def structured(self, *, name, system, user, schema):
        self.client.calls.append(name)
        if name == "graphcompliance_context_extraction":
            return {
                "claims": [
                    {
                        "text": "지난 3년간 조기상환 성공률이 높았던 ELS는 중위험 투자자에게 좋은 선택입니다.",
                        "start": 0,
                        "end": 46,
                        "meaning": "ELS 상품을 중위험 투자자에게 긍정적으로 제시함",
                        "implicature": "과거 조기상환 성공률이 향후 선택에도 유리하다는 인상",
                        "consumer_effect": "소비자가 원금손실 및 조건 위험을 과소평가할 수 있음",
                        "risk_hypernym": "past performance claim / suitability target",
                        "risk_severity": "HIGH",
                        "entities": [
                            {"name": "ELS", "entity_type": "product", "start": 17, "end": 20},
                            {"name": "중위험 투자자", "entity_type": "target_consumer", "start": 22, "end": 29},
                        ],
                        "relations": [
                            {
                                "source_name": "ELS",
                                "predicate": "recommended_to",
                                "target_name": "중위험 투자자",
                                "evidence": "중위험 투자자에게 좋은 선택",
                            }
                        ],
                    }
                ]
            }
        if name == "graphcompliance_policy_normalization":
            claim_id = re.search(r"'claim_id': '([^']+)'", user).group(1)
            return {
                "anchors": [
                    {
                        "anchor_type": "risk_anchor",
                        "claim_id": claim_id,
                        "start": 0,
                        "end": 46,
                        "text": "지난 3년간 조기상환 성공률이 높았던 ELS",
                        "facts": ["ELS cites past early-redemption success rate"],
                        "hypernyms": [
                            {
                                "hypernym_id": "policy_hypernym_past_performance",
                                "hypernym": "과거성과표시",
                                "support": "STRONG",
                                "confidence": 0.91,
                                "evidence_ids": ["premise_1"],
                                "why": "Premise discusses past performance disclaimers.",
                            }
                        ],
                    }
                ]
            }
        if name == "graphcompliance_cuplan_rerank":
            anchor_id = re.search(r"'anchor_id': '([^']+)'", user).group(1)
            cu_id = re.search(r"'cu_id': '([^']+)'", user).group(1)
            return {
                "selected": [
                    {
                        "anchor_id": anchor_id,
                        "cu_id": cu_id,
                        "rerank_score": 0.94,
                        "selection_reason": "Past performance claim maps to future-return-mislead CU.",
                    }
                ]
            }
        if name == "graphcompliance_cu_judgment":
            plan_item_id = re.search(r"'plan_item_id': '([^']+)'", user).group(1)
            return {
                "judgments": [
                    {
                        "plan_item_id": plan_item_id,
                        "verdict": self.verdict,
                        "score": 0.9,
                        "why": "과거 성과를 근거로 좋은 선택이라고 연결했습니다.",
                        "evidence_span": "지난 3년간 조기상환 성공률",
                        "used_policy_evidence": ["legal_chunk_1"],
                    }
                ]
            }
        if name == "graphcompliance_overall_impression":
            return {
                "verdict": "LOW",
                "misleading_risk_score": 0.2,
                "representative_consumer_impression": "상품 위험과 조건을 추가로 확인해야 한다는 인상",
                "misleading_factors": [],
                "grounded_claim_ids": [],
                "why": "제공된 claim path만으로 중대한 전체 인상 오인 신호는 낮습니다.",
            }
        if name == "graphcompliance_exception_override":
            self.exception_calls += 1
            return {
                "applies": False,
                "effect": "NONE",
                "why": "Closure 안에 위반을 뒤집는 예외가 없습니다.",
                "closure_evidence_ids": [],
            }
        if name == "graphcompliance_revision_suggestions":
            anchor_id = re.search(r"'anchor_id': '([^']+)'", user).group(1)
            return {
                "suggestions": [
                    {
                        "anchor_id": anchor_id,
                        "severity": "revise",
                        "risky_text": "지난 3년간 조기상환 성공률",
                        "why_problematic": "과거 성과를 현재 선택 근거로 연결했습니다.",
                        "required_disclosures": ["과거 성과는 미래 수익을 보장하지 않는다는 고지"],
                        "before": "좋은 선택입니다.",
                        "after": "상품 구조와 손실 가능성을 확인한 뒤 투자 여부를 판단하시기 바랍니다.",
                        "notes_for_reviewer": "위험고지 동반 여부를 확인하세요.",
                    }
                ]
            }
        raise AssertionError(f"unexpected LLM call: {name}")


class CapturingExtractionLLM(FakeLLM):
    def __init__(self) -> None:
        super().__init__()
        self.last_system = ""

    def structured(self, *, name, system, user, schema):
        if name == "graphcompliance_context_extraction":
            self.last_system = system
            return {
                "claims": [
                    {
                        "text": "최고 연 5.0% 금리를 확정 제공한다.",
                        "start": 0,
                        "end": 22,
                        "meaning": "확정 금리 제공 주장",
                        "implicature": "조건 없이 확정 금리를 받을 수 있다는 인상",
                        "consumer_effect": "소비자가 조건 변동 가능성을 낮게 볼 수 있음",
                        "risk_hypernym": "definitive-rate claim",
                        "risk_severity": "HIGH",
                        "entities": [],
                        "relations": [],
                    }
                ]
            }
        return super().structured(name=name, system=system, user=user, schema=schema)


class OverrideLLM(FakeLLM):
    def structured(self, *, name, system, user, schema):
        if name == "graphcompliance_exception_override":
            self.exception_calls += 1
            return {
                "applies": True,
                "effect": "OVERRIDE_TO_COMPLIANT",
                "why": "제공된 closure의 고지가 위반 판단을 뒤집습니다.",
                "closure_evidence_ids": ["exception_1"],
            }
        return super().structured(name=name, system=system, user=user, schema=schema)


class EmptyRerankLLM(FakeLLM):
    def structured(self, *, name, system, user, schema):
        if name == "graphcompliance_cuplan_rerank":
            return {"selected": []}
        return super().structured(name=name, system=system, user=user, schema=schema)


class MisleadingLLM(FakeLLM):
    def structured(self, *, name, system, user, schema):
        if name == "graphcompliance_overall_impression":
            return {
                "verdict": "HIGH",
                "misleading_risk_score": 0.84,
                "representative_consumer_impression": "보통 소비자는 조건 없이 누구나 좋은 결과를 얻는다고 이해할 수 있습니다.",
                "misleading_factors": ["조건 누락", "누구나 가능하다는 전체 인상"],
                "grounded_claim_ids": [],
                "why": "Claim의 의미와 함의가 소비자에게 승인/혜택의 제한 조건을 약하게 전달합니다.",
            }
        return super().structured(name=name, system=system, user=user, schema=schema)


class UnknownHypernymLLM(FakeLLM):
    def structured(self, *, name, system, user, schema):
        if name == "graphcompliance_policy_normalization":
            return {
                "anchors": [
                    {
                        "anchor_type": "risk_anchor",
                        "claim_id": "claim_1",
                        "start": 0,
                        "end": 3,
                        "text": "ELS",
                        "facts": ["ELS appears in ad"],
                        "hypernyms": [
                            {
                                "hypernym_id": "policy_hypernym_education",
                                "hypernym": "EDUCATION",
                                "support": "WEAK",
                                "confidence": 0.8,
                                "evidence_ids": [],
                                "why": "Not in vocabulary.",
                            }
                        ],
                    }
                ]
            }
        return super().structured(name=name, system=system, user=user, schema=schema)


class FakeRetriever(PolicyRetriever):
    def assert_policy_alignment_ready(self, *, workspace_id: str) -> None:
        return None

    def policy_context_for_claims(self, *, workspace_id: str, query_text: str, limit: int = 80):
        return {
            "hypernyms": [
                {
                    "hypernym_id": "policy_hypernym_past_performance",
                    "name": "과거성과표시",
                    "domain": "claim",
                    "description": "과거 수익률이나 성과를 표시하는 주장",
                }
            ],
            "premises": [
                {
                    "id": "premise_1",
                    "text": "과거 실적은 미래 수익률을 보장하지 않는다는 내용을 표시해야 한다.",
                    "hypernym_id": "policy_hypernym_past_performance",
                }
            ],
            "fragments": [{"id": "legal_chunk_1", "text": "과거 실적은 미래 수익률을 보장하지 않는다는 내용을 표시해야 한다."}],
        }

    def candidates_for_anchor(self, *, workspace_id: str, anchor: ContextAnchor, product_group: str = "auto", channel: str = "", limit: int = 12):
        return [
            PolicyCandidate(
                cu_id="cu_past_performance",
                principle="부당권유행위 금지",
                subject="투자성 상품 광고",
                condition="과거 성과를 표시하는 경우",
                constraint="미래 수익을 보장하는 것으로 오인하게 해서는 안 된다",
                context="investment_product_advertising",
                cu_type="ACTOR_CU",
                source_article="금소법 시행령 광고 금지행위",
                active_for_gate=True,
                matched_hypernym_ids=["policy_hypernym_past_performance"],
                legal_evidence_ids=["legal_chunk_1"],
                evidence_texts=["과거 실적은 미래 수익률을 보장하지 않는다는 내용을 표시해야 한다."],
                retrieval_scores={"active_for_gate": 1.0, "combined_score": 0.95},
            )
        ]

    def exception_closure(self, *, workspace_id: str, cu_id: str, max_depth: int = 4):
        return [{"id": "legal_chunk_1", "labels": ["LegalChunk"], "text": "예외 없음"}]


class EmptyCandidateRetriever(FakeRetriever):
    def candidates_for_anchor(self, *, workspace_id: str, anchor: ContextAnchor, product_group: str = "auto", channel: str = "", limit: int = 12):
        return []


class FakeWriter:
    def __init__(self) -> None:
        self.saved: list[ReviewGraph] = []

    def save(self, review_input: ReviewInput, graph: ReviewGraph) -> None:
        self.saved.append(graph)


def test_workflow_builds_cuplan_judges_and_persists() -> None:
    llm = FakeLLM(verdict="NON_COMPLIANT")
    writer = FakeWriter()
    workflow = GraphComplianceCCGWorkflow(llm=llm, retriever=FakeRetriever(), writer=writer)

    output = workflow.review(
        ReviewInput(
            dataset_item_id="demo_els_001",
            content_text="지난 3년간 조기상환 성공률이 높았던 ELS는 중위험 투자자에게 좋은 선택입니다.",
        )
    )

    assert output.final_verdict == "reject"
    assert output.routing["review_phrase_expected_in_input"] is False
    assert output.cu_plan
    assert output.context_triples
    assert any(triple["predicate"] == "recommended_to" for triple in output.context_triples)
    assert output.judgments[0]["verdict"] == "NON_COMPLIANT"
    assert output.effective_judgments[0]["verdict"] == "NON_COMPLIANT"
    assert output.anchor_display[0]["display_verdict"] == "NON_COMPLIANT"
    assert output.revision_suggestions
    assert output.context_anchors[0]["hypernyms"][0]["support"] == "STRONG"
    assert output.context_anchors[0]["hypernyms"][0]["hypernym_id"] == "policy_hypernym_past_performance"
    assert output.overall_impression_judgment["standard"].startswith("대법원")
    assert output.product_context["product_group"] == "investment"
    assert output.disclosure_requirements
    assert writer.saved
    assert llm.exception_calls == 1


def test_context_extractor_prompt_preserves_risky_claims_separately() -> None:
    llm = CapturingExtractionLLM()
    extractor = LLMContextExtractor(llm)

    claims = extractor.extract(
        ReviewInput(
            content_text=(
                "최고 연 5.0% 금리를 확정 제공한다. "
                "기본금리와 우대금리는 가입기간, 우대조건 충족 여부에 따라 달라질 수 있다."
            )
        ),
        review_run_id="run_prompt_check",
    )

    assert claims[0].risk_severity == "HIGH"
    assert "Do not collapse a risky claim into a later mitigating disclosure" in llm.last_system
    assert "최고 연 5.0% 금리를 확정 제공" in llm.last_system


def test_exception_override_only_runs_for_non_compliant() -> None:
    llm = FakeLLM(verdict="INSUFFICIENT")
    workflow = GraphComplianceCCGWorkflow(llm=llm, retriever=FakeRetriever(), writer=FakeWriter())

    output = workflow.review(ReviewInput(content_text="추가 근거가 필요한 광고입니다."))

    assert output.final_verdict == "needs_review"
    assert llm.exception_calls == 0
    assert output.revision_suggestions


def test_revision_suggester_skips_neutral_launch_anchor_with_broad_policy_tag() -> None:
    llm = FakeLLM(verdict="INSUFFICIENT")
    anchor = ContextAnchor(
        anchor_id="anchor_launch",
        anchor_type="claim_anchor",
        claim_id="claim_launch",
        span=Span(start=0, end=10, text="JB 특판예금 출시."),
        facts=["상품 출시를 알리는 중립 소개 문장"],
        hypernyms=[
            PolicyHypernymProposal(
                proposal_id="proposal_1",
                source_id="claim_launch",
                hypernym_id="policy_hypernym_ad_regulation",
                hypernym="광고 규제",
                support="WEAK",
                confidence=0.62,
                normalized_score=0.62,
            )
        ],
    )
    plan = CUPlanItem(
        plan_item_id="plan_launch",
        anchor_id=anchor.anchor_id,
        cu_id="cu_ad_general",
        principle="광고규제",
        source_article="금소법 제22조",
        subject="광고 표시",
        condition="금융상품 광고인 경우",
        constraint="소비자를 오인하게 해서는 안 된다",
        context="금융광고 일반 기준",
        legal_evidence_ids=["legal_chunk_1"],
        evidence_texts=["광고는 소비자를 오인하게 해서는 안 된다."],
        retrieval_scores={"combined_score": 0.62},
        rerank_score=0.62,
        selection_reason="일반 광고규제 후보",
    )
    judgment = LLMJudgment(
        judgment_id="judgment_launch",
        plan_item_id=plan.plan_item_id,
        anchor_id=anchor.anchor_id,
        cu_id=plan.cu_id,
        verdict="INSUFFICIENT",
        score=0.62,
        why="출시 문장만으로 광고 표시 기준 충족 여부를 판단하기 어렵습니다.",
        evidence_span=anchor.span.text,
        used_policy_evidence=["legal_chunk_1"],
    )
    graph = ReviewGraph(
        review_run_id="run_launch",
        ad_draft_id="ad_launch",
        content_hash="hash_launch",
        anchors=[anchor],
        cu_plan=[plan],
        judgments=[judgment],
    )

    suggestions = LLMRevisionSuggester(llm).suggest(
        review_input=ReviewInput(content_text="JB 특판예금 출시. 누구나 연 5% 확정 보장 수익"),
        graph=graph,
    )

    assert suggestions == []
    assert "graphcompliance_revision_suggestions" not in llm.client.calls


def test_exception_override_effective_verdict_drives_output() -> None:
    llm = OverrideLLM(verdict="NON_COMPLIANT")
    workflow = GraphComplianceCCGWorkflow(llm=llm, retriever=FakeRetriever(), writer=FakeWriter())

    output = workflow.review(ReviewInput(content_text="예외 고지가 있는 광고입니다."))

    assert output.final_verdict == "pass_candidate"
    assert output.judgments[0]["verdict"] == "NON_COMPLIANT"
    assert output.effective_judgments[0]["verdict"] == "COMPLIANT"
    assert output.anchor_display[0]["display_verdict"] == "COMPLIANT"
    assert output.detected_issues == []
    assert output.revision_suggestions == []


def test_actionable_anchor_keeps_retrieval_candidate_when_rerank_selects_none() -> None:
    workflow = GraphComplianceCCGWorkflow(llm=EmptyRerankLLM(verdict="INSUFFICIENT"), retriever=FakeRetriever(), writer=FakeWriter())

    output = workflow.review(ReviewInput(content_text="최고 금리를 확정 제공한다고 표시합니다."))

    assert output.cu_plan
    assert output.anchor_display[0]["display_verdict"] == "INSUFFICIENT"
    assert output.system_review_items == []


def test_empty_cuplan_routes_to_needs_review() -> None:
    workflow = GraphComplianceCCGWorkflow(llm=FakeLLM(verdict="COMPLIANT"), retriever=EmptyCandidateRetriever(), writer=FakeWriter())

    output = workflow.review(ReviewInput(content_text="지난 3년간 조기상환 성공률이 높았습니다."))

    assert output.final_verdict == "needs_review"
    assert output.detected_issues == []
    assert output.system_review_items[0]["risk_code"] == "MISSING_POLICY_COVERAGE"
    assert output.anchor_display[0]["display_verdict"] == "RETRIEVAL_FAILURE"
    assert output.anchor_display[0]["retrieval_failure_code"] == "MISSING_POLICY_COVERAGE"


def test_track_b_overall_impression_routes_to_revise() -> None:
    workflow = GraphComplianceCCGWorkflow(llm=MisleadingLLM(verdict="COMPLIANT"), retriever=FakeRetriever(), writer=FakeWriter())

    output = workflow.review(ReviewInput(product_group="loan", content_text="누구나 쉽게 승인되는 대출입니다."))

    assert output.final_verdict == "revise"
    assert any(issue["risk_code"] == "TRACK_B_OVERALL_IMPRESSION" for issue in output.detected_issues)
    assert output.overall_impression_judgment["misleading_risk_score"] == 0.84


def test_product_metadata_is_grounding_not_disclosure_fact() -> None:
    workflow = GraphComplianceCCGWorkflow(llm=FakeLLM(verdict="COMPLIANT"), retriever=FakeRetriever(), writer=FakeWriter())

    output = workflow.review(ReviewInput(product_group="deposit", content_text="JB시니어우대예금 안내입니다."))

    assert output.product_context["product_group"] == "deposit"
    assert any(item["label"] == "예금자보호 부보내용" for item in output.disclosure_requirements)
    assert "DisclosureFact" not in str(output.product_context)


def test_candidate_scoring_accepts_canonical_name_overlap() -> None:
    candidate = candidate_from_row(
        {
            "cu_id": "cu_false_ad",
            "principle": "광고규제",
            "subject": "허위ㆍ과장 광고 금지",
            "condition": "",
            "constraint": "오인 가능 표현 금지",
            "context": "financial_advertising",
            "cu_type": "ACTOR_CU",
            "source_article": "금소법 제22조",
            "active_for_gate": True,
            "matched_hypernym_ids": ["policy_hypernym_connected_duplicate"],
            "matched_hypernym_names": ["보장 금지"],
            "profile_embedding": [1.0, 0.0],
            "evidence": [{"id": "premise_1", "text": "보장 표현은 오인 가능 광고에 해당할 수 있다."}],
        },
        anchor_embedding=[1.0, 0.0],
        requested_hypernym_ids=["policy_hypernym_orphan_duplicate"],
        requested_hypernym_names=["보장 금지"],
    )

    assert candidate.retrieval_scores["hypernym_overlap"] == 1.0
    assert candidate.retrieval_scores["combined_score"] > 0.9


def test_review_procedure_candidate_is_not_actionable_cu() -> None:
    anchor = ContextAnchor(
        anchor_id="anchor_1",
        anchor_type="claim_anchor",
        claim_id="claim_1",
        span=Span(start=0, end=12, text="심의필 표시"),
        facts=["review procedure mention"],
        hypernyms=[],
    )
    candidate = PolicyCandidate(
        cu_id="cu_review_procedure",
        principle="광고 심의 절차",
        subject="협회 확인 표시",
        condition="온라인 매체 광고",
        constraint="직접판매업자 확인 표시를 해야 한다",
        context="ReviewProcedure",
        cu_type="REVIEW_PROCEDURE",
        source_article="은행 광고심의 기준",
        active_for_gate=True,
        matched_hypernym_ids=[],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.99, "hypernym_overlap": 0.0, "combined_score": 0.99},
    )

    assert candidate_allowed_for_anchor(candidate, anchor, product_group="deposit") is False


def test_normalizer_rejects_unknown_policy_hypernym() -> None:
    normalizer = PolicyGuidedNormalizer(UnknownHypernymLLM())

    with pytest.raises(RuntimeError, match="unknown PolicyHypernym"):
        normalizer.normalize(
            review_run_id="run_1",
            claims=[
                Claim(
                    claim_id="claim_1",
                    text="ELS",
                    span=Span(start=0, end=3, text="ELS"),
                    meaning="ELS mention",
                    implicature="",
                    consumer_effect="",
                    risk_hypernym="",
                    risk_severity="LOW",
                )
            ],
            policy_context={
                "hypernyms": [
                    {
                        "hypernym_id": "policy_hypernym_derivative_linked_security",
                        "name": "파생결합증권",
                        "domain": "product",
                        "description": "ELS 등 파생결합증권",
                    }
                ],
                "premises": [],
                "fragments": [],
            },
        )


def test_default_llm_gateway_requires_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required"):
        LLMGateway()


def test_llm_gateway_reads_model_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-nano")

    gateway = LLMGateway(client=FakeOpenAIClient())

    assert gateway.model == "gpt-5.4-nano"


def test_server_classifies_policy_normalization_runtime_error() -> None:
    detail = runtime_error_detail(RuntimeError("LLM returned unknown PolicyHypernym id: policy_hypernym_bad"))

    assert detail["status_code"] == 422
    assert detail["error"] == "policy_normalization_failed"


def test_server_classifies_missing_policy_alignment_as_service_setup_error() -> None:
    detail = runtime_error_detail(RuntimeError("Policy alignment graph is missing; run the policy compiler before review."))

    assert detail["status_code"] == 503
    assert detail["error"] == "policy_alignment_missing"


def test_compiler_rejects_english_only_hypernym_labels() -> None:
    errors = validate_compiler_output(
        {
            "policy_hypernyms": [
                {
                    "name": "financial_product",
                    "domain": "product",
                    "description": "Financial product.",
                    "priority": 1,
                }
            ],
            "premises": [],
            "cu_profiles": [
                {
                    "cu_id": "cu_1",
                    "subject_hypernym_names": ["financial_product"],
                    "profile_summary": "",
                    "embedding_text": "",
                }
            ],
        },
        {"cu_1"},
    )

    assert any("non-Korean canonical" in error for error in errors)


def test_vocabulary_governance_rejects_english_only_canonical_name() -> None:
    errors = validate_governance_output(
        {
            "items": [
                {
                    "hypernym_id": "h1",
                    "canonical_name_ko": "financial_product",
                    "domain": "product",
                    "description_ko": "금융상품",
                    "aliases": ["financial_product"],
                    "merge_key": "product:financial_product",
                    "confidence": 0.9,
                    "why": "bad",
                }
            ]
        },
        {"h1"},
    )

    assert any("non-Korean canonical_name_ko" in error for error in errors)


def test_evaluation_metrics_follow_article_level_multilabel_matrix() -> None:
    records = [
        EvaluationRecord(
            record_id="r1",
            text="case 1",
            labels=EvaluationLabels(violation=True, articles=["Art.A", "Art.B"], risk_level="high"),
        ),
        EvaluationRecord(
            record_id="r2",
            text="case 2",
            labels=EvaluationLabels(violation=True, articles=["Art.B"], risk_level="medium"),
        ),
    ]
    predictions = {
        "r1": {
            "dataset_item_id": "r1",
            "final_verdict": "revise",
            "cu_plan": [
                {"plan_item_id": "p1", "cu_id": "cu_a", "source_article": "Art.A", "principle": "광고규제"}
            ],
            "effective_judgments": [
                {"plan_item_id": "p1", "verdict": "NON_COMPLIANT", "used_policy_evidence": ["chunk_a"]}
            ],
        },
        "r2": {
            "dataset_item_id": "r2",
            "final_verdict": "revise",
            "cu_plan": [
                {"plan_item_id": "p2", "cu_id": "cu_b", "source_article": "Art.B", "principle": "광고규제"},
                {"plan_item_id": "p3", "cu_id": "cu_c", "source_article": "Art.C", "principle": "설명의무"},
            ],
            "effective_judgments": [
                {"plan_item_id": "p2", "verdict": "NON_COMPLIANT", "used_policy_evidence": ["chunk_b"]},
                {"plan_item_id": "p3", "verdict": "INSUFFICIENT", "used_policy_evidence": ["chunk_c"]},
            ],
        },
    }

    report = evaluate_records(records, predictions)
    metrics = report["article_metrics"]

    assert metrics["counts"] == {"tp": 2, "fp": 1, "fn": 1, "tn": 2}
    assert metrics["micro_f1"] == pytest.approx(2 / 3)
    assert metrics["micro_f2"] == pytest.approx(2 / 3)
    assert metrics["mcc"] == pytest.approx(1 / 3)


def test_gold_labels_are_excluded_from_review_payload() -> None:
    record = EvaluationRecord(
        record_id="eval_001",
        text="최고 금리 광고입니다.",
        facts={"gold_hint": "do not send"},
        product_group="deposit",
        labels=EvaluationLabels(
            violation=True,
            articles=["금소법 제22조"],
            sales_principles=["광고규제"],
            risk_level="high",
        ),
    )

    payload = review_payload_for_record(record, workspace_id="ws_eval")

    assert payload["content_text"] == record.text
    assert payload["product_group"] == "deposit"
    assert "labels" not in payload
    assert "facts" not in payload
    assert "금소법 제22조" not in str(payload)


def test_redteam_docx_eval_fixture_loads_without_prompt_label_leakage() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "eval"
        / "redteam_korean_financial_ad_12.jsonl"
    )

    records = load_records(path)

    assert len(records) == 12
    assert {record.record_id for record in records} == {
        "A01",
        "A02",
        "A03",
        "A04",
        "A05",
        "A06",
        "A07",
        "A08",
        "A09",
        "A10",
        "A11",
        "A12",
    }
    assert all(record.labels.violation for record in records)
    assert all(record.labels.articles for record in records)
    assert all(record.labels.violation_types for record in records)

    sample = next(record for record in records if record.record_id == "A09")
    payload = review_payload_for_record(sample, workspace_id="ws_redteam")

    assert payload["dataset_item_id"] == "A09"
    assert "labels" not in payload
    assert "facts" not in payload
    assert "V10" not in str(payload)
    assert "금소법 제22조" not in str(payload)
    assert "expected_problem_spans" not in str(payload)


def test_prediction_summary_uses_only_risky_plan_item_articles() -> None:
    summary = summarize_prediction(
        "risky_only",
        {
            "dataset_item_id": "risky_only",
            "final_verdict": "revise",
            "cu_plan": [
                {"plan_item_id": "p1", "source_article": "금소법 제22조", "principle": "광고규제"},
                {"plan_item_id": "p2", "source_article": "금소법 제19조", "principle": "설명의무"},
            ],
            "effective_judgments": [
                {"plan_item_id": "p1", "verdict": "COMPLIANT", "used_policy_evidence": ["chunk_1"]},
                {"plan_item_id": "p2", "verdict": "INSUFFICIENT", "used_policy_evidence": ["chunk_2"]},
            ],
            "context_triples": [{"predicate": "DENOTES"}],
        },
    )

    assert summary.predicted_articles == ["금소법 제19조"]
    assert summary.predicted_sales_principles == ["설명의무"]
    assert summary.context_triple_count == 1
