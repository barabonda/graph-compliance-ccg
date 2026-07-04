"""Generate a violation-focused report from a violation-sweep output directory.

Reads items/{review_id}.json produced by ``scripts_violation_sweep.py`` and emits:
  - report.md      — human-readable, violation-focused (guideline/principle first)
  - violations.csv — one row per detected violation (for reviewer follow-up)

Usage:
  python3 scripts_violation_report.py --sweep-dir eval/violation_sweep/pilot50
  python3 scripts_violation_report.py --sweep-dir <dir> --out-md report.md --out-csv violations.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from violation_sweep_lib import item_has_violation

logger = logging.getLogger("violation_report")


def load_items(sweep_dir: Path) -> list[dict[str, Any]]:
    items_dir = sweep_dir / "items"
    if not items_dir.exists():
        raise FileNotFoundError(f"no items/ directory under {sweep_dir}")
    items: list[dict[str, Any]] = []
    for path in sorted(items_dir.glob("*.json")):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("skipping unreadable item %s: %s", path.name, exc)
    return items


def _truncate(text: Any, length: int = 120) -> str:
    string = str(text if text is not None else "").replace("\n", " ").replace("|", "／").strip()
    return string if len(string) <= length else string[: length - 1] + "…"


def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [i for i in items if i.get("status") == "completed"]
    failed = [i for i in items if i.get("status") != "completed"]
    flagged = [i for i in completed if item_has_violation(i)]

    per_bank_total: Counter[str] = Counter()
    per_bank_flagged: Counter[str] = Counter()
    for item in completed:
        label = item.get("bank_label") or item.get("bank_key") or "?"
        per_bank_total[label] += 1
        if item_has_violation(item):
            per_bank_flagged[label] += 1

    # Principle-level distribution grounded in principle_aggregation.
    principle_counts: Counter[str] = Counter()
    principle_article: dict[str, set[str]] = defaultdict(set)
    for item in completed:
        for entry in item.get("principle_aggregation", []) or []:
            key = entry.get("key") or "(unknown)"
            principle_counts[key] += 1
            article = entry.get("article")
            if article:
                principle_article[key].add(str(article))

    # Also count violations by (principle, verdict) at the effective-judgment level.
    verdict_by_principle: dict[str, Counter[str]] = defaultdict(Counter)
    for item in completed:
        for viol in item.get("violations", []) or []:
            principle = viol.get("principle") or "(unmapped)"
            verdict_by_principle[principle][viol.get("verdict") or "?"] += 1

    oi_risks = [
        i for i in completed if i.get("overall_impression_risk")
    ]

    return {
        "total": len(items),
        "completed": len(completed),
        "failed": len(failed),
        "flagged": len(flagged),
        "failed_items": failed,
        "flagged_items": flagged,
        "per_bank_total": per_bank_total,
        "per_bank_flagged": per_bank_flagged,
        "principle_counts": principle_counts,
        "principle_article": principle_article,
        "verdict_by_principle": verdict_by_principle,
        "overall_impression_risks": oi_risks,
    }


def violation_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per detected violation (effective-judgment level)."""
    rows: list[dict[str, Any]] = []
    for item in items:
        if item.get("status") != "completed":
            continue
        missing = "; ".join(
            str(d.get("label") or d.get("id") or "") for d in item.get("disclosure_requirements", []) or []
        )
        for viol in item.get("violations", []) or []:
            rows.append(
                {
                    "review_id": item.get("review_id"),
                    "bank_label": item.get("bank_label"),
                    "title": _truncate(item.get("title"), 80),
                    "principle": viol.get("principle"),
                    "verdict": viol.get("verdict"),
                    "score": viol.get("score"),
                    "cu_id": viol.get("cu_id"),
                    "source_article": viol.get("source_article"),
                    "evidence_span": _truncate(viol.get("evidence_span"), 200),
                    "legal_basis": _truncate(viol.get("legal_basis"), 300),
                    "missing_disclosures": missing,
                }
            )
    return rows


def render_report_md(agg: dict[str, Any], items: list[dict[str, Any]], sweep_dir: Path) -> str:
    lines: list[str] = []
    ap = lines.append

    ap(f"# 실상품 위반 탐지 스윕 리포트")
    ap("")
    ap(f"- 스윕 디렉토리: `{sweep_dir}`")
    ap(f"- 심사 시도: **{agg['total']}건** (완료 {agg['completed']} / 실패 {agg['failed']})")
    ap(f"- 위반 검출: **{agg['flagged']}건** (완료 대비 "
       f"{(agg['flagged'] / agg['completed'] * 100 if agg['completed'] else 0):.1f}%)")
    ap(f"- Track B 전체인상 위험: **{len(agg['overall_impression_risks'])}건**")
    ap("")

    ap("## 1. 은행별 검출률")
    ap("")
    ap("| 은행 | 완료 | 위반 검출 | 검출률 |")
    ap("|------|------|-----------|--------|")
    for label in sorted(agg["per_bank_total"], key=lambda k: -agg["per_bank_total"][k]):
        total = agg["per_bank_total"][label]
        flagged = agg["per_bank_flagged"].get(label, 0)
        rate = flagged / total * 100 if total else 0
        ap(f"| {label} | {total} | {flagged} | {rate:.1f}% |")
    ap("")

    ap("## 2. 가이드라인/원칙별 위반 분포")
    ap("")
    if agg["verdict_by_principle"]:
        ap("| 원칙 | 근거 조문 | NON_COMPLIANT | INSUFFICIENT | 계 |")
        ap("|------|-----------|---------------|--------------|-----|")
        for principle in sorted(
            agg["verdict_by_principle"], key=lambda p: -sum(agg["verdict_by_principle"][p].values())
        ):
            counts = agg["verdict_by_principle"][principle]
            articles = ", ".join(sorted(agg["principle_article"].get(principle, set()))) or "—"
            nc = counts.get("NON_COMPLIANT", 0)
            ins = counts.get("INSUFFICIENT", 0)
            ap(f"| {principle} | {_truncate(articles, 60)} | {nc} | {ins} | {nc + ins} |")
    else:
        ap("_위반으로 분류된 effective_judgment 없음._")
    ap("")

    ap("## 3. 은행별 breakdown (완료 기준)")
    ap("")
    ap("| 은행 | 완료 | 위반 검출 | Track B 위험 |")
    ap("|------|------|-----------|--------------|")
    bank_oi = Counter(i.get("bank_label") or i.get("bank_key") for i in agg["overall_impression_risks"])
    for label in sorted(agg["per_bank_total"], key=lambda k: -agg["per_bank_total"][k]):
        ap(f"| {label} | {agg['per_bank_total'][label]} | {agg['per_bank_flagged'].get(label, 0)} | {bank_oi.get(label, 0)} |")
    ap("")

    ap("## 4. 위반 상세")
    ap("")
    rows = violation_rows(items)
    if rows:
        ap("| review_id | 은행 | 제목 | 위반 원칙 | verdict | 근거 조문 | 문제 문구 | 누락 필수고지 |")
        ap("|-----------|------|------|-----------|---------|-----------|-----------|---------------|")
        for row in rows:
            ap("| {rid} | {bank} | {title} | {principle} | {verdict} | {article} | {span} | {missing} |".format(
                rid=row["review_id"],
                bank=row["bank_label"] or "",
                title=row["title"],
                principle=_truncate(row["principle"], 30),
                verdict=row["verdict"],
                article=_truncate(row["source_article"], 40),
                span=_truncate(row["evidence_span"], 80),
                missing=_truncate(row["missing_disclosures"], 50),
            ))
    else:
        ap("_상세 위반 없음._")
    ap("")

    ap("## 5. Track B 전체인상 위험 검출")
    ap("")
    if agg["overall_impression_risks"]:
        ap("| review_id | 은행 | verdict | 위험점수 | 사유 |")
        ap("|-----------|------|---------|----------|------|")
        for item in agg["overall_impression_risks"]:
            oi = item.get("overall_impression") or {}
            ap(f"| {item.get('review_id')} | {item.get('bank_label') or ''} | "
               f"{oi.get('verdict')} | {oi.get('misleading_risk_score')} | {_truncate(oi.get('why'), 80)} |")
    else:
        ap("_Track B 위험 검출 없음._")
    ap("")

    ap("## 6. 심사 실패/미완료 항목")
    ap("")
    if agg["failed_items"]:
        ap("| review_id | 은행 | 오류 |")
        ap("|-----------|------|------|")
        for item in agg["failed_items"]:
            ap(f"| {item.get('review_id')} | {item.get('bank_label') or ''} | {_truncate(item.get('error'), 100)} |")
    else:
        ap("_실패 항목 없음._")
    ap("")

    return "\n".join(lines)


def write_violations_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    fields = [
        "review_id", "bank_label", "title", "principle", "verdict", "score",
        "cu_id", "source_article", "evidence_span", "legal_basis", "missing_disclosures",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sweep-dir", required=True, help="Violation-sweep output directory (contains items/).")
    parser.add_argument("--out-md", default=None, help="report.md path (default: <sweep-dir>/report.md).")
    parser.add_argument("--out-csv", default=None, help="violations.csv path (default: <sweep-dir>/violations.csv).")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)

    sweep_dir = Path(args.sweep_dir)
    items = load_items(sweep_dir)
    logger.info("loaded %d items from %s", len(items), sweep_dir / "items")

    agg = aggregate(items)
    report_md = render_report_md(agg, items, sweep_dir)
    rows = violation_rows(items)

    out_md = Path(args.out_md) if args.out_md else sweep_dir / "report.md"
    out_csv = Path(args.out_csv) if args.out_csv else sweep_dir / "violations.csv"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(report_md, encoding="utf-8")
    write_violations_csv(rows, out_csv)

    logger.info(
        "report: %s (%d violations across %d flagged items) + %s",
        out_md, len(rows), agg["flagged"], out_csv,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
