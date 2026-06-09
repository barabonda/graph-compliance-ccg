"""LLM revision suggestions for actionable CCG findings."""

from __future__ import annotations

from typing import Any

from llm_gateway import LLMGateway
from router import ACTIONABLE_ANCHOR_TYPES, effective_judgments
from schemas import ReviewGraph, ReviewInput
from utils import to_jsonable


REVISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "anchor_id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["needs_review", "revise", "reject"]},
                    "risky_text": {"type": "string"},
                    "why_problematic": {"type": "string"},
                    "required_disclosures": {"type": "array", "items": {"type": "string"}},
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                    "notes_for_reviewer": {"type": "string"},
                },
                "required": [
                    "anchor_id",
                    "severity",
                    "risky_text",
                    "why_problematic",
                    "required_disclosures",
                    "before",
                    "after",
                    "notes_for_reviewer",
                ],
            },
        }
    },
    "required": ["suggestions"],
}


class LLMRevisionSuggester:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def suggest(self, *, review_input: ReviewInput, graph: ReviewGraph) -> list[dict[str, Any]]:
        effective = effective_judgments(graph.judgments, graph.exception_reviews)
        anchor_by_id = {anchor.anchor_id: anchor for anchor in graph.anchors}
        plan_by_id = {item.plan_item_id: item for item in graph.cu_plan}
        exception_by_judgment = {review.judgment_id: review for review in graph.exception_reviews}
        risk_rows = []
        for judgment in effective:
            anchor = anchor_by_id.get(judgment.anchor_id)
            if not anchor or anchor.anchor_type not in ACTIONABLE_ANCHOR_TYPES:
                continue
            if judgment.verdict not in {"NON_COMPLIANT", "INSUFFICIENT"}:
                continue
            plan = plan_by_id.get(judgment.plan_item_id)
            risk_rows.append(
                {
                    "anchor": to_jsonable(anchor),
                    "effective_judgment": to_jsonable(judgment),
                    "cu_plan_item": to_jsonable(plan) if plan else None,
                    "exception_review": to_jsonable(exception_by_judgment.get(judgment.judgment_id)),
                }
            )
        if not risk_rows:
            return []

        result = self.llm.structured(
            name="graphcompliance_revision_suggestions",
            schema=REVISION_SCHEMA,
            system=(
                "You write Korean financial-ad compliance revision suggestions. "
                "Use only the provided original ad text, actionable anchor, effective judgment, CUPlanItem, "
                "and exception review. Do not cite outside law. Do not revise product names or scope anchors. "
                "Preserve accurate required disclosures when they mitigate risk. Return practical marketer-facing copy."
            ),
            user=(
                "[original_ad]\n"
                f"{review_input.content_text}\n\n"
                "[risk_rows]\n"
                f"{risk_rows}"
            ),
        )
        allowed_anchor_ids = {row["anchor"]["anchor_id"] for row in risk_rows}
        return [
            suggestion
            for suggestion in result["suggestions"]
            if suggestion.get("anchor_id") in allowed_anchor_ids
        ]
