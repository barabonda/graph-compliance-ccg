from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

import product_facts as product_facts_module
import jb_data_context as jb_data_context_module
from claim_modeling import fold_qualifier_anchors_into_parent_claims
from cross_encoder_reranker import with_cross_encoder_score
from context_extractor import LLMContextExtractor
from judge import LLMComplianceJudge
from legal_elements import build_anchor_feature_set, canonicalize_required_features
from llm_gateway import LLMGateway
from evaluate import (
    EvaluationLabels,
    EvaluationRecord,
    evaluate_records,
    load_records,
    review_payload_for_record,
    summarize_prediction,
)
from normalizer import PolicyGuidedNormalizer, normalization_schema_for_allowed_ids
from policy_evidence import build_policy_evidence_chains
from policy_compiler import validate_compiler_output
from product_facts import ProductFactAnalyzer
from prominence import build_prominence_artifacts
from retriever import PolicyRetriever, candidate_allowed_for_anchor, candidate_from_row, with_legal_element_gate, with_scope_gate
from revision import DISCLOSURE_BLOCK_ANCHOR, LLMRevisionSuggester
from router import build_output
from schemas import (
    AnchorFeatureSet,
    Claim,
    ClaimQualifier,
    ContextAnchor,
    CULegalElementProfile,
    CUPlanItem,
    EvidenceWindow,
    LLMJudgment,
    PolicyCandidate,
    PolicyHypernymProposal,
    ReviewGraph,
    ReviewInput,
    SentenceUnit,
    Span,
)
from vocabulary_governance import validate_governance_output
from workflow import GraphComplianceCCGWorkflow
from server import runtime_error_detail
from build_synthetic_eval_dataset import (
    best_deposit_rate_value,
    build_records_from_product_facts,
    load_taxonomy,
    parse_channels,
    validate_product_facts,
)
from quality_report_synthetic_eval_dataset import build_quality_report


def sample_plan_item_for_policy_chain() -> CUPlanItem:
    return CUPlanItem(
        plan_item_id="plan_guarantee",
        anchor_id="anchor_guarantee",
        cu_id="cu_guarantee_mislead",
        principle="광고규제",
        source_article="금소법 제22조",
        subject="수익 보장 오인 가능 표현",
        condition="예금 광고에서 최고금리 또는 수익을 단정적으로 표시하는 경우",
        constraint="조건과 한도를 명확히 고지해야 함",
        context="deposit_advertising",
        legal_evidence_ids=["premise_rate_disclosure"],
        evidence_texts=["금융상품 광고는 소비자가 오인하지 않도록 명확하고 공정하게 전달해야 한다."],
        retrieval_scores={"combined_score": 0.91},
        rerank_score=0.91,
        selection_reason="보장/확정/조건 누락 표현과 직접 관련된 CU입니다.",
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_guarantee",
            cu_id="cu_guarantee_mislead",
            action_type="guarantee_or_return_misleading",
            required_positive_features=["guarantee_expression", "certainty_expression"],
            applicability_scope=["deposit", "web_page"],
            risk_title="확정 보장 수익 표현으로 수익 보장 오인 가능",
            exception_eligible=False,
        ),
        matched_required_features=["guarantee_expression", "certainty_expression", "unconditional_expression"],
        legal_element_match=True,
        risk_title="확정 보장 수익 표현으로 수익 보장 오인 가능",
    )


def test_policy_evidence_chains_are_split_by_purpose() -> None:
    plan = sample_plan_item_for_policy_chain()

    chains = build_policy_evidence_chains(
        review_run_id="run_policy_chain",
        cu_plan=[plan],
        disclosure_requirements=[
            {
                "id": "disclosure_rate_condition",
                "label": "금리 및 우대조건 표시",
                "why": "최고금리 표시 시 적용 조건과 기간을 함께 안내해야 함",
                "source": "은행 광고심의 기준",
            }
        ],
        product_context={"product_group": "deposit"},
    )

    assert chains["legal_basis_chains"][0]["status"] == "FOUND"
    assert chains["legal_basis_chains"][0]["basis_nodes"][0]["label"] == "금소법 제22조"
    assert any(edge["relationship_type"] == "DELEGATES_TO" for edge in chains["legal_basis_chains"][0]["delegation_edges"])
    assert chains["disclosure_chains"][0]["status"] == "FOUND"
    assert chains["disclosure_chains"][0]["disclosure_nodes"][0]["label"] == "금리 및 우대조건 표시"
    assert chains["exception_chains"][0]["status"] == "NOT_FOUND"
    assert any(row["chain_type"] == "ExceptionChain" for row in chains["chain_diagnostics"])


def test_evidence_window_uses_only_found_policy_chains_for_judge() -> None:
    plan = sample_plan_item_for_policy_chain()
    chains = {
        "legal_basis_chains": [
            {
                "status": "FOUND",
                "anchor_id": plan.anchor_id,
                "plan_item_id": plan.plan_item_id,
                "summary": "금소법 제22조 광고규제 근거",
            }
        ],
        "disclosure_chains": [
            {
                "status": "FOUND",
                "anchor_id": plan.anchor_id,
                "plan_item_id": plan.plan_item_id,
                "summary": "금리 및 우대조건 표시 필요",
            }
        ],
        "exception_chains": [
            {
                "status": "INCOMPLETE",
                "anchor_id": plan.anchor_id,
                "plan_item_id": plan.plan_item_id,
                "summary": "예외 chain 미완성",
            }
        ],
        "chain_diagnostics": [],
    }

    window = LLMComplianceJudge(FakeLLM()).build_evidence_windows(
        review_run_id="run_policy_chain",
        anchors=[
            ContextAnchor(
                anchor_id=plan.anchor_id,
                anchor_type="claim_anchor",
                claim_id="claim_1",
                span=Span(0, 10, "누구나 연 5% 확정 보장"),
                facts=["확정 보장 수익 표현"],
                hypernyms=[],
            )
        ],
        plan=[plan],
        policy_evidence_chains=chains,
    )[0]

    assert window.policy_evidence_chains["legal_basis_chains"][0]["summary"] == "금소법 제22조 광고규제 근거"
    assert window.policy_evidence_chains["disclosure_chains"][0]["summary"] == "금리 및 우대조건 표시 필요"
    assert window.policy_evidence_chains["exception_chains"] == []


class DuplicateJudgmentLLM(LLMGateway):
    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
        if name != "graphcompliance_cu_judgment":
            raise AssertionError(f"unexpected LLM call: {name}")
        plan_item_id = re.search(r"'plan_item_id': '([^']+)'", user).group(1)
        return {
            "judgments": [
                {
                    "plan_item_id": plan_item_id,
                    "verdict": "NON_COMPLIANT",
                    "score": 0.9,
                    "why": "확정 보장 표현입니다.",
                    "evidence_span": "누구나 연 5% 확정 보장",
                    "used_policy_evidence": ["legal_chunk_1"],
                },
                {
                    "plan_item_id": plan_item_id,
                    "verdict": "NON_COMPLIANT",
                    "score": 0.7,
                    "why": "중복 판단입니다.",
                    "evidence_span": "누구나 연 5% 확정 보장",
                    "used_policy_evidence": ["legal_chunk_1"],
                },
            ]
        }


def test_judge_deduplicates_repeated_rows_for_one_plan_item() -> None:
    plan = sample_plan_item_for_policy_chain()
    anchor = ContextAnchor(
        anchor_id=plan.anchor_id,
        anchor_type="claim_anchor",
        claim_id="claim_1",
        span=Span(0, 14, "누구나 연 5% 확정 보장"),
        facts=["확정 보장 표현"],
        hypernyms=[],
    )
    window = EvidenceWindow(
        evidence_window_id="window_1",
        plan_item_id=plan.plan_item_id,
        anchor_id=plan.anchor_id,
        facts=anchor.facts,
        legal_evidence_ids=plan.legal_evidence_ids,
        legal_evidence_texts=plan.evidence_texts,
    )

    judgments = LLMComplianceJudge(DuplicateJudgmentLLM()).judge(
        review_run_id="run_duplicate_judgment",
        anchors=[anchor],
        plan=[plan],
        windows=[window],
    )

    assert len(judgments) == 1
    assert judgments[0].score == 0.9


def test_condition_disclosure_sentence_is_displayed_as_mitigation_not_issue() -> None:
    claim = Claim(
        claim_id="claim_disclosure",
        text="우대조건과 가입기간에 따라 실제 적용 금리는 달라질 수 있습니다.",
        span=Span(0, 35, "우대조건과 가입기간에 따라 실제 적용 금리는 달라질 수 있습니다."),
        meaning="금리 적용 조건이 달라질 수 있음을 고지",
        implicature="소비자가 조건을 확인해야 함",
        consumer_effect="확정 보장 인상을 완화",
        risk_hypernym="조건 고지",
        risk_severity="LOW",
        sentence_id="sentence_disclosure",
    )
    anchor = ContextAnchor(
        anchor_id="anchor_disclosure",
        anchor_type="claim_anchor",
        claim_id=claim.claim_id,
        span=claim.span,
        facts=["우대조건과 가입기간에 따라 금리가 달라질 수 있음을 고지"],
        hypernyms=[],
    )
    plan = CUPlanItem(
        plan_item_id="plan_disclosure",
        anchor_id=anchor.anchor_id,
        cu_id="cu_rate_disclosure",
        principle="광고규제",
        source_article="금소법 제22조",
        subject="금리 조건 고지",
        condition="최고금리 표시 시",
        constraint="조건을 명확히 표시해야 함",
        context="deposit_advertising",
        legal_evidence_ids=["legal_chunk_1"],
        evidence_texts=["최고금리 표시 시 조건을 명확히 표시해야 한다."],
        retrieval_scores={"combined_score": 0.8},
        rerank_score=0.8,
        selection_reason="조건 고지 확인",
    )
    judgment = LLMJudgment(
        judgment_id="judgment_disclosure",
        plan_item_id=plan.plan_item_id,
        anchor_id=anchor.anchor_id,
        cu_id=plan.cu_id,
        verdict="NON_COMPLIANT",
        score=0.86,
        why="테스트상 위험 판단이 반환되어도 condition_disclosure 문장은 issue로 승격하지 않는다.",
        evidence_span=anchor.span.text,
        used_policy_evidence=["legal_chunk_1"],
    )
    graph = ReviewGraph(
        review_run_id="run_disclosure",
        ad_draft_id="ad_disclosure",
        content_hash="hash_disclosure",
        sentence_units=[
            SentenceUnit(
                sentence_id="sentence_disclosure",
                index=1,
                text=claim.text,
                span=claim.span,
                role="condition_disclosure",
                local_meaning=claim.meaning,
                context_effect="위험 claim을 완화",
                risk_level="LOW",
            )
        ],
        claims=[claim],
        anchors=[anchor],
        cu_plan=[plan],
        judgments=[judgment],
    )

    output = build_output(ReviewInput(content_text=claim.text), graph)

    assert output.detected_issues == []
    assert output.anchor_display[0]["display_role"] == "mitigation"
    assert output.anchor_display[0]["display_verdict"] == "MITIGATION"
    assert output.highlight_spans[0]["verdict"] == "MITIGATION"


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.calls: list[str] = []


class FakeLLM(LLMGateway):
    def __init__(self, *, verdict: str = "NON_COMPLIANT") -> None:
        self.client = FakeOpenAIClient()
        self.model = "fake"
        self.verdict = verdict
        self.exception_calls = 0

    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
        self.client.calls.append(name)
        if name == "graphcompliance_context_extraction":
            return {
                "context_frame": {
                    "summary": "ELS 성과를 근거로 중위험 투자자에게 긍정적 선택 인상을 줌",
                    "primary_message": "과거 조기상환 성과가 투자 선택에 유리하다는 메시지",
                    "product_purpose": "ELS 투자 권유",
                    "tone": "긍정적 권유",
                    "representative_consumer_impression": "중위험 투자자에게 적합한 선택처럼 보일 수 있음",
                    "risk_axes": ["과거성과표시", "적합성판단"],
                    "overall_risk_level": "HIGH",
                },
                "sentence_units": [
                    {
                        "index": 0,
                        "text": "지난 3년간 조기상환 성공률이 높았던 ELS는 중위험 투자자에게 좋은 선택입니다.",
                        "start": 0,
                        "end": 46,
                        "role": "benefit_claim",
                        "local_meaning": "ELS의 과거 조기상환 성과와 투자자 적합성을 연결함",
                        "context_effect": "과거성과가 현재 선택의 근거라는 전체 인상을 만듦",
                        "risk_level": "HIGH",
                    }
                ],
                "inter_sentence_relations": [],
                "context_influences": [
                    {
                        "source_type": "sentence",
                        "source_index": 0,
                        "source_text": "지난 3년간 조기상환 성공률이 높았던 ELS는 중위험 투자자에게 좋은 선택입니다.",
                        "target_type": "context_frame",
                        "target_index": 0,
                        "influence_type": "FRAMES_PRODUCT_AS_SUITABLE",
                        "effect": "문장 하나가 전체 광고를 긍정적 투자권유 인상으로 만듦",
                        "risk_delta": "RAISES_RISK",
                        "confidence": 0.9,
                    }
                ],
                "claims": [
                    {
                        "sentence_index": 0,
                        "text": "지난 3년간 조기상환 성공률이 높았던 ELS는 중위험 투자자에게 좋은 선택입니다.",
                        "start": 0,
                        "end": 46,
                        "meaning": "ELS 상품을 중위험 투자자에게 긍정적으로 제시함",
                        "implicature": "과거 조기상환 성공률이 향후 선택에도 유리하다는 인상",
                        "consumer_effect": "소비자가 원금손실 및 조건 위험을 과소평가할 수 있음",
                        "risk_hypernym": "past performance claim / suitability target",
                        "risk_severity": "HIGH",
                        "qualifiers": [
                            {
                                "text": "좋은 선택",
                                "role": "benefit_scope",
                                "start": 33,
                                "end": 38,
                                "meaning": "투자 선택의 적합성을 긍정적으로 표현",
                                "risk_reason": "대상 투자자에게 적합하다는 인상을 줄 수 있음",
                                "confidence": 0.8,
                            }
                        ],
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
        if name == "graphcompliance_context_sentences":
            payload = self.structured(
                name="graphcompliance_context_extraction",
                system=system,
                user=user,
                schema=schema,
                timeout_seconds=timeout_seconds,
                model=model,
            )
            return {
                "context_frame": payload["context_frame"],
                "sentence_units": payload["sentence_units"],
            }
        if name == "graphcompliance_context_claims":
            payload = self.structured(
                name="graphcompliance_context_extraction",
                system=system,
                user=user,
                schema=schema,
                timeout_seconds=timeout_seconds,
                model=model,
            )
            return {"claims": payload["claims"]}
        if name == "graphcompliance_context_relations":
            payload = self.structured(
                name="graphcompliance_context_extraction",
                system=system,
                user=user,
                schema=schema,
                timeout_seconds=timeout_seconds,
                model=model,
            )
            return {
                "inter_sentence_relations": payload["inter_sentence_relations"],
                "context_influences": payload["context_influences"],
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
        if name == "graphcompliance_product_fact_extraction":
            return {
                "product_facts": [
                    {
                        "fact_type": "max_rate",
                        "value": "5.0",
                        "unit": "percent",
                        "condition": "우대조건 충족 시",
                        "source_document_id": "doc_1",
                        "page_or_chunk": "page 1",
                        "evidence_text": "우대조건 충족 시 최고 연 5.0%",
                        "confidence": 0.91,
                    }
                ]
            }
        if name == "graphcompliance_claim_fact_comparison":
            return {"claim_facts": [], "comparison_results": []}
        if name == "graphcompliance_exception_override":
            self.exception_calls += 1
            return {
                "applies": False,
                "effect": "NONE",
                "why": "Closure 안에 위반을 뒤집는 예외가 없습니다.",
                "closure_evidence_ids": [],
            }
        if name == "graphcompliance_revision_suggestions":
            # Production now invokes revision even when there are no per-span risk
            # rows — missing disclosures or a Track B overall-impression signal can
            # trigger it on their own (see revision.py needs_revision). In that case
            # the prompt's [risk_rows] block is empty, so there is no anchor to echo
            # back; the LLM returns no per-span suggestion and production appends the
            # disclosure block separately.
            anchor_match = re.search(r"'anchor_id': '([^']+)'", user)
            if anchor_match is None:
                return {"suggestions": []}
            anchor_id = anchor_match.group(1)
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

    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
        if name == "graphcompliance_context_extraction":
            self.last_system = system
            return {
                "context_frame": {
                    "summary": "최고 금리를 확정 제공한다는 전체 인상",
                    "primary_message": "조건 없는 확정 금리 제공",
                    "product_purpose": "예금 금리 혜택 안내",
                    "tone": "단정적",
                    "representative_consumer_impression": "소비자는 금리가 확정된다고 이해할 수 있음",
                    "risk_axes": ["확정표현", "조건누락"],
                    "overall_risk_level": "HIGH",
                },
                "sentence_units": [
                    {
                        "index": 0,
                        "text": "최고 연 5.0% 금리를 확정 제공한다.",
                        "start": 0,
                        "end": 22,
                        "role": "benefit_claim",
                        "local_meaning": "최고 금리를 단정적으로 제공한다고 표현",
                        "context_effect": "조건 없는 확정 혜택 인상을 강화",
                        "risk_level": "HIGH",
                    }
                ],
                "inter_sentence_relations": [],
                "context_influences": [
                    {
                        "source_type": "sentence",
                        "source_index": 0,
                        "source_text": "최고 연 5.0% 금리를 확정 제공한다.",
                        "target_type": "context_frame",
                        "target_index": 0,
                        "influence_type": "AMPLIFIES_RATE_CERTAINTY",
                        "effect": "확정이라는 표현이 전체 광고의 단정성을 높임",
                        "risk_delta": "RAISES_RISK",
                        "confidence": 0.9,
                    }
                ],
                "claims": [
                    {
                        "sentence_index": 0,
                        "text": "최고 연 5.0% 금리를 확정 제공한다.",
                        "start": 0,
                        "end": 22,
                        "meaning": "확정 금리 제공 주장",
                        "implicature": "조건 없이 확정 금리를 받을 수 있다는 인상",
                        "consumer_effect": "소비자가 조건 변동 가능성을 낮게 볼 수 있음",
                        "risk_hypernym": "definitive-rate claim",
                        "risk_severity": "HIGH",
                        "qualifiers": [
                            {
                                "text": "확정",
                                "role": "certainty",
                                "start": 13,
                                "end": 15,
                                "meaning": "금리 제공을 단정적으로 표현",
                                "risk_reason": "조건 없는 확정 제공으로 오인될 수 있음",
                                "confidence": 0.92,
                            }
                        ],
                        "entities": [],
                        "relations": [],
                    }
                ]
            }
        if name == "graphcompliance_context_sentences":
            payload = self.structured(
                name="graphcompliance_context_extraction",
                system=system,
                user=user,
                schema=schema,
                timeout_seconds=timeout_seconds,
                model=model,
            )
            return {
                "context_frame": payload["context_frame"],
                "sentence_units": payload["sentence_units"],
            }
        if name == "graphcompliance_context_claims":
            self.last_system = system
            payload = self.structured(
                name="graphcompliance_context_extraction",
                system=system,
                user=user,
                schema=schema,
                timeout_seconds=timeout_seconds,
                model=model,
            )
            return {"claims": payload["claims"]}
        if name == "graphcompliance_context_relations":
            previous_system = self.last_system
            payload = self.structured(
                name="graphcompliance_context_extraction",
                system=system,
                user=user,
                schema=schema,
                timeout_seconds=timeout_seconds,
                model=model,
            )
            self.last_system = previous_system
            return {
                "inter_sentence_relations": payload["inter_sentence_relations"],
                "context_influences": payload["context_influences"],
            }
        return super().structured(name=name, system=system, user=user, schema=schema)


class OverrideLLM(FakeLLM):
    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
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
    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
        if name == "graphcompliance_cuplan_rerank":
            return {"selected": []}
        return super().structured(name=name, system=system, user=user, schema=schema)


class MisleadingLLM(FakeLLM):
    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
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


class ProductFactLLM(FakeLLM):
    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
        if name == "graphcompliance_product_fact_extraction":
            return {
                "product_facts": [
                    {
                        "fact_type": "max_rate",
                        "value": "5.0",
                        "unit": "percent",
                        "condition": "가입기간 12개월 및 우대조건 충족 시",
                        "source_document_id": "doc_1",
                        "page_or_chunk": "page 1",
                        "evidence_text": "최고 연 5.0%는 가입기간 12개월 및 우대조건 충족 시 적용",
                        "confidence": 0.95,
                    }
                ]
            }
        if name == "graphcompliance_claim_fact_comparison":
            product_fact_id = re.search(r"'fact_id': '([^']+)'", user).group(1)
            return {
                "claim_facts": [
                    {
                        "claim_id": "claim_1",
                        "fact_type": "max_rate",
                        "value": "5.0",
                        "unit": "percent",
                        "qualifier": "누구나 조건 없이 확정",
                        "evidence_text": "누구나 조건 없이 연 5% 확정",
                        "confidence": 0.9,
                    }
                ],
                "comparison_results": [
                    {
                        "claim_fact_index": 0,
                        "product_fact_id": product_fact_id,
                        "status": "CONDITION_MISSING",
                        "rationale": "금리 숫자는 맞지만 가입기간과 우대조건이 광고 claim에 함께 표시되지 않았습니다.",
                        "evidence_text": "최고 연 5.0%는 가입기간 12개월 및 우대조건 충족 시 적용",
                        "confidence": 0.88,
                    }
                ],
            }
        return super().structured(name=name, system=system, user=user, schema=schema)


class UnknownHypernymLLM(FakeLLM):
    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
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


class AllUnusableAnchorLLM(FakeLLM):
    """Normalization returns only malformed anchors (unknown claim_id), so every
    item is dropped and no usable ContextAnchor survives — the all-bad case."""

    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
        if name == "graphcompliance_policy_normalization":
            return {
                "anchors": [
                    {
                        "anchor_type": "risk_anchor",
                        "claim_id": "claim_not_in_input",
                        "start": 0,
                        "end": 3,
                        "text": "ELS",
                        "facts": ["ELS appears in ad"],
                        "hypernyms": [],
                    }
                ]
            }
        return super().structured(name=name, system=system, user=user, schema=schema)


class LeakyEvidenceLLM(FakeLLM):
    def structured(self, *, name, system, user, schema, timeout_seconds=None, model=None):
        if name == "graphcompliance_cu_judgment":
            plan_item_id = re.search(r"'plan_item_id': '([^']+)'", user).group(1)
            return {
                "judgments": [
                    {
                        "plan_item_id": plan_item_id,
                        "verdict": "NON_COMPLIANT",
                        "score": 0.95,
                        "why": "다른 claim의 확정 보장 수익 문구를 근거로 위반이라고 판단했습니다.",
                        "evidence_span": "누구나 연 5% 확정 보장 수익을 받을 수 있는 절호의 기회입니다.",
                        "used_policy_evidence": ["legal_chunk_1"],
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
                legal_element_profile=CULegalElementProfile(
                    profile_id="profile_past_performance",
                    cu_id="cu_past_performance",
                    action_type="past_performance_or_future_return",
                    required_positive_features=["past_performance_claim"],
                    applicability_scope=["investment"],
                    risk_title="과거 성과를 미래 수익으로 오인시킬 가능성",
                    exception_eligible=True,
                    rationale="과거 성과 표시에는 미래 수익 보장 오인 방지 고지가 필요함",
                ),
                matched_required_features=["past_performance_claim"],
                legal_element_match=True,
                risk_title="과거 성과를 미래 수익으로 오인시킬 가능성",
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


class FakeCrossEncoderReranker:
    @property
    def enabled(self) -> bool:
        return True

    def rerank(self, *, candidates_by_anchor, anchors, limit_per_anchor: int):
        reranked = {}
        for anchor_id, candidates in candidates_by_anchor.items():
            scored = [
                with_cross_encoder_score(candidate, 0.95 if candidate.cu_id == "cu_past_performance" else 0.10)
                for candidate in candidates
            ]
            scored.sort(key=lambda candidate: candidate.retrieval_scores["cross_encoder_combined_score"], reverse=True)
            reranked[anchor_id] = scored[:limit_per_anchor]
        return reranked


class TwoCandidateRetriever(FakeRetriever):
    def candidates_for_anchor(self, *, workspace_id: str, anchor: ContextAnchor, product_group: str = "auto", channel: str = "", limit: int = 12):
        relevant = super().candidates_for_anchor(
            workspace_id=workspace_id,
            anchor=anchor,
            product_group=product_group,
            channel=channel,
            limit=limit,
        )[0]
        broad = PolicyCandidate(
            cu_id="cu_broad_ad",
            principle="광고규제",
            subject="일반 금융상품 광고",
            condition="금융상품 광고를 하는 경우",
            constraint="명확하고 공정하게 전달해야 한다",
            context="financial_product_advertising",
            cu_type="ACTOR_CU",
            source_article="금소법 제22조",
            active_for_gate=True,
            matched_hypernym_ids=["policy_hypernym_past_performance"],
            legal_evidence_ids=["legal_chunk_broad"],
            evidence_texts=["광고는 명확하고 공정해야 한다."],
            retrieval_scores={"active_for_gate": 1.0, "combined_score": 0.99, "legal_element_match": 1.0},
            legal_element_profile=CULegalElementProfile(
                profile_id="profile_broad",
                cu_id="cu_broad_ad",
                action_type="past_performance_or_future_return",
                required_positive_features=["past_performance_claim"],
                applicability_scope=["investment"],
                risk_title="일반 광고 명확성 검토",
                exception_eligible=False,
            ),
            matched_required_features=["past_performance_claim"],
            legal_element_match=True,
            risk_title="일반 광고 명확성 검토",
        )
        return [broad, relevant]


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


def test_workflow_uses_cross_encoder_reranker_before_llm_rerank() -> None:
    llm = FakeLLM(verdict="NON_COMPLIANT")
    workflow = GraphComplianceCCGWorkflow(
        llm=llm,
        retriever=TwoCandidateRetriever(),
        writer=FakeWriter(),
        cross_encoder_reranker=FakeCrossEncoderReranker(),
    )

    events = list(
        workflow.review_events(
            ReviewInput(
                dataset_item_id="demo_cross_encoder_001",
                content_text="지난 3년간 조기상환 성공률이 높았던 ELS는 중위험 투자자에게 좋은 선택입니다.",
            )
        )
    )

    output = next(event["result"] for event in events if event["event"] == "result")
    cross_encoder_event = next(
        event for event in events if event["event"] == "step_completed" and event["step"] == "Cross-encoder CU rerank"
    )

    assert cross_encoder_event["counts"]["enabled"] == 1
    assert output.cu_plan[0]["cu_id"] == "cu_past_performance"
    assert output.cu_plan[0]["retrieval_scores"]["cross_encoder_score"] == pytest.approx(0.95)


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


def test_generic_scope_qualifier_folds_into_parent_claim_anchor() -> None:
    claim = Claim(
        claim_id="claim_rate",
        text="누구나 연 5% 확정 보장 수익",
        span=Span(start=0, end=17, text="누구나 연 5% 확정 보장 수익"),
        meaning="모든 소비자가 확정 수익을 받을 수 있다는 주장",
        implicature="조건 없이 확정 수익을 받을 수 있다는 인상",
        consumer_effect="소비자가 가입대상과 우대조건을 확인하지 않을 수 있음",
        risk_hypernym="보장성 수익 오인",
        risk_severity="HIGH",
        qualifiers=[
            ClaimQualifier(
                qualifier_id="qualifier_anyone",
                text="누구나",
                role="target_scope",
                span=Span(start=0, end=3, text="누구나"),
                meaning="대상 제한이 없는 것으로 표현",
                risk_reason="가입대상 제한이나 조건이 없다는 인상을 줄 수 있음",
                confidence=0.93,
            )
        ],
    )
    claim_anchor = ContextAnchor(
        anchor_id="anchor_claim",
        anchor_type="claim_anchor",
        claim_id=claim.claim_id,
        span=claim.span,
        facts=["확정 보장 수익 주장"],
        hypernyms=[],
    )
    target_anchor = ContextAnchor(
        anchor_id="anchor_anyone",
        anchor_type="target_consumer_anchor",
        claim_id=claim.claim_id,
        span=Span(start=0, end=3, text="누구나"),
        facts=["일반 금융소비자 전체"],
        hypernyms=[],
    )

    folded = fold_qualifier_anchors_into_parent_claims([claim_anchor, target_anchor], [claim])

    assert [anchor.anchor_id for anchor in folded] == ["anchor_claim"]
    assert any("ClaimQualifier role=target_scope text='누구나'" in fact for fact in folded[0].facts)


def test_policy_normalization_schema_restricts_hypernym_ids_to_approved_vocabulary() -> None:
    schema = normalization_schema_for_allowed_ids({"policy_hypernym_a", "policy_hypernym_b"})
    hypernym_id_schema = (
        schema["properties"]["anchors"]["items"]["properties"]["hypernyms"]["items"]["properties"]["hypernym_id"]
    )

    assert hypernym_id_schema == {
        "type": "string",
        "enum": ["policy_hypernym_a", "policy_hypernym_b"],
    }


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


def test_judge_downgrades_cross_anchor_evidence_leakage() -> None:
    anchor = ContextAnchor(
        anchor_id="anchor_launch",
        anchor_type="claim_anchor",
        claim_id="claim_launch",
        span=Span(start=0, end=10, text="JB 특판예금 출시."),
        facts=["JB에서 특판예금 상품 출시 가능성을 알리는 중립 문장"],
        hypernyms=[
            PolicyHypernymProposal(
                proposal_id="proposal_launch",
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
        cu_id="cu_false_ad",
        principle="광고규제",
        source_article="금소법 제22조",
        subject="허위ㆍ과장 광고 금지",
        condition="금융상품 광고인 경우",
        constraint="오인 가능 표현 금지",
        context="financial_advertising",
        legal_evidence_ids=["legal_chunk_1"],
        evidence_texts=["광고는 소비자를 오인하게 해서는 안 된다."],
        retrieval_scores={"combined_score": 0.62},
        rerank_score=0.62,
        selection_reason="일반 광고규제 후보",
    )
    window = EvidenceWindow(
        evidence_window_id="window_launch",
        plan_item_id=plan.plan_item_id,
        anchor_id=anchor.anchor_id,
        facts=anchor.facts,
        legal_evidence_ids=plan.legal_evidence_ids,
        legal_evidence_texts=plan.evidence_texts,
    )

    judgments = LLMComplianceJudge(LeakyEvidenceLLM()).judge(
        review_run_id="run_launch",
        anchors=[anchor],
        plan=[plan],
        windows=[window],
    )

    assert judgments[0].verdict == "INSUFFICIENT"
    assert judgments[0].score == 0.5
    assert judgments[0].evidence_span == "JB 특판예금 출시."
    assert "outside this anchor" in judgments[0].why


def test_exception_override_effective_verdict_drives_output() -> None:
    llm = OverrideLLM(verdict="NON_COMPLIANT")
    workflow = GraphComplianceCCGWorkflow(llm=llm, retriever=FakeRetriever(), writer=FakeWriter())

    output = workflow.review(ReviewInput(content_text="예외 고지가 있는 광고입니다."))

    assert output.final_verdict == "pass_candidate"
    assert output.judgments[0]["verdict"] == "NON_COMPLIANT"
    assert output.effective_judgments[0]["verdict"] == "COMPLIANT"
    assert output.anchor_display[0]["display_verdict"] == "COMPLIANT"
    assert output.detected_issues == []
    # Override to COMPLIANT clears the per-span violation revision; the only item
    # that may remain is the separately-gated missing-disclosure block sentinel
    # (there must be no anchor-specific violation suggestion).
    assert all(
        suggestion["anchor_id"] == DISCLOSURE_BLOCK_ANCHOR
        for suggestion in output.revision_suggestions
    )


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
    assert output.system_review_items[0]["risk_code"] == "NO_LEGAL_ELEMENT_MATCH"
    assert output.anchor_display[0]["display_verdict"] == "RETRIEVAL_FAILURE"
    assert output.anchor_display[0]["retrieval_failure_code"] == "NO_LEGAL_ELEMENT_MATCH"


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
    assert "product_fact_context" in output.__dict__


def test_product_fact_analyzer_requires_exact_product_selection() -> None:
    llm = FakeLLM()
    analyzer = ProductFactAnalyzer(llm)

    context = analyzer.analyze(
        review_input=ReviewInput(product_group="deposit", content_text="JB 특판예금 출시."),
        claims=[],
        product_context={
            "matched_products": [
                {"product": "JB시니어우대예금", "match_basis": "product_group_candidate"},
                {"product": "JB다이렉트예금", "match_basis": "product_group_candidate"},
            ]
        },
    )

    assert context["extraction_status"] == "NEEDS_PRODUCT_SELECTION"
    assert context["product_facts"] == []
    assert "graphcompliance_product_fact_extraction" not in llm.client.calls
    assert any(item["check_id"] == "disc_depositor_protection_notice" for item in context["disclosure_checks"])
    assert "applicability_gate" in context


def test_disclosure_check_handles_negated_protection_notice() -> None:
    checks = product_facts_module.build_disclosure_checks(
        ReviewInput(product_group="deposit", content_text="이 상품은 예금자보호 안 됨 상품입니다.")
    )

    protection = next(item for item in checks if item["check_id"] == "disc_depositor_protection_notice")
    assert protection["status"] == "PRESENT_BUT_NEGATED"
    assert protection["present"] is False


def test_disclosure_check_reports_unsupported_graph_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        product_facts_module,
        "disclosure_catalog_for_group",
        lambda workspace_id, product_group: (
            {
                "check_id": "disc_unknown_new_rule",
                "label": "새로운 고지",
                "source": "새 심의기준",
                "detect_tokens": ["새로운 고지"],
                "negative_tokens": [],
                "fact_match_tokens": ["새로운 고지"],
                "required_roles": [],
                "prominence_required": False,
                "check_type": "unsupported",
                "on_missing": "needs_review",
                "severity": 2,
                "product_groups": ["deposit"],
                "channels": [],
                "profile_supported": False,
            },
        ),
    )

    checks = product_facts_module.build_disclosure_checks(
        ReviewInput(product_group="deposit", content_text="JB 예금 안내입니다.")
    )

    unsupported = next(item for item in checks if item["check_id"] == "disc_unknown_new_rule")
    assert unsupported["status"] == "UNSUPPORTED_DISCLOSURE_CHECK"


def test_disclosure_check_detects_review_approval_notice_with_unicode_drift() -> None:
    text = "• 준법감시인 심의필 제2026-가-326호"
    decomposed = unicodedata.normalize("NFD", text)

    checks = product_facts_module.build_disclosure_checks(
        ReviewInput(product_group="deposit", content_text=decomposed)
    )

    review_approval = next(item for item in checks if item["check_id"] == "disc_review_approval_notice")
    assert review_approval["status"] == "PRESENT"
    assert review_approval["present"] is True
    assert {"준법감시인", "심의필"} & set(review_approval["detected_tokens"])


def test_product_fact_analyzer_accepts_selected_product(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        product_facts_module,
        "select_product_documents",
        lambda product: [
            {
                "document_id": "doc_selected",
                "product": product,
                "label": "상품설명서",
                "file_name": "jumpup.pdf",
                "relative_path": "예금/jumpup.pdf",
                "file_path": "/tmp/jumpup.pdf",
                "exists": True,
            }
        ],
    )
    monkeypatch.setattr(
        product_facts_module,
        "extract_document_snippet",
        lambda document: {
            "source_document_id": document["document_id"],
            "label": document["label"],
            "file_name": document["file_name"],
            "text": "최고 연 5.0%는 12개월 가입 및 우대조건 충족 시 적용됩니다.",
        },
    )

    context = ProductFactAnalyzer(ProductFactLLM()).analyze(
        review_input=ReviewInput(
            product_group="deposit",
            selected_product_name="(26년 JUMP UP) 특판 예금",
            content_text="JB 특판예금 출시. 누구나 조건 없이 최고 연 5.0% 확정.",
        ),
        claims=[
            Claim(
                claim_id="claim_selected",
                text="누구나 조건 없이 최고 연 5.0% 확정",
                span=Span(start=0, end=22, text="누구나 조건 없이 최고 연 5.0% 확정"),
                meaning="조건 없는 확정 금리 주장",
                implicature="모든 소비자가 최고금리를 받을 수 있다는 인상",
                consumer_effect="소비자가 우대조건을 확인하지 않을 수 있음",
                risk_hypernym="조건 누락 금리 주장",
                risk_severity="HIGH",
            )
        ],
        product_context={
            "matched_products": [
                {"product": "(26년 JUMP UP) 특판 예금", "match_basis": "selected_product"}
            ]
        },
    )

    assert context["extraction_status"] == "EXTRACTED"
    assert context["matched_product"] == "(26년 JUMP UP) 특판 예금"
    assert context["claim_facts"]
    assert context["comparison_results"]


def test_base_product_name_resolves_to_disclosure_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jb_data_context_module, "match_products_from_neo4j", lambda text, claims, product_group: [])
    monkeypatch.setattr(
        jb_data_context_module,
        "load_product_rows",
        lambda: {
            "JB시니어우대예금(만기일시지급식)": {
                "product": "JB시니어우대예금(만기일시지급식)",
                "product_group": "deposit",
                "major": "예금상품공시",
                "subcategory": "거치식예금",
                "category": "거치식예금",
                "document_count": 3,
                "document_labels": ["상품설명서", "특약", "약관"],
                "source_ids": ["doc_maturity"],
                "documents": [],
            },
            "JB시니어우대예금(월이자지급식)": {
                "product": "JB시니어우대예금(월이자지급식)",
                "product_group": "deposit",
                "major": "예금상품공시",
                "subcategory": "거치식예금",
                "category": "거치식예금",
                "document_count": 3,
                "document_labels": ["상품설명서", "특약", "약관"],
                "source_ids": ["doc_monthly"],
                "documents": [],
            },
        },
    )

    product_context, _ = jb_data_context_module.build_product_context(
        ReviewInput(
            product_group="deposit",
            selected_product_name="JB시니어우대예금",
            content_text="JB시니어우대예금 특판 안내입니다.",
        ),
        claims=[],
    )

    first = product_context["matched_products"][0]
    assert first["match_basis"] == "selected_product"
    assert first["selected_product_alias"] == "JB시니어우대예금"
    assert first["product"] in {
        "JB시니어우대예금(만기일시지급식)",
        "JB시니어우대예금(월이자지급식)",
    }
    assert first["document_count"] > 0


def test_product_fact_analyzer_accepts_exact_product_family(monkeypatch: pytest.MonkeyPatch) -> None:
    selected_products: list[str] = []

    def fake_select_product_documents(product: str) -> list[dict[str, object]]:
        selected_products.append(product)
        return [
            {
                "document_id": "doc_senior",
                "product": product,
                "label": "상품설명서",
                "file_name": "senior.pdf",
                "relative_path": "예금/senior.pdf",
                "file_path": "/tmp/senior.pdf",
                "exists": True,
            }
        ]

    monkeypatch.setattr(product_facts_module, "select_product_documents", fake_select_product_documents)
    monkeypatch.setattr(
        product_facts_module,
        "extract_document_snippet",
        lambda document: {
            "source_document_id": document["document_id"],
            "label": document["label"],
            "file_name": document["file_name"],
            "text": "최고 연 5.0%는 12개월 가입 및 우대조건 충족 시 적용됩니다.",
        },
    )

    context = ProductFactAnalyzer(ProductFactLLM()).analyze(
        review_input=ReviewInput(
            product_group="deposit",
            content_text="JB시니어우대예금 안내. 최고 연 5.0% 금리.",
        ),
        claims=[],
        product_context={
            "matched_products": [
                {"product": "JB시니어우대예금(만기일시지급식)", "match_basis": "exact_product_family"}
            ]
        },
    )

    assert context["extraction_status"] == "EXTRACTED"
    assert context["matched_product"] == "JB시니어우대예금(만기일시지급식)"
    assert selected_products == ["JB시니어우대예금(만기일시지급식)"]


def test_prominence_gate_marks_weak_disclosure_and_updates_comparison() -> None:
    benefit = SentenceUnit(
        sentence_id="sentence_benefit",
        index=0,
        text="최고 연 5.0% 확정 금리를 받을 수 있습니다.",
        span=Span(start=0, end=24, text="최고 연 5.0% 확정 금리를 받을 수 있습니다."),
        role="benefit_claim",
        local_meaning="최고금리 혜택 주장",
        context_effect="혜택을 강조",
        risk_level="HIGH",
        prominence_tier="headline",
    )
    disclosure = SentenceUnit(
        sentence_id="sentence_disclosure",
        index=1,
        text="* 우대조건 충족 시 적용됩니다.",
        span=Span(start=25, end=42, text="* 우대조건 충족 시 적용됩니다."),
        role="condition_disclosure",
        local_meaning="조건 고지",
        context_effect="금리 조건을 일부 완화",
        risk_level="LOW",
        prominence_tier="footnote",
    )
    claim = Claim(
        claim_id="claim_rate",
        text=benefit.text,
        span=benefit.span,
        meaning="최고금리 확정 주장",
        implicature="조건 없이 최고금리를 받을 수 있다는 인상",
        consumer_effect="소비자가 조건을 놓칠 수 있음",
        risk_hypernym="조건 누락 금리 주장",
        risk_severity="HIGH",
        sentence_id=benefit.sentence_id,
    )
    product_context = {
        "claim_facts": [
            {
                "claim_fact_id": "claim_fact_rate",
                "claim_id": claim.claim_id,
                "fact_type": "최고금리",
                "value": "5.0",
                "unit": "%",
                "qualifier": "확정",
                "evidence_text": benefit.text,
                "confidence": 0.9,
            }
        ],
        "product_facts": [
            {
                "fact_id": "product_fact_rate",
                "fact_type": "최고금리",
                "value": "5.0",
                "unit": "%",
                "condition": "우대조건 충족 시",
                "evidence_text": "우대조건 충족 시 최고 연 5.0%",
            }
        ],
        "comparison_results": [
            {
                "comparison_id": "comparison_rate",
                "claim_fact_id": "claim_fact_rate",
                "product_fact_id": "product_fact_rate",
                "status": "SUPPORTED",
                "rationale": "숫자는 상품문서와 일치",
                "evidence_text": "5.0%",
                "confidence": 0.9,
            }
        ],
        "disclosure_checks": [],
    }

    analysis, links, diagnostics, updated_context = build_prominence_artifacts(
        review_input=ReviewInput(product_group="deposit", content_text=f"{benefit.text} {disclosure.text}"),
        sentence_units=[benefit, disclosure],
        claims=[claim],
        product_fact_context=product_context,
    )

    assert analysis["weak_disclosure_count"] == 1
    assert links[0]["status"] == "PROMINENCE_INSUFFICIENT"
    assert diagnostics[0]["diagnostic_code"] == "PROMINENCE_INSUFFICIENT"
    assert updated_context["comparison_results"][0]["status"] == "PROMINENCE_INSUFFICIENT"


def test_prominence_gate_marks_supported_rate_as_condition_missing_when_disclosure_absent() -> None:
    benefit = SentenceUnit(
        sentence_id="sentence_benefit_missing",
        index=0,
        text="최고 연 5.0% 확정 금리를 받을 수 있습니다.",
        span=Span(start=0, end=24, text="최고 연 5.0% 확정 금리를 받을 수 있습니다."),
        role="benefit_claim",
        local_meaning="최고금리 혜택 주장",
        context_effect="혜택을 강조",
        risk_level="HIGH",
        prominence_tier="headline",
    )
    claim = Claim(
        claim_id="claim_rate_missing",
        text=benefit.text,
        span=benefit.span,
        meaning="최고금리 확정 주장",
        implicature="조건 없이 최고금리를 받을 수 있다는 인상",
        consumer_effect="소비자가 조건을 놓칠 수 있음",
        risk_hypernym="조건 누락 금리 주장",
        risk_severity="HIGH",
        sentence_id=benefit.sentence_id,
    )
    product_context = {
        "claim_facts": [
            {
                "claim_fact_id": "claim_fact_missing",
                "claim_id": claim.claim_id,
                "fact_type": "최고금리",
                "value": "5.0",
                "unit": "%",
                "qualifier": "확정",
                "evidence_text": benefit.text,
                "confidence": 0.9,
            }
        ],
        "product_facts": [{"fact_id": "product_fact_missing", "fact_type": "최고금리", "value": "5.0"}],
        "comparison_results": [
            {
                "comparison_id": "comparison_missing",
                "claim_fact_id": "claim_fact_missing",
                "product_fact_id": "product_fact_missing",
                "status": "SUPPORTED",
                "rationale": "숫자는 상품문서와 일치",
                "evidence_text": "5.0%",
                "confidence": 0.9,
            }
        ],
        "disclosure_checks": [
            {"check_id": "deposit_rate_condition", "label": "최고금리 적용 조건", "status": "MISSING", "present": False}
        ],
    }

    _analysis, _links, diagnostics, updated_context = build_prominence_artifacts(
        review_input=ReviewInput(product_group="deposit", content_text=benefit.text),
        sentence_units=[benefit],
        claims=[claim],
        product_fact_context=product_context,
    )

    assert diagnostics[0]["diagnostic_code"] == "DISCLOSURE_MISSING"
    assert updated_context["comparison_results"][0]["status"] == "CONDITION_MISSING"


def test_product_fact_analyzer_extracts_and_compares_exact_product(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        product_facts_module,
        "select_product_documents",
        lambda product: [
            {
                "document_id": "doc_1",
                "product": product,
                "label": "상품주요내용",
                "file_name": "jb_senior_summary.pdf",
                "relative_path": "예금/jb_senior_summary.pdf",
                "file_path": "/tmp/jb_senior_summary.pdf",
                "exists": True,
            }
        ],
    )
    monkeypatch.setattr(
        product_facts_module,
        "extract_document_snippet",
        lambda document: {
            "source_document_id": document["document_id"],
            "label": document["label"],
            "file_name": document["file_name"],
            "text": "최고 연 5.0%는 가입기간 12개월 및 우대조건 충족 시 적용됩니다.",
        },
    )
    claim = Claim(
        claim_id="claim_1",
        text="누구나 조건 없이 연 5% 확정",
        span=Span(start=0, end=17, text="누구나 조건 없이 연 5% 확정"),
        meaning="조건 없는 확정 금리 주장",
        implicature="누구나 조건 없이 최고 금리를 받을 수 있다는 인상",
        consumer_effect="소비자가 우대조건을 확인하지 않을 수 있음",
        risk_hypernym="조건 누락 금리 주장",
        risk_severity="HIGH",
    )

    context = ProductFactAnalyzer(ProductFactLLM()).analyze(
        review_input=ReviewInput(product_group="deposit", content_text="JB시니어우대예금. 누구나 조건 없이 연 5% 확정."),
        claims=[claim],
        product_context={"matched_products": [{"product": "JB시니어우대예금", "match_basis": "exact_product_name"}]},
    )

    assert context["extraction_status"] == "EXTRACTED"
    assert context["matched_product"] == "JB시니어우대예금"
    assert context["selected_documents"][0]["label"] == "상품주요내용"
    assert context["product_facts"][0]["fact_type"] == "max_rate"
    assert context["claim_facts"][0]["claim_id"] == "claim_1"
    assert context["comparison_results"][0]["status"] == "CONDITION_MISSING"
    assert context["comparison_results"][0]["product_fact_id"] == context["product_facts"][0]["fact_id"]


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
            "legal_profile_id": "legal_profile_false_ad",
            "action_type": "guarantee_or_return_misleading",
            "required_positive_features": ["guarantee_expression"],
            "applicability_scope": ["deposit"],
            "risk_title": "확정·보장 표현으로 수익 보장 오인 가능",
            "exception_eligible": False,
            "legal_profile_rationale": "보장 표현은 오인 가능 광고에 해당할 수 있다.",
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


def test_legal_element_gate_excludes_comparison_cu_without_comparison_feature() -> None:
    anchor = ContextAnchor(
        anchor_id="anchor_guarantee",
        anchor_type="claim_anchor",
        claim_id="claim_1",
        span=Span(start=0, end=17, text="누구나 연 5% 확정 보장"),
        facts=["ClaimQualifier role=target_scope text='누구나'", "ClaimQualifier role=guarantee text='보장'"],
        hypernyms=[],
        feature_set=AnchorFeatureSet(
            feature_set_id="feature_1",
            anchor_id="anchor_guarantee",
            action_types=["guarantee_or_return_misleading", "condition_or_scope_missing"],
            positive_features=["universal_scope_expression", "guarantee_expression", "certainty_expression"],
            missing_context=["no_comparison_target"],
            evidence=["누구나/확정/보장 qualifier"],
        ),
    )
    comparison_candidate = PolicyCandidate(
        cu_id="cu_comparison_ad",
        principle="광고규제",
        subject="비교광고",
        condition="다른 금융상품과 비교하는 광고",
        constraint="객관적 근거 없이 우월하게 표시해서는 안 된다",
        context="financial_advertising",
        cu_type="ACTOR_CU",
        source_article="금소법 제22조",
        active_for_gate=True,
        matched_hypernym_ids=["policy_hypernym_ad"],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.99, "hypernym_overlap": 1.0, "active_for_gate": 1.0, "combined_score": 0.99},
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_comparison",
            cu_id="cu_comparison_ad",
            action_type="comparison_ad",
            required_positive_features=["comparison_target", "comparative_superiority_claim"],
            applicability_scope=["deposit"],
            risk_title="비교·우월 표현에 대한 객관 근거 필요",
            exception_eligible=False,
        ),
    )

    gated = with_legal_element_gate(comparison_candidate, anchor)

    assert gated.legal_element_match is False
    assert "action_type_not_supported:comparison_ad" in gated.missing_required_features
    assert candidate_allowed_for_anchor(gated, anchor, product_group="deposit") is False


def test_canonicalizes_existing_free_text_required_features_for_runtime_gate() -> None:
    free_text_features = [
        "광고 문구/자료가 ‘보장성 상품 만기환급금이 확정적으로 지급되는 것으로 오인’되게 표시됨",
        "불확실한 사항을 단정적 판단으로 제공하거나 확실하다고 오인하게 할 소지가 있음",
    ]

    assert canonicalize_required_features(free_text_features) == ["guarantee_expression", "certainty_expression"]

    anchor = ContextAnchor(
        anchor_id="anchor_guarantee",
        anchor_type="claim_anchor",
        claim_id="claim_1",
        span=Span(start=0, end=17, text="누구나 연 5% 확정 보장"),
        facts=["ClaimQualifier role=guarantee text='보장'", "ClaimQualifier role=certainty text='확정'"],
        hypernyms=[],
        feature_set=AnchorFeatureSet(
            feature_set_id="feature_free_text",
            anchor_id="anchor_guarantee",
            action_types=["guarantee_or_return_misleading"],
            positive_features=["guarantee_expression", "certainty_expression"],
            missing_context=[],
            evidence=["확정/보장 qualifier"],
        ),
    )
    legacy_candidate = PolicyCandidate(
        cu_id="cu_legacy_guarantee",
        principle="광고규제",
        subject="보장 표현",
        condition="확정 보장처럼 오인되는 광고",
        constraint="오인 유발 광고 금지",
        context="financial_advertising",
        cu_type="ACTOR_CU",
        source_article="금소법 제22조",
        active_for_gate=True,
        matched_hypernym_ids=["policy_hypernym_ad"],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.9, "hypernym_overlap": 1.0, "active_for_gate": 1.0, "combined_score": 0.9},
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_legacy_guarantee",
            cu_id="cu_legacy_guarantee",
            action_type="guarantee_or_return_misleading",
            required_positive_features=free_text_features,
            applicability_scope=["deposit"],
            risk_title="확정·보장 표현으로 수익 보장 오인 가능",
            exception_eligible=False,
        ),
    )

    gated = with_legal_element_gate(legacy_candidate, anchor)

    assert gated.legal_element_match is True
    assert gated.matched_required_features == ["certainty_expression", "guarantee_expression"]
    assert gated.legal_element_profile
    assert gated.legal_element_profile.required_positive_features == ["guarantee_expression", "certainty_expression"]


def test_bare_must_check_phrase_does_not_canonicalize_as_certainty_expression() -> None:
    assert canonicalize_required_features(["계약 체결 전 상품설명서 및 약관을 반드시 확인"]) == []
    assert canonicalize_required_features(["수익을 반드시 지급받을 수 있다고 오인하게 하는 표현"]) == [
        "certainty_expression"
    ]


def test_bare_must_check_qualifier_does_not_emit_certainty_expression() -> None:
    claim = Claim(
        claim_id="claim_must_check",
        text="계약 체결 전 상품설명서 및 약관을 반드시 확인하시기 바랍니다",
        span=Span(start=0, end=33, text="계약 체결 전 상품설명서 및 약관을 반드시 확인하시기 바랍니다"),
        meaning="계약 전 상품설명서와 약관 확인을 권유하는 보호 고지",
        implicature="중요 사항을 확인해야 한다는 안내",
        consumer_effect="소비자가 약관과 상품설명서를 확인하도록 유도",
        risk_hypernym="",
        risk_severity="LOW",
        qualifiers=[
            ClaimQualifier(
                qualifier_id="qualifier_must_check",
                role="certainty",
                text="반드시 확인",
                span=Span(start=21, end=27, text="반드시 확인"),
                meaning="약관 확인을 강조하는 보호 문구",
                risk_reason="",
                confidence=0.9,
            )
        ],
    )
    anchor = ContextAnchor(
        anchor_id="anchor_must_check",
        anchor_type="claim_anchor",
        claim_id="claim_must_check",
        span=claim.span,
        facts=[],
        hypernyms=[],
    )

    feature_set = build_anchor_feature_set(review_run_id="run_must_check", anchor=anchor, claim=claim)

    assert "certainty_expression" not in feature_set.positive_features
    assert any("완화 한정어" in item for item in feature_set.evidence)


def test_legal_element_gate_allows_comparison_cu_with_comparison_feature() -> None:
    anchor = ContextAnchor(
        anchor_id="anchor_compare",
        anchor_type="claim_anchor",
        claim_id="claim_1",
        span=Span(start=0, end=12, text="타 은행보다 높은 금리"),
        facts=["타 은행과 비교해 높은 금리를 주장"],
        hypernyms=[],
        feature_set=AnchorFeatureSet(
            feature_set_id="feature_2",
            anchor_id="anchor_compare",
            action_types=["comparison_ad"],
            positive_features=["comparison_target", "comparative_superiority_claim"],
            missing_context=[],
            evidence=["비교 대상과 우월 표현 있음"],
        ),
    )
    comparison_candidate = PolicyCandidate(
        cu_id="cu_comparison_ad",
        principle="광고규제",
        subject="비교광고",
        condition="다른 금융상품과 비교하는 광고",
        constraint="객관적 근거 없이 우월하게 표시해서는 안 된다",
        context="financial_advertising",
        cu_type="ACTOR_CU",
        source_article="금소법 제22조",
        active_for_gate=True,
        matched_hypernym_ids=["policy_hypernym_ad"],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.88, "hypernym_overlap": 1.0, "active_for_gate": 1.0, "combined_score": 0.88},
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_comparison",
            cu_id="cu_comparison_ad",
            action_type="comparison_ad",
            required_positive_features=["comparison_target", "comparative_superiority_claim"],
            applicability_scope=["deposit"],
            risk_title="비교·우월 표현에 대한 객관 근거 필요",
            exception_eligible=False,
        ),
    )

    gated = with_legal_element_gate(comparison_candidate, anchor)

    assert gated.legal_element_match is True
    assert gated.matched_required_features == ["comparative_superiority_claim", "comparison_target"]
    assert candidate_allowed_for_anchor(gated, anchor, product_group="deposit") is True


def test_scope_anchor_is_not_actionable_even_with_legal_element_overlap() -> None:
    anchor = ContextAnchor(
        anchor_id="anchor_product_scope",
        anchor_type="product_anchor",
        claim_id="claim_1",
        span=Span(start=0, end=12, text="JB 특판예금"),
        facts=["상품 scope"],
        hypernyms=[],
        feature_set=AnchorFeatureSet(
            feature_set_id="feature_scope",
            anchor_id="anchor_product_scope",
            action_types=["guarantee_or_return_misleading"],
            positive_features=["guarantee_expression"],
            missing_context=["scope_anchor_not_actionable_by_default"],
            evidence=["scope anchor"],
        ),
    )
    candidate = PolicyCandidate(
        cu_id="cu_guarantee",
        principle="광고규제",
        subject="보장 표현",
        condition="확정 보장 표현",
        constraint="오인 유발 광고 금지",
        context="financial_advertising",
        cu_type="ACTOR_CU",
        source_article="금소법 제22조",
        active_for_gate=True,
        matched_hypernym_ids=["policy_hypernym_ad"],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.9, "hypernym_overlap": 1.0, "active_for_gate": 1.0, "combined_score": 0.9},
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_guarantee",
            cu_id="cu_guarantee",
            action_type="guarantee_or_return_misleading",
            required_positive_features=["guarantee_expression"],
            applicability_scope=["deposit"],
            risk_title="확정·보장 표현으로 수익 보장 오인 가능",
            exception_eligible=False,
        ),
    )

    gated = with_legal_element_gate(candidate, anchor)

    assert gated.legal_element_match is True
    assert candidate_allowed_for_anchor(gated, anchor, product_group="deposit") is False


def test_profile_applicability_scope_suppresses_wrong_product_group() -> None:
    candidate = PolicyCandidate(
        cu_id="cu_investment_only",
        principle="광고규제",
        subject="상품 위험고지",
        condition="상품 광고",
        constraint="중요 위험을 고지해야 한다",
        context="financial_advertising",
        cu_type="ACTOR_CU",
        source_article="금소법 제22조",
        active_for_gate=True,
        matched_hypernym_ids=["policy_hypernym_risk"],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.91, "hypernym_overlap": 1.0, "active_for_gate": 1.0, "combined_score": 0.91},
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_investment",
            cu_id="cu_investment_only",
            action_type="required_disclosure_missing",
            required_positive_features=["benefit_claim_expression"],
            applicability_scope=["investment"],
            risk_title="투자성 상품 위험고지 누락 가능",
            exception_eligible=True,
        ),
        legal_element_match=True,
    )

    gated = with_scope_gate(candidate, product_group="deposit", channel="web_page")

    assert gated.gate_status == "suppressed"
    assert gated.retrieval_scores["scope_gate"] == 0.0
    assert gated.retrieval_scores["scope_gate_reason"] == "product_scope_mismatch"


def test_profile_applicability_scope_allows_auto_product_group_probe() -> None:
    candidate = PolicyCandidate(
        cu_id="cu_investment_only",
        principle="광고규제",
        subject="투자성 상품 위험고지",
        condition="투자성 상품 광고",
        constraint="원금손실 가능성을 고지해야 한다",
        context="financial_investment_advertising",
        cu_type="ACTOR_CU",
        source_article="금소법 제22조",
        active_for_gate=True,
        matched_hypernym_ids=["policy_hypernym_risk"],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.91, "hypernym_overlap": 1.0, "active_for_gate": 1.0, "combined_score": 0.91},
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_investment",
            cu_id="cu_investment_only",
            action_type="required_disclosure_missing",
            required_positive_features=["benefit_claim_expression"],
            applicability_scope=["investment"],
            risk_title="투자성 상품 위험고지 누락 가능",
            exception_eligible=True,
        ),
        legal_element_match=True,
    )

    gated = with_scope_gate(candidate, product_group="auto", channel="web_page")

    assert gated.gate_status == "active"
    assert gated.retrieval_scores["scope_gate"] == 1.0


def test_legal_element_gate_excludes_unfair_sales_cu_without_coercion_context() -> None:
    anchor = ContextAnchor(
        anchor_id="anchor_guarantee",
        anchor_type="claim_anchor",
        claim_id="claim_1",
        span=Span(start=0, end=17, text="누구나 연 5% 확정 보장"),
        facts=["보장성 금리 표현"],
        hypernyms=[],
        feature_set=AnchorFeatureSet(
            feature_set_id="feature_3",
            anchor_id="anchor_guarantee",
            action_types=["guarantee_or_return_misleading"],
            positive_features=["guarantee_expression"],
            missing_context=["no_superior_position_or_coercion_context"],
            evidence=["보장 qualifier"],
        ),
    )
    unfair_candidate = PolicyCandidate(
        cu_id="cu_unfair_sales",
        principle="불공정영업행위 금지",
        subject="우월적 지위 이용",
        condition="판매 과정에서 소비자에게 부당한 요구를 하는 경우",
        constraint="다른 계약 강요, 부당한 담보 또는 보증 요구 금지",
        context="sales_process",
        cu_type="ACTOR_CU",
        source_article="금소법 제20조",
        active_for_gate=True,
        matched_hypernym_ids=["policy_hypernym_ad"],
        legal_evidence_ids=[],
        evidence_texts=[],
        retrieval_scores={"vector_score": 0.92, "hypernym_overlap": 1.0, "active_for_gate": 1.0, "combined_score": 0.92},
        legal_element_profile=CULegalElementProfile(
            profile_id="profile_unfair",
            cu_id="cu_unfair_sales",
            action_type="unfair_superior_position_sales",
            required_positive_features=["coercion_or_tie_in_context", "collateral_or_guarantee_demand", "sales_process_context"],
            applicability_scope=["loan"],
            risk_title="우월적 지위 이용 또는 끼워팔기 정황 검토",
            exception_eligible=False,
        ),
    )

    gated = with_legal_element_gate(unfair_candidate, anchor)

    assert gated.legal_element_match is False
    assert "action_type_not_supported:unfair_superior_position_sales" in gated.missing_required_features
    assert candidate_allowed_for_anchor(gated, anchor, product_group="deposit") is False


def _normalizer_policy_context() -> dict[str, object]:
    return {
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
    }


def test_normalizer_drops_unknown_policy_hypernym(caplog: pytest.LogCaptureFixture) -> None:
    # Contract (commit 1450c98, PPCBank E2E stabilization): an individual out-of-
    # vocabulary PolicyHypernym is no longer a hard failure. It is dropped with an
    # audit-log warning while the owning anchor survives (partial tolerance).
    normalizer = PolicyGuidedNormalizer(UnknownHypernymLLM())

    with caplog.at_level(logging.WARNING, logger="normalizer"):
        anchors = normalizer.normalize(
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
            policy_context=_normalizer_policy_context(),
        )

    # The unknown hypernym is dropped, not surfaced on the anchor.
    assert len(anchors) == 1
    assert anchors[0].hypernyms == []
    assert not any(
        proposal.hypernym_id == "policy_hypernym_education"
        for anchor in anchors
        for proposal in anchor.hypernyms
    )
    # The drop is audited with an explicit reason so governance can trace it.
    drop_logs = [
        record.getMessage()
        for record in caplog.records
        if "normalizer.hypernym_dropped" in record.getMessage()
    ]
    assert any(
        "reason=unknown_hypernym_id" in message and "policy_hypernym_education" in message
        for message in drop_logs
    )


def test_normalizer_fails_when_all_anchors_are_unusable() -> None:
    # Partial tolerance ends at total failure: if every anchor item is dropped and
    # none survive, the old fail-fast contract still holds (governance must not get
    # a silently empty normalization).
    normalizer = PolicyGuidedNormalizer(AllUnusableAnchorLLM())

    with pytest.raises(RuntimeError, match="no usable ContextAnchor"):
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
            policy_context=_normalizer_policy_context(),
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


def test_llm_gateway_routes_claude_model_to_anthropic_tool_use(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAnthropicClient:
        def __init__(self, **_: object) -> None:
            self.messages = self

        def create(self, **kwargs: object) -> object:
            tool_choice = kwargs["tool_choice"]
            assert isinstance(tool_choice, dict)
            return SimpleNamespace(
                id="msg_test",
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        name=tool_choice["name"],
                        input={"ok": True},
                    )
                ],
            )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setattr("llm_gateway.Anthropic", FakeAnthropicClient)

    gateway = LLMGateway(model="claude-sonnet-5")
    parsed = gateway.structured(
        name="graphcompliance_test",
        system="Return JSON.",
        user="{}",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
    )

    assert gateway.mode == "anthropic"
    assert parsed == {"ok": True}


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
            "cu_legal_element_profiles": [
                {
                    "cu_id": "cu_1",
                    "action_type": "required_disclosure_missing",
                    "required_positive_features": [],
                    "applicability_scope": [],
                    "risk_title": "필수 고지 확인 필요",
                    "exception_eligible": True,
                    "rationale": "",
                }
            ],
        },
        {"cu_1"},
    )

    assert any("non-Korean canonical" in error for error in errors)


def test_compiler_rejects_free_text_legal_element_features() -> None:
    errors = validate_compiler_output(
        {
            "policy_hypernyms": [
                {
                    "name": "보장 금지",
                    "domain": "risk",
                    "description": "확정 보장 표현 관련 정책어",
                    "priority": 1,
                }
            ],
            "premises": [],
            "cu_profiles": [
                {
                    "cu_id": "cu_1",
                    "subject_hypernym_names": ["보장 금지"],
                    "profile_summary": "",
                    "embedding_text": "",
                }
            ],
            "cu_legal_element_profiles": [
                {
                    "cu_id": "cu_1",
                    "action_type": "guarantee_or_return_misleading",
                    "required_positive_features": ["보장성 상품이 확정적으로 지급되는 것으로 오인되는 문구"],
                    "applicability_scope": [],
                    "risk_title": "확정·보장 표현으로 수익 보장 오인 가능",
                    "exception_eligible": False,
                    "rationale": "",
                }
            ],
        },
        {"cu_1"},
    )

    assert any("unknown required_positive_features" in error for error in errors)


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


def test_product_fact_synthetic_records_are_grounded_in_extracted_facts() -> None:
    taxonomy = load_taxonomy(Path(__file__).resolve().parents[1] / "eval" / "violation_taxonomy_v0_1.json")
    bundle = {
        "product_name": "(26년 JUMP UP) 특판 예금",
        "product_group": "deposit",
        "channel": "web_page",
        "disclosure_requirements": [
            {"label": "금리 범위 및 산정방법"},
            {"label": "우대조건 및 적용기간"},
            {"label": "예금자보호 부보내용"},
        ],
        "selected_documents": [
            {
                "document_id": "doc_jumpup_terms",
                "label": "상품설명서",
                "file_name": "0235_(26년 JUMP UP) 특판 예금_상품설명서.pdf",
                "relative_path": "예금/0235.pdf",
            }
        ],
        "product_facts": [
            {
                "fact_id": "pf_rate",
                "fact_type": "최고금리",
                "value": "연 5.0%",
                "unit": "percent",
                "condition": "12개월 가입 및 우대조건 충족 시",
                "source_document_id": "doc_jumpup_terms",
                "page_or_chunk": "page 1",
                "evidence_text": "12개월 가입 및 우대조건 충족 시 최고 연 5.0%",
                "confidence": 0.93,
            },
            {
                "fact_id": "pf_protection",
                "fact_type": "예금자보호",
                "value": "1인당 최고 1억원",
                "unit": "KRW",
                "condition": "예금자보호법상 보호한도",
                "source_document_id": "doc_jumpup_terms",
                "page_or_chunk": "page 2",
                "evidence_text": "원금과 소정의 이자를 합하여 1인당 최고 1억원까지 보호",
                "confidence": 0.91,
            },
        ],
    }
    clean_ad = {
        "headline": "(26년 JUMP UP) 특판 예금 안내",
        "subcopy": "12개월 가입 및 우대조건 충족 시 최고 연 5.0%(세전) 금리가 적용될 수 있습니다.",
        "body": "실제 적용금리는 조건에 따라 달라질 수 있습니다.",
        "footnote": "계약 전 상품설명서와 약관을 확인해 주세요.",
        "used_fact_ids": ["pf_rate", "pf_protection"],
        "compliance_notes": ["조건을 같은 위계에 표시"],
    }

    records = build_records_from_product_facts(taxonomy, bundle, clean_ad)

    assert any(record["source_type"] == "synthetic_product_fact_clean" for record in records)
    mutated = next(record for record in records if record["labels"]["violation_types"] == ["DEPOSIT_UNIVERSAL_SCOPE_MISLEADING"])
    assert mutated["facts"]["product_facts"][0]["fact_id"] == "pf_rate"
    assert mutated["facts"]["source_product_documents"][0]["document_id"] == "doc_jumpup_terms"
    assert "canonical_product_facts" not in mutated["facts"]
    assert "누구나 조건 없이" in mutated["facts"]["expected_problem_spans"]


def test_synthetic_dataset_channel_parser_rejects_unknown_channel() -> None:
    assert parse_channels("web_page,sns") == ["web_page", "sns"]
    with pytest.raises(ValueError, match="Unknown channels"):
        parse_channels("web_page,kiosk")


def test_synthetic_product_fact_validation_requires_selected_document_source() -> None:
    documents = [{"document_id": "doc_known"}]
    facts = [
        {
            "fact_id": "pf_rate",
            "fact_type": "최고금리",
            "value": "연 5.0%",
            "source_document_id": "doc_unknown",
            "evidence_text": "최고 연 5.0%",
            "confidence": 0.9,
        }
    ]

    with pytest.raises(RuntimeError, match="source_document_id must match selected documents"):
        validate_product_facts(facts, documents)


def test_synthetic_deposit_rate_slot_combines_base_and_preferential_rates() -> None:
    facts = [
        {"fact_type": "basic_interest_rate_3m", "value": "연 2.40%"},
        {"fact_type": "basic_interest_rate_12m", "value": "연 2.55%"},
        {"fact_type": "event_preferential_interest_rate_max", "value": "최고 0.30%p"},
    ]

    assert best_deposit_rate_value(facts) == "2.85%"


def test_synthetic_quality_report_checks_spans_and_product_fact_sources() -> None:
    report = build_quality_report(
        [
            {
                "id": "syn_ok",
                "text": "누구나 조건 없이 최고 연 5.0%",
                "source_type": "synthetic_product_fact_mutation",
                "product_group": "deposit",
                "channel": "web_page",
                "facts": {
                    "expected_problem_spans": ["누구나 조건 없이"],
                    "source_product_documents": [{"document_id": "doc_1"}],
                    "product_facts": [
                        {
                            "fact_id": "pf_rate",
                            "source_document_id": "doc_1",
                            "evidence_text": "최고 연 5.0%",
                            "confidence": 0.9,
                        }
                    ],
                },
                "labels": {
                    "violation": True,
                    "violation_types": ["DEPOSIT_UNIVERSAL_SCOPE_MISLEADING"],
                    "risk_level": "high",
                    "expected_routing": "revise",
                },
            },
            {
                "id": "syn_bad",
                "text": "최고 연 5.0%",
                "source_type": "synthetic_product_fact_mutation",
                "product_group": "deposit",
                "channel": "web_page",
                "facts": {
                    "expected_problem_spans": ["없는 span"],
                    "source_product_documents": [{"document_id": "doc_1"}],
                    "product_facts": [
                        {
                            "fact_id": "pf_bad",
                            "source_document_id": "doc_missing",
                            "evidence_text": "",
                            "confidence": 1.2,
                        }
                    ],
                },
                "labels": {
                    "violation": True,
                    "violation_types": ["DEPOSIT_RATE_CONDITION_MISSING"],
                    "risk_level": "medium",
                    "expected_routing": "revise",
                },
            },
        ]
    )

    assert report["record_count"] == 2
    assert report["blocking_error_count"] == 4
    assert report["violation_type_counts"]["DEPOSIT_UNIVERSAL_SCOPE_MISLEADING"] == 1


def test_selected_base_product_name_resolves_from_csv_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_USER", raising=False)
    monkeypatch.delenv("NEO4J_USERNAME", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    # Pin the local metadata source to the repo-bundled demo CSV so the family
    # resolution assertion is deterministic on any machine (no external dataset).
    monkeypatch.setenv(
        "JB_PRODUCT_METADATA_PATH",
        str(jb_data_context_module.BUNDLED_PRODUCT_DISCLOSURE_META_PATH),
    )
    jb_data_context_module.load_product_rows.cache_clear()

    text = "JB 골든에이지 예금 특판 안내. 최고 연 5.0% 금리를 확정 제공하며 안정적으로 목돈을 관리할 수 있습니다."
    review_input = ReviewInput(
        dataset_item_id="product_match_regression",
        title="JB 골든에이지 예금",
        content_text=text,
        channel="web_page",
        product_group="deposit",
        selected_product_name="JB 골든에이지 예금",
        workspace_id="graphcompliance_mvp_jb_20260530",
    )
    claims = [
        Claim(
            claim_id="claim_rate",
            text=text,
            span=Span(text=text, start=0, end=len(text)),
            entities=[],
            qualifiers=[],
            meaning="",
            implicature="",
            consumer_effect="",
            risk_hypernym="",
            risk_severity="LOW",
        )
    ]

    product_context, _requirements = jb_data_context_module.build_product_context(review_input, claims)
    first_product = product_context["matched_products"][0]

    assert first_product["match_basis"] == "selected_product"
    # Base name resolves to the bundled disclosure variant.
    assert first_product["product"] == "JB 골든에이지 예금(월이자지급식)"
    assert first_product["document_count"] >= 1
