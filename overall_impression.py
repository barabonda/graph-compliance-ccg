"""Track B overall-impression judgment for consumer misleading risk."""

from __future__ import annotations

from typing import Any

from llm_gateway import LLMGateway
from schemas import Claim, ReviewInput, SentenceUnit
from utils import to_jsonable


OVERALL_IMPRESSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH", "INSUFFICIENT"],
        },
        "misleading_risk_score": {"type": "number"},
        "representative_consumer_impression": {"type": "string"},
        "misleading_factors": {"type": "array", "items": {"type": "string"}},
        "grounded_claim_ids": {"type": "array", "items": {"type": "string"}},
        "why": {"type": "string"},
    },
    "required": [
        "verdict",
        "misleading_risk_score",
        "representative_consumer_impression",
        "misleading_factors",
        "grounded_claim_ids",
        "why",
    ],
}


class LLMOverallImpressionJudge:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def judge(
        self,
        *,
        review_input: ReviewInput,
        claims: list[Claim],
        disclosure_requirements: list[dict[str, Any]],
        sentence_units: list[SentenceUnit] | None = None,
        prominence_diagnostics: list[dict[str, Any]] | None = None,
        product_fact_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mitigation_signals = extract_mitigation_signals(review_input.content_text)
        # 복잡 위반을 위한 흩어진 구조화 증거: 문장 위계/역할, 혜택↔고지 위계차,
        # 광고 주장↔상품문서 사실 모순. 개별 조각은 합법이어도 종합 인상은 다를 수 있다.
        sentence_layers = [
            {"role": s.role, "tier": s.prominence_tier, "text": s.text}
            for s in (sentence_units or [])
            if s.role in {"benefit_claim", "condition_disclosure", "risk_disclosure", "protection_disclosure"}
        ]
        prominence_gaps = [
            {"code": d.get("diagnostic_code"), "message": d.get("message"), "evidence": d.get("evidence")}
            for d in (prominence_diagnostics or [])
            if d.get("diagnostic_code") in {"PROMINENCE_INSUFFICIENT", "DISCLOSURE_MISSING"}
        ]
        fact_contradictions = [
            {"status": c.get("status"), "rationale": c.get("rationale")}
            for c in ((product_fact_context or {}).get("comparison_results") or [])
            if c.get("status") in {"CONTRADICTED", "CONDITION_MISSING", "NO_PRODUCT_FACT"}
        ]
        result = self.llm.structured(
            name="graphcompliance_overall_impression",
            schema=OVERALL_IMPRESSION_SCHEMA,
            system=(
                "당신은 한국 금융광고의 Track B '전체적·궁극적 인상' 기준 소비자 오인위험을 판단합니다. "
                "핵심은 '복잡 위반' 탐지입니다: 개별 문구는 모두 합법(예: '최고 10%'는 조건 충족 시 사실, "
                "'예금자보호 안 됨'도 정직한 고지)이어도, 흩어진 조각을 종합하면 '안전한 고금리'라는 전체 "
                "인상과 '조건 까다롭고 원금손실 가능'이라는 실체 사이에 간극이 생길 수 있습니다. 그 간극이 "
                "오인위험입니다. 다음 구조화 증거를 반드시 종합하세요:\n"
                "- sentence_layers: 혜택(benefit) 문구는 headline에, 위험·조건 고지는 footnote에 놓였는지 "
                "(위계 비대칭은 오인을 키움).\n"
                "- prominence_gaps: 혜택 대비 고지가 낮은 위계이거나 누락된 신호.\n"
                "- fact_contradictions: 광고 주장과 상품설명서·약관 사실의 모순(CONTRADICTED) 또는 근거 부재. "
                "수치 불일치(예: 본문 10% vs 예상수취 11%)나 '확정' 주장 vs 변동금리 실체는 강한 오인 신호.\n"
                "misleading_factors에는 '어떤 조각들을 어떻게 연결했는지'를 구체적으로 적으세요(예: '친근한 "
                "상품명+headline 최고금리 강조' vs 'footnote 예금자보호 미해당+원금손실' vs '문서상 변동금리'를 "
                "종합하면 안전·확정 인상과 실체가 괴리). 법적 위반을 단정하지 말고 라우팅용 오인위험만 판단. "
                "명시된 조건·한도·변동·예금자보호·위험·수수료·심의 고지는 완화 증거로 보되, footnote로 약하게 "
                "표시되면 완화력이 제한됨을 반영하세요. 모든 산출은 한국어."
            ),
            user=(
                "[ad]\n"
                f"title={review_input.title}\nchannel={review_input.channel}\nproduct_group={review_input.product_group}\n"
                f"{review_input.content_text}\n\n"
                "[claims]\n"
                f"{to_jsonable(claims)}\n\n"
                "[sentence_layers] (역할·위계)\n"
                f"{sentence_layers}\n\n"
                "[prominence_gaps] (혜택↔고지 위계차/누락)\n"
                f"{prominence_gaps}\n\n"
                "[fact_contradictions] (광고 주장↔상품문서 사실 모순)\n"
                f"{fact_contradictions}\n\n"
                "[disclosure_requirements]\n"
                f"{disclosure_requirements}\n\n"
                "[explicit_mitigation_signals]\n"
                f"{mitigation_signals}"
            ),
        )
        score = calibrate_score(result["verdict"], float(result["misleading_risk_score"]))
        return {
            "track": "B",
            "standard": "대법원 2017두60109 전체적·궁극적 인상 기준",
            "verdict": result["verdict"],
            "misleading_risk_score": score,
            "representative_consumer_impression": result["representative_consumer_impression"],
            "misleading_factors": result["misleading_factors"],
            "explicit_mitigation_signals": mitigation_signals,
            # 종합에 사용된 흩어진 증거(감사 추적): 어떤 조각을 연결해 인상을 판단했는지.
            "synthesized_evidence": {
                "sentence_layers": sentence_layers,
                "prominence_gaps": prominence_gaps,
                "fact_contradictions": fact_contradictions,
            },
            "grounded_claim_ids": result["grounded_claim_ids"],
            "evidence_paths": [
                {
                    "claim_id": claim.claim_id,
                    "path": "Claim -> Meaning -> Implicature -> ConsumerEffect -> OverallImpressionStandard",
                    "claim": claim.text,
                    "meaning": claim.meaning,
                    "implicature": claim.implicature,
                    "consumer_effect": claim.consumer_effect,
                }
                for claim in claims
                if not result["grounded_claim_ids"] or claim.claim_id in result["grounded_claim_ids"]
            ],
            "why": result["why"],
        }


def extract_mitigation_signals(text: str) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    patterns = [
        ("condition_disclosure", ["우대조건", "조건 충족", "가입기간", "대상", "자격요건"], "혜택/금리 적용 조건 고지"),
        ("variable_rate_disclosure", ["달라질 수", "변동", "상이"], "금리나 조건 변동 가능성 고지"),
        ("depositor_protection", ["예금자보호", "1억원", "보호됩니다"], "예금자보호 한도 고지"),
        ("risk_warning", ["원금손실", "손실 가능성", "투자위험"], "원금손실/투자위험 고지"),
        ("fee_disclosure", ["수수료", "부대비용", "중도상환"], "수수료/부대비용 고지"),
        ("review_notice", ["심의필", "준법감시인", "유효기간"], "심의필/심의주체 고지"),
    ]
    for signal_id, tokens, label in patterns:
        matched = [token for token in tokens if token in text]
        if matched:
            signals.append({"id": signal_id, "label": label, "matched_terms": ", ".join(matched)})
    return signals


def calibrate_score(verdict: str, score: float) -> float:
    bounded = max(0.0, min(1.0, score))
    if verdict == "LOW":
        return min(bounded, 0.35)
    if verdict == "MEDIUM":
        return min(max(bounded, 0.36), 0.68)
    if verdict == "INSUFFICIENT":
        return min(max(bounded, 0.36), 0.6)
    return max(bounded, 0.69)
