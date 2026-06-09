"""LLM-only CU judging and exception override."""

from __future__ import annotations

from typing import Any

from llm_gateway import LLMGateway
from schemas import CUPlanItem, ContextAnchor, EvidenceWindow, ExceptionReview, LLMJudgment
from utils import stable_id, to_jsonable


JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "plan_item_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["COMPLIANT", "NON_COMPLIANT", "INSUFFICIENT", "NOT_APPLICABLE"],
                    },
                    "score": {"type": "number"},
                    "why": {"type": "string"},
                    "evidence_span": {"type": "string"},
                    "used_policy_evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["plan_item_id", "verdict", "score", "why", "evidence_span", "used_policy_evidence"],
            },
        }
    },
    "required": ["judgments"],
}

EXCEPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "applies": {"type": "boolean"},
        "effect": {"type": "string", "enum": ["NONE", "DOWNGRADE_TO_REVIEW", "OVERRIDE_TO_COMPLIANT"]},
        "why": {"type": "string"},
        "closure_evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["applies", "effect", "why", "closure_evidence_ids"],
}


class LLMComplianceJudge:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def build_evidence_windows(
        self,
        *,
        review_run_id: str,
        anchors: list[ContextAnchor],
        plan: list[CUPlanItem],
    ) -> list[EvidenceWindow]:
        anchor_by_id = {anchor.anchor_id: anchor for anchor in anchors}
        windows: list[EvidenceWindow] = []
        for item in plan:
            anchor = anchor_by_id[item.anchor_id]
            windows.append(
                EvidenceWindow(
                    evidence_window_id=stable_id("evidence_window", review_run_id, item.plan_item_id),
                    plan_item_id=item.plan_item_id,
                    anchor_id=item.anchor_id,
                    facts=anchor.facts,
                    legal_evidence_ids=item.legal_evidence_ids,
                    legal_evidence_texts=item.evidence_texts,
                )
            )
        return windows

    def judge(
        self,
        *,
        review_run_id: str,
        anchors: list[ContextAnchor],
        plan: list[CUPlanItem],
        windows: list[EvidenceWindow],
    ) -> list[LLMJudgment]:
        if not plan:
            return []
        anchor_by_id = {anchor.anchor_id: anchor for anchor in anchors}
        window_by_plan_id = {window.plan_item_id: window for window in windows}
        judgments: list[LLMJudgment] = []
        for item in plan:
            anchor = anchor_by_id.get(item.anchor_id)
            if not anchor:
                continue
            window = window_by_plan_id.get(item.plan_item_id)
            payload = {
                "judgment_item": {
                    "context_anchor": to_jsonable(anchor),
                    "cu_plan_item": to_jsonable(item),
                    "evidence_window": to_jsonable(window) if window else {},
                }
            }
            result = self.llm.structured(
                name="graphcompliance_cu_judgment",
                schema=JUDGE_SCHEMA,
                system=(
                    "You are a Korean financial-ad compliance judge. Judge exactly one isolated "
                    "ContextAnchor, EvidenceWindow, and CUPlanItem. Do not use outside law, outside facts, "
                    "or any other advertising claim that is not inside this judgment_item. Prioritize explicit "
                    "contradiction. Strong implication is allowed. Never infer a violation from silence. If the "
                    "CU is unrelated to the anchor, return NOT_APPLICABLE. If the CU is related but a required "
                    "fact or document is missing from the window, return INSUFFICIENT. Do not return "
                    "INSUFFICIENT merely because there is no evidence of wrongdoing; that should usually be "
                    "NOT_APPLICABLE or COMPLIANT depending on the CU. A mitigating disclosure anchor can be "
                    "COMPLIANT for that disclosure, but it must not erase a separate risky anchor such as a "
                    "definitive guarantee, unconditional best-rate, easy-approval, or past-performance claim. "
                    "When the CU principle/subject is about unfair sales, sanctions, review procedure, or "
                    "association workflow, return NOT_APPLICABLE unless the anchor itself describes that conduct. "
                    "The evidence_span must be copied from the provided ContextAnchor span text or facts."
                ),
                user=f"[judgment_payload]\n{payload}",
            )
            for row in result["judgments"]:
                if row["plan_item_id"] != item.plan_item_id:
                    continue
                grounded = grounded_judgment_row(row, anchor)
                judgments.append(
                    LLMJudgment(
                        judgment_id=stable_id("judgment", review_run_id, grounded["plan_item_id"]),
                        plan_item_id=grounded["plan_item_id"],
                        anchor_id=item.anchor_id,
                        cu_id=item.cu_id,
                        verdict=grounded["verdict"],
                        score=float(grounded["score"]),
                        why=grounded["why"],
                        evidence_span=grounded["evidence_span"],
                        used_policy_evidence=grounded["used_policy_evidence"],
                    )
                )
        return judgments

    def review_exception(
        self,
        *,
        review_run_id: str,
        judgment: LLMJudgment,
        closure: list[dict[str, Any]],
    ) -> ExceptionReview:
        result = self.llm.structured(
            name="graphcompliance_exception_override",
            schema=EXCEPTION_SCHEMA,
            system=(
                "You are reviewing exception override for one NON_COMPLIANT CU. "
                "Use only the closure evidence. Decide whether an exception, disclosure, or reference chain "
                "inside this closure reverses or downgrades the violation. Do not invent missing evidence."
            ),
            user=f"[judgment]\n{to_jsonable(judgment)}\n\n[closure]\n{closure}",
        )
        return ExceptionReview(
            exception_review_id=stable_id("exception_review", review_run_id, judgment.judgment_id),
            judgment_id=judgment.judgment_id,
            cu_id=judgment.cu_id,
            applies=bool(result["applies"]),
            effect=result["effect"],
            why=result["why"],
            closure_evidence_ids=result["closure_evidence_ids"],
        )


def grounded_judgment_row(row: dict[str, Any], anchor: ContextAnchor) -> dict[str, Any]:
    """Reject cross-anchor evidence leakage before routing uses a judgment."""
    if row.get("verdict") == "NOT_APPLICABLE":
        return row
    evidence_span = str(row.get("evidence_span") or "").strip()
    if not evidence_span or evidence_span_belongs_to_anchor(evidence_span, anchor):
        return row
    return {
        **row,
        "verdict": "INSUFFICIENT",
        "score": min(float(row.get("score") or 0.0), 0.5),
        "why": (
            f"{row.get('why', '')} / Evidence grounding warning: evidence_span was outside this "
            "anchor's isolated evidence window, so the violation cannot be attributed to this anchor."
        ),
        "evidence_span": anchor.span.text,
    }


def evidence_span_belongs_to_anchor(evidence_span: str, anchor: ContextAnchor) -> bool:
    anchor_evidence = "\n".join([anchor.span.text, *anchor.facts])
    return evidence_span in anchor_evidence or anchor.span.text in evidence_span
