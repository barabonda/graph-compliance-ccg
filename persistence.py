"""Neo4j persistence for graph-compliance-ccg review runs."""

from __future__ import annotations

import os
import json
from datetime import UTC, datetime
from typing import Protocol

from schemas import ReviewGraph, ReviewInput
from utils import stable_id, to_jsonable


SOURCE = "graphcompliance_ccg_review"


class ReviewWriter(Protocol):
    def save(self, review_input: ReviewInput, graph: ReviewGraph) -> None:
        ...


class Neo4jReviewWriter:
    def __init__(self, uri: str | None = None, user: str | None = None, password: str | None = None) -> None:
        from neo4j import GraphDatabase

        self.uri = uri or os.environ.get("NEO4J_URI", "")
        self.user = user or os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "")
        if not self.uri or not self.user or not self.password:
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, and NEO4J_PASSWORD are required.")
        # 30초 이상 쉰 풀 연결은 재사용 전 ping — 긴 LLM 단계 후 저장 시 SessionExpired 방지.
        self.driver = GraphDatabase.driver(
            self.uri, auth=(self.user, self.password), liveness_check_timeout=30
        )
        self.database = os.environ.get("NEO4J_DATABASE")

    def close(self) -> None:
        self.driver.close()

    def _session_kwargs(self) -> dict[str, str]:
        return {"database": self.database} if self.database else {}

    def save(self, review_input: ReviewInput, graph: ReviewGraph) -> None:
        now = datetime.now(UTC).isoformat()
        common = {
            "workspace_id": review_input.workspace_id,
            "review_run_id": graph.review_run_id,
            "dataset_item_id": review_input.dataset_item_id,
            "content_hash": graph.content_hash,
            "created_at": now,
            "source": SOURCE,
        }
        with self.driver.session(**self._session_kwargs()) as session:
            session.run(
                """
                MERGE (ad:AdDraft {id: $ad_id, workspace_id: $workspace_id})
                SET ad += $ad_props
                MERGE (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                SET run += $run_props
                MERGE (ad)-[:HAS_REVIEW_RUN {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(run)
                """,
                ad_id=graph.ad_draft_id,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                ad_props={
                    **common,
                    "id": graph.ad_draft_id,
                    "title": review_input.title,
                    "text": review_input.content_text,
                    "channel": review_input.channel,
                    "source_type": review_input.source_type,
                    "product_group": review_input.product_group,
                },
                run_props=neo4j_props(
                    {
                        **common,
                        "id": graph.review_run_id,
                        "overall_impression_judgment": graph.overall_impression_judgment,
                        "context_frame": graph.context_frame,
                        "sentence_units": to_jsonable(graph.sentence_units),
                        "inter_sentence_relations": to_jsonable(graph.inter_sentence_relations),
                        "context_influences": to_jsonable(graph.context_influences),
                        "anchor_feature_sets": to_jsonable(graph.anchor_feature_sets),
                        "product_context": graph.product_context,
                        "product_fact_context": graph.product_fact_context,
                        "disclosure_requirements": graph.disclosure_requirements,
                        "track_c_summary": graph.track_c_summary,
                        "retrieval_diagnostics": graph.retrieval_diagnostics,
                    }
                ),
            )
            self._save_claims(session, review_input, graph, common)
            self._save_hierarchical_context(session, review_input, graph, common)
            # context_triples 는 저장하지 않는다: 클레임 체인(DENOTES→IMPLIES→
            # CAN_MISLEAD→RAISES)·한정어·문장 노드로 같은 정보가 이미 저장되는
            # 결정론 파생물이라 이중 기록이었다. 필요 시 build_context_triples 로
            # 언제든 동일하게 재생성 가능(stable_id).
            self._save_anchors(session, review_input, graph, common)
            self._save_plan(session, review_input, graph, common)
            self._save_judgments(session, review_input, graph, common)
            self._save_product_context(session, review_input, graph, common)
            self._save_product_fact_context(session, review_input, graph, common)

    def _save_claims(self, session, review_input: ReviewInput, graph: ReviewGraph, common: dict[str, object]) -> None:
        for claim in graph.claims:
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (claim:Claim {id: $claim_id, workspace_id: $workspace_id})
                SET claim += $claim_props
                MERGE (run)-[:HAS_CLAIM {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(claim)
                MERGE (meaning:Meaning {id: $meaning_id, workspace_id: $workspace_id})
                SET meaning += $meaning_props
                MERGE (imp:Implicature {id: $implicature_id, workspace_id: $workspace_id})
                SET imp += $implicature_props
                MERGE (effect:ConsumerEffect {id: $effect_id, workspace_id: $workspace_id})
                SET effect += $effect_props
                MERGE (risk:RiskNode {id: $risk_id, workspace_id: $workspace_id})
                SET risk += $risk_props
                MERGE (claim)-[:DENOTES {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(meaning)
                MERGE (meaning)-[:IMPLIES {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(imp)
                MERGE (imp)-[:CAN_MISLEAD {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(effect)
                MERGE (effect)-[:RAISES {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(risk)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                claim_id=claim.claim_id,
                meaning_id=f"meaning_{claim.claim_id}",
                implicature_id=f"implicature_{claim.claim_id}",
                effect_id=f"effect_{claim.claim_id}",
                risk_id=f"risk_{claim.claim_id}",
                claim_props={
                    **common,
                    "id": claim.claim_id,
                    "text": claim.text,
                    "span_start": claim.span.start,
                    "span_end": claim.span.end,
                    "risk_hypernym": claim.risk_hypernym,
                    "risk_severity": claim.risk_severity,
                },
                meaning_props={**common, "id": f"meaning_{claim.claim_id}", "text": claim.meaning},
                implicature_props={**common, "id": f"implicature_{claim.claim_id}", "text": claim.implicature},
                effect_props={**common, "id": f"effect_{claim.claim_id}", "text": claim.consumer_effect},
                risk_props={**common, "id": f"risk_{claim.claim_id}", "name": claim.risk_hypernym, "severity": claim.risk_severity},
            )
            session.run(
                """
                UNWIND $entities AS row
                MATCH (claim:Claim {id: $claim_id, workspace_id: $workspace_id})
                MERGE (entity:ContextEntity {id: row.id, workspace_id: $workspace_id})
                SET entity += row
                MERGE (claim)-[:MENTIONS_ENTITY {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(entity)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                claim_id=claim.claim_id,
                entities=[
                    {
                        **common,
                        "id": entity.entity_id,
                        "name": entity.name,
                        "entity_type": entity.entity_type,
                        "span_start": entity.span.start,
                        "span_end": entity.span.end,
                    }
                for entity in claim.entities
                ],
            )
            session.run(
                """
                UNWIND $qualifiers AS row
                MATCH (claim:Claim {id: $claim_id, workspace_id: $workspace_id})
                MERGE (qualifier:ClaimQualifier {id: row.id, workspace_id: $workspace_id})
                SET qualifier += row
                MERGE (claim)-[:HAS_QUALIFIER {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(qualifier)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                claim_id=claim.claim_id,
                qualifiers=[
                    {
                        **common,
                        "id": qualifier.qualifier_id,
                        "text": qualifier.text,
                        "role": qualifier.role,
                        "span_start": qualifier.span.start,
                        "span_end": qualifier.span.end,
                        "meaning": qualifier.meaning,
                        "risk_reason": qualifier.risk_reason,
                        "confidence": qualifier.confidence,
                    }
                    for qualifier in claim.qualifiers
                ],
            )

    def _save_hierarchical_context(self, session, review_input: ReviewInput, graph: ReviewGraph, common: dict[str, object]) -> None:
        if graph.context_frame:
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (frame:ContextFrame {id: $frame_id, workspace_id: $workspace_id})
                SET frame += $frame_props
                MERGE (run)-[:HAS_CONTEXT_FRAME {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(frame)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                frame_id=graph.context_frame.get("frame_id", f"context_frame_{graph.review_run_id}"),
                frame_props=neo4j_props({**common, **graph.context_frame}),
            )
        for sentence in graph.sentence_units:
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                OPTIONAL MATCH (frame:ContextFrame {id: $frame_id, workspace_id: $workspace_id})
                MERGE (sentence:SentenceUnit {id: $sentence_id, workspace_id: $workspace_id})
                SET sentence += $sentence_props
                MERGE (run)-[:HAS_SENTENCE_UNIT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(sentence)
                FOREACH (_ IN CASE WHEN frame IS NULL THEN [] ELSE [1] END |
                  MERGE (frame)-[:HAS_SENTENCE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(sentence)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                frame_id=graph.context_frame.get("frame_id", f"context_frame_{graph.review_run_id}") if graph.context_frame else "",
                sentence_id=sentence.sentence_id,
                sentence_props=neo4j_props({**common, **to_jsonable(sentence)}),
            )
        for claim in graph.claims:
            if not claim.sentence_id:
                continue
            session.run(
                """
                MATCH (sentence:SentenceUnit {id: $sentence_id, workspace_id: $workspace_id})
                MATCH (claim:Claim {id: $claim_id, workspace_id: $workspace_id})
                MERGE (sentence)-[:CONTAINS_CLAIM {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(claim)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                sentence_id=claim.sentence_id,
                claim_id=claim.claim_id,
            )
        for relation in graph.inter_sentence_relations:
            session.run(
                """
                MATCH (source_sentence:SentenceUnit {id: $source_sentence_id, workspace_id: $workspace_id})
                MATCH (target_sentence:SentenceUnit {id: $target_sentence_id, workspace_id: $workspace_id})
                MERGE (relation:InterSentenceRelation {id: $relation_id, workspace_id: $workspace_id})
                SET relation += $relation_props
                MERGE (source_sentence)-[:HAS_INTER_SENTENCE_RELATION {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source, relation_type: $relation_type}]->(relation)
                MERGE (relation)-[:RELATES_TO_SENTENCE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source, relation_type: $relation_type}]->(target_sentence)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                source_sentence_id=relation.source_sentence_id,
                target_sentence_id=relation.target_sentence_id,
                relation_id=relation.relation_id,
                relation_type=relation.relation_type,
                relation_props=neo4j_props({**common, **to_jsonable(relation)}),
            )
        for influence in graph.context_influences:
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (influence:ContextInfluence {id: $influence_id, workspace_id: $workspace_id})
                SET influence += $influence_props
                MERGE (run)-[:HAS_CONTEXT_INFLUENCE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(influence)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                influence_id=influence.influence_id,
                influence_props=neo4j_props({**common, **to_jsonable(influence)}),
            )

    def _save_anchors(self, session, review_input: ReviewInput, graph: ReviewGraph, common: dict[str, object]) -> None:
        for anchor in graph.anchors:
            session.run(
                """
                MATCH (claim:Claim {id: $claim_id, workspace_id: $workspace_id})
                MERGE (anchor:ContextAnchor {id: $anchor_id, workspace_id: $workspace_id})
                SET anchor += $anchor_props
                MERGE (claim)-[:HAS_ANCHOR {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(anchor)
                WITH anchor
                UNWIND $hypernyms AS row
                MERGE (h:PolicyHypernymProposal {id: row.id, workspace_id: $workspace_id})
                SET h += row
                MERGE (anchor)-[:NORMALIZED_TO {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(h)
                WITH h, row
                OPTIONAL MATCH (canonical:PolicyHypernym {id: row.hypernym_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN canonical IS NULL THEN [] ELSE [1] END |
                  MERGE (h)-[:SELECTS_HYPERNYM {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(canonical)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                claim_id=anchor.claim_id,
                anchor_id=anchor.anchor_id,
                anchor_props={
                    **common,
                    "id": anchor.anchor_id,
                    "anchor_type": anchor.anchor_type,
                    "text": anchor.span.text,
                    "span_start": anchor.span.start,
                    "span_end": anchor.span.end,
                    "facts_json": to_jsonable(anchor.facts),
                },
                hypernyms=[
                    {
                        **common,
                        "id": proposal.proposal_id,
                        "hypernym_id": proposal.hypernym_id,
                        "hypernym": proposal.hypernym,
                        "support": proposal.support,
                        "confidence": proposal.confidence,
                        "normalized_score": proposal.normalized_score,
                        "evidence_ids": proposal.evidence_ids,
                        "why": proposal.why,
                    }
                    for proposal in anchor.hypernyms
                ],
            )
            if anchor.feature_set:
                session.run(
                    """
                    MATCH (anchor:ContextAnchor {id: $anchor_id, workspace_id: $workspace_id})
                    MERGE (feature_set:AnchorFeatureSet {id: $feature_set_id, workspace_id: $workspace_id})
                    SET feature_set += $feature_set_props
                    MERGE (anchor)-[:HAS_FEATURE_SET {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(feature_set)
                    """,
                    workspace_id=review_input.workspace_id,
                    review_run_id=graph.review_run_id,
                    source=SOURCE,
                    anchor_id=anchor.anchor_id,
                    feature_set_id=anchor.feature_set.feature_set_id,
                    feature_set_props=neo4j_props({**common, **to_jsonable(anchor.feature_set)}),
                )

    def _save_plan(self, session, review_input: ReviewInput, graph: ReviewGraph, common: dict[str, object]) -> None:
        session.run(
            """
            MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
            MERGE (plan:CUPlan {id: $plan_id, workspace_id: $workspace_id})
            SET plan += $plan_props
            MERGE (run)-[:HAS_CU_PLAN {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(plan)
            """,
            workspace_id=review_input.workspace_id,
            review_run_id=graph.review_run_id,
            source=SOURCE,
            plan_id=f"cuplan_{graph.review_run_id}",
            plan_props={**common, "id": f"cuplan_{graph.review_run_id}"},
        )
        for item in graph.cu_plan:
            session.run(
                """
                MATCH (plan:CUPlan {id: $plan_id, workspace_id: $workspace_id})
                MATCH (anchor:ContextAnchor {id: $anchor_id, workspace_id: $workspace_id})
                MERGE (item:CUPlanItem {id: $item_id, workspace_id: $workspace_id})
                SET item += $item_props
                MERGE (plan)-[:HAS_PLAN_ITEM {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(item)
                MERGE (anchor)-[:SELECTED_FOR_PLAN {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(item)
                WITH item
                OPTIONAL MATCH (cu:ComplianceUnit {id: $cu_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN cu IS NULL THEN [] ELSE [1] END |
                  MERGE (item)-[:TARGETS_CU {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(cu)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                plan_id=f"cuplan_{graph.review_run_id}",
                anchor_id=item.anchor_id,
                item_id=item.plan_item_id,
                cu_id=item.cu_id,
                item_props=neo4j_props({**common, **to_jsonable(item)}),
            )
        for window in graph.evidence_windows:
            window_props = to_jsonable(window)
            # Purpose-specific evidence chains are runtime/UI artifacts in v1.
            # Persist the EvidenceWindow itself and its evidence links, but do
            # not store chain payloads as Neo4j properties or hop nodes.
            window_props.pop("policy_evidence_chains", None)
            session.run(
                """
                MATCH (item:CUPlanItem {id: $plan_item_id, workspace_id: $workspace_id})
                MERGE (window:EvidenceWindow {id: $window_id, workspace_id: $workspace_id})
                SET window += $window_props
                MERGE (item)-[:HAS_EVIDENCE_WINDOW {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(window)
                WITH window
                UNWIND $legal_evidence_ids AS evidence_id
                OPTIONAL MATCH (evidence {id: evidence_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN evidence IS NULL THEN [] ELSE [1] END |
                  MERGE (window)-[:USES_EVIDENCE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(evidence)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                plan_item_id=window.plan_item_id,
                window_id=window.evidence_window_id,
                legal_evidence_ids=window.legal_evidence_ids,
                window_props=neo4j_props({**common, **window_props}),
            )

    def _save_judgments(self, session, review_input: ReviewInput, graph: ReviewGraph, common: dict[str, object]) -> None:
        for judgment in graph.judgments:
            session.run(
                """
                MATCH (item:CUPlanItem {id: $plan_item_id, workspace_id: $workspace_id})
                MERGE (j:LLMJudgment {id: $judgment_id, workspace_id: $workspace_id})
                SET j += $judgment_props
                MERGE (item)-[:JUDGED_AS {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(j)
                WITH item, j
                OPTIONAL MATCH (window:EvidenceWindow {plan_item_id: $plan_item_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN window IS NULL THEN [] ELSE [1] END |
                  MERGE (j)-[:USES_EVIDENCE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(window)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                plan_item_id=judgment.plan_item_id,
                judgment_id=judgment.judgment_id,
                judgment_props=neo4j_props({**common, **to_jsonable(judgment)}),
            )
        for review in graph.exception_reviews:
            session.run(
                """
                MATCH (j:LLMJudgment {id: $judgment_id, workspace_id: $workspace_id})
                MERGE (e:ExceptionReview {id: $review_id, workspace_id: $workspace_id})
                SET e += $review_props
                MERGE (j)-[:HAS_EXCEPTION_REVIEW {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(e)
                WITH e
                UNWIND $closure_evidence_ids AS evidence_id
                OPTIONAL MATCH (evidence {id: evidence_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN evidence IS NULL THEN [] ELSE [1] END |
                  MERGE (e)-[:USES_EVIDENCE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(evidence)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                judgment_id=review.judgment_id,
                review_id=review.exception_review_id,
                closure_evidence_ids=review.closure_evidence_ids,
                review_props=neo4j_props({**common, **to_jsonable(review)}),
            )

    def _save_product_context(self, session, review_input: ReviewInput, graph: ReviewGraph, common: dict[str, object]) -> None:
        product_group = graph.product_context.get("product_group", "auto")
        session.run(
            """
            MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
            MERGE (group:ProductGroup {id: $group_id, workspace_id: $workspace_id})
            SET group += $group_props
            MERGE (run)-[:SCOPED_TO_PRODUCT_GROUP {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(group)
            """,
            workspace_id=review_input.workspace_id,
            review_run_id=graph.review_run_id,
            source=SOURCE,
            group_id=f"product_group_{product_group}",
            group_props=neo4j_props({**common, "id": f"product_group_{product_group}", "name": product_group}),
        )
        for requirement in graph.disclosure_requirements:
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MATCH (group:ProductGroup {id: $group_id, workspace_id: $workspace_id})
                MERGE (req:DisclosureRequirement {id: $requirement_id, workspace_id: $workspace_id})
                SET req += $requirement_props
                MERGE (group)-[:REQUIRES_DISCLOSURE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(req)
                MERGE (run)-[:CHECKS_DISCLOSURE {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(req)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                group_id=f"product_group_{product_group}",
                requirement_id=requirement["id"],
                requirement_props=neo4j_props({**common, **requirement}),
            )
        for product in graph.product_context.get("matched_products", []):
            product_id = f"product_{product.get('product', '')}"
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MATCH (group:ProductGroup {id: $group_id, workspace_id: $workspace_id})
                MERGE (product:Product {id: $product_id, workspace_id: $workspace_id})
                SET product += $product_props
                MERGE (group)-[:HAS_PRODUCT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(product)
                MERGE (run)-[:ABOUT_PRODUCT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(product)
                WITH product
                UNWIND $source_ids AS source_id
                MERGE (doc:ProductDocument {id: source_id, workspace_id: $workspace_id})
                SET doc += $doc_props
                MERGE (product)-[:HAS_PRODUCT_DOCUMENT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(doc)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                group_id=f"product_group_{product_group}",
                product_id=product_id,
                product_props=neo4j_props({**common, **product, "id": product_id, "name": product.get("product", "")}),
                source_ids=product.get("source_ids", []),
                doc_props=neo4j_props(
                    {
                        **common,
                        "product": product.get("product", ""),
                        "document_labels": product.get("document_labels", []),
                        "metadata_source": "전북은행 상품문서 메타데이터.xlsx",
                    }
                ),
            )

    def _save_product_fact_context(self, session, review_input: ReviewInput, graph: ReviewGraph, common: dict[str, object]) -> None:
        context = graph.product_fact_context or {}
        if not context:
            return

        matched_product = str(context.get("matched_product") or "")
        product_id = f"product_{matched_product}" if matched_product else ""
        if matched_product:
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (product:Product {id: $product_id, workspace_id: $workspace_id})
                SET product += $product_props
                MERGE (run)-[:ABOUT_PRODUCT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(product)
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                product_id=product_id,
                product_props=neo4j_props({**common, "id": product_id, "name": matched_product}),
            )

        for document in context.get("selected_documents", []) or []:
            document_id = str(document.get("document_id") or document.get("source_id") or "")
            if not document_id:
                document_id = stable_id("product_document", document.get("file_name", ""), document.get("relative_path", ""))
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (doc:ProductDocument {id: $document_id, workspace_id: $workspace_id})
                SET doc += $document_props
                MERGE (run)-[:USES_PRODUCT_DOCUMENT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(doc)
                WITH doc
                OPTIONAL MATCH (product:Product {id: $product_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN product IS NULL THEN [] ELSE [1] END |
                  MERGE (product)-[:HAS_PRODUCT_DOCUMENT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(doc)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                product_id=product_id,
                document_id=document_id,
                document_props=neo4j_props({**common, **document, "id": document_id}),
            )

        for fact in context.get("product_facts", []) or []:
            fact_id = str(fact.get("fact_id") or "")
            if not fact_id:
                fact_id = stable_id("product_fact", matched_product, fact.get("source_document_id", ""), fact.get("fact_type", ""), fact.get("value", ""))
            source_document_id = str(fact.get("source_document_id") or "")
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (fact:ProductFact {id: $fact_id, workspace_id: $workspace_id})
                SET fact += $fact_props
                MERGE (run)-[:EXTRACTED_PRODUCT_FACT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(fact)
                WITH fact
                OPTIONAL MATCH (doc:ProductDocument {id: $source_document_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN doc IS NULL THEN [] ELSE [1] END |
                  MERGE (doc)-[:CONTAINS_FACT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(fact)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                fact_id=fact_id,
                source_document_id=source_document_id,
                fact_props=neo4j_props({**common, **fact, "id": fact_id, "matched_product": matched_product}),
            )

        claim_by_fact_id: dict[str, str] = {}
        for claim_fact in context.get("claim_facts", []) or []:
            claim_fact_id = str(claim_fact.get("claim_fact_id") or "")
            if not claim_fact_id:
                claim_fact_id = stable_id("claim_fact", claim_fact.get("claim_id", ""), claim_fact.get("fact_type", ""), claim_fact.get("value", ""))
            claim_id = str(claim_fact.get("claim_id") or "")
            claim_by_fact_id[claim_fact_id] = claim_id
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (claimFact:ClaimFact {id: $claim_fact_id, workspace_id: $workspace_id})
                SET claimFact += $claim_fact_props
                MERGE (run)-[:EXTRACTED_CLAIM_FACT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(claimFact)
                WITH claimFact
                OPTIONAL MATCH (claim:Claim {id: $claim_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN claim IS NULL THEN [] ELSE [1] END |
                  MERGE (claim)-[:ASSERTS_FACT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(claimFact)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                claim_fact_id=claim_fact_id,
                claim_id=claim_id,
                claim_fact_props=neo4j_props({**common, **claim_fact, "id": claim_fact_id}),
            )

        for comparison in context.get("comparison_results", []) or []:
            comparison_id = str(comparison.get("comparison_id") or "")
            claim_fact_id = str(comparison.get("claim_fact_id") or "")
            product_fact_id = str(comparison.get("product_fact_id") or "")
            if not comparison_id:
                comparison_id = stable_id("comparison", claim_fact_id, product_fact_id, comparison.get("status", ""))
            claim_id = claim_by_fact_id.get(claim_fact_id, "")
            source_document_id = ""
            for fact in context.get("product_facts", []) or []:
                if str(fact.get("fact_id") or "") == product_fact_id:
                    source_document_id = str(fact.get("source_document_id") or "")
                    break
            session.run(
                """
                MATCH (run:ReviewRun {id: $review_run_id, workspace_id: $workspace_id})
                MERGE (result:ComparisonResult {id: $comparison_id, workspace_id: $workspace_id})
                SET result += $comparison_props
                MERGE (run)-[:HAS_COMPARISON_RESULT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(result)
                WITH result
                OPTIONAL MATCH (claimFact:ClaimFact {id: $claim_fact_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN claimFact IS NULL THEN [] ELSE [1] END |
                  MERGE (claimFact)-[:HAS_COMPARISON_RESULT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(result)
                )
                FOREACH (_ IN CASE WHEN claimFact IS NULL THEN [] ELSE [1] END |
                  MERGE (claimFact)-[:COMPARED_TO {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(result)
                )
                WITH result, claimFact
                OPTIONAL MATCH (productFact:ProductFact {id: $product_fact_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN productFact IS NULL THEN [] ELSE [1] END |
                  MERGE (result)-[:COMPARES_TO {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(productFact)
                )
                FOREACH (_ IN CASE WHEN claimFact IS NULL OR productFact IS NULL THEN [] ELSE [1] END |
                  MERGE (claimFact)-[:COMPARED_TO {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(productFact)
                )
                WITH result
                OPTIONAL MATCH (doc:ProductDocument {id: $source_document_id, workspace_id: $workspace_id})
                FOREACH (_ IN CASE WHEN doc IS NULL THEN [] ELSE [1] END |
                  MERGE (result)-[:EVIDENCED_BY {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(doc)
                )
                WITH result
                OPTIONAL MATCH (claim:Claim {id: $claim_id, workspace_id: $workspace_id})-[:HAS_ANCHOR]->(:ContextAnchor)-[:SELECTED_FOR_PLAN]->(:CUPlanItem)-[:JUDGED_AS]->(judgment:LLMJudgment)
                FOREACH (_ IN CASE WHEN judgment IS NULL THEN [] ELSE [1] END |
                  MERGE (result)-[:SUPPORTS_JUDGMENT {workspace_id: $workspace_id, review_run_id: $review_run_id, source: $source}]->(judgment)
                )
                """,
                workspace_id=review_input.workspace_id,
                review_run_id=graph.review_run_id,
                source=SOURCE,
                comparison_id=comparison_id,
                claim_fact_id=claim_fact_id,
                product_fact_id=product_fact_id,
                source_document_id=source_document_id,
                claim_id=claim_id,
                comparison_props=neo4j_props({**common, **comparison, "id": comparison_id}),
            )


def neo4j_props(values: dict[str, object]) -> dict[str, object]:
    props: dict[str, object] = {}
    for key, value in values.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            props[key] = value
        elif isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
            props[key] = value
        else:
            props[key] = json.dumps(value, ensure_ascii=False)
    return props
