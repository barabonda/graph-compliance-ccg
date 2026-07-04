"""`/api/eval/reports` 요약(`_eval_report_summary`) 단위 테스트.

리포트(실제 심사 결과 요약) vs 중간 산출물(batch·quality·grounding·metrics 중간본)
분류, report_kind(gold|live|synthetic|guideline|unknown) 판별, additive 필드
(model/product_selection/breakdown) 노출을 스텁 JSON으로 검증한다.

이 테스트는 eval/*.json 실물 산출물을 읽지 않는다 — evaluate.py/eval/ 산출물은
합성 에이전트 소유이며 이 모듈은 server.py 변경 대상 이외를 건드리지 않는다
(스텁만 사용해 회귀에 강하게 유지).
"""

from __future__ import annotations

import json
from pathlib import Path

from server import _classify_eval_report, _eval_breakdown_summary, _eval_report_summary


def _write(tmp_path: Path, name: str, payload: dict | None) -> Path:
    path = tmp_path / name
    if payload is None:
        path.write_text("# not json content\n", encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_gold_report_has_article_metrics_and_is_report_true(tmp_path: Path) -> None:
    payload = {
        "record_count": 13,
        "article_metrics": {
            "micro_f1": 0.29,
            "macro_f1": 0.07,
            "micro_f2": 0.41,
            "macro_f2": 0.07,
            "mcc": 0.15,
            "counts": {"tp": 1, "fp": 2, "fn": 0, "tn": 10},
            "per_article": {
                "articleA": {"tp": 1, "fp": 0, "fn": 0, "tn": 5, "f1": 1.0, "f2": 1.0},
                "articleB": {"tp": 0, "fp": 1, "fn": 1, "tn": 4, "f1": 0.0, "f2": 0.0},
            },
        },
        "ccg_metrics": {"violation_precision": 0.5, "violation_recall": 0.6},
    }
    path = _write(tmp_path, "regulator_vlm_full_report.json", payload)
    info = _eval_report_summary(path)

    assert info["is_report"] is True
    assert info["report_kind"] == "gold"
    # 기존 필드 회귀 없음.
    assert info["metrics"]["micro_f1"] == 0.29
    assert info["counts"] == {"tp": 1, "fp": 2, "fn": 0, "tn": 10}
    assert info["ccg_metrics"]["violation_precision"] == 0.5
    # 조문별 분해 top-N.
    assert info["breakdown"] == [
        {
            "dimension": "article",
            "top": [
                {"key": "articleA", "precision": 1.0, "recall": 1.0, "f1": 1.0, "support": 1},
                {"key": "articleB", "precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 1},
            ],
        }
    ]
    # 없는 필드는 생략.
    assert "model" not in info
    assert "product_selection" not in info


def test_live_report_flagged_via_kind_and_verdict_counts(tmp_path: Path) -> None:
    payload = {
        "kind": "jbbank_live_eval",
        "gold_available": False,
        "record_count": 13,
        "verdict_counts": {"needs_review": 8, "reject": 1, "revise": 4},
    }
    path = _write(tmp_path, "jbbank_eval_report.json", payload)
    info = _eval_report_summary(path)

    assert info["is_report"] is True
    assert info["report_kind"] == "live"
    assert info["verdict_counts"] == payload["verdict_counts"]
    assert info["gold_available"] is False


def test_synthetic_dataset_report_recognized_without_article_metrics(tmp_path: Path) -> None:
    payload = {
        "record_count": 100,
        "source_type_counts": {"synthetic_product_fact_clean": 20},
        "violation_type_counts": {"DEPOSIT_RATE_CONDITION_MISSING": 20},
        "clean_count": 20,
        "mutation_count": 60,
    }
    path = _write(tmp_path, "synthetic_product_fact_100_report.json", payload)
    info = _eval_report_summary(path)

    assert info["is_report"] is True
    assert info["report_kind"] == "synthetic"


def test_intermediate_quality_artifact_is_not_a_report(tmp_path: Path) -> None:
    """spec 예시: `quality.json` 류 중간 산출물은 'report'가 파일명에 없고
    article_metrics/verdict_counts/kind가 없으면 is_report=False."""
    payload = {
        "record_count": 22,
        "source_type_counts": {"synthetic_product_fact_mutation": 18},
        "duplicate_ids": [],
        "blocking_error_count": 0,
    }
    path = _write(tmp_path, "synth_v0_2_quality.json", payload)
    info = _eval_report_summary(path)

    assert info["is_report"] is False
    # report_kind는 is_report와 별개로 내용 기반 라벨을 유지한다(토글 시 배지용) —
    # 파일명에 'synth'가 있어 "synthetic"으로 분류되지만 카드 노출 여부는 is_report가 결정.
    assert info["report_kind"] == "synthetic"
    # 하드 필터가 아니라 플래그 — 기존처럼 요약 필드는 여전히 채워진다.
    assert info["record_count"] == 22


def test_guideline_markdown_report_recognized_by_filename(tmp_path: Path) -> None:
    path = _write(tmp_path, "guideline_vlm_report.md", None)
    info = _eval_report_summary(path)

    assert info["kind"] == "md"
    assert info["is_report"] is True
    assert info["report_kind"] == "guideline"


def test_non_report_markdown_is_not_flagged_as_report(tmp_path: Path) -> None:
    path = _write(tmp_path, "DATASET_CARD.md", None)
    info = _eval_report_summary(path)

    assert info["is_report"] is False
    assert info["report_kind"] == "unknown"


def test_future_synth_v0_2_breakdown_report_shape_is_safe(tmp_path: Path) -> None:
    """synth_v0_2_breakdown.py가 만드는 아직 없는 리포트의 예상 shape(부재 안전 —
    파일이 실제로 없어도 이 테스트는 스텁으로 shape만 검증한다)."""
    payload = {
        "record_count": 22,
        "model": "claude-opus-4-8",
        "product_selection": {"selected": True, "workspace_id": "graphcompliance_mvp_jb_20260530"},
        "overall": {
            "counts": {"tp": 10, "fp": 2, "fn": 3, "tn": 7},
            "precision": 0.833,
            "recall": 0.769,
            "f1": 0.8,
        },
        "per_violation_type_recall": {
            "RATE_OVERSTATED_OR_STALE": {"mutations": 3, "detected": 2, "recall": 0.6667},
            "TAX_BENEFIT_LIMIT_OMITTED": {"mutations": 1, "detected": 1, "recall": 1.0},
        },
        "per_product_group": {
            "deposit": {"counts": {"tp": 4, "fp": 1, "fn": 1, "tn": 4}, "precision": 0.8, "recall": 0.8, "f1": 0.8},
            "loan": {"counts": {"tp": 6, "fp": 1, "fn": 2, "tn": 3}, "precision": 0.857, "recall": 0.75, "f1": 0.8},
        },
    }
    path = _write(tmp_path, "synth_v0_2_metrics.json", payload)
    info = _eval_report_summary(path)

    assert info["is_report"] is True
    assert info["report_kind"] == "synthetic"
    assert info["model"] == "claude-opus-4-8"
    assert info["product_selection"] == payload["product_selection"]
    dims = {b["dimension"] for b in info["breakdown"]}
    assert dims == {"violation_type", "product_group"}
    vt_block = next(b for b in info["breakdown"] if b["dimension"] == "violation_type")
    assert vt_block["top"][0]["key"] == "RATE_OVERSTATED_OR_STALE"  # support(mutations) 내림차순


def test_absent_synth_v0_2_report_file_does_not_break_listing(tmp_path: Path) -> None:
    """파일이 아직 없을 때 목록 엔드포인트 쪽에서 정상적으로 없는 채로 넘어가는지는
    eval_reports()가 존재하는 파일만 순회하므로 자연히 안전하다 — 이 테스트는
    그 계약을 명시적으로 문서화한다."""
    missing = tmp_path / "synth_v0_2_metrics.json"
    assert not missing.exists()


def test_corrupted_json_still_gets_report_flags(tmp_path: Path) -> None:
    path = tmp_path / "broken_report.json"
    path.write_text("{not valid json", encoding="utf-8")
    info = _eval_report_summary(path)

    assert info["is_report"] is True  # 파일명에 'report' 포함 — 손상돼도 플래그는 살아있음.
    assert info["report_kind"] == "unknown"
    assert "record_count" not in info


def test_classify_eval_report_helper_priority_order() -> None:
    # kind/verdict_counts가 article_metrics보다 우선(라이브 로그가 gold 필드를 겸유해도 live).
    is_report, kind = _classify_eval_report(
        "mixed.json", {"kind": "jbbank_live_eval", "article_metrics": {"micro_f1": 1.0}}
    )
    assert (is_report, kind) == (True, "live")


def test_breakdown_summary_returns_none_when_no_known_shape() -> None:
    assert _eval_breakdown_summary({"record_count": 5}) is None
