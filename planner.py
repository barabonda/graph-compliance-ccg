"""LLM reranking and CUPlan construction."""

from __future__ import annotations

from typing import Any

from llm_gateway import LLMGateway
from schemas import CUPlanItem, ContextAnchor, PolicyCandidate
from utils import stable_id


ACTIONABLE_ANCHOR_TYPES = {"claim_anchor", "risk_anchor"}


RERANK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "selected": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "anchor_id": {"type": "string"},
                    "cu_id": {"type": "string"},
                    "rerank_score": {"type": "number"},
                    "selection_reason": {"type": "string"},
                },
                "required": ["anchor_id", "cu_id", "rerank_score", "selection_reason"],
            },
        }
    },
    "required": ["selected"],
}


class LLMCUPlanner:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def plan(
        self,
        *,
        review_run_id: str,
        anchors: list[ContextAnchor],
        candidates_by_anchor: dict[str, list[PolicyCandidate]],
        per_anchor_limit: int = 5,
        total_limit: int = 20,
    ) -> list[CUPlanItem]:
        candidate_rows: list[dict[str, Any]] = []
        for anchor in anchors:
            for candidate in candidates_by_anchor.get(anchor.anchor_id, []):
                candidate_rows.append(
                    {
                        "anchor_id": anchor.anchor_id,
                        "anchor_type": anchor.anchor_type,
                        "anchor_text": anchor.span.text,
                        "anchor_facts": anchor.facts,
                        "anchor_hypernyms": [
                            {
                                "hypernym_id": h.hypernym_id,
                                "hypernym": h.hypernym,
                                "support": h.support,
                                "normalized_score": h.normalized_score,
                            }
                            for h in anchor.hypernyms
                        ],
                        "anchor_feature_set": anchor.feature_set.__dict__ if anchor.feature_set else {},
                        "candidate": compact_candidate_for_rerank(candidate),
                    }
                )
        result = self.llm.structured(
            name="graphcompliance_cuplan_rerank",
            schema=RERANK_SCHEMA,
            system=(
                "You are a cross-encoder-style reranker for Korean financial-ad compliance. "
                "Select only CUs that are materially relevant to the anchor. You are not a legal "
                "interpreter at this step; you are confirming the already retrieved and legally "
                "eligible candidate set before the judge step. Prefer active gate CUs, direct "
                "subject/constraint matches, and legal evidence that explains the anchor. "
                "Do not select CUs just because they share broad words. If an anchor is a condition, "
                "rate, fee, depositor-protection, or risk disclosure, prefer disclosure/explanation/ad "
                "regulation CUs and reject unfair-sales, sanction, procedure, or association-review CUs "
                "unless the anchor explicitly describes coercion, tie-in sales, unfair demand, review-number "
                "process, or sanction conduct. If an anchor is a definitive guarantee or unconditional "
                "benefit claim, keep the misleading-ad and explanation-duty CUs even when another anchor "
                "contains a mitigating disclosure. The candidate.cu_legal_element_profile is the primary "
                "eligibility contract: do not select candidates whose required legal elements are missing. "
                "Respect candidate.gate_status and retrieval_scores.scope_gate; suppressed candidates must "
                "not be revived. selection_reason must cite the matched_required_features, source_article, "
                "and the concrete anchor fact/span that made the CU relevant."
            ),
            user=(
                f"Select at most {per_anchor_limit} CUs per anchor and {total_limit} total.\n"
                f"[candidate_rows]\n{candidate_rows}"
            ),
        ) if candidate_rows else {"selected": []}
        candidates = {
            (anchor_id, candidate.cu_id): candidate
            for anchor_id, items in candidates_by_anchor.items()
            for candidate in items
        }
        selected: list[CUPlanItem] = []
        per_anchor_counts: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for item in sorted(result["selected"], key=lambda row: float(row["rerank_score"]), reverse=True):
            key = (item["anchor_id"], item["cu_id"])
            if key in seen or key not in candidates:
                continue
            if per_anchor_counts.get(item["anchor_id"], 0) >= per_anchor_limit:
                continue
            if len(selected) >= total_limit:
                break
            seen.add(key)
            per_anchor_counts[item["anchor_id"]] = per_anchor_counts.get(item["anchor_id"], 0) + 1
            candidate = candidates[key]
            selected.append(plan_item_from_candidate(review_run_id, item["anchor_id"], candidate, float(item["rerank_score"]), item["selection_reason"]))
        selected = ensure_actionable_anchors_have_plan_items(
            review_run_id=review_run_id,
            anchors=anchors,
            candidates_by_anchor=candidates_by_anchor,
            selected=selected,
            per_anchor_counts=per_anchor_counts,
            total_limit=total_limit,
        )
        return selected


def ensure_actionable_anchors_have_plan_items(
    *,
    review_run_id: str,
    anchors: list[ContextAnchor],
    candidates_by_anchor: dict[str, list[PolicyCandidate]],
    selected: list[CUPlanItem],
    per_anchor_counts: dict[str, int],
    total_limit: int,
) -> list[CUPlanItem]:
    selected_keys = {(item.anchor_id, item.cu_id) for item in selected}
    for anchor in anchors:
        if anchor.anchor_type not in ACTIONABLE_ANCHOR_TYPES:
            continue
        if per_anchor_counts.get(anchor.anchor_id, 0) > 0:
            continue
        candidates = candidates_by_anchor.get(anchor.anchor_id, [])
        if not candidates or len(selected) >= total_limit:
            continue
        legally_matched = [candidate for candidate in candidates if candidate.legal_element_match]
        if not legally_matched:
            continue
        candidate = max(legally_matched, key=lambda item: item.retrieval_scores.get("combined_score", 0.0))
        key = (anchor.anchor_id, candidate.cu_id)
        if key in selected_keys:
            continue
        selected.append(
            plan_item_from_candidate(
                review_run_id,
                anchor.anchor_id,
                candidate,
                candidate.retrieval_scores.get("combined_score", 0.0),
                "Highest legal-element-matched retrieval candidate retained so the actionable anchor is judged instead of becoming CUPlan 0.",
            )
        )
        selected_keys.add(key)
        per_anchor_counts[anchor.anchor_id] = 1
    return selected


def compact_candidate_for_rerank(candidate: PolicyCandidate) -> dict[str, Any]:
    return {
        "cu_id": candidate.cu_id,
        "principle": candidate.principle,
        "subject": candidate.subject,
        "condition": candidate.condition,
        "constraint": candidate.constraint,
        "context": candidate.context,
        "cu_type": candidate.cu_type,
        "source_article": candidate.source_article,
        "active_for_gate": candidate.active_for_gate,
        "gate_status": candidate.gate_status,
        "retrieval_basis": candidate.retrieval_basis,
        "matched_hypernym_ids": candidate.matched_hypernym_ids[:8],
        "legal_evidence_ids": candidate.legal_evidence_ids[:8],
        "evidence_snippets": [shorten_evidence(text, 360) for text in candidate.evidence_texts[:4]],
        "retrieval_scores": candidate.retrieval_scores,
        "cu_legal_element_profile": candidate.legal_element_profile.__dict__ if candidate.legal_element_profile else {},
        "matched_required_features": candidate.matched_required_features,
        "missing_required_features": candidate.missing_required_features,
        "legal_element_match": candidate.legal_element_match,
        "risk_title": candidate.risk_title,
    }


def shorten_evidence(text: str, max_chars: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"


def plan_item_from_candidate(
    review_run_id: str,
    anchor_id: str,
    candidate: PolicyCandidate,
    rerank_score: float,
    selection_reason: str,
) -> CUPlanItem:
    return CUPlanItem(
        plan_item_id=stable_id("cuplan_item", review_run_id, anchor_id, candidate.cu_id),
        anchor_id=anchor_id,
        cu_id=candidate.cu_id,
        principle=candidate.principle,
        source_article=candidate.source_article,
        subject=candidate.subject,
        condition=candidate.condition,
        constraint=candidate.constraint,
        context=candidate.context,
        legal_evidence_ids=candidate.legal_evidence_ids,
        evidence_texts=candidate.evidence_texts,
        retrieval_scores=candidate.retrieval_scores,
        rerank_score=rerank_score,
        selection_reason=selection_reason,
        retrieval_basis=candidate.retrieval_basis,
        gate_status=candidate.gate_status,
        reference_paths=candidate.reference_paths,
        legal_element_profile=candidate.legal_element_profile,
        matched_required_features=candidate.matched_required_features,
        missing_required_features=candidate.missing_required_features,
        legal_element_match=candidate.legal_element_match,
        risk_title=candidate.risk_title,
    )
