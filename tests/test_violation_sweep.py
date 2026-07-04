"""Unit tests for the violation-detection sweep + report (stub run dicts only).

No live review, Neo4j, or LLM required: stratified sampling, checkpoint/resume,
run-dict extraction, and report aggregation are all exercised against fixtures.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import violation_sweep_lib as lib
import scripts_violation_sweep as sweep
import scripts_violation_report as report


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
BANK_POPULATION = {
    "kb": ("국민은행", 852),
    "hana": ("하나은행", 549),
    "jb": ("전북은행", 364),
    "woori": ("우리은행", 358),
    "shinhan": ("신한은행", 40),
}


def _write_dataset(path: Path) -> None:
    fields = ["review_id", "bank_key", "bank_label", "title", "review_text", "review_text_chars", "representative_source"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for bank_key, (label, count) in BANK_POPULATION.items():
            for i in range(count):
                text = "광고 문구 " * (i % 5 + 1)
                writer.writerow({
                    "review_id": f"{bank_key}_{i:04d}",
                    "bank_key": bank_key,
                    "bank_label": label,
                    "title": f"{label} 이벤트 {i}",
                    "review_text": text,
                    "review_text_chars": len(text),
                    "representative_source": "pc_baseline",
                })


def _stub_run(*, review_run_id: str = "run_test") -> dict:
    """A run dict shaped like runs/review_run_*.json with one violation + Track B risk."""
    return {
        "review_run_id": review_run_id,
        "final_verdict": "reject",
        "routing": {"ad_scope": "AD"},
        "cu_plan": [
            {"cu_id": "KR-CU-01", "principle": "부당표시광고", "source_article": "표시광고법 제3조", "subject": "허위·과장"},
            {"cu_id": "KR-CU-09", "principle": "필수고지", "source_article": "은행광고심의 제16조", "subject": "금리표시"},
        ],
        "effective_judgments": [
            {"cu_id": "KR-CU-01", "verdict": "NON_COMPLIANT", "score": 0.9,
             "legal_basis": "표시광고법 제3조 위반", "evidence_span": "무조건 최고금리 보장", "why": "단정적 표현"},
            {"cu_id": "KR-CU-09", "verdict": "INSUFFICIENT", "score": 0.4,
             "legal_basis": "금리 산정근거 불충분", "evidence_span": "연 5%", "why": "근거 부족"},
            {"cu_id": "KR-CU-03", "verdict": "COMPLIANT", "score": 0.1,
             "legal_basis": "", "evidence_span": "안내", "why": "문제 없음"},
            {"cu_id": "KR-CU-04", "verdict": "NOT_APPLICABLE", "score": 0.0,
             "legal_basis": "", "evidence_span": "", "why": ""},
        ],
        "disclosure_requirements": [
            {"id": "disclosure_deposit_rate_basis", "label": "금리 범위 및 산정방법",
             "source": "은행광고심의 제16조", "why": "오인 방지"},
        ],
        "overall_impression_judgment": {
            "track": "B", "standard": "대법원 2017두60109", "verdict": "HIGH",
            "misleading_risk_score": 0.72, "why": "전체 인상이 오인 유발",
        },
        "article_aggregation": [
            {"key": "표시광고법 제3조", "article": "표시광고법 제3조", "principles": ["부당표시광고"],
             "effective_verdict": "NON_COMPLIANT", "max_score": 0.9, "cu_count": 1, "issue_count": 1,
             "cu_titles": ["허위·과장"], "anchor_spans": ["무조건 최고금리 보장"]},
        ],
        "principle_aggregation": [
            {"key": "부당표시광고", "article": "표시광고법 제3조", "principles": ["부당표시광고"],
             "effective_verdict": "NON_COMPLIANT", "max_score": 0.9, "cu_count": 1, "issue_count": 1,
             "cu_titles": ["허위·과장"], "anchor_spans": ["무조건 최고금리 보장"]},
        ],
        "policy_evidence_chains": {
            "legal_basis_chains": [1, 2], "disclosure_chains": [1], "exception_chains": [], "chain_diagnostics": [1],
        },
    }


# --------------------------------------------------------------------------- #
# Stratified sampling
# --------------------------------------------------------------------------- #
def test_allocate_counts_hamilton_pilot50():
    sizes = {key: count for key, (_, count) in BANK_POPULATION.items()}
    alloc = lib.allocate_counts(sizes, 50)
    assert sum(alloc.values()) == 50
    assert alloc == {"kb": 20, "hana": 13, "jb": 8, "woori": 8, "shinhan": 1}


def test_allocate_counts_never_exceeds_group():
    alloc = lib.allocate_counts({"a": 3, "b": 1}, 100)
    assert alloc == {"a": 3, "b": 1}  # capped at availability


def test_stratified_sample_matches_expected_distribution(tmp_path):
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    rows = lib.load_dataset(csv_path)
    assert len(rows) == sum(c for _, c in BANK_POPULATION.values())

    sampled = lib.stratified_sample(rows, 50, seed=42)
    counts = {}
    for row in sampled:
        counts[row.bank_key] = counts.get(row.bank_key, 0) + 1
    assert counts == {"kb": 20, "hana": 13, "jb": 8, "woori": 8, "shinhan": 1}
    assert len(sampled) == 50


def test_stratified_sample_is_reproducible(tmp_path):
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    rows = lib.load_dataset(csv_path)
    a = [r.review_id for r in lib.stratified_sample(rows, 50, seed=42)]
    b = [r.review_id for r in lib.stratified_sample(rows, 50, seed=42)]
    c = [r.review_id for r in lib.stratified_sample(rows, 50, seed=7)]
    assert a == b
    assert a != c  # different seed -> different (but valid) sample


def test_load_dataset_limit_chars_filters_long_rows(tmp_path):
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    all_rows = lib.load_dataset(csv_path)
    short = lib.load_dataset(csv_path, limit_chars=20)
    assert len(short) < len(all_rows)
    assert all(r.review_text_chars <= 20 for r in short)


def test_load_dataset_bank_filter(tmp_path):
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    kb = lib.load_dataset(csv_path, bank="kb")
    assert all(r.bank_key == "kb" for r in kb)
    assert len(kb) == 852


# --------------------------------------------------------------------------- #
# Run-dict extraction
# --------------------------------------------------------------------------- #
def test_extract_violations_only_violation_verdicts():
    viol = lib.extract_violations(_stub_run())
    verdicts = {v["verdict"] for v in viol}
    assert verdicts == {"NON_COMPLIANT", "INSUFFICIENT"}
    # cu metadata enriched from cu_plan
    nc = next(v for v in viol if v["verdict"] == "NON_COMPLIANT")
    assert nc["principle"] == "부당표시광고"
    assert nc["source_article"] == "표시광고법 제3조"


def test_summarize_run_shape():
    summary = lib.summarize_run(_stub_run())
    assert summary["violation_count"] == 2
    assert summary["final_verdict"] == "reject"
    assert summary["overall_impression_risk"] is True
    assert summary["policy_evidence_chain_counts"]["legal_basis_chains"] == 2
    assert len(summary["disclosure_requirements"]) == 1


def test_overall_impression_risk_threshold():
    assert lib.is_overall_impression_risk({"verdict": "HIGH"}) is True
    assert lib.is_overall_impression_risk({"verdict": "MEDIUM"}) is True
    assert lib.is_overall_impression_risk({"verdict": "LOW"}) is False
    assert lib.is_overall_impression_risk({}) is False


def test_build_item_record_failed_has_no_run_data():
    row = lib.DatasetRow("kb_0001", "kb", "국민은행", "t", "text", 4)
    record = lib.build_item_record(row, status="failed", error="RuntimeError: no LLM key")
    assert record["status"] == "failed"
    assert record["violation_count"] == 0
    assert record["workspace_id"] == lib.KR_WORKSPACE_ID
    assert "no LLM key" in record["error"]


# --------------------------------------------------------------------------- #
# Checkpoint / resume
# --------------------------------------------------------------------------- #
def test_resume_skips_completed(tmp_path, monkeypatch):
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    rows = lib.stratified_sample(lib.load_dataset(csv_path), 10, seed=42)
    out_dir = tmp_path / "sweep"

    calls: list[str] = []

    def fake_run_one(row, workspace_id):
        calls.append(row.review_id)
        return _stub_run(review_run_id=f"run_{row.review_id}")

    monkeypatch.setattr(sweep, "_run_one", fake_run_one)

    stats1 = sweep.run_sweep(rows, out_dir, workspace_id=lib.KR_WORKSPACE_ID, concurrency=1, resume=True)
    assert stats1["completed"] == len(rows)
    first_calls = list(calls)
    assert len(first_calls) == len(rows)

    # Second run must skip everything already written.
    calls.clear()
    stats2 = sweep.run_sweep(rows, out_dir, workspace_id=lib.KR_WORKSPACE_ID, concurrency=1, resume=True)
    assert calls == []
    assert stats2["skipped"] == len(rows)
    # Every item persisted.
    assert len(list((out_dir / "items").glob("*.json"))) == len(rows)


def test_resume_retries_failed_items(tmp_path, monkeypatch):
    """Failed items must be retried on resume — only completed ids are skipped."""
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    rows = lib.stratified_sample(lib.load_dataset(csv_path), 4, seed=42)
    out_dir = tmp_path / "sweep"

    def boom(row, workspace_id):
        raise RuntimeError("no LLM credentials")

    monkeypatch.setattr(sweep, "_run_one", boom)
    first = sweep.run_sweep(rows, out_dir, workspace_id=lib.KR_WORKSPACE_ID, concurrency=1, resume=True)
    assert first["failed"] == len(rows)

    # Now credentials "work": re-run must reprocess the previously-failed items.
    calls: list[str] = []

    def ok(row, workspace_id):
        calls.append(row.review_id)
        return _stub_run(review_run_id=f"run_{row.review_id}")

    monkeypatch.setattr(sweep, "_run_one", ok)
    second = sweep.run_sweep(rows, out_dir, workspace_id=lib.KR_WORKSPACE_ID, concurrency=1, resume=True)
    assert len(calls) == len(rows)  # all retried, none skipped
    assert second["completed"] == len(rows)
    records = [json.loads(p.read_text(encoding="utf-8")) for p in (out_dir / "items").glob("*.json")]
    assert all(r["status"] == "completed" for r in records)


def test_skip_failed_keeps_failures_and_only_adds_new(tmp_path, monkeypatch):
    """--skip-failed: previously-failed ids are not retried; only new rows run."""
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    rows5 = lib.stratified_sample(lib.load_dataset(csv_path), 5, seed=42)
    out_dir = tmp_path / "sweep"

    # First pass: everything fails.
    monkeypatch.setattr(sweep, "_run_one", lambda row, ws: (_ for _ in ()).throw(RuntimeError("ctx")))
    sweep.run_sweep(rows5, out_dir, workspace_id=lib.KR_WORKSPACE_ID, concurrency=1, resume=True)

    # Extend to a superset; credentials now work. With skip_failed, the 5 failed
    # ids must NOT be retried — only genuinely-new rows execute.
    rows10 = lib.stratified_sample(lib.load_dataset(csv_path), 10, seed=42)
    assert set(r.review_id for r in rows5).issubset(r.review_id for r in rows10)  # superset property
    calls: list[str] = []
    monkeypatch.setattr(sweep, "_run_one", lambda row, ws: calls.append(row.review_id) or _stub_run())
    stats = sweep.run_sweep(
        rows10, out_dir, workspace_id=lib.KR_WORKSPACE_ID, concurrency=1, resume=True, skip_failed=True
    )
    failed_ids = {r.review_id for r in rows5}
    assert not (set(calls) & failed_ids)  # none of the failed ids retried
    assert set(calls) == {r.review_id for r in rows10} - failed_ids  # exactly the new ones
    assert stats["skipped"] == len(failed_ids)


def test_failed_item_recorded_not_silently_dropped(tmp_path, monkeypatch):
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    rows = lib.stratified_sample(lib.load_dataset(csv_path), 6, seed=42)
    out_dir = tmp_path / "sweep"

    def boom(row, workspace_id):
        raise RuntimeError("no LLM credentials")

    monkeypatch.setattr(sweep, "_run_one", boom)
    stats = sweep.run_sweep(rows, out_dir, workspace_id=lib.KR_WORKSPACE_ID, concurrency=1, resume=True)
    assert stats["failed"] == len(rows)
    records = [json.loads(p.read_text(encoding="utf-8")) for p in (out_dir / "items").glob("*.json")]
    assert records and all(r["status"] == "failed" and "no LLM credentials" in r["error"] for r in records)


# --------------------------------------------------------------------------- #
# Report aggregation
# --------------------------------------------------------------------------- #
def _write_items(out_dir: Path, records: list[dict]) -> None:
    items_dir = out_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        (items_dir / f"{record['review_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )


def test_report_aggregate_and_render(tmp_path):
    out_dir = tmp_path / "sweep"
    good = lib.build_item_record(
        lib.DatasetRow("kb_0001", "kb", "국민은행", "이벤트", "text", 4),
        status="completed", run=_stub_run(),
    )
    clean = lib.build_item_record(
        lib.DatasetRow("hana_0002", "hana", "하나은행", "안내", "text", 4),
        status="completed",
        run={"final_verdict": "approve", "effective_judgments": [], "overall_impression_judgment": {"verdict": "LOW"}},
    )
    failed = lib.build_item_record(
        lib.DatasetRow("jb_0003", "jb", "전북은행", "t", "text", 4),
        status="failed", error="RuntimeError: boom",
    )
    _write_items(out_dir, [good, clean, failed])

    items = report.load_items(out_dir)
    agg = report.aggregate(items)
    assert agg["total"] == 3
    assert agg["completed"] == 2
    assert agg["failed"] == 1
    assert agg["flagged"] == 1  # only the kb item has violations
    assert len(agg["overall_impression_risks"]) == 1

    rows = report.violation_rows(items)
    assert len(rows) == 2  # NON_COMPLIANT + INSUFFICIENT from the kb item
    md = report.render_report_md(agg, items, out_dir)
    assert "위반 검출" in md
    assert "국민은행" in md
    assert "부당표시광고" in md
    assert "RuntimeError: boom" in md


def test_report_main_writes_outputs(tmp_path):
    out_dir = tmp_path / "sweep"
    good = lib.build_item_record(
        lib.DatasetRow("kb_0001", "kb", "국민은행", "이벤트", "text", 4),
        status="completed", run=_stub_run(),
    )
    _write_items(out_dir, [good])
    rc = report.main(["--sweep-dir", str(out_dir)])
    assert rc == 0
    assert (out_dir / "report.md").exists()
    assert (out_dir / "violations.csv").exists()
    csv_text = (out_dir / "violations.csv").read_text(encoding="utf-8-sig")
    assert "review_id" in csv_text
    assert "kb_0001" in csv_text


# --------------------------------------------------------------------------- #
# Dry-run CLI (no live review)
# --------------------------------------------------------------------------- #
def test_sweep_dry_run_cli(tmp_path, capsys):
    csv_path = tmp_path / "ds.csv"
    _write_dataset(csv_path)
    rc = sweep.main(["--csv", str(csv_path), "--sample", "50", "--seed", "42", "--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sampled_total"] == 50
    plan_by_bank = {p["bank_key"]: p["sampled"] for p in payload["plan"]}
    assert plan_by_bank == {"kb": 20, "hana": 13, "jb": 8, "woori": 8, "shinhan": 1}
