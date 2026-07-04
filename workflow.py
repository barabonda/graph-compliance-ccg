"""End-to-end LLM-only GraphCompliance CCG workflow."""

from __future__ import annotations

import dataclasses
import logging
import unicodedata
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from ad_translation import translate_ad_for_display
from applicability_gate import summarize_cu_gate
from claim_modeling import fold_qualifier_anchors_into_parent_claims
from context_extractor import LLMContextExtractor, build_context_triples
from cross_encoder_reranker import CUReranker, NoopCUReranker, create_cross_encoder_reranker_from_env
from jb_data_context import build_product_context
from judge import LLMComplianceJudge
from legal_elements import attach_anchor_feature_sets
from llm_gateway import LLMGateway
from normalizer import PolicyGuidedNormalizer
from overall_impression import LLMOverallImpressionJudge
from parallel import ordered_parallel_map, worker_count
from persistence import Neo4jReviewWriter, ReviewWriter
from policy_evidence import build_policy_evidence_chains
from planner import LLMCUPlanner
from product_facts import ProductFactAnalyzer
from prominence import build_prominence_artifacts
from retriever import Neo4jPolicyRetriever, PolicyRetriever
from revision import LLMRevisionSuggester
from router import build_output
from track_c import run_track_c
from schemas import PolicyCandidate, ReviewGraph, ReviewInput, ReviewOutput
from utils import content_hash, stable_id, to_jsonable, uses_korean_law_context


LOGGER = logging.getLogger(__name__)


class GraphComplianceCCGWorkflow:
    def __init__(
        self,
        *,
        llm: LLMGateway | None = None,
        retriever: PolicyRetriever | None = None,
        writer: ReviewWriter | None = None,
        cross_encoder_reranker: CUReranker | None = None,
    ) -> None:
        self.llm = llm or LLMGateway()
        self.extractor = LLMContextExtractor(self.llm)
        self.normalizer = PolicyGuidedNormalizer(self.llm)
        self.planner = LLMCUPlanner(self.llm)
        self.judge = LLMComplianceJudge(self.llm)
        self.overall_impression = LLMOverallImpressionJudge(self.llm)
        self.revision = LLMRevisionSuggester(self.llm)
        self.product_facts = ProductFactAnalyzer(self.llm)
        self.retriever = retriever or Neo4jPolicyRetriever()
        self.writer = writer or Neo4jReviewWriter()
        if cross_encoder_reranker is not None:
            self.cross_encoder_reranker = cross_encoder_reranker
        elif llm is not None or retriever is not None or writer is not None:
            # Tests and embedded harnesses often inject fake dependencies and
            # should not implicitly download/load a local cross-encoder model.
            self.cross_encoder_reranker = NoopCUReranker()
        else:
            self.cross_encoder_reranker = create_cross_encoder_reranker_from_env()

    def review(self, review_input: ReviewInput) -> ReviewOutput:
        output: ReviewOutput | None = None
        for event in self.review_events(review_input):
            if event.get("event") == "result":
                output = event["result"]
        if output is None:
            raise RuntimeError("Review workflow finished without a result event.")
        return output

    def review_events(self, review_input: ReviewInput) -> Iterator[dict[str, Any]]:
        digest = content_hash(review_input.content_text)
        ad_draft_id = stable_id("ad_draft", review_input.workspace_id, review_input.dataset_item_id, digest)
        review_run_id = stable_id("review_run", ad_draft_id, digest, uuid4().hex)

        yield workflow_event(
            "start",
            "Review started",
            review_run_id=review_run_id,
            summary=f"{review_input.product_group} · {review_input.channel}",
        )

        yield workflow_event("step_started", "Policy alignment check", review_run_id=review_run_id)
        self.retriever.assert_policy_alignment_ready(workspace_id=review_input.workspace_id)
        yield workflow_event("step_completed", "Policy alignment check", review_run_id=review_run_id, summary="Policy alignment graph is ready.")

        yield workflow_event(
            "step_started",
            "Hierarchical context extraction",
            review_run_id=review_run_id,
            summary="LLM builds ContextFrame, SentenceUnits, sentence relations, claims, qualifiers, and context triples.",
        )
        extraction = self.extractor.extract_hierarchical(review_input, review_run_id=review_run_id)
        claims = extraction.claims
        context_triples = build_context_triples(
            review_run_id=review_run_id,
            claims=claims,
            context_frame=extraction.context_frame,
            sentence_units=extraction.sentence_units,
            inter_sentence_relations=extraction.inter_sentence_relations,
            context_influences=extraction.context_influences,
        )
        yield workflow_event(
            "step_completed",
            "Hierarchical context extraction",
            review_run_id=review_run_id,
            summary=(
                f"{len(extraction.sentence_units)} sentences · {len(claims)} claims · "
                f"{len(extraction.inter_sentence_relations)} sentence relations · {len(context_triples)} context triples"
            ),
            counts={
                "sentences": len(extraction.sentence_units),
                "claims": len(claims),
                "inter_sentence_relations": len(extraction.inter_sentence_relations),
                "context_triples": len(context_triples),
            },
            sample=[claim.text for claim in claims[:5]],
            payload={
                "context_frame": to_jsonable(extraction.context_frame),
                "sentence_units": to_jsonable(extraction.sentence_units[:5]),
                "inter_sentence_relations": to_jsonable(extraction.inter_sentence_relations[:5]),
            },
        )

        yield workflow_event("step_started", "Policy context retrieval", review_run_id=review_run_id, summary="Retrieve approved PolicyHypernym vocabulary, Premise evidence, and supporting fragments.")
        policy_context = self.retriever.policy_context_for_claims(
            workspace_id=review_input.workspace_id,
            query_text=review_input.content_text[:1200],
            limit=80,
        )
        yield workflow_event(
            "step_completed",
            "Policy context retrieval",
            review_run_id=review_run_id,
            summary=(
                f"{len(policy_context.get('hypernyms', []))} hypernyms · "
                f"{len(policy_context.get('premises', []))} premises · "
                f"{len(policy_context.get('fragments', []))} fragments"
            ),
            counts={
                "hypernyms": len(policy_context.get("hypernyms", [])),
                "premises": len(policy_context.get("premises", [])),
                "fragments": len(policy_context.get("fragments", [])),
            },
        )

        yield workflow_event("step_started", "Policy normalization", review_run_id=review_run_id, summary="LLM maps each claim/risk anchor only to approved PolicyHypernym ids.")
        anchors = self.normalizer.normalize(
            review_run_id=review_run_id,
            claims=claims,
            policy_context=policy_context,
            top_n=5,
            korean=uses_korean_law_context(review_input.workspace_id),
        )
        anchors = fold_qualifier_anchors_into_parent_claims(anchors, claims)
        anchors, anchor_feature_sets = attach_anchor_feature_sets(
            review_run_id=review_run_id,
            anchors=anchors,
            claims=claims,
            relations=extraction.inter_sentence_relations,
            korean=uses_korean_law_context(review_input.workspace_id),
        )
        yield workflow_event(
            "step_completed",
            "Policy normalization",
            review_run_id=review_run_id,
            summary=f"{len(anchors)} anchors normalized",
            counts={
                "anchors": len(anchors),
                "hypernym_proposals": sum(len(anchor.hypernyms) for anchor in anchors),
                "anchor_feature_sets": len(anchor_feature_sets),
            },
            sample=[
                {
                    "anchor": anchor.span.text,
                    "hypernyms": [proposal.hypernym for proposal in anchor.hypernyms],
                    "action_types": anchor.feature_set.action_types if anchor.feature_set else [],
                    "positive_features": anchor.feature_set.positive_features if anchor.feature_set else [],
                }
                for anchor in anchors[:5]
            ],
        )

        yield workflow_event("step_started", "Product disclosure context", review_run_id=review_run_id, summary="Resolve product metadata and required-disclosure hints.")
        product_context, disclosure_requirements = build_product_context(review_input, claims)
        yield workflow_event(
            "step_completed",
            "Product disclosure context",
            review_run_id=review_run_id,
            summary=(
                f"{product_context.get('product_group', review_input.product_group)} · "
                f"{len(disclosure_requirements)} disclosure requirements · "
                f"{product_context.get('document_count', 0)} product documents"
            ),
            counts={
                "disclosure_requirements": len(disclosure_requirements),
                "product_documents": product_context.get("document_count", 0),
            },
        )

        yield workflow_event("step_started", "Product fact graph", review_run_id=review_run_id, summary="Resolve product documents, extract ProductFact evidence, and compare ad ClaimFacts.")
        product_fact_context = self.product_facts.analyze(
            review_input=review_input,
            claims=claims,
            product_context=product_context,
            sentence_units=extraction.sentence_units,
        )
        yield workflow_event(
            "step_completed",
            "Product fact graph",
            review_run_id=review_run_id,
            summary=(
                f"{product_fact_context.get('extraction_status', 'UNKNOWN')} · "
                f"{len(product_fact_context.get('product_facts', []))} product facts · "
                f"{len(product_fact_context.get('comparison_results', []))} comparisons"
            ),
            counts={
                "product_facts": len(product_fact_context.get("product_facts", [])),
                "claim_facts": len(product_fact_context.get("claim_facts", [])),
                "comparison_results": len(product_fact_context.get("comparison_results", [])),
            },
            payload={
                "matched_product": product_fact_context.get("matched_product", ""),
                "extraction_status": product_fact_context.get("extraction_status", ""),
                "reason": product_fact_context.get("reason", ""),
            },
        )

        yield workflow_event("step_started", "Prominence disclosure gate", review_run_id=review_run_id, summary="Compare disclosure presence and display prominence against benefit claims.")
        prominence_analysis, disclosure_links, prominence_diagnostics, product_fact_context = build_prominence_artifacts(
            review_input=review_input,
            sentence_units=extraction.sentence_units,
            claims=claims,
            product_fact_context=product_fact_context,
        )
        yield workflow_event(
            "step_completed",
            "Prominence disclosure gate",
            review_run_id=review_run_id,
            summary=(
                f"{len(disclosure_links)} disclosure links · "
                f"{len(prominence_diagnostics)} diagnostics"
            ),
            counts={
                "disclosure_links": len(disclosure_links),
                "prominence_diagnostics": len(prominence_diagnostics),
                "weak_disclosures": prominence_analysis.get("weak_disclosure_count", 0),
                "missing_disclosures": prominence_analysis.get("missing_disclosure_count", 0),
            },
        )

        yield workflow_event("step_started", "Track B overall impression", review_run_id=review_run_id, summary="LLM judges the representative consumer impression from Claim -> Meaning -> Implicature -> ConsumerEffect paths.")
        overall_impression_judgment = self.overall_impression.judge(
            review_input=review_input,
            claims=claims,
            disclosure_requirements=disclosure_requirements,
            # 복잡 위반(전체 인상 vs 실체 간극)을 종합하도록 흩어진 구조화 증거 주입:
            # 문장 위계/역할, 혜택↔고지 위계차(prominence), 광고 주장↔상품문서 사실 모순.
            sentence_units=extraction.sentence_units,
            prominence_diagnostics=prominence_diagnostics,
            product_fact_context=product_fact_context,
            inter_sentence_relations=extraction.inter_sentence_relations,
            context_frame=extraction.context_frame,
        )
        yield workflow_event(
            "step_completed",
            "Track B overall impression",
            review_run_id=review_run_id,
            summary=(
                f"{overall_impression_judgment.get('verdict', 'pending')} · "
                f"{float(overall_impression_judgment.get('misleading_risk_score', 0) or 0):.2f}"
            ),
            payload={
                "verdict": overall_impression_judgment.get("verdict"),
                "misleading_risk_score": overall_impression_judgment.get("misleading_risk_score"),
                "representative_consumer_impression": overall_impression_judgment.get("representative_consumer_impression"),
            },
        )

        yield workflow_event("step_started", "CU candidate retrieval", review_run_id=review_run_id, summary="Retrieve candidate CUs per anchor using PolicyHypernym overlap and CU embedding profiles.")
        # Per-anchor candidate retrieval is an independent read fan-out: each call
        # opens its own Neo4j session (driver is thread-safe, sessions are not) and
        # returns candidates keyed by anchor_id. Parallelizing the fan-out and
        # rebuilding the dict in anchor order yields the identical candidate set and
        # ordering as the previous sequential dict comprehension — judgment inputs
        # are unchanged.
        product_group_for_retrieval = product_context.get("product_group", review_input.product_group)
        candidate_lists = ordered_parallel_map(
            lambda anchor: self.retriever.candidates_for_anchor(
                workspace_id=review_input.workspace_id,
                anchor=anchor,
                product_group=product_group_for_retrieval,
                channel=review_input.channel,
                limit=12,
            ),
            anchors,
            workers=worker_count("CCG_PARALLEL_NEO4J_WORKERS", 6),
            label="cu_candidate_retrieval",
        )
        candidates_by_anchor = {
            anchor.anchor_id: candidate_lists[index] for index, anchor in enumerate(anchors)
        }
        yield workflow_event(
            "step_completed",
            "CU candidate retrieval",
            review_run_id=review_run_id,
            summary=f"{sum(len(items) for items in candidates_by_anchor.values())} candidates across {len(anchors)} anchors",
            counts={
                "anchors": len(anchors),
                "candidates": sum(len(items) for items in candidates_by_anchor.values()),
            },
            sample=[
                {
                    "anchor": anchor.span.text,
                    "candidate_count": len(candidates_by_anchor.get(anchor.anchor_id, [])),
                    "top_cu_ids": [candidate.cu_id for candidate in candidates_by_anchor.get(anchor.anchor_id, [])[:3]],
                }
                for anchor in anchors[:5]
            ],
        )

        yield workflow_event(
            "step_started",
            "Cross-encoder CU rerank",
            review_run_id=review_run_id,
            summary="Optionally rerank graph-retrieved CU candidates with a pairwise cross-encoder before LLM rerank.",
        )
        before_cross_encoder = sum(len(items) for items in candidates_by_anchor.values())
        candidates_by_anchor = self.cross_encoder_reranker.rerank(
            candidates_by_anchor=candidates_by_anchor,
            anchors=anchors,
            limit_per_anchor=8,
        )
        after_cross_encoder = sum(len(items) for items in candidates_by_anchor.values())
        yield workflow_event(
            "step_completed",
            "Cross-encoder CU rerank",
            review_run_id=review_run_id,
            summary=(
                f"{'enabled' if self.cross_encoder_reranker.enabled else 'disabled'} · "
                f"{before_cross_encoder} -> {after_cross_encoder} candidates"
            ),
            counts={
                "enabled": int(self.cross_encoder_reranker.enabled),
                "before": before_cross_encoder,
                "after": after_cross_encoder,
            },
            sample=[
                {
                    "anchor": anchor.span.text,
                    "top_cu_ids": [candidate.cu_id for candidate in candidates_by_anchor.get(anchor.anchor_id, [])[:3]],
                    "top_cross_encoder_scores": [
                        candidate.retrieval_scores.get("cross_encoder_score")
                        for candidate in candidates_by_anchor.get(anchor.anchor_id, [])[:3]
                    ],
                }
                for anchor in anchors[:5]
            ],
        )

        yield workflow_event("step_started", "LLM CU rerank", review_run_id=review_run_id, summary="LLM reranks candidates into the final CUPlan.")
        cu_plan = self.planner.plan(
            review_run_id=review_run_id,
            anchors=anchors,
            candidates_by_anchor=candidates_by_anchor,
            per_anchor_limit=5,
            total_limit=20,
        )
        retrieval_diagnostics = build_retrieval_diagnostics(
            anchors=anchors,
            candidates_by_anchor=candidates_by_anchor,
            planned_anchor_ids={item.anchor_id for item in cu_plan},
        )
        applicability_gate = {
            **(product_fact_context.get("applicability_gate") or {}),
            "cu_gate": summarize_cu_gate(
                review_input=review_input,
                anchors=anchors,
                candidates_by_anchor=candidates_by_anchor,
                retrieval_diagnostics=retrieval_diagnostics,
            ),
        }
        yield workflow_event(
            "step_completed",
            "LLM CU rerank",
            review_run_id=review_run_id,
            summary=f"{len(cu_plan)} CUPlan items · {sum(1 for row in retrieval_diagnostics.values() if row['failure_code'] != 'MATCHED')} diagnostics",
            counts={
                "cu_plan": len(cu_plan),
                "diagnostics": sum(1 for row in retrieval_diagnostics.values() if row["failure_code"] != "MATCHED"),
            },
            sample=[{"cu_id": item.cu_id, "principle": item.principle, "anchor_id": item.anchor_id} for item in cu_plan[:5]],
        )

        yield workflow_event(
            "step_started",
            "Policy evidence chains",
            review_run_id=review_run_id,
            summary="Build purpose-specific LegalBasis, Disclosure, and Exception chain summaries.",
        )
        policy_evidence_chains = build_policy_evidence_chains(
            review_run_id=review_run_id,
            cu_plan=cu_plan,
            disclosure_requirements=disclosure_requirements,
            product_context=product_context,
            workspace_id=review_input.workspace_id,
        )
        yield workflow_event(
            "step_completed",
            "Policy evidence chains",
            review_run_id=review_run_id,
            summary=(
                f"{len(policy_evidence_chains['legal_basis_chains'])} legal · "
                f"{len(policy_evidence_chains['disclosure_chains'])} disclosure · "
                f"{len(policy_evidence_chains['exception_chains'])} exception"
            ),
            counts={
                "legal_basis": len(policy_evidence_chains["legal_basis_chains"]),
                "disclosure": len(policy_evidence_chains["disclosure_chains"]),
                "exception": len(policy_evidence_chains["exception_chains"]),
                "diagnostics": len(policy_evidence_chains["chain_diagnostics"]),
            },
            sample=to_jsonable(policy_evidence_chains["legal_basis_chains"][:2]),
        )

        yield workflow_event("step_started", "Evidence window build", review_run_id=review_run_id, summary="Build narrow Anchor + CUPlan + Premise/LegalChunk windows for judge.")
        evidence_windows = self.judge.build_evidence_windows(
            review_run_id=review_run_id,
            anchors=anchors,
            plan=cu_plan,
            claims=claims,
            context_frame=extraction.context_frame,
            sentence_units=extraction.sentence_units,
            context_influences=extraction.context_influences,
            inter_sentence_relations=extraction.inter_sentence_relations,
            policy_evidence_chains=policy_evidence_chains,
        )
        yield workflow_event("step_completed", "Evidence window build", review_run_id=review_run_id, summary=f"{len(evidence_windows)} evidence windows", counts={"evidence_windows": len(evidence_windows)})

        yield workflow_event("step_started", "LLM judgment", review_run_id=review_run_id, summary="LLM judges each CU using only its evidence window.")
        judgments = self.judge.judge(
            review_run_id=review_run_id,
            anchors=anchors,
            plan=cu_plan,
            windows=evidence_windows,
            product_fact_signals=product_fact_signals_by_anchor(product_fact_context, claims, anchors),
            workspace_id=review_input.workspace_id,
        )
        yield workflow_event(
            "step_completed",
            "LLM judgment",
            review_run_id=review_run_id,
            summary=f"{len(judgments)} judgments",
            counts={
                "judgments": len(judgments),
                "non_compliant": sum(1 for judgment in judgments if judgment.verdict == "NON_COMPLIANT"),
                "insufficient": sum(1 for judgment in judgments if judgment.verdict == "INSUFFICIENT"),
            },
            sample=[{"cu_id": judgment.cu_id, "verdict": judgment.verdict, "score": judgment.score} for judgment in judgments[:5]],
        )

        yield workflow_event("step_started", "Exception override", review_run_id=review_run_id, summary="For NON_COMPLIANT judgments only, retrieve reference/exception closure and ask whether it mitigates the verdict.")
        plan_by_item_id = {item.plan_item_id: item for item in cu_plan}
        # Same eligibility filter as before (NON_COMPLIANT + exception_eligible),
        # applied deterministically in judgment order so the parallel fan-out sees
        # the identical candidate set.
        eligible_judgments = [
            judgment
            for judgment in judgments
            if judgment.verdict == "NON_COMPLIANT"
            and (plan_item := plan_by_item_id.get(judgment.plan_item_id)) is not None
            and plan_item.legal_element_profile is not None
            and plan_item.legal_element_profile.exception_eligible
        ]

        def _review_exception(judgment: Any) -> Any:
            # Each override is independent: closure retrieval opens its own Neo4j
            # session and the LLM call uses only this judgment's closure. The
            # mitigation-evidence gate is unchanged; items without mitigation
            # evidence produce no review (None) exactly as the sequential loop
            # skipped them.
            closure = self.retriever.exception_closure(
                workspace_id=review_input.workspace_id,
                cu_id=judgment.cu_id,
                max_depth=4,
            )
            if not exception_closure_has_mitigation_evidence(closure):
                return None
            return self.judge.review_exception(
                review_run_id=review_run_id,
                judgment=judgment,
                closure=closure,
            )

        review_results = ordered_parallel_map(
            _review_exception,
            eligible_judgments,
            workers=worker_count("CCG_PARALLEL_EXCEPTION_WORKERS", 4),
            label="exception_override",
        )
        # Preserve judgment order and drop skipped (None) items — byte-identical to
        # the sequential append order.
        exception_reviews = [review for review in review_results if review is not None]
        yield workflow_event("step_completed", "Exception override", review_run_id=review_run_id, summary=f"{len(exception_reviews)} exception reviews", counts={"exception_reviews": len(exception_reviews)})

        # Track C(표현·브랜드세이프티): 게이트(CCG_ENABLE_TRACK_C) OFF 면 정적 extension
        # 요약(무회귀), ON 이면 로컬 리스크 코퍼스로 실판정. additive shape 이므로 기존
        # 프론트 OverallTab 은 그대로 동작한다.
        # 비-KR 관할 제외: Track C 의 리스크 축·판례 코퍼스(UnSmile 등)와 정적 요약은
        # 전부 한국 표현·한국어 기준이라 다른 관할에 적용되지 않는다 — 주입하지 않는다.
        if uses_korean_law_context(review_input.workspace_id):
            track_c_summary = run_track_c(
                review_input=review_input,
                sentences=[unit.text for unit in extraction.sentence_units],
                retriever=self.retriever,
                llm=self.llm,
            )
        else:
            track_c_summary = {}

        graph = ReviewGraph(
            review_run_id=review_run_id,
            ad_draft_id=ad_draft_id,
            content_hash=digest,
            context_frame=to_jsonable(extraction.context_frame),
            sentence_units=extraction.sentence_units,
            inter_sentence_relations=extraction.inter_sentence_relations,
            context_influences=extraction.context_influences,
            claims=claims,
            context_triples=context_triples,
            anchors=anchors,
            anchor_feature_sets=anchor_feature_sets,
            cu_plan=cu_plan,
            evidence_windows=evidence_windows,
            judgments=judgments,
            exception_reviews=exception_reviews,
            graph_paths=graph_path_summary(cu_plan, judgments),
            retrieval_diagnostics=retrieval_diagnostics,
            product_context=product_context,
            product_fact_context=product_fact_context,
            applicability_gate=applicability_gate,
            prominence_analysis=prominence_analysis,
            disclosure_links=disclosure_links,
            prominence_diagnostics=prominence_diagnostics,
            disclosure_requirements=disclosure_requirements,
            policy_evidence_chains=policy_evidence_chains,
            overall_impression_judgment=overall_impression_judgment,
            track_c_summary=track_c_summary,
        )
        yield workflow_event("step_started", "Neo4j persistence", review_run_id=review_run_id, summary="Persist AdDraft, Context Graph, CUPlan, judgments, and evidence paths.")
        self.writer.save(review_input, graph)
        yield workflow_event("step_completed", "Neo4j persistence", review_run_id=review_run_id, summary="Review graph persisted.")

        yield workflow_event("step_started", "Revision suggestions", review_run_id=review_run_id, summary="Generate reviewer-facing revision suggestions for risky actionable anchors.")
        revision_suggestions = self.revision.suggest(review_input=review_input, graph=graph)
        yield workflow_event("step_completed", "Revision suggestions", review_run_id=review_run_id, summary=f"{len(revision_suggestions)} suggestions", counts={"revision_suggestions": len(revision_suggestions)})

        yield workflow_event("step_started", "Routing", review_run_id=review_run_id, summary="Aggregate effective judgments, Track B, CUPlan diagnostics, and disclosure context.")
        output = build_output(review_input, graph, revision_suggestions=revision_suggestions)
        yield workflow_event("step_completed", "Routing", review_run_id=review_run_id, summary=output.final_verdict, payload={"final_verdict": output.final_verdict, "routing": output.routing})

        # 참고용 번역(표시 전용) — 비-KR workspace에서만. 판정은 이미 끝났으므로
        # 파이프라인에 개입할 수 없고, 실패해도 심사 결과는 그대로 전달된다.
        if not uses_korean_law_context(review_input.workspace_id):
            yield workflow_event("step_started", "Reference translation", review_run_id=review_run_id, summary="Display-only EN/KM/KO reference translation of the original ad text and revisions.")
            translations = translate_ad_for_display(
                self.llm,
                review_input.content_text,
                review_input.workspace_id,
                # 파이프라인의 문장 분할(sentence_units) 그대로 — 콘솔이 문장별로
                # 원문 바로 아래 EN/KM/KO 3개 언어를 병기한다.
                sentence_texts=[unit.text for unit in extraction.sentence_units],
                # 수정문(교정안) 줄 — diff의 + 줄과 하단 고지 블록에도 3개 언어 병기.
                revision_texts=revision_display_texts(revision_suggestions),
            )
            output = dataclasses.replace(output, ad_translations=translations)
            yield workflow_event("step_completed", "Reference translation", review_run_id=review_run_id, summary="reference translation attached" if translations and (translations.get("en") or translations.get("ko")) else "translation unavailable (review unaffected)")

        yield workflow_event("result", "Review result", review_run_id=review_run_id, summary=output.final_verdict, result=output)


def review_input_from_payload(payload: dict[str, Any]) -> ReviewInput:
    # 입력이 NFD(분해형 자모)면 NFC로 정규화 — macOS 등에서 들어온 NFD 텍스트는 폰트에
    # 따라 자모가 벌어져 '깨진' 것처럼 보이고, NFC인 추출 결과와 정렬도 어긋난다. 여기서
    # 한 번 정규화하면 원문·문장·앵커·인용·판정 등 다운스트림 텍스트가 모두 NFC가 된다.
    return ReviewInput(
        dataset_item_id=str(payload.get("dataset_item_id", "")),
        title=unicodedata.normalize("NFC", str(payload.get("title", ""))),
        content_text=unicodedata.normalize("NFC", str(payload.get("content_text", ""))),
        channel=str(payload.get("channel", "bank_event_page_text")),
        source_type=str(payload.get("source_type", "")),
        product_group=str(payload.get("product_group", "auto")),
        selected_product_id=str(payload.get("selected_product_id", "")),
        selected_product_name=str(payload.get("selected_product_name", "")),
        workspace_id=str(payload.get("workspace_id", "graphcompliance_mvp_jb_20260530")),
        language=str(payload.get("language", "ko")),
    )


def revision_display_texts(revision_suggestions: list[dict[str, Any]]) -> list[str]:
    """수정문 표시 줄(diff의 + 줄이 되는 텍스트) 수집 — 참고 번역 대상.

    개별 교정(after), 전체 일관 교정본(__document__)의 줄 분할, 하단 고지 블록
    (add 항목)을 모아 프론트 diff 가 줄 단위로 3개 언어를 병기할 수 있게 한다.
    """
    texts: list[str] = []
    for suggestion in revision_suggestions or []:
        if not isinstance(suggestion, dict):
            continue
        anchor_id = str(suggestion.get("anchor_id") or "")
        after = str(suggestion.get("after") or "").strip()
        if anchor_id == "__document__":
            # 프론트 diff 는 교정본을 줄/문장 단위로 나눠 + 줄을 만든다 — 같은
            # 단위로 번역해야 줄별 매칭이 된다(tokenize 규칙과 동일: 개행 우선).
            for line in after.splitlines():
                line = line.strip()
                if line:
                    texts.append(line)
            continue
        if after:
            texts.append(after)
        for item in suggestion.get("disclosure_block") or []:
            if isinstance(item, dict) and item.get("status") == "add" and str(item.get("text") or "").strip():
                texts.append(str(item["text"]).strip())
    return texts


def graph_path_summary(cu_plan, judgments) -> list[dict[str, Any]]:
    judgment_by_item = {judgment.plan_item_id: judgment for judgment in judgments}
    return [
        {
            "anchor_id": item.anchor_id,
            "cu_id": item.cu_id,
            "plan_item_id": item.plan_item_id,
            "judgment_id": judgment_by_item.get(item.plan_item_id).judgment_id if item.plan_item_id in judgment_by_item else "",
            "path": "ContextAnchor -> CUPlanItem -> ComplianceUnit -> EvidenceWindow -> LLMJudgment",
        }
        for item in cu_plan
    ]


def build_retrieval_diagnostics(
    *,
    anchors,
    candidates_by_anchor: dict[str, list[PolicyCandidate]],
    planned_anchor_ids: set[str],
) -> dict[str, dict[str, Any]]:
    diagnostics: dict[str, dict[str, Any]] = {}
    for anchor in anchors:
        candidates = candidates_by_anchor.get(anchor.anchor_id, [])
        code = ""
        if anchor.anchor_id in planned_anchor_ids:
            code = "MATCHED"
        elif not anchor.hypernyms:
            code = "NO_HYPERNYM_MATCH"
        elif not candidates:
            code = "NO_LEGAL_ELEMENT_MATCH" if anchor.feature_set and anchor.feature_set.action_types else "MISSING_POLICY_COVERAGE"
        elif not any(candidate.active_for_gate for candidate in candidates):
            code = "NO_ACTIVE_CU_AFTER_GATE"
        else:
            code = "RERANK_DROPPED_ALL"
        diagnostics[anchor.anchor_id] = {
            "anchor_id": anchor.anchor_id,
            "failure_code": code,
            "candidate_count": len(candidates),
            "active_candidate_count": sum(1 for candidate in candidates if candidate.active_for_gate),
            "hypernym_count": len(anchor.hypernyms),
            "top_candidate_ids": [candidate.cu_id for candidate in candidates[:5]],
            "top_candidate_principles": [candidate.principle for candidate in candidates[:5]],
            "anchor_action_types": anchor.feature_set.action_types if anchor.feature_set else [],
            "anchor_positive_features": anchor.feature_set.positive_features if anchor.feature_set else [],
            "top_candidate_missing_required_features": [
                candidate.missing_required_features for candidate in candidates[:5]
            ],
        }
    return diagnostics


def product_fact_signals_by_anchor(
    product_fact_context: dict[str, Any],
    claims: list[Any],
    anchors: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    """anchor_id -> 그 anchor의 claim에 대한 상품문서 대조 신호(상태/사유).

    광고 주장 ↔ 약관·상품설명서 사실의 모순(CONTRADICTED 등)을 judge가 결론에
    엮을 수 있도록, claim_fact -> claim -> anchor 경로로 비교 결과를 모은다.
    """
    claim_facts = {cf.get("claim_fact_id"): cf for cf in (product_fact_context.get("claim_facts") or [])}
    comparisons = product_fact_context.get("comparison_results") or []
    anchor_by_claim: dict[str, str] = {}
    for anchor in anchors:
        anchor_by_claim.setdefault(getattr(anchor, "claim_id", ""), getattr(anchor, "anchor_id", ""))
    signals: dict[str, list[dict[str, Any]]] = {}
    for comparison in comparisons:
        status = str(comparison.get("status") or "")
        if status == "SUPPORTED":
            continue  # 일치 신호는 위반 추론에 불필요
        claim_fact = claim_facts.get(comparison.get("claim_fact_id"))
        claim_id = str(claim_fact.get("claim_id")) if claim_fact else ""
        anchor_id = anchor_by_claim.get(claim_id)
        if not anchor_id:
            continue
        signals.setdefault(anchor_id, []).append(
            {
                "status": status,
                "rationale": str(comparison.get("rationale") or "")[:400],
            }
        )
    return signals


def workflow_event(event: str, step: str, *, review_run_id: str, summary: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "event": event,
        "step": step,
        "review_run_id": review_run_id,
        "summary": summary,
        **extra,
    }


def exception_closure_has_mitigation_evidence(closure: list[dict[str, Any]]) -> bool:
    mitigation_labels = {"ExceptionRule", "DisclosureRequirement", "EvidenceRequirement", "ProductFact", "ComparisonResult", "ReviewApproval"}
    mitigation_tokens = ["예외", "고지", "설명", "증거", "상품사실", "예금자보호", "조건", "승인", "완화"]
    for row in closure:
        labels = {str(label) for label in row.get("labels") or []}
        text = str(row.get("text") or "")
        if labels & mitigation_labels:
            return True
        if any(token in text for token in mitigation_tokens):
            return True
    return False
