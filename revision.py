"""LLM revision suggestions for actionable CCG findings."""

from __future__ import annotations

from typing import Any

from llm_gateway import LLMGateway
from router import ACTIONABLE_ANCHOR_TYPES, anchor_display_role, effective_judgments
from schemas import ReviewGraph, ReviewInput
from utils import to_jsonable


BROAD_CONTEXT_HYPERNYMS = {
    "광고 규제",
    "광고 준수",
    "광고 진실성",
    "광고 공정화",
    "금융소비자 보호",
    "금융상품",
}

REVISION_RISK_TERMS = {
    "보장",
    "확정",
    "원금",
    "손실",
    "수익",
    "최고",
    "최저",
    "조건 없이",
    "누구나",
    "승인",
    "무료",
    "수수료",
    "과거",
    "성과",
    "추천",
}

GENERIC_INSTRUCTION_PREFIXES = (
    "상품의 적용 조건",
    "위험 표현을 수정",
    "추가 근거",
    "필수고지를 함께 표시",
)

# `after`(교체 문안)에 조언/지시문이 새는 것을 막는다. 광고에 그대로 붙일 수 있는
# 카피가 아니라 '~하세요/병기/표시' 같은 지시면 제안이 아니라 조언이다 →
# notes_for_reviewer로 가야 하므로 after에서는 걸러낸다.
INSTRUCTION_ENDINGS = (
    "하세요",
    "하십시오",
    "해야 합니다",
    "해야 한다",
    "바랍니다",
    "권장합니다",
    "권장됩니다",
    "필요합니다",
    "표시",
    "병기",
    "기재",
)
INSTRUCTION_MARKERS = (
    "필수고지를",
    "고지를 함께",
    "조건을 함께",
    "함께 표시",
    "함께 기재",
    "유의사항을 추가",
    "다음 고지를",
    "삭제하",
    "추가하",
)


def is_instruction_like(text: str) -> bool:
    """광고 카피가 아니라 심사자 조언/지시문인지 판별."""
    stripped = text.strip().rstrip(".。!! ")
    if stripped.endswith(INSTRUCTION_ENDINGS):
        return True
    return any(marker in stripped for marker in INSTRUCTION_MARKERS)

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
        },
        "integrated_revision": {"type": "string"},
    },
    "required": ["suggestions", "integrated_revision"],
}

# 전체 교정본을 별도 항목으로 revision_suggestions 리스트에 실어 보내는 센티넬.
# (router/schema 변경 없이 기존 흐름을 통과시키기 위함. 프론트는 이 항목을
#  꺼내 원문↔교정본 문서 diff로 렌더하고, 인라인 카드에서는 제외한다.)
DOCUMENT_REVISION_ANCHOR = "__document__"


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
            if anchor_display_role(graph, anchor.anchor_id) != "actionable":
                continue
            if judgment.verdict not in {"NON_COMPLIANT", "INSUFFICIENT"}:
                continue
            if not should_generate_revision(anchor=anchor, judgment=judgment):
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
                "Use only the provided original ad text, actionable anchors, effective judgments, CUPlanItems, "
                "and exception reviews. Do not cite outside law. Do not revise product names or scope anchors. "
                "Preserve accurate required disclosures when they mitigate risk. Return practical marketer-facing copy.\n"
                "WHOLE-AD COHERENCE: you receive ALL risky spans of one ad at once, and the individual edits "
                "are assembled back into a SINGLE final ad draft. Make the edits mutually coherent — keep one "
                "consistent tone and voice across spans, do NOT repeat the same disclosure in multiple spans, "
                "and place each required disclosure once in the single most natural span. Each `after` must read "
                "naturally when all edits are applied together to form the final ad.\n"
                "SEPARATE PROPOSAL FROM ADVICE: `after` MUST be clean replacement ad copy that can be pasted "
                "directly into the ad. It must NEVER be an instruction or advisory phrasing (e.g. "
                "'조건을 함께 표시하세요', '필수고지를 병기', 'add disclosures', 'show conditions'). Put ALL reviewer "
                "guidance, rationale, and instructions in `notes_for_reviewer` ONLY. If a risky span has no clean "
                "replacement copy and only advice applies, omit that span (do not put advice in `after`).\n"
                "Create suggestions only for the risky span itself. If an anchor is merely a product launch, title, "
                "brand mention, or neutral scope sentence, omit it.\n"
                "ALSO produce `integrated_revision`: the COMPLETE ad text rewritten as ONE coherent final draft "
                "with every fix applied together. Keep ALL non-risky text VERBATIM (line breaks, sections, "
                "disclosures, hashtags) and change ONLY what the suggestions require. When a fix merges a "
                "condition into the benefit sentence, do not leave the now-duplicated original line — fold it in "
                "so the corrected document reads cleanly with no repetition. Return the full text, not a fragment."
            ),
            user=(
                "[original_ad]\n"
                f"{review_input.content_text}\n\n"
                "[risk_rows]\n"
                f"{risk_rows}"
            ),
        )
        anchor_text_by_id = {row["anchor"]["anchor_id"]: row["anchor"]["span"]["text"] for row in risk_rows}
        usable = [
            suggestion
            for suggestion in result["suggestions"]
            if suggestion_is_usable(suggestion, anchor_text_by_id)
        ]
        if not usable:
            usable = fallback_suggestions(risk_rows)
        # 전체 교정본을 센티넬 항목으로 첨부(원문과 달라야 의미 있음).
        integrated = str(result.get("integrated_revision") or "").strip()
        if integrated and integrated != review_input.content_text.strip():
            usable.append(
                {
                    "anchor_id": DOCUMENT_REVISION_ANCHOR,
                    "severity": "revise",
                    "risky_text": "",
                    "why_problematic": "",
                    "required_disclosures": [],
                    "before": review_input.content_text,
                    "after": integrated,
                    "notes_for_reviewer": "광고 전체를 일관되게 재작성한 교정본입니다.",
                }
            )
        return usable


def should_generate_revision(*, anchor: Any, judgment: Any) -> bool:
    if judgment.verdict == "NON_COMPLIANT":
        return True
    text = " ".join(
        [
            anchor.span.text,
            *anchor.facts,
            *(proposal.hypernym for proposal in anchor.hypernyms),
        ]
    )
    hypernyms = {proposal.hypernym for proposal in anchor.hypernyms}
    if hypernyms and hypernyms <= BROAD_CONTEXT_HYPERNYMS:
        return False
    return any(term in text for term in REVISION_RISK_TERMS)


def suggestion_is_usable(suggestion: dict[str, Any], anchor_text_by_id: dict[str, str]) -> bool:
    anchor_id = str(suggestion.get("anchor_id") or "")
    anchor_text = anchor_text_by_id.get(anchor_id)
    if not anchor_text:
        return False
    before = str(suggestion.get("before") or suggestion.get("risky_text") or "").strip()
    after = str(suggestion.get("after") or "").strip()
    if not after or after == before or after == anchor_text:
        return False
    if any(after.startswith(prefix) for prefix in GENERIC_INSTRUCTION_PREFIXES):
        return False
    # 조언/지시문이 교체 문안(after)으로 샌 경우는 제안에서 제외(조언은 notes로).
    if is_instruction_like(after):
        return False
    return True


def fallback_suggestions(risk_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for row in risk_rows:
        anchor = row.get("anchor") or {}
        anchor_id = str(anchor.get("anchor_id") or "")
        span = (anchor.get("span") or {}).get("text") or ""
        if not anchor_id or not span:
            continue
        suggestions.append(
            {
                "anchor_id": anchor_id,
                "severity": "revise",
                "risky_text": span,
                "why_problematic": "근거와 조건을 함께 제시하지 않으면 소비자 오인 가능성이 있습니다.",
                "required_disclosures": ["적용 조건, 위험, 수수료, 상품설명서 확인 문구"],
                "before": span,
                "after": "상품의 적용 조건과 유의사항을 확인한 뒤 가입 여부를 결정할 수 있습니다.",
                "notes_for_reviewer": "LLM 수정안이 필터링되어 안전한 기본 교정안을 제시했습니다.",
            }
        )
    return suggestions
