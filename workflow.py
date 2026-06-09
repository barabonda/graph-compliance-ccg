"""End-to-end LLM-only GraphCompliance CCG workflow."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from context_extractor import LLMContextExtractor, build_context_triples
from jb_data_context import build_product_context
from judge import LLMComplianceJudge
from llm_gateway import LLMGateway
from normalizer import PolicyGuidedNormalizer
from overall_impression import LLMOverallImpressionJudge
from persistence import Neo4jReviewWriter, ReviewWriter
from planner import LLMCUPlanner
from retriever import Neo4jPolicyRetriever, PolicyRetriever
from revision import LLMRevisionSuggester
from router import build_output
from risk_context import track_c_extension_summary
from schemas import PolicyCandidate, ReviewGraph, ReviewInput, ReviewOutput
from utils import content_hash, stable_id


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
        self.retriever = retriever or Neo4jPolicyRetriever()
        self.writer = writer or Neo4jReviewWriter()

    def review(self, review_input: ReviewInput) -> ReviewOutput:
        digest = content_hash(review_input.content_text)
        ad_draft_id = stable_id("ad_draft", review_input.workspace_id, review_input.dataset_item_id, digest)
        review_run_id = stable_id("review_run", ad_draft_id, digest, uuid4().hex)

        self.retriever.assert_policy_alignment_ready(workspace_id=review_input.workspace_id)
        claims = self.extractor.extract(review_input, review_run_id=review_run_id)
        context_triples = build_context_triples(review_run_id=review_run_id, claims=claims)
        policy_context = self.retriever.policy_context_for_claims(
            workspace_id=review_input.workspace_id,
            query_text=review_input.content_text[:1200],
            limit=80,
        )
        anchors = self.normalizer.normalize(
            review_run_id=review_run_id,
            claims=claims,
            policy_context=policy_context,
            top_n=5,
        )
        product_context, disclosure_requirements = build_product_context(review_input, claims)
        overall_impression_judgment = self.overall_impression.judge(
            review_input=review_input,
            claims=claims,
            disclosure_requirements=disclosure_requirements,
        )
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
        evidence_windows = self.judge.build_evidence_windows(
            review_run_id=review_run_id,
            anchors=anchors,
            plan=cu_plan,
        )
        judgments = self.judge.judge(
            review_run_id=review_run_id,
            anchors=anchors,
            plan=cu_plan,
            windows=evidence_windows,
        )
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

        graph = ReviewGraph(
            review_run_id=review_run_id,
            ad_draft_id=ad_draft_id,
            content_hash=digest,
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
            disclosure_requirements=disclosure_requirements,
            overall_impression_judgment=overall_impression_judgment,
            track_c_summary=track_c_extension_summary(),
        )
        self.writer.save(review_input, graph)
        revision_suggestions = self.revision.suggest(review_input=review_input, graph=graph)
        return build_output(review_input, graph, revision_suggestions=revision_suggestions)


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
