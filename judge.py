"""LLM-only CU judging and exception override."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from llm_gateway import LLMGateway
from schemas import CUPlanItem, Claim, ContextAnchor, ContextFrame, ContextInfluence, EvidenceWindow, ExceptionReview, InterSentenceRelation, LLMJudgment, SentenceUnit
from utils import normalize_space, stable_id, to_jsonable, uses_korean_law_context


# 비(非)한국 관할 워크스페이스에서만 judge 프롬프트에 덧붙이는 오버라이드.
# 위 legal_basis 지침의 한국법 예시(금소법·시행령·감독규정·심의기준, 위임 사슬)를
# 무효화하고, 각 항목의 실제 source_article(해당 관할 조문)만 인용하게 한다.
# 한국 워크스페이스에서는 append되지 않으므로 프롬프트가 바이트 단위로 동일하다.
NON_KR_LAW_OVERRIDE = (
    "\n[관할 우선 규칙] 이 심사 대상은 한국이 아닌 관할의 워크스페이스입니다. legal_basis와 "
    "conclusion에는 각 항목의 cu_plan_item.source_article에 명시된 해당 관할의 조문만 인용하세요. "
    "위 1)에 예시로 든 한국 법령(금융소비자보호법·시행령·감독규정·금융광고 심의기준)과 "
    "'법률→시행령→감독규정→심의기준' 위임 사슬은 이 관할에 적용되지 않으므로 절대 인용하지 마세요. "
    "evidence에 제시되지 않은 외부 법령을 만들어내지 마세요."
    "\nOUTPUT LANGUAGE OVERRIDE: this jurisdiction's reviews are English-first. The earlier rule "
    "'모든 산출 텍스트는 한국어' does NOT apply here — write ALL free-text output fields "
    "(legal_basis, finding, conclusion, reservation, why, disclosure suggestions) in ENGLISH. "
    "Use plain compliance English instead of verdict enums (say 'violation', 'insufficient "
    "grounds', 'compliant'). evidence_span stays a verbatim copy of the original ad text."
)


# 규칙기반 행위요건(positive_feature) 코드 → 심사원이 읽는 한국어 요건명.
FEATURE_KO: dict[str, str] = {
    "universal_scope_expression": "대상 무제한 표현(누구나·전 고객)",
    "unconditional_expression": "조건 없음 표현",
    "certainty_expression": "단정·확정 표현",
    "guarantee_expression": "보장 표현",
    "benefit_claim_expression": "혜택 강조 표현",
    "risk_downplay_expression": "위험 축소 표현",
    "past_performance_claim": "과거실적·미래수익 암시",
    "comparison_target": "비교 대상 제시",
    "comparative_superiority_claim": "우위·최상급 표현",
    "coercion_or_tie_in_context": "강요·끼워팔기 정황",
    "product_fact_assertion": "상품사실 단정",
    "sales_process_context": "판매과정 관여 정황",
}

# 비-KR(영어 우선) 워크스페이스용 영어 요건명 — 판정 산출물(criteria_findings의
# criterion)에 그대로 노출되므로, KH 심사에서 한국어 요건명이 새지 않게 한다.
FEATURE_EN: dict[str, str] = {
    "universal_scope_expression": "Unlimited-audience expression (anyone / all customers)",
    "unconditional_expression": "No-conditions expression",
    "certainty_expression": "Definitive / certainty expression",
    "guarantee_expression": "Guarantee expression",
    "benefit_claim_expression": "Benefit emphasis expression",
    "risk_downplay_expression": "Risk-downplaying expression",
    "past_performance_claim": "Past-performance / future-return implication",
    "comparison_target": "Comparison target presented",
    "comparative_superiority_claim": "Superiority / superlative claim",
    "coercion_or_tie_in_context": "Coercion or tie-in context",
    "product_fact_assertion": "Definitive product-fact assertion",
    "sales_process_context": "Sales-process involvement context",
}


def feature_ko(feature: str) -> str:
    return FEATURE_KO.get(feature, feature)


def feature_label(feature: str, *, korean: bool = True) -> str:
    if korean:
        return FEATURE_KO.get(feature, feature)
    return FEATURE_EN.get(feature, feature)


_REGULATOR_GROUNDING_PATH = Path(__file__).resolve().parent / "eval" / "regulator_grounding.jsonl"


@lru_cache(maxsize=1)
def regulator_precedents_block() -> str:
    """금융위·금감원 가이드라인의 지적사례/해석을 판정 few-shot 근거로 제공.

    특히 명시 표현(누구나/무조건)이 없어도 함의로 오인을 유발하면 위반이라는
    규제당국 해석을 판단자가 참고하도록 한다. 파일이 없으면 빈 문자열(무해).
    """
    try:
        rows = [json.loads(line) for line in _REGULATOR_GROUNDING_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:  # noqa: BLE001
        return ""
    lines: list[str] = []
    for row in rows:
        arts = row.get("articles") or []
        head = arts[0] if arts else row.get("rule", "")
        interp = row.get("regulator_interpretation", "")
        viol = (row.get("violation_example") or {}).get("ad", "")
        lines.append(f"- [{head}] {row.get('requirement','')} / 규제당국 해석: {interp}" + (f" / 위반 예시: \"{viol}\"" if viol else ""))
    if not lines:
        return ""
    return (
        "\n[규제당국 지적사례·해석 (금융위·금감원 금융광고규제 가이드라인)]\n"
        "아래는 규제당국이 실제로 위법/미흡으로 본 사례와 그 해석이다. 판단 시 참고하되, 특히 "
        "'누구나/무조건' 같은 명시 표현이 없어도 문안의 함의가 조건 없이 누구에게나 적용되는 것으로 "
        "오인하게 하면 위반으로 본다는 해석을 적용하라. 중요: 이렇게 광고가 스스로 조건을 밝히지 않은 채 "
        "'심사·자격 없이 누구나/얼마까지 받는다'는 인상을 적극적으로 유발하는 경우는 정보가 부족한 것이 "
        "아니라 '적극적 오인 유발'이므로, 판정을 '근거 부족'으로 회피하지 말고 '위반'으로 분류하라. "
        "('근거 부족'은 광고가 스스로 조건·유보를 밝혀 침묵에 해당할 때로 한정한다.) "
        "다만 각 항목은 여전히 해당 광고 사실에 근거해 판단한다.\n"
        + "\n".join(lines)
    )


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
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    # 적용 법리: 이 CU/조문이 금지(또는 요구)하는 행위의 정의를 한 문장으로.
                    "legal_basis": {"type": "string"},
                    # 판단 기준별 적용: 규칙기반으로 제시된 각 요건(criterion)에 대해,
                    # 이 광고의 어느 표현/사실이 왜 그 요건을 충족/불충족하는지.
                    "criteria_findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "criterion": {"type": "string"},
                                "satisfied": {"type": "boolean"},
                                "finding": {"type": "string"},
                            },
                            "required": ["criterion", "satisfied", "finding"],
                        },
                    },
                    # 결론: 요건 적용을 종합한 판단 근거(왜 이 verdict인지).
                    "conclusion": {"type": "string"},
                    # 유보: 구체적 사실관계/추가 고지에 따라 달라질 수 있는 한계.
                    "reservation": {"type": "string"},
                    "evidence_span": {"type": "string"},
                    "used_policy_evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "plan_item_id",
                    "verdict",
                    "score",
                    "legal_basis",
                    "criteria_findings",
                    "conclusion",
                    "reservation",
                    "evidence_span",
                    "used_policy_evidence",
                ],
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
        claims: list[Claim] | None = None,
        context_frame: ContextFrame | None = None,
        sentence_units: list[SentenceUnit] | None = None,
        context_influences: list[ContextInfluence] | None = None,
        inter_sentence_relations: list[InterSentenceRelation] | None = None,
        policy_evidence_chains: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[EvidenceWindow]:
        anchor_by_id = {anchor.anchor_id: anchor for anchor in anchors}
        claim_by_id = {claim.claim_id: claim for claim in claims or []}
        sentence_by_id = {sentence.sentence_id: sentence for sentence in sentence_units or []}
        windows: list[EvidenceWindow] = []
        for item in plan:
            anchor = anchor_by_id[item.anchor_id]
            claim = claim_by_id.get(anchor.claim_id)
            sentence = sentence_by_id.get(claim.sentence_id) if claim and claim.sentence_id else None
            related_sentences = build_related_sentences(
                sentence_id=claim.sentence_id if claim else "",
                relations=inter_sentence_relations or [],
                sentence_by_id=sentence_by_id,
            )
            related_influences = [
                influence
                for influence in context_influences or []
                if (
                    influence.source_id in {anchor.claim_id, claim.sentence_id if claim else ""}
                    or influence.target_id in {anchor.claim_id, claim.sentence_id if claim else ""}
                )
            ]
            windows.append(
                EvidenceWindow(
                    evidence_window_id=stable_id("evidence_window", review_run_id, item.plan_item_id),
                    plan_item_id=item.plan_item_id,
                    anchor_id=item.anchor_id,
                    facts=anchor.facts,
                    legal_evidence_ids=item.legal_evidence_ids,
                    legal_evidence_texts=item.evidence_texts,
                    context_frame=to_jsonable(context_frame) if context_frame else {},
                    sentence_unit=to_jsonable(sentence) if sentence else {},
                    related_sentences=related_sentences,
                    context_influences=to_jsonable(related_influences),
                    policy_evidence_chains=chains_for_plan_item(policy_evidence_chains or {}, item.plan_item_id),
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
        product_fact_signals: dict[str, list[dict[str, Any]]] | None = None,
        workspace_id: str = "",
    ) -> list[LLMJudgment]:
        if not plan:
            return []
        korean = uses_korean_law_context(workspace_id)
        anchor_by_id = {anchor.anchor_id: anchor for anchor in anchors}
        window_by_plan_id = {window.plan_item_id: window for window in windows}
        judgment_items = []
        item_by_plan_id: dict[str, CUPlanItem] = {}
        anchor_by_plan_id: dict[str, ContextAnchor] = {}
        judgments: list[LLMJudgment] = []
        for item in plan:
            anchor = anchor_by_id.get(item.anchor_id)
            if not anchor:
                # Coverage guarantee: never drop a CUPlan item silently.
                judgments.append(missing_judgment(review_run_id, item, reason="anchor", korean=korean))
                continue
            window = window_by_plan_id.get(item.plan_item_id)
            item_by_plan_id[item.plan_item_id] = item
            anchor_by_plan_id[item.plan_item_id] = anchor
            judgment_items.append(
                {
                    "context_anchor": to_jsonable(anchor),
                    "cu_plan_item": to_jsonable(item),
                    # 규칙기반 판단 레이어를 명시적으로 제시 — LLM은 이 요건들에
                    # 사실을 적용해 설명을 '종합'한다(처음부터 판단하지 않는다).
                    "legal_test": build_legal_test(item, anchor, korean=korean),
                    # 상품문서 대조 신호: 광고 주장 ↔ 약관/상품설명서 사실의 모순.
                    "product_fact_signals": (product_fact_signals or {}).get(item.anchor_id, []),
                    "evidence_window": to_jsonable(window) if window else {},
                }
            )
        if not judgment_items:
            return judgments
        result = self.llm.structured(
            name="graphcompliance_cu_judgment",
            schema=JUDGE_SCHEMA,
            system=(
                "당신은 한국 금융광고 준법 심사 판단자입니다. 금융감독원 법령해석 회답과 같은 방식으로, "
                "규칙기반으로 제시된 법적 요건에 광고 사실을 적용해 '설명가능한 판단'을 종합합니다. "
                "각 judgment_items 항목은 독립된 ContextAnchor·EvidenceWindow·CUPlanItem이며, 그 안의 "
                "legal_test가 규칙기반 판단 레이어입니다. 항목마다 독립적으로 판단하고, 외부 법·외부 사실·"
                "다른 항목의 광고 문구를 증거로 쓰지 마세요.\n"
                "각 항목에 대해 다음을 산출하세요:\n"
                "1) legal_basis: 금감원 법령해석 회답의 '이유'처럼, 근거 조문을 명시하여 이 기준이 금지(또는 "
                "요구)하는 행위가 무엇인지 한 문장으로. cu_plan_item.source_article와 evidence_window의 위임 "
                "사슬(법률→시행령→감독규정→심의기준)을 인용하세요. 증거에 '은행 광고심의 기준' 원문이 포함되어 있으면 legal_basis 에 병기하세요(법령이 대표 근거, 심의기준은 '및 은행 광고심의 기준 제N조' 형태의 병기 — 법령 요건 불성립인데 심의기준만 걸리면 심의기준을 대표로 하되 '법령 위반이 아닌 심의기준 미흡'임을 명시). (예: '금융소비자보호법 시행령 제20조 제1항 "
                "제4호는 광고 시 불확실한 사항에 대해 단정적 판단을 제공하거나 확실하다고 오인하게 할 소지가 있는 "
                "내용을 알리는 행위를 금지한다')\n"
                "2) criteria_findings: legal_test.required_elements의 '모든' 요건(criterion)을 빠짐없이 다루세요. "
                "충족 요건은 satisfied=true와 함께 이 광고의 어느 표현/사실(legal_test.matched_facts, "
                "ContextAnchor.span, facts)이 왜 그 요건을 충족하는지, 불충족 요건은 satisfied=false와 함께 무엇이 "
                "없어서 불충족인지 finding에 구체적으로. 규칙기반 매칭(rule_satisfied)을 존중하되 사실이 뒷받침하지 "
                "않으면 false로 교정. 요건명은 한국어 그대로.\n"
                "3) conclusion: 요건 적용을 종합해 왜 이 verdict인지를 조문과 함께. product_fact_signals가 있으면 "
                "(예: CONTRADICTED) '광고는 ~라고 하나 상품설명서·약관 사실은 ~로 서로 모순된다'처럼 사실 대조를 "
                "결론에 반드시 엮으세요. 핵심 요건 충족+모순 시 NON_COMPLIANT, 요건은 관련되나 사실/문서가 부족하면 "
                "INSUFFICIENT, 무관하면 NOT_APPLICABLE, 충족 안 되면 COMPLIANT.\n"
                "4) reservation: 금감원 회답의 마무리처럼 '이는 개별적 사실인정에 관한 사항으로 구체적 사실관계(추가 "
                "고지·실제 운영 등)에 따라 해석·적용이 달라질 수 있다'는 취지의 유보를 한 문장. 단정 회피.\n"
                "판단 원칙: 명시적 모순/단정/보장을 우선. 침묵으로부터 위반을 추론하지 말 것. anchor 자체가 조건·"
                "유보 표현(세전, 조건에 따라, 달라질 수 있습니다 등)을 말하면 추가 세부 부재는 위반이 아니라 최대 "
                "INSUFFICIENT. evidence_window.related_sentences(QUALIFIES/MITIGATES로 이 anchor를 한정·완화하는 "
                "다른 문장)가 anchor의 주장을 조건부로 만들면 그 주장을 순수 단정으로 보지 말 것 — 조건이 광고 안에 "
                "존재하므로 단정성 위반보다는 최대 INSUFFICIENT다. 다만 그 한정 문장이 별도 문장으로 분리되어 혜택 "
                "문구와 인접하지 않으면 '조건이 혜택과 분리 표시되어 오인 소지(현저성)'로 criteria_findings·conclusion에 "
                "적되 위반 강도는 낮춰라. 완화 고지 anchor는 그 고지에 대해 COMPLIANT일 수 있으나 별개의 단정·보장·무조건 "
                "최고금리·과거실적 anchor를 지우지 못합니다. CU가 불공정영업·제재·심의절차·협회워크플로우인데 anchor가 "
                "그 행위를 기술하지 않으면 NOT_APPLICABLE. evidence_span은 반드시 해당 항목 ContextAnchor의 span "
                "또는 facts에서 그대로 복사. 모든 산출 텍스트는 한국어.\n"
                "용어 규칙(준법 심사 도메인): 사용자에게 보이는 산출 텍스트에 내부/개발 용어를 쓰지 말 것 — "
                "EvidenceWindow·anchor·CUPlanItem·product_facts·source_article 같은 스키마/필드명, 그리고 "
                "NON_COMPLIANT·INSUFFICIENT·COMPLIANT 같은 영문 verdict enum을 문장에 노출하지 말 것. "
                "대신 '근거 자료', '해당 문구', '심의 항목', '상품설명서 사실', '근거 조문'과 '위반/근거 부족/적합' "
                "같은 한국어로 쓴다. 또한 광고 채널과 무관한 표현요소(웹 텍스트 광고에 '음성 속도' 등)를 예시로 "
                "끌어오지 말고, 실제 매체에 맞는 근거만 든다."
                # KR 전용 꼬리: 규제당국 판단사례 few-shot 은 금소법 인용이라 비-KR 관할에선
                # 제외하고, 대신 관할 우선 규칙(NON_KR_LAW_OVERRIDE)을 붙인다.
                + (regulator_precedents_block() if uses_korean_law_context(workspace_id) else "")
            )
            + ("" if uses_korean_law_context(workspace_id) else NON_KR_LAW_OVERRIDE),
            user=f"[judgment_payload]\n{{'judgment_items': {judgment_items}}}",
        )
        seen_plan_ids: set[str] = set()
        for row in result.get("judgments", []):
            item = item_by_plan_id.get(row.get("plan_item_id"))
            anchor = anchor_by_plan_id.get(row.get("plan_item_id"))
            if not item or not anchor:
                continue
            if item.plan_item_id in seen_plan_ids:
                continue
            seen_plan_ids.add(item.plan_item_id)
            grounded = grounded_judgment_row(row, anchor)
            criteria = [
                {
                    "criterion": str(cf.get("criterion") or ""),
                    "satisfied": bool(cf.get("satisfied")),
                    "finding": str(cf.get("finding") or ""),
                }
                for cf in (row.get("criteria_findings") or [])
                if cf.get("criterion")
            ]
            conclusion = str(row.get("conclusion") or grounded.get("why") or row.get("legal_basis") or "")
            judgments.append(
                LLMJudgment(
                    judgment_id=stable_id("judgment", review_run_id, item.plan_item_id),
                    plan_item_id=item.plan_item_id,
                    anchor_id=item.anchor_id,
                    cu_id=item.cu_id,
                    verdict=grounded["verdict"],
                    score=normalize_judgment_score(grounded["score"]),
                    # why는 하위호환: 결론을 요약으로 유지.
                    why=grounded.get("why", conclusion) if grounded.get("regrounded") else conclusion,
                    evidence_span=grounded["evidence_span"],
                    used_policy_evidence=grounded["used_policy_evidence"],
                    legal_basis=str(row.get("legal_basis") or ""),
                    criteria_findings=criteria,
                    conclusion=conclusion,
                    reservation=str(row.get("reservation") or ""),
                )
            )
        for item in item_by_plan_id.values():
            if item.plan_item_id not in seen_plan_ids:
                # Coverage guarantee: the judge call returned no row for this
                # CUPlan item, so backfill INSUFFICIENT instead of leaving it unjudged.
                judgments.append(missing_judgment(review_run_id, item, reason="no_row", korean=korean))
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


QUALIFYING_RELATIONS = {"QUALIFIES", "MITIGATES"}


def build_related_sentences(
    *,
    sentence_id: str,
    relations: list[InterSentenceRelation],
    sentence_by_id: dict[str, SentenceUnit],
) -> list[dict[str, Any]]:
    """이 anchor 문장을 한정/완화하는 다른 문장(QUALIFIES/MITIGATES)을 모은다.

    혜택 주장이 별도 문장의 조건으로 한정되는데 anchor 문장만 보면 과도하게
    단정으로 보이는 것을 막기 위해, 연결된 조건/완화 문장을 judge에 함께 제시한다.
    """
    if not sentence_id:
        return []
    related: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relation in relations:
        if relation.relation_type not in QUALIFYING_RELATIONS:
            continue
        if sentence_id not in {relation.source_sentence_id, relation.target_sentence_id}:
            continue
        other_id = (
            relation.target_sentence_id
            if relation.source_sentence_id == sentence_id
            else relation.source_sentence_id
        )
        other = sentence_by_id.get(other_id)
        if not other or other_id in seen:
            continue
        seen.add(other_id)
        related.append(
            {
                "relation_type": relation.relation_type,
                "text": other.text,
                "role": other.role,
                "prominence_tier": getattr(other, "prominence_tier", "") or "",
                "explanation": relation.explanation,
            }
        )
    return related


def build_legal_test(item: CUPlanItem, anchor: ContextAnchor, *, korean: bool = True) -> dict[str, Any]:
    """규칙기반 판단 레이어: 이 CU의 법적 요건 ↔ 광고에서 매칭된 사실.

    legal_element_profile.required_positive_features를 요건(criterion)으로,
    matched/missing_required_features로 충족 여부를, anchor.feature_set.evidence로
    그 요건을 뒷받침하는 사실 텍스트를 제시한다. LLM은 이 위에 사실 적용을 종합한다.
    ``korean=False``(비-KR 관할)에서는 요건명을 영어로 제시해, 판정 산출물의
    criteria_findings.criterion 에 한국어 요건명이 새지 않게 한다.
    """
    profile = item.legal_element_profile
    matched = set(item.matched_required_features or [])
    feature_set = anchor.feature_set
    evidence_by_feature: dict[str, list[str]] = {}
    if feature_set:
        for text in feature_set.evidence or []:
            for feature in feature_set.positive_features or []:
                if feature in str(text) or feature_ko(feature) in str(text):
                    evidence_by_feature.setdefault(feature, []).append(str(text))
    required = (profile.required_positive_features if profile else []) or item.matched_required_features or []
    required_elements = [
        {
            "criterion": feature_label(feature, korean=korean),
            "rule_satisfied": feature in matched,
            "matched_facts": evidence_by_feature.get(feature, []),
        }
        for feature in required
    ]
    return {
        "action_type_ko": feature_label(profile.action_type, korean=korean) if profile and profile.action_type in FEATURE_KO else (profile.action_type if profile else ""),
        "risk_title": item.risk_title or (profile.risk_title if profile else ""),
        "cu_definition": item.constraint or item.context,
        "cu_principle": item.principle,
        "cu_subject": item.subject,
        "required_elements": required_elements,
        "matched_facts": sorted({fact for facts in evidence_by_feature.values() for fact in facts}),
        "anchor_positive_features": [feature_label(f, korean=korean) for f in (feature_set.positive_features if feature_set else [])],
    }


def normalize_judgment_score(raw: Any) -> float:
    """LLM score 스케일 드리프트 방지. 0~1 기대이나 간혹 10점/100점 척도로 반환됨 —
    라우팅 문턱(0.82=reject)이 8.6 같은 값을 그대로 받으면 클린 광고도 반려된다."""
    try:
        value = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if value > 1.0:
        value = value / 10.0 if value <= 10.0 else value / 100.0
    return max(0.0, min(1.0, value))


def grounded_judgment_row(row: dict[str, Any], anchor: ContextAnchor) -> dict[str, Any]:
    """Reject cross-anchor evidence leakage before routing uses a judgment."""
    if row.get("verdict") == "NOT_APPLICABLE":
        return {**row, "regrounded": False}
    evidence_span = str(row.get("evidence_span") or "").strip()
    if not evidence_span or evidence_span_belongs_to_anchor(evidence_span, anchor):
        return {**row, "regrounded": False}
    return {
        **row,
        "regrounded": True,
        "verdict": "INSUFFICIENT",
        "score": min(normalize_judgment_score(row.get("score")), 0.5),
        "why": (
            f"{row.get('conclusion') or row.get('why', '')} / 근거 정합성 경고: evidence_span이 이 anchor의 "
            "격리된 증거창 밖이라 위반을 이 anchor에 귀속할 수 없습니다. "
            "(Evidence grounding warning: evidence_span was outside this anchor's isolated evidence window.)"
        ),
        "evidence_span": anchor.span.text,
    }


def evidence_span_belongs_to_anchor(evidence_span: str, anchor: ContextAnchor) -> bool:
    # Normalize whitespace so a verbatim quote with different spacing is not
    # falsely flagged as cross-anchor leakage.
    span = normalize_space(evidence_span)
    if not span:
        return True
    anchor_evidence = normalize_space(" ".join([anchor.span.text, *anchor.facts]))
    anchor_span = normalize_space(anchor.span.text)
    return span in anchor_evidence or (bool(anchor_span) and anchor_span in span)


def missing_judgment(review_run_id: str, item: CUPlanItem, *, reason: str, korean: bool = True) -> LLMJudgment:
    """Backfill an INSUFFICIENT judgment so every CUPlan item is accounted for."""
    if korean:
        note = {
            # 사용자 노출 문구 — 심사 실무 언어로.
            "no_row": "이 심의 항목은 자동 판단이 완료되지 않아 '근거 부족(추가 확인 필요)'으로 분류했습니다. 심사자가 직접 확인해 주세요.",
            "anchor": "이 심의 항목과 연결된 광고 문구를 특정하지 못해 '근거 부족(추가 확인 필요)'으로 분류했습니다. 심사자가 직접 확인해 주세요.",
        }.get(reason, "자동 판단이 완료되지 않아 '근거 부족(추가 확인 필요)'으로 분류했습니다.")
    else:
        note = {
            "no_row": "Automated judgment did not complete for this review item — classified as 'insufficient grounds (reviewer confirmation required)'. Please review manually.",
            "anchor": "The ad expression linked to this review item could not be identified — classified as 'insufficient grounds (reviewer confirmation required)'. Please review manually.",
        }.get(reason, "Automated judgment did not complete — classified as 'insufficient grounds (reviewer confirmation required)'.")
    return LLMJudgment(
        judgment_id=stable_id("judgment", review_run_id, item.plan_item_id),
        plan_item_id=item.plan_item_id,
        anchor_id=item.anchor_id,
        cu_id=item.cu_id,
        verdict="INSUFFICIENT",
        score=0.0,
        why=note,
        evidence_span="",
        used_policy_evidence=[],
    )


def chains_for_plan_item(chains: dict[str, list[dict[str, Any]]], plan_item_id: str) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [chain for chain in values if chain.get("plan_item_id") == plan_item_id and chain.get("status") == "FOUND"]
        for key, values in chains.items()
        if key != "chain_diagnostics"
    }
