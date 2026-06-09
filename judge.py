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
        payload = {
            "anchors": to_jsonable(anchors),
            "cu_plan": to_jsonable(plan),
            "evidence_windows": to_jsonable(windows),
        }
        result = self.llm.structured(
            name="graphcompliance_cu_judgment",
            schema=JUDGE_SCHEMA,
            system=(
                "You are a Korean financial-ad compliance judge. Judge only with the provided "
                "ContextAnchor, EvidenceWindow, and CUPlanItem. Do not use outside law or outside facts. "
                "Prioritize explicit contradiction. Strong implication is allowed. Never infer a violation "
                "from silence. If the CU is unrelated to the anchor, return NOT_APPLICABLE. If the CU is "
                "related but a required fact or document is missing from the window, return INSUFFICIENT. "
                "Do not return INSUFFICIENT merely because there is no evidence of wrongdoing; that should "
                "usually be NOT_APPLICABLE or COMPLIANT depending on the CU. A mitigating disclosure anchor "
                "can be COMPLIANT for that disclosure, but it must not erase a separate risky anchor such as "
                "a definitive guarantee, unconditional best-rate, easy-approval, or past-performance claim. "
                "When the CU principle/subject is about unfair sales, sanctions, review procedure, or "
                "association workflow, return NOT_APPLICABLE unless the anchor itself describes that conduct."
            ),
            user=f"[judgment_payload]\n{payload}",
        )
        plan_by_id = {item.plan_item_id: item for item in plan}
        judgments: list[LLMJudgment] = []
        for row in result["judgments"]:
            item = plan_by_id.get(row["plan_item_id"])
            if not item:
                continue
            judgments.append(
                LLMJudgment(
                    judgment_id=stable_id("judgment", review_run_id, row["plan_item_id"]),
                    plan_item_id=row["plan_item_id"],
                    anchor_id=item.anchor_id,
                    cu_id=item.cu_id,
                    verdict=row["verdict"],
                    score=float(row["score"]),
                    why=row["why"],
                    evidence_span=row["evidence_span"],
                    used_policy_evidence=row["used_policy_evidence"],
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
