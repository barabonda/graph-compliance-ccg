"""LLM revision suggestions for actionable CCG findings."""

from __future__ import annotations

import re
from typing import Any

from llm_gateway import LLMGateway
from router import ACTIONABLE_ANCHOR_TYPES, anchor_display_role, effective_judgments
from schemas import ReviewGraph, ReviewInput
from utils import to_jsonable, uses_korean_law_context

# 비-KR 관할 언어 규칙 — judge.py NON_KR_LAW_OVERRIDE(kunwoo)와 같은 append 패턴.
# KR 워크스페이스에서는 붙지 않으므로 KR 프롬프트는 바이트 단위로 동일하다.
NON_KR_LANGUAGE_OVERRIDE = (
    "\nAD LANGUAGE (non-Korean jurisdiction, English-first): every `after` MUST be written in the "
    "SAME language as the original ad (English ad → English replacement copy; Khmer ad → Khmer). "
    "NEVER translate or rewrite the ad into Korean. Write `why_problematic` and "
    "`notes_for_reviewer` in ENGLISH as well — no Korean anywhere in the output."
)


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
    """광고 카피가 아니라 심사자 조언/지시문인지 판별(교체 span 검증용)."""
    stripped = text.strip().rstrip(".。!! ")
    if stripped.endswith(INSTRUCTION_ENDINGS):
        return True
    return any(marker in stripped for marker in INSTRUCTION_MARKERS)


# ── 교정본(integrated_revision) 무결성 검증 ──────────────────────────────────
# 핵심: 교정본 자리에 '수정 제안/조언'이나 '미수정 no-op'이 들어가는 것을 구조적으로
# 막는다. per-span `after`와 달리 교정본은 광고 문장이므로 CTA(가입하세요)는 허용하되,
# 편집 지시("함께 표시", "추가하"), 제안 목록(불릿/화살표), 조각, 공백만 다른 동일본을
# 거부한다. 검증 실패 시 문서를 첨부하지 않는다(억지 교정본보다 미생성이 안전).
DOC_MIN_LENGTH_RATIO = 0.6        # 교정본은 원문의 최소 60% 길이(조각 거부)
DOC_MIN_WORD_OVERLAP = 0.3        # 원문 단어 보존율 최소(무관·조언 텍스트 거부)
DOC_MAX_ADVICE_LINE_RATIO = 0.5   # 편집 지시·불릿이 과반이면 문서가 아님


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _looks_like_reviewer_advice(line: str) -> bool:
    """광고 카피엔 안 나오는 '편집 지시' 표지. CTA(가입하세요)는 제외하기 위해
    INSTRUCTION_ENDINGS가 아니라 메타-지시 마커만 본다."""
    return any(marker in line for marker in INSTRUCTION_MARKERS)


def _word_overlap(corrected: str, original: str) -> float:
    """원문 단어가 교정본에 얼마나 보존됐는지(0~1). 조각·조언이면 낮다."""
    orig_words = {w for w in re.split(r"[\s.,!?·…()/]+", original) if len(w) >= 2}
    if not orig_words:
        return 1.0
    corrected_norm = _normalize_ws(corrected)
    kept = sum(1 for w in orig_words if w in corrected_norm)
    return kept / len(orig_words)


def validate_integrated_revision(integrated: str, original: str) -> str | None:
    """integrated_revision이 '진짜 전체 교정본'인지 검증. 아니면 None(문서 미첨부).

    거부 대상: ① 공백만 다른 미수정본(no-op), ② 편집 지시/조언이 과반인 텍스트,
    ③ 제안 목록(불릿/화살표), ④ 원문 대비 너무 짧은 조각, ⑤ 원문 보존율이 낮은
    무관 텍스트. 광고 CTA(가입하세요 등)는 정상으로 통과시킨다.
    """
    doc = (integrated or "").strip()
    original = (original or "").strip()
    if not doc:
        return None
    # ① 공백만 다른 사실상 동일본(위반 미수정 no-op) 거부.
    if _normalize_ws(doc) == _normalize_ws(original):
        return None
    lines = [ln.strip() for ln in doc.splitlines() if ln.strip()]
    if lines:
        # ② 편집 지시/조언이 과반이면 문서가 아님.
        advice_lines = sum(1 for ln in lines if _looks_like_reviewer_advice(ln))
        if advice_lines / len(lines) > DOC_MAX_ADVICE_LINE_RATIO:
            return None
        # ③ 제안 목록(불릿/화살표) 형태 거부.
        listish = sum(1 for ln in lines if re.match(r"^[-*•·▶]\s", ln) or "→" in ln or "->" in ln)
        if listish / len(lines) > DOC_MAX_ADVICE_LINE_RATIO:
            return None
    # ④ 길이 sanity: 조각 거부(전체 재작성은 원문 상당부분 유지·확장).
    if original and len(doc) < DOC_MIN_LENGTH_RATIO * len(original):
        return None
    # ⑤ 보존성: 원문 단어 보존율이 너무 낮으면 무관 텍스트(조언 등).
    if original and _word_overlap(doc, original) < DOC_MIN_WORD_OVERLAP:
        return None
    return doc


def revision_context(graph: Any) -> dict[str, Any]:
    """교정본 재작성에 필요한 '전체 맥락' — 누락 필수고지, Track B 전체 인상,
    상품문서 사실 모순. risky span만으로는 못 고치는 부분을 LLM에 함께 준다."""
    pfc = getattr(graph, "product_fact_context", {}) or {}
    checks = pfc.get("disclosure_checks") or []
    # '누락'은 gate_status==ON(상품군·채널 적용범위 내)이면서 부재인 것만. 적용범위 밖
    # (OFF)인 고지를 누락으로 오인하면 예금 광고에 대출·투자 고지를 들이대게 된다.
    missing = [
        {"label": c.get("label"), "source": c.get("source"), "in_product_doc": bool(c.get("in_product_doc"))}
        for c in checks
        if _gate_on(c) and not c.get("present")
    ]
    track_b_raw = getattr(graph, "overall_impression_judgment", {}) or {}
    overall = None
    if str(track_b_raw.get("verdict") or "").upper() in {"MEDIUM", "HIGH"}:
        overall = {
            "verdict": track_b_raw.get("verdict"),
            "representative_consumer_impression": track_b_raw.get("representative_consumer_impression"),
            "misleading_factors": track_b_raw.get("misleading_factors"),
        }
    contradictions = [
        {"status": c.get("status"), "rationale": c.get("rationale")}
        for c in (pfc.get("comparison_results") or [])
        if c.get("status") in {"CONTRADICTED", "CONDITION_MISSING"}
    ]
    return {
        "missing_disclosures": missing,
        "overall_impression": overall,
        "fact_contradictions": contradictions,
    }


# ── 하단 고지 블록 ('꼭 확인해 주세요') ──────────────────────────────────────
# 실제 광고는 약관·유의사항을 본문 중간이 아니라 하단 불릿 블록으로 모은다. 누락
# 고지는 '문장에 끼워넣기'가 아니라 이 블록에 한 줄씩 추가한다. 문구는 상품별 숫자가
# 아닌 보일러플레이트 규제 문장이라 할루시네이션 위험이 없다. 심의필 번호처럼 상품별
# 값이 필요한 고지는 자동 생성하지 않고 심사자 보완 항목으로 둔다.
DISCLOSURE_BLOCK_ANCHOR = "__disclosure_block__"


def _gate_on(check: dict[str, Any]) -> bool:
    """고지가 이 광고의 상품군·채널 적용범위 안인지(gate_status==ON). 필드가 없으면
    보수적으로 ON 취급(구버전 데이터 호환)."""
    return str(check.get("gate_status") or "ON").upper() == "ON"

DISCLOSURE_NOTICE_TEXT: dict[str, str] = {
    "disc_depositor_protection_notice": "이 예금은 예금자보호법에 따라 원금과 소정의 이자를 합하여 1인당 최고 1억원까지(본 은행의 여타 보호상품과 합산) 보호됩니다.",
    "disc_variable_rate_notice": "시장 상황에 따라 기본이율 및 우대이율이 변경될 수 있습니다.",
    "disc_interest_condition": "우대금리는 우대조건을 충족하고 만기해지하는 경우에 한해 제공되며, 기본금리와 적용 조건이 다를 수 있습니다.",
    "disc_tax_and_after_tax_notice": "표시된 이율 및 이자는 세전 기준이며, 이자소득에 대해 관련 세금이 부과됩니다.",
    "disc_product_terms_notice": "계약을 체결하기 전에 상품설명서 및 약관을 반드시 읽어보시기 바랍니다.",
    "disc_overdue_interest_rate": "만기 전 해지할 경우 약정한 이율보다 낮은 중도해지 이율이 적용됩니다.",
    "disc_early_repayment_fee": "중도상환 시 중도상환수수료가 부과될 수 있습니다.",
    "disc_loan_conditions": "대출 자격·한도·금리는 심사 결과에 따라 달라지며, 일부 고객은 이용이 제한될 수 있습니다.",
    "disc_credit_score_impact": "대출 거래 내용은 신용평점에 영향을 줄 수 있습니다.",
    "disc_principal_loss_notice": "이 상품은 예금자보호 대상이 아니며, 운용 결과에 따라 원금 손실이 발생할 수 있습니다.",
    "disc_past_performance_disclaimer": "과거의 운용실적이 미래의 수익률을 보장하지 않습니다.",
    "disc_risk_grade": "투자위험등급 등 상품 위험을 확인한 뒤 투자 여부를 결정하시기 바랍니다.",
    "disc_fee_notice": "선취·후취 수수료 및 보수 등 비용이 부과될 수 있습니다.",
    "disc_product_terms": "계약을 체결하기 전에 상품설명서 및 약관을 반드시 읽어보시기 바랍니다.",
}
# 상품별 값(심의필 번호·판매업자 명칭 등)이 필요해 자동 문구를 만들 수 없는 고지.
DISCLOSURE_ADVISORY_ONLY = {"disc_review_approval_notice", "disc_seller_name"}


def build_disclosure_block(graph: Any) -> list[dict[str, Any]]:
    """광고 하단 고지 블록에 '추가'해야 할 항목(이미 있는 present 고지는 제외).

    실제 광고처럼 고지가 다 있으면 빈 리스트 → 교정본에 추가할 것이 없다. 자동 문구가
    없는 고지(심의필 번호 등)는 status='reviewer'로 심사자 보완을 표시(할루시네이션 방지).
    """
    pfc = getattr(graph, "product_fact_context", {}) or {}
    checks = pfc.get("disclosure_checks") or []
    block: list[dict[str, Any]] = []
    for check in checks:
        # 적용범위 밖(상품군/채널 OFF)이거나 이미 있는 고지는 제외.
        if not _gate_on(check) or check.get("present"):
            continue
        cid = str(check.get("check_id") or "")
        label = str(check.get("label") or "")
        text = DISCLOSURE_NOTICE_TEXT.get(cid)
        if text:
            block.append({"check_id": cid, "label": label, "status": "add", "text": text})
        else:
            block.append({"check_id": cid, "label": label, "status": "reviewer", "text": ""})
    return block


def render_disclosure_block(block: list[dict[str, Any]]) -> str:
    """추가 가능한 표준 고지를 '꼭 확인해 주세요' 하단 불릿 블록 문자열로."""
    addable = [b for b in block if b.get("status") == "add" and b.get("text")]
    if not addable:
        return ""
    return "\n".join(["꼭 확인해 주세요!", *[f"ㆍ{b['text']}" for b in addable]])

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
            # 확정된 위반(NON_COMPLIANT)만 수정안을 만든다. INSUFFICIENT(판단 불가)는
            # 위반이 아니므로 '수정 후보'를 만들지 않는다 — 중립·적법 고지(가입대상·이율
            # 기준 등)에 단정·보장 위반 카드를 억지로 붙이는 과판정을 막는다.
            if judgment.verdict != "NON_COMPLIANT":
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
        context = revision_context(graph)
        # 교정본은 per-span 위반이 없어도 '누락 고지'나 'Track B 전체 인상'만 있으면
        # 생성해야 한다(흩어진 맥락은 span 단위로 안 잡힘).
        needs_revision = (
            bool(risk_rows)
            or bool(context["missing_disclosures"])
            or context["overall_impression"] is not None
        )
        if not needs_revision:
            return []

        result = self.llm.structured(
            name="graphcompliance_revision_suggestions",
            schema=REVISION_SCHEMA,
            system=(
                "You write Korean financial-ad compliance revision suggestions. "
                "Use only the provided original ad text, actionable anchors, effective judgments, CUPlanItems, "
                "exception reviews, and the revision_context (missing disclosures, overall impression, product-fact "
                "contradictions). Do not cite outside law. Do not revise product names or scope anchors. "
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
                "DISCLOSURES ARE HANDLED SEPARATELY: do NOT insert required-disclosure sentences into `after`. Each "
                "`after` fixes ONLY the risky wording in place (e.g. tone down '확정·보장·조건 없이·누구나' into accurate, "
                "qualified copy), preserving the ad's structure, numbers, and tables. Required disclosures are added "
                "to a separate bottom notice block by the system, not by you, so never append 고지/유의사항 to a span.\n"
                "`integrated_revision` is unused by the pipeline; you may return the original text. Focus on precise, "
                "structure-preserving per-span `after` copy."
                + ("" if uses_korean_law_context(review_input.workspace_id) else NON_KR_LANGUAGE_OVERRIDE)
            ),
            user=(
                "[original_ad]\n"
                f"{review_input.content_text}\n\n"
                "[risk_rows]\n"
                f"{risk_rows}\n\n"
                "[revision_context] (전체 맥락 — 반드시 교정본에 반영)\n"
                f"{context}"
            ),
        )
        anchor_text_by_id = {row["anchor"]["anchor_id"]: row["anchor"]["span"]["text"] for row in risk_rows}
        usable = [
            suggestion
            for suggestion in result["suggestions"]
            if suggestion_is_usable(suggestion, anchor_text_by_id)
        ]
        if not usable and risk_rows:
            usable = fallback_suggestions(risk_rows, korean=uses_korean_law_context(review_input.workspace_id))
        # 교정본 구조: (본문) per-span 제안을 원문 제자리에 적용해 구조·숫자·심의필을 보존
        # + (하단) 고지를 문장에 끼우지 않고 '꼭 확인해 주세요' 블록으로 모은다. 적용범위
        # (gate ON) 내 누락 고지만 표준 문구로 추가하고, 자동 생성 불가 고지(심의필 번호 등)는
        # 심사자 보완으로 표시. inline 전체 재작성(integrated_revision)은 폐기.
        block = build_disclosure_block(graph)
        block_text = render_disclosure_block(block)
        reviewer_items = [b for b in block if b.get("status") == "reviewer"]
        if block_text or reviewer_items:
            usable.append(
                {
                    "anchor_id": DISCLOSURE_BLOCK_ANCHOR,
                    "severity": "revise",
                    "risky_text": "",
                    "why_problematic": "",
                    "required_disclosures": [b["label"] for b in block],
                    "before": "",
                    "after": block_text,
                    "notes_for_reviewer": (
                        "광고 하단 '꼭 확인해 주세요' 고지 블록에 위 항목을 반영하세요."
                        + (" 심의필 번호·판매업자 명칭 등 상품별 정보는 심사자가 보완합니다." if reviewer_items else "")
                    ),
                    "disclosure_block": block,
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


def fallback_suggestions(risk_rows: list[dict[str, Any]], korean: bool = True) -> list[dict[str, Any]]:
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
                "why_problematic": (
                    "근거와 조건을 함께 제시하지 않으면 소비자 오인 가능성이 있습니다."
                    if korean
                    else "Without the underlying conditions and evidence, this wording may mislead consumers."
                ),
                "required_disclosures": (
                    ["적용 조건, 위험, 수수료, 상품설명서 확인 문구"]
                    if korean
                    else ["Applicable conditions, risks, fees, and a reference to the product terms"]
                ),
                "before": span,
                # after 는 광고 문안 자체이므로 관할 언어를 따른다(비-KR은 영어 메인).
                # 위험/수정 이유·검토 노트는 한국 준법감시인용이라 한국어 유지.
                "after": (
                    "상품의 적용 조건과 유의사항을 확인한 뒤 가입 여부를 결정할 수 있습니다."
                    if korean
                    else "Please review the product's terms, conditions and key notices before deciding to apply."
                ),
                "notes_for_reviewer": (
                    "LLM 수정안이 필터링되어 안전한 기본 교정안을 제시했습니다."
                    if korean
                    else "The model's suggestions were filtered out; a safe default correction is provided."
                ),
            }
        )
    return suggestions
