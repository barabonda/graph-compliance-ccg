"""Tests for v0.2 guideline-synth taxonomy, build controls, and eval runners.

All tests here are offline (no LLM/Neo4j): they exercise the taxonomy schema,
the deterministic per-combo code sampler, template mutation, the JB real-ad
runner helpers, and the breakdown metrics.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import build_synthetic_eval_dataset as build

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_V0_2 = ROOT / "eval" / "violation_taxonomy_v0_2.json"


def _load_eval_module(name: str, filename: str) -> ModuleType:
    """Load an eval/ module by path (eval/ is not an importable package)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


jbbank = _load_eval_module("run_jbbank_eval", "run_jbbank_eval.py")
breakdown = _load_eval_module("synth_v0_2_breakdown", "synth_v0_2_breakdown.py")

REQUIRED_KEYS = {
    "code",
    "type",
    "product_groups",
    "channels",
    "category",
    "mutation_instruction",
    "mutation_phrase",
    "gold_span_hint",
    "articles",
    "required_disclosures",
    "risk_level",
    "expected_routing",
    "source_document",
    "source_article",
    "source_quote",
}
VALID_GROUPS = {"deposit", "loan", "investment"}
SLOT_DEFAULTS = {
    "rate": "X%",
    "term": "12개월",
    "eligibility": "성인",
    "condition": "우대조건",
    "protection": "예금자보호",
}


def _taxonomy() -> dict:
    return json.loads(TAXONOMY_V0_2.read_text(encoding="utf-8"))


def test_taxonomy_schema_and_backward_compat() -> None:
    tax = _taxonomy()
    assert tax["version"] == "0.2"
    assert tax["schema_compatible_with"] == "0.1"
    codes = tax["codes"]
    assert len(codes) >= 30
    seen = set()
    for code in codes:
        missing = REQUIRED_KEYS - set(code)
        assert not missing, f"{code.get('code')} missing keys: {missing}"
        assert code["code"] not in seen, f"duplicate code {code['code']}"
        seen.add(code["code"])
        for group in code["product_groups"]:
            assert group in VALID_GROUPS, f"{code['code']} bad group {group}"
        assert code["source_quote"].strip(), f"{code['code']} empty source_quote"


def test_insurance_patterns_are_excluded_from_generation() -> None:
    tax = _taxonomy()
    insurance = [c for c in tax["codes"] if c["type"] == "보험"]
    assert insurance, "insurance patterns must be catalogued"
    for code in insurance:
        assert code["product_groups"] == [], f"{code['code']} insurance must have empty product_groups"


def test_v0_1_codes_merged_or_preserved() -> None:
    v0_1 = json.loads((ROOT / "eval" / "violation_taxonomy_v0_1.json").read_text(encoding="utf-8"))
    v0_2_codes = {c["code"] for c in _taxonomy()["codes"]}
    # v0_1 codes kept verbatim or explicitly merged (documented in origin field).
    preserved = {
        "DEPOSIT_RATE_CONDITION_MISSING",
        "LOAN_EASY_APPROVAL_MISLEADING",
        "INVEST_PAST_PERFORMANCE_NO_WARNING",
        "HARD_CASE_DEPOSIT_RATE_WITH_SAME_LEVEL_DISCLOSURE",
    }
    assert preserved <= v0_2_codes
    # merged v0_1 codes are represented by successor codes.
    merged_successors = {"UNIVERSAL_SCOPE_MISLEADING", "GUARANTEE_RETURN_DEFINITIVE"}
    assert merged_successors <= v0_2_codes
    assert {"DEPOSIT_UNIVERSAL_SCOPE_MISLEADING", "RETURN_GUARANTEE_MISLEADING"} & set(v0_1_codes(v0_1))


def v0_1_codes(v0_1: dict) -> set[str]:
    return {c["code"] for c in v0_1["codes"]}


def test_gold_span_hint_is_substring_of_mutation_phrase() -> None:
    """Self-contained invariant: template mutation span must appear verbatim in text.

    This validates the template generation path for every generatable code without
    an LLM. gold_span_hint (formatted) must be a substring of mutation_phrase (formatted).
    """
    for code in _taxonomy()["codes"]:
        if code["category"] == "hard_case_compliant":
            continue
        if not code["product_groups"] or code["product_groups"] == ["investment"]:
            continue
        phrase = code["mutation_phrase"].format(**SLOT_DEFAULTS)
        hint = (code["gold_span_hint"] or "").format(**SLOT_DEFAULTS)
        assert hint and hint in phrase, f"{code['code']}: span {hint!r} not in phrase {phrase!r}"


def test_select_codes_for_combo_determinism_and_balance() -> None:
    codes = [{"code": f"C{i}"} for i in range(10)]
    # None -> all (v0_1 behavior)
    assert build.select_codes_for_combo(codes, codes_per_combo=None, combo_index=0) == codes
    # size respected
    sel0 = build.select_codes_for_combo(codes, codes_per_combo=4, combo_index=0)
    assert [c["code"] for c in sel0] == ["C0", "C1", "C2", "C3"]
    # deterministic rotation across combos
    sel1 = build.select_codes_for_combo(codes, codes_per_combo=4, combo_index=1)
    assert [c["code"] for c in sel1] == ["C4", "C5", "C6", "C7"]
    sel2 = build.select_codes_for_combo(codes, codes_per_combo=4, combo_index=2)
    assert [c["code"] for c in sel2] == ["C8", "C9", "C0", "C1"]
    # coverage: over enough combos every code appears at least once
    covered: set[str] = set()
    for idx in range(6):
        covered |= {c["code"] for c in build.select_codes_for_combo(codes, codes_per_combo=4, combo_index=idx)}
    assert covered == {c["code"] for c in codes}


def test_applicable_codes_filters_group_and_channel() -> None:
    tax = _taxonomy()
    bundle = {"product_group": "deposit", "channel": "web_page"}
    codes = build.applicable_codes(tax, bundle)
    assert codes, "deposit/web_page must have applicable codes"
    for code in codes:
        assert "deposit" in code["product_groups"]
    # insurance/investment never applicable to deposit
    assert all(c["type"] != "보험" for c in codes)
    loan_bundle = {"product_group": "loan", "channel": "web_page"}
    loan_codes = {c["code"] for c in build.applicable_codes(tax, loan_bundle)}
    assert "LOAN_EASY_APPROVAL_MISLEADING" in loan_codes


def test_build_records_template_path_spans_present() -> None:
    """llm=None template path produces records whose spans appear in text."""
    tax = _taxonomy()
    bundle = {
        "product_name": "테스트 정기예금",
        "product_group": "deposit",
        "channel": "web_page",
        "disclosure_requirements": [{"label": "우대조건"}],
        "selected_documents": [{"document_id": "doc1", "label": "약관", "file_name": "a.pdf", "relative_path": "a.pdf"}],
        "product_facts": [
            {"fact_id": "pf_0", "fact_type": "기본금리", "value": "연 3.0%", "source_document_id": "doc1", "evidence_text": "기본 연 3.0%", "confidence": 0.9},
        ],
    }
    clean_ad = {"headline": "정기예금", "subcopy": "안내", "body": "", "footnote": "약관 확인", "used_fact_ids": [], "compliance_notes": []}
    records = build.build_records_from_product_facts(
        tax, bundle, clean_ad, llm=None, codes_per_combo=5, combo_index=0
    )
    assert records[0]["labels"]["violation"] is False  # clean control first
    mutations = [r for r in records if r["source_type"] == "synthetic_product_fact_mutation"]
    assert mutations, "expected at least one mutation record"
    for record in mutations:
        for span in record["facts"]["expected_problem_spans"]:
            assert span in record["text"], f"{record['id']}: span {span!r} absent from text"
        assert record["labels"]["violation"] is True
        assert record["labels"]["violation_types"]


# ---- JB real-ad runner helpers ----

def test_infer_product_group() -> None:
    infer_product_group = jbbank.infer_product_group

    assert infer_product_group("JB 슈퍼씨드 적금 출시 이벤트", "") == "deposit"
    assert infer_product_group("전세자금대출 이벤트", "") == "loan"
    assert infer_product_group("JB카드 오토 캐시백", "카드 혜택 안내") == "other"
    # title empty -> body used
    assert infer_product_group("이벤트", "이 정기예금에 가입하세요") == "deposit"


def test_clean_ad_text_strips_images_keeps_figure_desc() -> None:
    clean_ad_text = jbbank.clean_ad_text

    md = (
        "JB 적금\n\n![image](/image/placeholder)\n\n"
        '<figcaption>\n<p class="figure-type">infographic</p>\n'
        '<p class="figure-description">두 캐릭터가 5만원권을 들고 있다.</p>\n</figcaption>\n\n'
        "연 최고 13.6%"
    )
    out = clean_ad_text(md)
    assert "/image/placeholder" not in out
    assert "<" not in out and ">" not in out
    assert "[이미지 설명] 두 캐릭터가 5만원권을 들고 있다." in out
    assert "연 최고 13.6%" in out


def test_build_report_counts() -> None:
    build_report = jbbank.build_report

    rows = [
        {"final_verdict": "reject", "product_group": "deposit"},
        {"final_verdict": "revise", "product_group": "deposit"},
        {"final_verdict": "needs_review", "product_group": "loan"},
        {"final_verdict": "pass_candidate", "product_group": "loan"},
    ]
    report = build_report(rows, workspace_id="graphcompliance_mvp_jb_20260530")
    assert report["gold_available"] is False
    assert report["kind"] == "jbbank_live_eval"
    assert report["record_count"] == 4
    assert report["flagged_count"] == 2  # reject + revise
    assert report["verdict_counts"]["reject"] == 1
    assert report["product_group_counts"]["deposit"] == 2


# ---- breakdown metrics ----

def test_breakdown_prf_and_build() -> None:
    module = breakdown

    assert module._prf(2, 0, 0) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    prf = module._prf(1, 1, 2)
    assert prf["precision"] == 0.5 and round(prf["recall"], 3) == 0.333

    from evaluate import EvaluationLabels, EvaluationRecord

    records = [
        EvaluationRecord(
            record_id="m1",
            text="x",
            facts={"injected_violation_code": "SUPERLATIVE_NO_BASIS", "product_name": "JB 참 괜찮은 정기예금"},
            product_group="deposit",
            labels=EvaluationLabels(
                violation=True,
                articles=["금소법 제22조", "은행 광고심의 기준 제17조"],
                required_disclosures=["우대조건", "예금자보호 여부 및 한도"],
                expected_routing="revise",
            ),
        ),
        EvaluationRecord(
            record_id="c1",
            text="y",
            facts={},
            product_group="deposit",
            labels=EvaluationLabels(violation=False, expected_routing="pass_candidate"),
        ),
    ]
    # m1 predicted violation (revise); pipeline cites a LOWER delegation article + lists disclosures.
    predictions = {
        "m1": {
            "final_verdict": "revise",
            "detected_issues": [],
            "cu_plan": [{"plan_item_id": "p1", "source_article": "금융소비자보호에 관한 법률 시행령 제20조"}],
            "effective_judgments": [{"plan_item_id": "p1", "verdict": "NON_COMPLIANT"}],
            "disclosure_requirements": [{"label": "우대조건 및 적용기간"}],
            "product_fact_context": {"disclosure_checks": [{"label": "예금자보호 부보내용", "gate_status": "ON", "present": False}]},
        },
        "c1": {"final_verdict": "pass_candidate", "detected_issues": [], "cu_plan": []},
    }
    code_type = {"SUPERLATIVE_NO_BASIS": "금지행위"}
    report = module.build(records, predictions, code_type)
    ax = report["axes"]
    # A: binary detection perfect
    assert ax["A_violation_detection"]["precision"] == 1.0
    assert ax["A_violation_detection"]["recall"] == 1.0
    # B: exact article match fails (gold §22 vs pred 시행령 §20), family merge succeeds
    assert ax["B_articles"]["exact_match"]["counts"]["tp"] == 0
    assert ax["B_articles"]["family_merged"]["counts"]["tp"] >= 1
    # C: coverage recall — 우대조건→우대조건 및 적용기간 (required), 예금자보호→부보내용 (missing)
    assert ax["C_required_disclosures"]["coverage_recall"]["detected"] >= 1
    assert ax["C_required_disclosures"]["missing_detection_recall"]["detected"] >= 1
    # D: routing — gold revise vs pred revise = exact
    assert ax["D_routing_confusion"]["matrix"]["revise"]["revise"] == 1
    assert ax["D_routing_confusion"]["matrix"]["pass_candidate"]["pass_candidate"] == 1
    # E: per-type recall + code exact-match declared N/A
    assert ax["E_violation_type_recall"]["per_type"]["금지행위"]["recall"] == 1.0
    assert "N/A" in ax["E_violation_type_recall"]["exact_code_match"]
    # F: clean control no overblocking
    assert ax["F_clean_control_overblocking"]["reject_fp"] == 0
    assert report["per_product_group"]["deposit"]["counts"]["tp"] == 1
    # per selected product name aggregation (coordinator: product_group 뭉갬 해소)
    assert "JB 참 괜찮은 정기예금" in report["selected_product_names"]
    pn = report["per_product_name"]["JB 참 괜찮은 정기예금"]
    assert pn["violation_detection"]["tp"] == 1
    assert pn["required_disclosure_coverage"]["detected"] >= 1
    assert "3-way" in report["product_selection_note"]


def test_disclosure_hit_keyword_matching() -> None:
    hit = breakdown.disclosure_hit
    assert hit("우대조건", ["우대조건 및 적용기간", "가입기간"]) is True
    assert hit("대출금리 범위 및 산출기준", ["금리 범위 및 산정방법"]) is True
    assert hit("예금자보호 여부 및 한도", ["예금자보호 부보내용"]) is True
    assert hit("예금자보호", ["상품설명서·약관 확인"]) is False


def test_article_family_shared_from_vlm() -> None:
    fam = breakdown.article_family
    # all 금소법 delegation-chain articles collapse to one family
    assert fam("금소법 제22조") == fam("금융소비자보호에 관한 법률 시행령 제20조") == fam("은행 광고심의 기준 제17조")
    # 표시광고공정화법 is a separate family
    assert fam("표시·광고의 공정화에 관한 법률 제3조") != fam("금소법 제22조")


# ---- record-level match / overall_pass (레코드별 통과 검증) ----

def test_compute_record_match_needs_review_hold_is_not_a_pass() -> None:
    """pred가 needs_review(유보)면 gold가 revise를 기대할 때 인접(adjacent)이어도
    통과로 세지 않는다 — overall_pass 정의의 핵심 정직성 게이트."""
    from evaluate import EvaluationLabels, EvaluationRecord

    record = EvaluationRecord(
        record_id="hold1",
        text="x",
        labels=EvaluationLabels(
            violation=True,
            articles=["금소법 제22조"],
            required_disclosures=["우대조건"],
            expected_routing="revise",
        ),
    )
    output = {"product_fact_context": {"disclosure_checks": []}}
    # violation/article_family/disclosures 모두 일치하도록 조작한 스텁 summary —
    # 오직 routing(needs_review 유보) 축 하나만으로 overall_pass가 막히는지 검증.
    summary = {
        "predicted_violation": True,
        "predicted_articles": ["금소법 제22조"],
        "predicted_routing": "needs_review",
    }
    matches, overall_pass = breakdown.compute_record_match(record, output, summary)
    assert matches["routing"] == {"gold": "revise", "pred": "needs_review", "exact": False, "adjacent": True}
    assert overall_pass is False  # 인접이지만 유보라서 통과 아님


def test_compute_record_match_needs_review_exact_gold_match_passes() -> None:
    """gold도 needs_review를 기대하는 케이스(정말 애매해서 사람 확인이 정답)는
    정확일치이므로 통과로 인정한다 — 유보 자체를 막는 게 아니라 '근접 매칭으로
    유보를 얼버무리는 것'만 막는다."""
    from evaluate import EvaluationLabels, EvaluationRecord

    record = EvaluationRecord(
        record_id="hold2",
        text="x",
        labels=EvaluationLabels(violation=False, expected_routing="needs_review"),
    )
    output = {}
    summary = {"predicted_violation": False, "predicted_articles": [], "predicted_routing": "needs_review"}
    matches, overall_pass = breakdown.compute_record_match(record, output, summary)
    assert matches["routing"]["exact"] is True
    assert overall_pass is True


def test_build_metrics_report_full_gold_and_matches() -> None:
    """evaluate.evaluate_records()에 실린 gold가 violation_types/required_disclosures까지
    완전하고, review_run_id·matches·overall_pass가 채워지는지 — 라이브 재심사 없이
    기존 predictions만으로 재계산."""
    from evaluate import EvaluationLabels, EvaluationRecord

    records = [
        EvaluationRecord(
            record_id="m1",
            text="x",
            facts={"injected_violation_code": "SUPERLATIVE_NO_BASIS", "product_name": "JB 참 괜찮은 정기예금"},
            product_group="deposit",
            labels=EvaluationLabels(
                violation=True,
                violation_types=["SUPERLATIVE_NO_BASIS"],
                articles=["금소법 제22조", "은행 광고심의 기준 제17조"],
                required_disclosures=["우대조건", "예금자보호 여부 및 한도"],
                expected_routing="revise",
            ),
        ),
        EvaluationRecord(
            record_id="c1",
            text="y",
            facts={},
            product_group="deposit",
            labels=EvaluationLabels(violation=False, expected_routing="pass_candidate"),
        ),
    ]
    predictions = {
        "m1": {
            "review_run_id": "review_run_m1",
            "final_verdict": "revise",
            "detected_issues": [],
            "cu_plan": [{"plan_item_id": "p1", "source_article": "금융소비자보호에 관한 법률 시행령 제20조"}],
            "effective_judgments": [{"plan_item_id": "p1", "verdict": "NON_COMPLIANT"}],
            "disclosure_requirements": [{"label": "우대조건 및 적용기간"}],
            "product_fact_context": {
                "disclosure_checks": [{"label": "예금자보호 부보내용", "gate_status": "ON", "present": False}]
            },
        },
        "c1": {"review_run_id": "review_run_c1", "final_verdict": "pass_candidate", "detected_issues": [], "cu_plan": []},
    }
    report = breakdown.build_metrics_report(records, predictions)

    m1 = next(r for r in report["records"] if r["id"] == "m1")
    assert m1["gold"]["violation_types"] == ["SUPERLATIVE_NO_BASIS"]
    assert m1["gold"]["required_disclosures"] == ["우대조건", "예금자보호 여부 및 한도"]
    assert m1["review_run_id"] == "review_run_m1"
    assert m1["matches"]["violation"] is True
    assert m1["matches"]["article_exact"] is False  # gold §22 vs pred 시행령 §20
    assert m1["matches"]["article_family"] is True  # 위임사슬 계열 병합
    assert m1["matches"]["disclosures"] == {"gold_n": 2, "matched_n": 2, "recall": 1.0}
    assert m1["matches"]["routing"]["exact"] is True
    assert m1["overall_pass"] is True

    c1 = next(r for r in report["records"] if r["id"] == "c1")
    assert c1["gold"]["violation_types"] == []
    assert c1["review_run_id"] == "review_run_c1"
    assert c1["matches"]["disclosures"] == {"gold_n": 0, "matched_n": 0, "recall": 1.0}
    assert c1["overall_pass"] is True

    assert "overall_pass_definition" in report
    assert report["overall_pass_summary"] == {"pass": 2, "total": 2, "rate": 1.0}
