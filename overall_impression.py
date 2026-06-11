"""Track B overall-impression judgment for consumer misleading risk."""

from __future__ import annotations

from typing import Any

from llm_gateway import LLMGateway
from schemas import Claim, ReviewInput
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
    ) -> dict[str, Any]:
        mitigation_signals = extract_mitigation_signals(review_input.content_text)
        result = self.llm.structured(
            name="graphcompliance_overall_impression",
            schema=OVERALL_IMPRESSION_SCHEMA,
            system=(
                "You judge Track B consumer misleading risk for Korean financial advertisements. "
                "Apply the overall and ultimate impression standard: ordinary consumers form impressions "
                "from direct wording, implied meaning, context, customary interpretation, and omissions. "
                "Use only the provided ad, extracted Claim->Meaning->Implicature->ConsumerEffect path, "
                "and disclosure requirement hints. Do not decide legal violation; decide misleading-risk "
                "for compliance review routing. Treat explicit conditions, limits, variable-rate wording, "
                "depositor-protection limits, risk warnings, fee notices, and review-process notices as "
                "mitigating evidence. Do not say a condition is missing when the ad explicitly states that "
                "the benefit depends on conditions; in that case judge whether the stated condition is still "
                "too vague, not whether it is absent."
            ),
            user=(
                "[ad]\n"
                f"title={review_input.title}\nchannel={review_input.channel}\nproduct_group={review_input.product_group}\n"
                f"{review_input.content_text}\n\n"
                "[claims]\n"
                f"{to_jsonable(claims)}\n\n"
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
