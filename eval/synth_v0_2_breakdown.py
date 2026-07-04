"""합성 gold 평가의 라벨 정합 채점 — 축별로 '무엇을 라벨과 대조하는가'를 명시.

evaluate.py의 레코드 로딩·예측 요약을 재사용하고, compare_guideline_vlm.py의
위임사슬 계열(article_family)을 공유한다. 각 축은 gold 라벨의 서로 다른 필드를 대조한다:

- A. 위반검출(이진): final_verdict∈{reject,revise} vs gold.violation.
- B. 조문 멀티라벨: gold.articles vs 예측 조문 — (B1) 정확일치(canonical 조 레벨),
  (B2) 위임사슬 계열병합(article_family). gold는 상위 조문, 파이프라인은 하위
  위임조문을 인용하므로 정확일치는 과소평가된다 — 두 수치를 병기해 과대·과소 모두 방지.
- C. required_disclosures 재현율: gold.required_disclosures(변이가 제거한 필수고지) vs
  파이프라인의 disclosure_requirements(커버리지)·missing_disclosures(누락검출) 키워드 대조.
  이 데이터셋에서 가장 의미 있는 축(변이는 특정 고지를 제거해 만든 것).
- D. expected_routing 혼동행렬: gold.expected_routing(4값) vs final_verdict(4값),
  정확일치 + 인접오차(revise↔needs_review, reject↔revise) 별도 집계.
- E. violation_types(택소노미 코드): 파이프라인이 코드를 출력하지 않아 정확-코드 매칭 불가.
  유형별 위반검출률(recall)로 환산해 보고하고 정확-코드 매칭은 N/A로 명시.
- F. clean 대조군: 오탐(overblocking) — clean(violation=false)이 reject/non-pass면 FP.

gold 라벨은 생성 시점에 확정돼 있고 이 스크립트는 예측과 대조만 한다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from evaluate import (  # noqa: E402
    EvaluationRecord,
    canonical_article,
    evaluate_records,
    load_predictions,
    load_records,
    summarize_prediction,
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# 위임사슬 계열(article_family)을 compare_guideline_vlm.py와 공유.
_vlm = _load_module("compare_guideline_vlm", Path(__file__).resolve().parent / "compare_guideline_vlm.py")
article_family = _vlm.article_family

ROUTING_VALUES = ["reject", "revise", "needs_review", "pass_candidate"]
# 인접(near-miss) 판정 쌍 — 심각도 인접이라 1칸 오차로 별도 집계.
ADJACENT_ROUTING = {frozenset({"reject", "revise"}), frozenset({"revise", "needs_review"}), frozenset({"needs_review", "pass_candidate"})}
_DISCLOSURE_STOPWORDS = {"및", "등", "여부", "관한", "대한", "사항", "표시", "고지", "안내", "확인"}


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def code_to_type(taxonomy_path: Path) -> dict[str, str]:
    tax = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    return {str(c["code"]): str(c.get("type") or "기타") for c in tax.get("codes", [])}


# ---- C. required_disclosures matching ----

def disclosure_keywords(label: str) -> set[str]:
    """필수고지 문구에서 핵심 키워드(길이≥2, 불용어 제외)를 추출."""
    parts = re.split(r"[\s·,()/]+", str(label))
    return {p for p in parts if len(p) >= 2 and p not in _DISCLOSURE_STOPWORDS}


def pred_disclosure_signals(output: dict[str, Any]) -> dict[str, list[str]]:
    """예측에서 (a) 필수로 판단한 고지(커버리지)와 (b) 누락으로 검출한 고지."""
    pfc = output.get("product_fact_context") or {}
    checks = pfc.get("disclosure_checks") or []
    missing = [
        str(c.get("label") or "")
        for c in checks
        if str(c.get("gate_status") or "ON").upper() == "ON" and not c.get("present")
    ]
    required = [str(d.get("label") or d.get("name") or "") for d in (output.get("disclosure_requirements") or [])]
    required += [str(c.get("label") or "") for c in checks if str(c.get("gate_status") or "ON").upper() == "ON"]
    return {"missing": [m for m in missing if m], "required": [r for r in required if r]}


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text))


def disclosure_hit(gold_label: str, pred_labels: list[str]) -> bool:
    keywords = disclosure_keywords(gold_label)
    if not keywords:
        return False
    pred_norm = [_norm(p) for p in pred_labels]
    return any(any(kw in p for p in pred_norm) for kw in keywords)


# ---- B. article axes ----

def _multilabel_counts(gold_sets: list[set[str]], pred_sets: list[set[str]]) -> dict[str, Any]:
    tp = fp = fn = 0
    for gold, pred in zip(gold_sets, pred_sets, strict=True):
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
    return {"counts": {"tp": tp, "fp": fp, "fn": fn}, **_prf(tp, fp, fn)}


def build(
    records: list[EvaluationRecord],
    predictions: dict[str, dict[str, Any]],
    code_type: dict[str, str],
) -> dict[str, Any]:
    # Axis A — binary violation
    a_tp = a_fp = a_fn = a_tn = 0
    per_group: dict[str, dict[str, int]] = {}
    per_type: dict[str, dict[str, int]] = {}
    # Axis B — articles
    gold_exact: list[set[str]] = []
    pred_exact: list[set[str]] = []
    gold_fam: list[set[str]] = []
    pred_fam: list[set[str]] = []
    # Axis C — disclosures
    disc_cov_tp = disc_cov_fn = 0
    disc_miss_tp = disc_miss_fn = 0
    per_type_disc: dict[str, dict[str, int]] = {}
    # Axis D — routing confusion
    routing_matrix: dict[str, dict[str, int]] = {g: {p: 0 for p in ROUTING_VALUES} for g in ROUTING_VALUES}
    routing_exact = routing_adjacent = routing_total = 0
    # Axis F — clean control
    clean_total = clean_reject = clean_non_pass = 0
    # Per selected product NAME (coordinator: product_group 뭉갬 해소)
    per_product_name: dict[str, dict[str, int]] = {}

    for record in records:
        summary = summarize_prediction(record.record_id, predictions.get(record.record_id))
        output = predictions.get(record.record_id) or {}
        gold_v = record.labels.violation
        pred_v = summary.predicted_violation
        group = record.product_group or "auto"
        per_group.setdefault(group, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})

        # A
        if gold_v and pred_v:
            a_tp += 1; per_group[group]["tp"] += 1
        elif not gold_v and pred_v:
            a_fp += 1; per_group[group]["fp"] += 1
        elif gold_v and not pred_v:
            a_fn += 1; per_group[group]["fn"] += 1
        else:
            a_tn += 1; per_group[group]["tn"] += 1

        # B (only records with gold articles, i.e. violations)
        if record.labels.articles:
            g_exact = {canonical_article(a) for a in record.labels.articles if a}
            p_exact = {canonical_article(a) for a in summary.predicted_articles if a}
            gold_exact.append(g_exact); pred_exact.append(p_exact)
            gold_fam.append({article_family(a) for a in record.labels.articles if a})
            pred_fam.append({article_family(a) for a in summary.predicted_articles if a})

        # per selected product name — violation detection + disclosure coverage
        pname = str(record.facts.get("product_name") or "unknown")
        pn = per_product_name.setdefault(
            pname, {"records": 0, "det_tp": 0, "det_fn": 0, "det_fp": 0, "cov_tp": 0, "cov_fn": 0}
        )
        pn["records"] += 1
        if gold_v:
            pn["det_tp" if pred_v else "det_fn"] += 1
        elif pred_v:
            pn["det_fp"] += 1

        # C (mutations with gold required_disclosures)
        vtype = code_type.get(str(record.facts.get("injected_violation_code") or ""), "기타")
        if gold_v and record.labels.required_disclosures:
            signals = pred_disclosure_signals(output)
            bucket = per_type_disc.setdefault(vtype, {"cov_tp": 0, "cov_fn": 0})
            for gold_disc in record.labels.required_disclosures:
                if disclosure_hit(gold_disc, signals["required"]):
                    disc_cov_tp += 1; bucket["cov_tp"] += 1; pn["cov_tp"] += 1
                else:
                    disc_cov_fn += 1; bucket["cov_fn"] += 1; pn["cov_fn"] += 1
                if disclosure_hit(gold_disc, signals["missing"]):
                    disc_miss_tp += 1
                else:
                    disc_miss_fn += 1

        # D routing
        gold_r = record.labels.expected_routing or ""
        pred_r = summary.predicted_routing or ""
        if gold_r in ROUTING_VALUES and pred_r in ROUTING_VALUES:
            routing_matrix[gold_r][pred_r] += 1
            routing_total += 1
            if gold_r == pred_r:
                routing_exact += 1
            elif frozenset({gold_r, pred_r}) in ADJACENT_ROUTING:
                routing_adjacent += 1

        # E per-type detection recall
        if gold_v:
            tb = per_type.setdefault(vtype, {"tp": 0, "fn": 0})
            tb["tp" if pred_v else "fn"] += 1

        # F clean control
        if not gold_v:
            clean_total += 1
            if summary.predicted_routing == "reject":
                clean_reject += 1
            if summary.predicted_routing != "pass_candidate":
                clean_non_pass += 1

    return {
        "record_count": len(records),
        "axes": {
            "A_violation_detection": {
                "description": "final_verdict∈{reject,revise} vs gold.violation (이진)",
                "counts": {"tp": a_tp, "fp": a_fp, "fn": a_fn, "tn": a_tn},
                **_prf(a_tp, a_fp, a_fn),
            },
            "B_articles": {
                "description": "gold.articles vs 예측 조문 — 정확일치(조 레벨) vs 위임사슬 계열병합",
                "exact_match": _multilabel_counts(gold_exact, pred_exact),
                "family_merged": _multilabel_counts(gold_fam, pred_fam),
            },
            "C_required_disclosures": {
                "description": "gold.required_disclosures vs 파이프라인 disclosure_requirements(커버리지)·missing(누락검출) 키워드 대조",
                "coverage_recall": {"detected": disc_cov_tp, "total": disc_cov_tp + disc_cov_fn, "recall": round(disc_cov_tp / (disc_cov_tp + disc_cov_fn), 4) if (disc_cov_tp + disc_cov_fn) else 0.0},
                "missing_detection_recall": {"detected": disc_miss_tp, "total": disc_miss_tp + disc_miss_fn, "recall": round(disc_miss_tp / (disc_miss_tp + disc_miss_fn), 4) if (disc_miss_tp + disc_miss_fn) else 0.0},
            },
            "D_routing_confusion": {
                "description": "gold.expected_routing vs final_verdict (4x4) + 인접오차",
                "matrix": routing_matrix,
                "exact_accuracy": round(routing_exact / routing_total, 4) if routing_total else 0.0,
                "within_one_accuracy": round((routing_exact + routing_adjacent) / routing_total, 4) if routing_total else 0.0,
                "total": routing_total,
            },
            "E_violation_type_recall": {
                "description": "택소노미 코드는 파이프라인 미출력 → 정확-코드 매칭 N/A; 유형별 위반검출률(recall)로 환산",
                "exact_code_match": "N/A (라벨공간 불일치)",
                "per_type": {
                    vtype: {"mutations": b["tp"] + b["fn"], "detected": b["tp"], "recall": round(b["tp"] / (b["tp"] + b["fn"]), 4) if (b["tp"] + b["fn"]) else 0.0}
                    for vtype, b in sorted(per_type.items())
                },
                "per_type_disclosure_coverage": {
                    vtype: {"detected": b["cov_tp"], "total": b["cov_tp"] + b["cov_fn"], "recall": round(b["cov_tp"] / (b["cov_tp"] + b["cov_fn"]), 4) if (b["cov_tp"] + b["cov_fn"]) else 0.0}
                    for vtype, b in sorted(per_type_disc.items())
                },
            },
            "F_clean_control_overblocking": {
                "description": "clean(violation=false) 대조군 오탐 — reject면 FP, non-pass면 soft FP",
                "clean_total": clean_total,
                "reject_fp": clean_reject,
                "non_pass": clean_non_pass,
                "overblocking_rate": round(clean_reject / clean_total, 4) if clean_total else 0.0,
                "clean_non_pass_rate": round(clean_non_pass / clean_total, 4) if clean_total else 0.0,
            },
        },
        "per_product_group": {
            group: {"counts": b, **_prf(b["tp"], b["fp"], b["fn"])}
            for group, b in sorted(per_group.items())
        },
        "selected_product_names": sorted(per_product_name.keys()),
        "per_product_name": {
            pname: {
                "records": b["records"],
                "violation_detection": {"tp": b["det_tp"], "fp": b["det_fp"], "fn": b["det_fn"], **_prf(b["det_tp"], b["det_fp"], b["det_fn"])},
                "required_disclosure_coverage": {
                    "detected": b["cov_tp"],
                    "total": b["cov_tp"] + b["cov_fn"],
                    "recall": round(b["cov_tp"] / (b["cov_tp"] + b["cov_fn"]), 4) if (b["cov_tp"] + b["cov_fn"]) else 0.0,
                },
            }
            for pname, b in sorted(per_product_name.items())
        },
        "product_selection_note": (
            "3-way 심사 상품결속 구분: 합성셋=상품명 선택(selected_product, 전건 특정 상품문서 오픈) · "
            "JB 실광고(run_jbbank_eval)=상품군만(product_group_only, 실광고라 상품 매핑 없음) · "
            "크롤링 위반스윕=미선택. 상품명 선택 레그에서만 required_disclosures 채점이 유효."
        ),
    }


# ---- 레코드별 통과 검증(record view) — 집계 축과 동일 로직을 레코드 단위로 재적용 ----
#
# overall_pass 정의(정직성 원칙: needs_review 유보를 통과로 세지 않는다):
#   violation ∧ article_family ∧ routing_pass ∧ disclosures_pass
#   - violation        : gold.violation == pred.predicted_violation(final_verdict∈{reject,revise})
#   - article_family   : 위임사슬 계열(article_family, compare_guideline_vlm 재사용) 교집합 ≠ ∅
#                        (gold에 조문이 없는 클린 레코드는 자동 통과)
#   - routing_pass     : routing.exact 이거나, (routing.adjacent ∧ pred_routing != "needs_review").
#                        인접(adjacent)에는 needs_review↔revise, needs_review↔pass_candidate 쌍이
#                        포함되는데, pred가 needs_review(유보)인 경우는 gold와 정확히 일치할 때만
#                        (즉 gold도 needs_review일 때만) 통과로 인정한다 — 유보를 근접 매칭으로
#                        얼버무려 통과로 세지 않기 위함.
#   - disclosures_pass : gold_n == 0 이거나 matched_n == gold_n (필수고지 완전 재현율).
# ARTICLE_EXACT/ARTICLE_FAMILY/DISCLOSURES/ROUTING 필드는 축 B/C/D의 동일 함수(article_family,
# disclosure_hit, pred_disclosure_signals, ADJACENT_ROUTING)를 그대로 재사용한다 — 새 규칙 없음.
OVERALL_PASS_DEFINITION = (
    "violation ∧ article_family ∧ (routing.exact ∨ (routing.adjacent ∧ pred_routing≠needs_review)) "
    "∧ disclosures(matched_n==gold_n). needs_review 예측은 gold도 needs_review로 정확히 일치할 때만 "
    "통과로 인정 — 인접성만으로 유보(hold)를 통과로 세지 않는다."
)


def compute_record_match(
    record: EvaluationRecord,
    output: dict[str, Any],
    summary: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """레코드 하나의 축별 match 판정 + overall_pass. 집계(build())와 동일 로직 재사용."""
    gold_v = record.labels.violation
    pred_v = bool(summary.get("predicted_violation"))
    violation_match = gold_v == pred_v

    pred_articles = list(summary.get("predicted_articles") or [])
    gold_articles = record.labels.articles

    g_exact = {canonical_article(a) for a in gold_articles if a}
    p_exact = {canonical_article(a) for a in pred_articles if a}
    article_exact = (not g_exact) or bool(g_exact & p_exact)

    g_fam = {article_family(a) for a in gold_articles if a}
    p_fam = {article_family(a) for a in pred_articles if a}
    article_fam_match = (not g_fam) or bool(g_fam & p_fam)

    gold_disc = record.labels.required_disclosures
    signals = pred_disclosure_signals(output)
    gold_n = len(gold_disc)
    matched_n = sum(1 for d in gold_disc if disclosure_hit(d, signals["required"]))
    disc_recall = round(matched_n / gold_n, 4) if gold_n else 1.0

    gold_r = record.labels.expected_routing
    pred_r = str(summary.get("predicted_routing") or "")
    routing_exact = bool(gold_r) and gold_r == pred_r
    routing_adjacent = (
        gold_r in ROUTING_VALUES and pred_r in ROUTING_VALUES and frozenset({gold_r, pred_r}) in ADJACENT_ROUTING
    )

    matches = {
        "violation": violation_match,
        "article_exact": article_exact,
        "article_family": article_fam_match,
        "disclosures": {"gold_n": gold_n, "matched_n": matched_n, "recall": disc_recall},
        "routing": {"gold": gold_r, "pred": pred_r, "exact": routing_exact, "adjacent": routing_adjacent},
    }

    routing_pass = routing_exact or (routing_adjacent and pred_r != "needs_review")
    disclosures_pass = gold_n == 0 or matched_n == gold_n
    overall_pass = violation_match and article_fam_match and routing_pass and disclosures_pass
    return matches, overall_pass


def augment_report_with_matches(
    report: dict[str, Any],
    records: list[EvaluationRecord],
    predictions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """evaluate.evaluate_records() 산출물의 records에 matches/overall_pass를 채운다.

    report["records"]는 evaluate_records가 ``records`` 인자와 동일한 순서로 만들므로
    zip으로 짝지어 라이브 재심사 없이 기존 예측(predictions)만으로 채점한다.
    """
    for row, record in zip(report["records"], records, strict=True):
        output = predictions.get(record.record_id) or {}
        matches, overall_pass = compute_record_match(record, output, row["prediction"])
        row["matches"] = matches
        row["overall_pass"] = overall_pass
    report["overall_pass_definition"] = OVERALL_PASS_DEFINITION
    pass_count = sum(1 for row in report["records"] if row["overall_pass"])
    report["overall_pass_summary"] = {
        "pass": pass_count,
        "total": len(report["records"]),
        "rate": round(pass_count / len(report["records"]), 4) if report["records"] else 0.0,
    }
    return report


def build_metrics_report(
    records: list[EvaluationRecord],
    predictions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """evaluate.py의 evaluate_records()에 레코드별 match/overall_pass를 얹은 최종 리포트."""
    report = evaluate_records(records, predictions)
    return augment_report_with_matches(report, records, predictions)


def to_markdown(report: dict[str, Any], *, title: str, model: str) -> str:
    ax = report["axes"]
    a = ax["A_violation_detection"]
    b = ax["B_articles"]
    c = ax["C_required_disclosures"]
    d = ax["D_routing_confusion"]
    e = ax["E_violation_type_recall"]
    f = ax["F_clean_control_overblocking"]
    lines = [
        f"# {title}",
        "",
        f"- 심사 모델: **{model}**  |  총 레코드: **{report['record_count']}**",
        "- 각 축은 gold 라벨의 서로 다른 필드를 대조한다(축별 설명 병기). 정확일치·계열병합 두 수치를 나란히 보고해 과대·과소평가를 모두 방지.",
        "",
        "## A. 위반검출(이진)",
        f"> {a['description']}",
        "",
        f"- 정밀도 **{a['precision']:.3f}** · 재현율 **{a['recall']:.3f}** · F1 **{a['f1']:.3f}**",
        f"- TP {a['counts']['tp']} / FP {a['counts']['fp']} / FN {a['counts']['fn']} / TN {a['counts']['tn']}",
        "",
        "## B. 조문(article) 멀티라벨 — 정확일치 vs 위임사슬 계열병합",
        f"> {b['description']}",
        "",
        "| 방식 | TP | FP | FN | 정밀도 | 재현율 | F1 |",
        "|------|---:|---:|---:|-------:|-------:|---:|",
        f"| 정확일치(조 레벨) | {b['exact_match']['counts']['tp']} | {b['exact_match']['counts']['fp']} | {b['exact_match']['counts']['fn']} | {b['exact_match']['precision']:.3f} | {b['exact_match']['recall']:.3f} | {b['exact_match']['f1']:.3f} |",
        f"| 계열병합(위임사슬) | {b['family_merged']['counts']['tp']} | {b['family_merged']['counts']['fp']} | {b['family_merged']['counts']['fn']} | {b['family_merged']['precision']:.3f} | {b['family_merged']['recall']:.3f} | {b['family_merged']['f1']:.3f} |",
        "",
        "## C. required_disclosures 재현율 (이 데이터셋의 1급 지표)",
        f"> {c['description']}",
        "",
        f"- 커버리지 재현율(파이프라인이 해당 고지를 필수로 인지): **{c['coverage_recall']['recall']:.3f}** ({c['coverage_recall']['detected']}/{c['coverage_recall']['total']})",
        f"- 누락검출 재현율(실제 누락으로 플래그): **{c['missing_detection_recall']['recall']:.3f}** ({c['missing_detection_recall']['detected']}/{c['missing_detection_recall']['total']})",
        "",
        "## D. expected_routing 혼동행렬",
        f"> {d['description']}",
        "",
        f"- 정확일치 정확도 **{d['exact_accuracy']:.3f}** · 인접(±1) 포함 **{d['within_one_accuracy']:.3f}** (n={d['total']})",
        "",
        "| gold \\ pred | " + " | ".join(ROUTING_VALUES) + " |",
        "|" + "---|" * (len(ROUTING_VALUES) + 1),
    ]
    for g in ROUTING_VALUES:
        row = d["matrix"][g]
        lines.append(f"| {g} | " + " | ".join(str(row[p]) for p in ROUTING_VALUES) + " |")
    lines += [
        "",
        "## E. 위반 유형별 검출률 (택소노미 코드 정확매칭 N/A)",
        f"> {e['description']}",
        "",
        "| 유형 | 변이 수 | 검출 | 검출률 | 고지 커버리지 |",
        "|------|--------:|-----:|-------:|-------------:|",
    ]
    disc_by_type = e["per_type_disclosure_coverage"]
    for vtype, rec in e["per_type"].items():
        dc = disc_by_type.get(vtype)
        dc_str = f"{dc['recall']:.3f} ({dc['detected']}/{dc['total']})" if dc else "—"
        lines.append(f"| {vtype} | {rec['mutations']} | {rec['detected']} | {rec['recall']:.3f} | {dc_str} |")
    lines += [
        "",
        "## F. clean 대조군 오탐(overblocking)",
        f"> {f['description']}",
        "",
        f"- clean {f['clean_total']}건 중 reject(FP) **{f['reject_fp']}** (과차단율 {f['overblocking_rate']:.3f}), non-pass {f['non_pass']} (soft {f['clean_non_pass_rate']:.3f})",
        "",
        "## 상품군별 위반검출",
        "",
        "| 상품군 | TP | FP | FN | TN | 정밀도 | 재현율 | F1 |",
        "|--------|---:|---:|---:|---:|-------:|-------:|---:|",
    ]
    for group, gb in report["per_product_group"].items():
        cc = gb["counts"]
        lines.append(f"| {group} | {cc['tp']} | {cc['fp']} | {cc['fn']} | {cc['tn']} | {gb['precision']:.3f} | {gb['recall']:.3f} | {gb['f1']:.3f} |")
    lines += [
        "",
        "## 선택 상품명별 (상품명 선택 심사 — product_group 뭉갬 해소)",
        "",
        "| 선택 상품명 | 레코드 | 위반검출 P | 위반검출 R | 필수고지 커버리지 |",
        "|-------------|-------:|----------:|----------:|-----------------:|",
    ]
    for pname, pb in report["per_product_name"].items():
        vd = pb["violation_detection"]
        cov = pb["required_disclosure_coverage"]
        cov_str = f"{cov['recall']:.3f} ({cov['detected']}/{cov['total']})" if cov["total"] else "—"
        lines.append(f"| {pname} | {pb['records']} | {vd['precision']:.3f} | {vd['recall']:.3f} | {cov_str} |")
    lines += ["", f"> {report['product_selection_note']}", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=Path(__file__).resolve().parent / "violation_taxonomy_v0_2.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "synth_v0_2_report.md")
    parser.add_argument("--json-output", type=Path, default=Path(__file__).resolve().parent / "synth_v0_2_breakdown.json")
    parser.add_argument("--model", default="claude-opus-4-8")
    parser.add_argument("--title", default="합성 v0.2 평가 — 라벨 정합 채점(정확일치 vs 계열병합)")
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=Path(__file__).resolve().parent / "synth_v0_2_metrics.json",
        help=(
            "레코드별 통과 검증(gold 전체 필드 + matches + overall_pass)을 담은 "
            "evaluate.py 계약 리포트 출력 경로. 라이브 재심사 없이 --records/--predictions로만 "
            "재계산한다. 비우려면 --metrics-output ''"
        ),
    )
    args = parser.parse_args()

    records = load_records(args.records)
    predictions = load_predictions(args.predictions)
    report = build(records, predictions, code_to_type(args.taxonomy))
    report["review_model"] = args.model
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(to_markdown(report, title=args.title, model=args.model), encoding="utf-8")
    if args.json_output:
        args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.metrics_output:
        metrics_report = build_metrics_report(records, predictions)
        args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_output.write_text(json.dumps(metrics_report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"metrics report written: {args.metrics_output} (overall_pass rate={metrics_report['overall_pass_summary']})")
    print(json.dumps(report["axes"]["A_violation_detection"], ensure_ascii=False))
    print("articles exact vs family f1:", report["axes"]["B_articles"]["exact_match"]["f1"], report["axes"]["B_articles"]["family_merged"]["f1"])
    print("disclosure coverage recall:", report["axes"]["C_required_disclosures"]["coverage_recall"]["recall"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
