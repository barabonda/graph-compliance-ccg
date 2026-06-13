"""결정론적 규칙 판정 트랙 (GraphCompliance의 rule-based 레이어).

위반은 두 부류다:
- 기계적 위반: 필수 기재사항의 존재/부재. 해석의 여지가 없다 → 규칙으로 직접 판정.
  LLM에 맡기면 비결정성(같은 입력 다른 답)과 감사 불가(규칙 대신 그럴듯한 말)가 생긴다.
- 해석적 위반: 단정성·오인 소지 등 맥락 판단 → LLM 트랙(judge.py)이 담당.

이 모듈은 build_disclosure_checks(키워드 기반, 결정론적) 결과 위에 '필수 여부'와
'심의기준 근거'를 입혀, 재현 가능하고 추적 가능한 규칙 판정을 만든다. 이 판정은
라우팅에 escalate-only로 합류한다(LLM이 못 잡은 누락도 결정론적으로 잡되, LLM이
잡은 위반을 낮추지는 않는다).
"""

from __future__ import annotations

from typing import Any


# 제품군별 '필수 기재사항'(누락 시 기계적 위반). 권장 항목은 제외.
REQUIRED_DISCLOSURES: dict[str, set[str]] = {
    "deposit": {"deposit_rate_condition", "deposit_term", "depositor_protection_limit"},
    "loan": {"loan_rate_range", "loan_screening", "loan_fee"},
    "investment": {"investment_loss_risk", "past_performance_warning"},
}

# 각 고지의 근거 심의기준 (감사 추적용).
DISCLOSURE_BASIS: dict[str, str] = {
    "deposit_rate_condition": "은행 광고심의 기준 제16조·제17조 (금리 범위·산정방법)",
    "deposit_term": "은행 광고심의 기준 제18조 (우대조건·적용기간)",
    "deposit_tax_basis": "은행 광고심의 기준 (세전/세후 기준 표시)",
    "depositor_protection_limit": "은행 광고심의 기준 제16조 (예금자보호 부보내용)",
    "product_document_notice": "금융소비자보호법 제19조 (설명서·약관 확인 안내)",
    "loan_rate_range": "은행 광고심의 기준 (대출금리 범위 표시)",
    "loan_screening": "은행 광고심의 기준 (심사 조건 고지)",
    "loan_fee": "은행 광고심의 기준 (수수료·부대비용 고지)",
    "investment_loss_risk": "자본시장법 제57조 (원금손실 가능성 고지)",
    "past_performance_warning": "금융투자회사 영업·업무규정 제2-26조 (과거실적 미래수익 비보장)",
    "product_document_notice_invest": "금융소비자보호법 제19조 (투자설명서·약관 확인)",
}

VERDICT_RANK = {"pass_candidate": 0, "needs_review": 1, "revise": 2, "reject": 3}


def resolve_product_group(content_text: str, product_group: str) -> str:
    if product_group != "auto":
        return product_group
    lowered = content_text.lower()
    if any(token in lowered for token in ["예금", "적금", "특판"]):
        return "deposit"
    if any(token in lowered for token in ["대출", "한도", "승인"]):
        return "loan"
    if any(token in lowered for token in ["els", "펀드", "투자", "수익률"]):
        return "investment"
    return product_group


def build_rule_findings(disclosure_checks: list[dict[str, Any]], product_group: str) -> list[dict[str, Any]]:
    """필수고지 존재/부재를 결정론적으로 판정한 규칙 트랙 결과."""
    required = REQUIRED_DISCLOSURES.get(product_group, set())
    findings: list[dict[str, Any]] = []
    for check in disclosure_checks or []:
        code = str(check.get("check_id") or "")
        present = bool(check.get("present"))
        is_required = code in required
        findings.append(
            {
                "code": code,
                "label": str(check.get("label") or code),
                "status": "PRESENT" if present else "MISSING",
                "required": is_required,
                "basis": DISCLOSURE_BASIS.get(code, "은행 광고심의 기준"),
                "deterministic": True,
                "engine": "rule",
            }
        )
    return findings


def rule_verdict(findings: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """규칙 트랙 단독 verdict (escalate-only로 라우팅에 합류).

    필수 고지가 빠지면 해석 없이도 기계적 위반이다. 예금자보호 누락이나 2건 이상
    누락은 수정 사유(revise), 1건 누락은 검토 필요(needs_review)로 본다. reject는
    해석적 고위험 판단(LLM)에 남긴다.
    """
    missing_required = [f for f in findings if f["required"] and f["status"] == "MISSING"]
    if not missing_required:
        return "pass_candidate", missing_required
    critical = any("protection" in f["code"] or "loss_risk" in f["code"] for f in missing_required)
    if critical or len(missing_required) >= 2:
        return "revise", missing_required
    return "needs_review", missing_required


def fuse_verdict(llm_verdict: str, rule_v: str) -> str:
    """규칙은 verdict를 올릴 수만 있다(누락 직접 판정). 내리지 않는다."""
    return llm_verdict if VERDICT_RANK.get(llm_verdict, 0) >= VERDICT_RANK.get(rule_v, 0) else rule_v
