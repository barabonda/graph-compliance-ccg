"""eval/compare_guideline_vlm.py 사례 대조 로직 단위 테스트.

라이브 워크플로/Neo4j/LLM 없이 순수 함수만 검증한다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "compare_guideline_vlm", _ROOT / "eval" / "compare_guideline_vlm.py"
)
assert _spec and _spec.loader
cg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cg)


def test_article_family_maps_delegation_chain() -> None:
    # 금소법 §22 / 시행령 / 감독규정 / 은행 광고심의 기준 → 하나의 위임사슬 계열
    assert cg.article_family("금소법 제22조") == cg.FMLA_ADSCOPE
    assert cg.article_family("금융소비자 보호에 관한 법률 시행령 제20조 ④") == cg.FMLA_ADSCOPE
    assert cg.article_family("금융소비자보호 감독규정 제17조") == cg.FMLA_ADSCOPE
    assert cg.article_family("은행 광고심의 기준 제16조") == cg.FMLA_ADSCOPE
    # 공정위 표시광고 공정화법은 별도 계열
    assert cg.article_family("표시ㆍ광고의 공정화에 관한 법률 제3조") == cg.FMLA_FAIR


def _case(cid: str) -> dict:
    return {"id": cid, "labels": {"articles": ["금소법 제22조"], "violation": True},
            "facts": {"gold_finding": "x"}, "text": "x"}


def test_classify_reject_with_intent_is_hit() -> None:
    case = _case("reg_guideline_p16_case1_apt_loan_rate")
    pred = {
        "final_verdict": "reject",
        "detected_issues": [{"source_article": "금소법 제22조",
                             "rationale": "이자율의 범위 및 산출기준 미표시"}],
    }
    r = cg.classify(case, pred)
    assert r["status"] == "적중"
    assert r["intent_matched"] is True


def test_classify_needs_review_with_detection_is_partial() -> None:
    case = _case("reg_guideline_p16_case3_savings_insurance_mislead")
    pred = {
        "final_verdict": "needs_review",
        "detected_issues": [{"source_article": "금소법 제22조",
                             "rationale": "종신보험을 저축성으로 오인할 우려"}],
    }
    r = cg.classify(case, pred)
    assert r["status"].startswith("부분")


def test_classify_missing_prediction_is_miss() -> None:
    case = _case("reg_guideline_p16_case2_universal_scope")
    r = cg.classify(case, None)
    assert r["status"].startswith("누락")


def test_classify_pass_without_intent_is_miss() -> None:
    case = _case("reg_guideline_p16_case4_fintech_child_savings")
    pred = {"final_verdict": "pass_candidate", "detected_issues": []}
    r = cg.classify(case, pred)
    assert r["status"] == "누락"
