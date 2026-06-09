"""End-to-end LLM-only GraphCompliance CCG workflow."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from claim_modeling import fold_qualifier_anchors_into_parent_claims
from context_extractor import LLMContextExtractor, build_context_triples
from jb_data_context import build_product_context
from judge import LLMComplianceJudge
from llm_gateway import LLMGateway
from normalizer import PolicyGuidedNormalizer
from overall_impression import LLMOverallImpressionJudge
from persistence import Neo4jReviewWriter, ReviewWriter
from planner import LLMCUPlanner
from product_facts import ProductFactAnalyzer
from retriever import Neo4jPolicyRetriever, PolicyRetriever
from revision import LLMRevisionSuggester
from router import build_output
from risk_context import track_c_extension_summary
from schemas import PolicyCandidate, ReviewGraph, ReviewInput, ReviewOutput
from utils import content_hash, stable_id, to_jsonable


class GraphComplianceCCGWorkflow:
    def __init__(
        self,
        *,
        llm: LLMGateway | None = None,
        retriever: PolicyRetriever | None = None,
        writer: ReviewWriter | None = None,
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
        )
        anchors = fold_qualifier_anchors_into_parent_claims(anchors, claims)
        yield workflow_event(
            "step_completed",
            "Policy normalization",
            review_run_id=review_run_id,
            summary=f"{len(anchors)} anchors normalized",
            counts={"anchors": len(anchors), "hypernym_proposals": sum(len(anchor.hypernyms) for anchor in anchors)},
            sample=[
                {
                    "anchor": anchor.span.text,
                    "hypernyms": [proposal.hypernym for proposal in anchor.hypernyms],
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

        yield workflow_event("step_started", "Track B overall impression", review_run_id=review_run_id, summary="LLM judges the representative consumer impression from Claim -> Meaning -> Implicature -> ConsumerEffect paths.")
        overall_impression_judgment = self.overall_impression.judge(
            review_input=review_input,
            claims=claims,
            disclosure_requirements=disclosure_requirements,
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
        candidates_by_anchor = {
            anchor.anchor_id: self.retriever.candidates_for_anchor(
                workspace_id=review_input.workspace_id,
                anchor=anchor,
                product_group=product_context.get("product_group", review_input.product_group),
                channel=review_input.channel,
                limit=12,
            )
            for anchor in anchors
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

        yield workflow_event("step_started", "Evidence window build", review_run_id=review_run_id, summary="Build narrow Anchor + CUPlan + Premise/LegalChunk windows for judge.")
        evidence_windows = self.judge.build_evidence_windows(
            review_run_id=review_run_id,
            anchors=anchors,
            plan=cu_plan,
            claims=claims,
            context_frame=extraction.context_frame,
            sentence_units=extraction.sentence_units,
            context_influences=extraction.context_influences,
        )
        yield workflow_event("step_completed", "Evidence window build", review_run_id=review_run_id, summary=f"{len(evidence_windows)} evidence windows", counts={"evidence_windows": len(evidence_windows)})

        yield workflow_event("step_started", "LLM judgment", review_run_id=review_run_id, summary="LLM judges each CU using only its evidence window.")
        judgments = self.judge.judge(
            review_run_id=review_run_id,
            anchors=anchors,
            plan=cu_plan,
            windows=evidence_windows,
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
        exception_reviews = []
        for judgment in judgments:
            if judgment.verdict != "NON_COMPLIANT":
                continue
            closure = self.retriever.exception_closure(
                workspace_id=review_input.workspace_id,
                cu_id=judgment.cu_id,
                max_depth=4,
            )
            exception_reviews.append(
                self.judge.review_exception(
                    review_run_id=review_run_id,
                    judgment=judgment,
                    closure=closure,
                )
            )
        yield workflow_event("step_completed", "Exception override", review_run_id=review_run_id, summary=f"{len(exception_reviews)} exception reviews", counts={"exception_reviews": len(exception_reviews)})

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
            cu_plan=cu_plan,
            evidence_windows=evidence_windows,
            judgments=judgments,
            exception_reviews=exception_reviews,
            graph_paths=graph_path_summary(cu_plan, judgments),
            retrieval_diagnostics=retrieval_diagnostics,
            product_context=product_context,
            product_fact_context=product_fact_context,
            disclosure_requirements=disclosure_requirements,
            overall_impression_judgment=overall_impression_judgment,
            track_c_summary=track_c_extension_summary(),
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
        yield workflow_event("result", "Review result", review_run_id=review_run_id, summary=output.final_verdict, result=output)


def review_input_from_payload(payload: dict[str, Any]) -> ReviewInput:
    return ReviewInput(
        dataset_item_id=str(payload.get("dataset_item_id", "")),
        title=str(payload.get("title", "")),
        content_text=str(payload.get("content_text", "")),
        channel=str(payload.get("channel", "bank_event_page_text")),
        source_type=str(payload.get("source_type", "")),
        product_group=str(payload.get("product_group", "auto")),
        workspace_id=str(payload.get("workspace_id", "graphcompliance_mvp_jb_20260530")),
    )


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
            code = "MISSING_POLICY_COVERAGE"
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
        }
    return diagnostics


def workflow_event(event: str, step: str, *, review_run_id: str, summary: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "event": event,
        "step": step,
        "review_run_id": review_run_id,
        "summary": summary,
        **extra,
    }
