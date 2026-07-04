"""Real-product violation-detection sweep over the compliance_review_text dataset.

Drives the product-unselected review path (same entry point as
``review_ad.py --text``) across a bank-proportional stratified sample of real
KR bank advertising records, and persists a violation-focused summary per item.

This is a *violation-discovery sweep*, not an accuracy benchmark: there are no
gold labels, the goal is to surface regulatory-guideline violations in real ads.

Usage:
  # Plan-only (no live review; CSV parse + stratified sample + plan):
  python3 scripts_violation_sweep.py --csv <dataset.csv> --sample 50 --seed 42 --dry-run

  # Live sweep (requires LLM + Neo4j; run only after the pipeline QA passes):
  python3 scripts_violation_sweep.py --csv <dataset.csv> --sample 50 --seed 42 \
      --concurrency 2 --out-dir eval/violation_sweep/pilot50

Resume: re-running with the same --out-dir skips review_ids that already have an
items/{review_id}.json record (checkpoint recovery / scope extension).

Contract: no deterministic fallback. If the live review path lacks credentials
(LLM/Neo4j), each item fails loudly and is recorded as a failed item — it is not
silently downgraded to a rule-only result.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from env_loader import load_local_env
from violation_sweep_lib import (
    KR_WORKSPACE_ID,
    DatasetRow,
    build_item_record,
    load_dataset,
    sample_plan,
    stratified_sample,
)

logger = logging.getLogger("violation_sweep")


def _default_sweep_id() -> str:
    return "sweep_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _done_review_ids(items_dir: Path, *, skip_failed: bool = False) -> set[str]:
    """review_ids already treated as done for checkpoint/resume.

    Completed items are always skipped (spec: skip "이미 완료된" ids). By default a
    previously *failed* item is retried on the next run. When ``skip_failed`` is
    set, failed items are also treated as done and left untouched — used when
    extending a sweep without re-attempting known failures.
    """
    if not items_dir.exists():
        return set()
    done: set[str] = set()
    for path in items_dir.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        status = record.get("status")
        if status == "completed" or (skip_failed and status == "failed"):
            done.add(record.get("review_id") or path.stem)
    return done


def _run_one(row: DatasetRow, workspace_id: str) -> dict[str, Any]:
    """Execute a single live review and return the JSON-able run dict.

    Imports the workflow lazily so --dry-run never touches Neo4j/LLM modules.
    """
    # Imported here (not at module top) to keep the dry-run path import-light.
    from workflow import GraphComplianceCCGWorkflow, review_input_from_payload
    from utils import to_jsonable

    payload = {
        "dataset_item_id": row.review_id,
        "title": row.title,
        "content_text": row.review_text,
        "channel": row.channel,
        "source_type": row.source_type,
        "product_group": "auto",
        "workspace_id": workspace_id,
    }
    review_input = review_input_from_payload(payload)
    output = GraphComplianceCCGWorkflow().review(review_input)
    return to_jsonable(output)


def _write_item(items_dir: Path, record: dict[str, Any]) -> None:
    items_dir.mkdir(parents=True, exist_ok=True)
    path = items_dir / f"{record['review_id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic-ish rename so a crash never leaves a half file


def run_sweep(
    rows: list[DatasetRow],
    out_dir: Path,
    *,
    workspace_id: str,
    concurrency: int,
    resume: bool,
    skip_failed: bool = False,
) -> dict[str, int]:
    """Execute the sweep over ``rows``, writing per-item JSON + index.jsonl."""
    items_dir = out_dir / "items"
    index_path = out_dir / "index.jsonl"
    done = _done_review_ids(items_dir, skip_failed=skip_failed) if resume else set()

    pending = [row for row in rows if row.review_id not in done]
    logger.info(
        "sweep start: %d rows, %d already done (skipped), %d to run, concurrency=%d",
        len(rows), len(done), len(pending), concurrency,
    )

    stats = {"completed": 0, "failed": 0, "skipped": len(rows) - len(pending)}
    write_lock = threading.Lock()
    start = time.perf_counter()
    processed = 0
    total = len(pending)

    def _task(row: DatasetRow) -> dict[str, Any]:
        item_start = time.perf_counter()
        try:
            run = _run_one(row, workspace_id)
            return build_item_record(
                row, status="completed", run=run, duration_sec=time.perf_counter() - item_start
            )
        except Exception as exc:  # noqa: BLE001 — record failure, keep sweeping
            logger.warning("item failed: %s: %s: %s", row.review_id, type(exc).__name__, exc)
            return build_item_record(
                row,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                duration_sec=time.perf_counter() - item_start,
            )

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(_task, row): row for row in pending}
        for future in as_completed(futures):
            record = future.result()
            with write_lock:
                _write_item(items_dir, record)
                with index_path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "review_id": record["review_id"],
                                "bank_key": record["bank_key"],
                                "status": record["status"],
                                "final_verdict": record.get("final_verdict"),
                                "violation_count": record.get("violation_count", 0),
                                "overall_impression_risk": record.get("overall_impression_risk", False),
                                "duration_sec": record.get("duration_sec"),
                                "ts": datetime.now(timezone.utc).isoformat(),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                processed += 1
                if record["status"] == "completed":
                    stats["completed"] += 1
                else:
                    stats["failed"] += 1
            elapsed = time.perf_counter() - start
            rate = processed / elapsed if elapsed > 0 else 0.0
            remaining = (total - processed) / rate if rate > 0 else 0.0
            logger.info(
                "%d/%d done (%.0fs elapsed, ~%.0fs remaining) — %s [%s] viol=%d",
                processed, total, elapsed, remaining,
                record["review_id"], record["status"], record.get("violation_count", 0),
            )
    return stats


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="Dataset CSV path.")
    parser.add_argument("--sample", type=int, default=None, help="Total stratified sample size (bank-proportional). Omit for full dataset.")
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed (reproducible).")
    parser.add_argument("--bank", default=None, help="Filter to a single bank_key or bank_label.")
    parser.add_argument("--limit-chars", type=int, default=None, help="Exclude rows whose review_text_chars exceeds this (cost control). Default: no limit.")
    parser.add_argument("--concurrency", type=int, default=2, help="Max concurrent reviews (kept low; multiplies with in-review parallelism).")
    parser.add_argument("--workspace-id", default=KR_WORKSPACE_ID, help="KR workspace (all rows are KR-jurisdiction).")
    parser.add_argument("--out-dir", default=None, help="Output dir. Default eval/violation_sweep/{sweep_id}/. Reuse to resume.")
    parser.add_argument("--no-resume", action="store_true", help="Do not skip already-completed review_ids.")
    parser.add_argument("--skip-failed", action="store_true", help="Also skip previously-failed review_ids (do not retry them). Default: failed items are retried.")
    parser.add_argument("--dry-run", action="store_true", help="Parse CSV, compute stratified sample + plan, print, and exit (no live review).")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)

    # Load .env (OPENAI_API_KEY, NEO4J_*) the same way the other CCG scripts do.
    # Cheap + safe even for --dry-run; the review path still fails loudly if a
    # required credential is genuinely absent (no deterministic fallback).
    load_local_env()

    rows = load_dataset(args.csv, limit_chars=args.limit_chars, bank=args.bank)
    logger.info("loaded %d eligible rows from %s", len(rows), args.csv)

    plan = sample_plan(rows, args.sample)
    sampled = stratified_sample(rows, args.sample, seed=args.seed)

    logger.info("=== stratified sample plan (seed=%d, sample=%s) ===", args.seed, args.sample)
    for entry in plan:
        logger.info(
            "  %-8s %-8s available=%4d  sampled=%4d",
            entry["bank_key"], entry["bank_label"], entry["available"], entry["sampled"],
        )
    logger.info("  TOTAL sampled=%d", len(sampled))

    if args.dry_run:
        preview = [
            {"review_id": r.review_id, "bank_key": r.bank_key, "chars": r.review_text_chars}
            for r in sampled[:10]
        ]
        print(json.dumps({
            "eligible_rows": len(rows),
            "sample": args.sample,
            "seed": args.seed,
            "plan": plan,
            "sampled_total": len(sampled),
            "sampled_preview": preview,
        }, ensure_ascii=False, indent=2))
        logger.info("dry-run: no live review executed.")
        return 0

    sweep_id = _default_sweep_id()
    out_dir = Path(args.out_dir) if args.out_dir else Path("eval/violation_sweep") / sweep_id
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "sweep_id": out_dir.name,
        "csv": str(args.csv),
        "sample": args.sample,
        "seed": args.seed,
        "bank": args.bank,
        "limit_chars": args.limit_chars,
        "concurrency": args.concurrency,
        "workspace_id": args.workspace_id,
        "sampled_total": len(sampled),
        "plan": plan,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = run_sweep(
        sampled,
        out_dir,
        workspace_id=args.workspace_id,
        concurrency=args.concurrency,
        resume=not args.no_resume,
        skip_failed=args.skip_failed,
    )
    logger.info("=== sweep done: %s ===", stats)
    logger.info("output: %s  (run scripts_violation_report.py on this dir)", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
