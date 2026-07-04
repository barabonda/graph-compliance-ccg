"""Shared, side-effect-free logic for the real-product violation-detection sweep.

This module holds the pure pieces that both ``scripts_violation_sweep.py`` (the
batch runner) and ``scripts_violation_report.py`` (the report generator) rely on,
so they can be unit-tested with stub run dictionaries — no Neo4j, no LLM, no live
review required.

Design contract:
- The sweep drives the *product-unselected* review path (same as
  ``review_ad.py --text``), which returns the run dict whose top-level keys are
  documented in ``runs/review_run_*.json``.
- All banks in this dataset are KR-jurisdiction, so ``workspace_id`` is pinned to
  the KR graph (``graphcompliance_mvp_jb_20260530``). This module never silently
  substitutes a different workspace.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("violation_sweep")

# All rows in this dataset are KR-jurisdiction (see spec_eval.md).
KR_WORKSPACE_ID = "graphcompliance_mvp_jb_20260530"

# effective_judgment verdicts that count as a detected regulatory violation.
VIOLATION_VERDICTS: frozenset[str] = frozenset({"NON_COMPLIANT", "INSUFFICIENT"})

# Track B (overall-impression) verdicts that count as a misleading-impression risk.
OVERALL_IMPRESSION_RISK_VERDICTS: frozenset[str] = frozenset({"HIGH", "MEDIUM"})


# --------------------------------------------------------------------------- #
# Dataset loading + stratified sampling
# --------------------------------------------------------------------------- #
@dataclass
class DatasetRow:
    """One advertising record from the compliance_review_text dataset."""

    review_id: str
    bank_key: str
    bank_label: str
    title: str
    review_text: str
    review_text_chars: int
    channel: str = "bank_event_page_text"
    source_type: str = ""
    raw: dict[str, str] = field(default_factory=dict)


def load_dataset(
    csv_path: Path | str,
    *,
    limit_chars: Optional[int] = None,
    bank: Optional[str] = None,
) -> list[DatasetRow]:
    """Load the dataset CSV into ``DatasetRow`` objects (no preprocessing of text).

    ``limit_chars`` is an *upper-bound filter*: rows whose ``review_text_chars``
    exceeds the limit are excluded from the eligible pool (cost control for very
    long crawled documents). Default ``None`` means no limit.
    ``bank`` filters by ``bank_key`` or ``bank_label`` (exact match).
    """
    path = Path(csv_path)
    rows: list[DatasetRow] = []
    # utf-8-sig strips the leading BOM present in this dataset's header.
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for record in reader:
            review_id = (record.get("review_id") or "").strip()
            if not review_id:
                continue
            bank_key = (record.get("bank_key") or "").strip()
            bank_label = (record.get("bank_label") or "").strip()
            if bank is not None and bank not in (bank_key, bank_label):
                continue
            text = record.get("review_text") or ""
            raw_chars = record.get("review_text_chars")
            try:
                chars = int(raw_chars) if raw_chars not in (None, "") else len(text)
            except (TypeError, ValueError):
                chars = len(text)
            if limit_chars is not None and chars > limit_chars:
                continue
            rows.append(
                DatasetRow(
                    review_id=review_id,
                    bank_key=bank_key,
                    bank_label=bank_label,
                    title=(record.get("title") or "").strip(),
                    review_text=text,
                    review_text_chars=chars,
                    source_type=(record.get("representative_source") or "").strip(),
                    raw=dict(record),
                )
            )
    return rows


def allocate_counts(group_sizes: dict[str, int], sample_size: int) -> dict[str, int]:
    """Largest-remainder (Hamilton) proportional allocation.

    Returns per-group counts summing to ``min(sample_size, total)``. Each group's
    allocation never exceeds its available size.
    """
    total = sum(group_sizes.values())
    if total == 0 or sample_size <= 0:
        return {key: 0 for key in group_sizes}
    if sample_size >= total:
        return dict(group_sizes)

    quotas = {key: size * sample_size / total for key, size in group_sizes.items()}
    floors = {key: int(quota) for key, quota in quotas.items()}
    assigned = sum(floors.values())
    remainder = sample_size - assigned

    # Rank groups by fractional remainder, then by group size, then name — all
    # deterministic tie-breaks so the allocation is reproducible.
    ranked = sorted(
        group_sizes,
        key=lambda key: (quotas[key] - floors[key], group_sizes[key], key),
        reverse=True,
    )
    idx = 0
    while remainder > 0 and idx < len(ranked) * 4:
        key = ranked[idx % len(ranked)]
        if floors[key] < group_sizes[key]:
            floors[key] += 1
            remainder -= 1
        idx += 1
    return floors


def _bank_seed(seed: int, bank_key: str) -> int:
    """Derive a stable per-bank RNG seed from the global seed + bank key."""
    digest = hashlib.sha256(f"{seed}:{bank_key}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def stratified_sample(
    rows: list[DatasetRow],
    sample_size: Optional[int],
    *,
    seed: int,
) -> list[DatasetRow]:
    """Bank-proportional stratified sample, reproducible for a fixed ``seed``.

    ``sample_size=None`` (or >= population) returns all rows. Allocation across
    banks uses ``allocate_counts``; within each bank, rows are shuffled with a
    seed derived from ``(seed, bank_key)`` and the top ``k`` taken.
    """
    if sample_size is None or sample_size >= len(rows):
        return list(rows)

    groups: dict[str, list[DatasetRow]] = {}
    for row in rows:
        groups.setdefault(row.bank_key, []).append(row)

    alloc = allocate_counts({key: len(pool) for key, pool in groups.items()}, sample_size)

    picked: list[DatasetRow] = []
    for bank_key in sorted(groups):
        take = alloc.get(bank_key, 0)
        if take <= 0:
            continue
        pool = sorted(groups[bank_key], key=lambda r: r.review_id)
        rng = random.Random(_bank_seed(seed, bank_key))
        rng.shuffle(pool)
        picked.extend(pool[:take])
    return picked


def sample_plan(rows: list[DatasetRow], sample_size: Optional[int]) -> list[dict[str, Any]]:
    """Per-bank allocation plan (for --dry-run reporting)."""
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = groups.setdefault(row.bank_key, {"bank_key": row.bank_key, "bank_label": row.bank_label, "available": 0})
        entry["available"] += 1
    sizes = {key: entry["available"] for key, entry in groups.items()}
    alloc = allocate_counts(sizes, sample_size) if sample_size is not None else dict(sizes)
    plan = []
    for bank_key in sorted(groups):
        entry = groups[bank_key]
        plan.append(
            {
                "bank_key": bank_key,
                "bank_label": entry["bank_label"],
                "available": entry["available"],
                "sampled": alloc.get(bank_key, entry["available"]),
            }
        )
    return plan


# --------------------------------------------------------------------------- #
# Extraction from a review run dict
# --------------------------------------------------------------------------- #
def build_cu_index(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map cu_id -> {principle, source_article, subject} using the cu_plan.

    ``effective_judgments`` carry cu_id but not principle/article; the cu_plan is
    the authoritative source of that mapping.
    """
    index: dict[str, dict[str, Any]] = {}
    for item in run.get("cu_plan", []) or []:
        cu_id = item.get("cu_id")
        if not cu_id or cu_id in index:
            continue
        index[cu_id] = {
            "principle": item.get("principle"),
            "source_article": item.get("source_article"),
            "subject": item.get("subject"),
        }
    return index


def extract_violations(run: dict[str, Any]) -> list[dict[str, Any]]:
    """effective_judgments whose verdict is a violation, enriched with cu metadata."""
    cu_index = build_cu_index(run)
    violations: list[dict[str, Any]] = []
    for judgment in run.get("effective_judgments", []) or []:
        verdict = judgment.get("verdict")
        if verdict not in VIOLATION_VERDICTS:
            continue
        cu_id = judgment.get("cu_id")
        meta = cu_index.get(cu_id, {})
        violations.append(
            {
                "cu_id": cu_id,
                "verdict": verdict,
                "score": judgment.get("score"),
                "principle": meta.get("principle"),
                "source_article": meta.get("source_article"),
                "subject": meta.get("subject"),
                "legal_basis": judgment.get("legal_basis"),
                "evidence_span": judgment.get("evidence_span"),
                "why": judgment.get("why"),
            }
        )
    return violations


def extract_disclosure_requirements(run: dict[str, Any]) -> list[dict[str, Any]]:
    """Required disclosures the pipeline surfaced for this ad (id/label/source/why)."""
    out: list[dict[str, Any]] = []
    for req in run.get("disclosure_requirements", []) or []:
        out.append({key: req.get(key) for key in ("id", "label", "source", "why")})
    return out


def extract_overall_impression(run: dict[str, Any]) -> dict[str, Any]:
    """Track B overall-impression summary (subset of fields)."""
    oi = run.get("overall_impression_judgment") or {}
    return {
        "track": oi.get("track"),
        "standard": oi.get("standard"),
        "verdict": oi.get("verdict"),
        "misleading_risk_score": oi.get("misleading_risk_score"),
        "why": oi.get("why"),
    }


def is_overall_impression_risk(overall_impression: dict[str, Any]) -> bool:
    return str(overall_impression.get("verdict") or "").upper() in OVERALL_IMPRESSION_RISK_VERDICTS


def _aggregation_summary(entries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for entry in entries or []:
        summary.append(
            {
                "key": entry.get("key"),
                "article": entry.get("article"),
                "principles": entry.get("principles"),
                "effective_verdict": entry.get("effective_verdict"),
                "max_score": entry.get("max_score"),
                "cu_count": entry.get("cu_count"),
                "issue_count": entry.get("issue_count"),
                "cu_titles": entry.get("cu_titles"),
                "anchor_spans": entry.get("anchor_spans"),
            }
        )
    return summary


def _policy_chain_counts(run: dict[str, Any]) -> dict[str, int]:
    chains = run.get("policy_evidence_chains") or {}
    counts: dict[str, int] = {}
    for key in ("legal_basis_chains", "disclosure_chains", "exception_chains", "chain_diagnostics"):
        value = chains.get(key)
        counts[key] = len(value) if hasattr(value, "__len__") else 0
    return counts


def summarize_run(run: dict[str, Any]) -> dict[str, Any]:
    """Extract the violation-focused summary from a full review run dict."""
    violations = extract_violations(run)
    overall_impression = extract_overall_impression(run)
    return {
        "final_verdict": run.get("final_verdict"),
        "routing": run.get("routing"),
        "review_run_id": run.get("review_run_id"),
        "violations": violations,
        "violation_count": len(violations),
        "disclosure_requirements": extract_disclosure_requirements(run),
        "overall_impression": overall_impression,
        "overall_impression_risk": is_overall_impression_risk(overall_impression),
        "article_aggregation": _aggregation_summary(run.get("article_aggregation")),
        "principle_aggregation": _aggregation_summary(run.get("principle_aggregation")),
        "policy_evidence_chain_counts": _policy_chain_counts(run),
    }


def build_item_record(
    row: DatasetRow,
    *,
    status: str,
    run: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> dict[str, Any]:
    """Assemble the per-item JSON record persisted under items/{review_id}.json."""
    record: dict[str, Any] = {
        "review_id": row.review_id,
        "bank_key": row.bank_key,
        "bank_label": row.bank_label,
        "title": row.title,
        "review_text_chars": row.review_text_chars,
        "workspace_id": KR_WORKSPACE_ID,
        "status": status,
        "error": error,
        "duration_sec": duration_sec,
    }
    if run is not None:
        record.update(summarize_run(run))
    else:
        record.update(
            {
                "final_verdict": None,
                "violations": [],
                "violation_count": 0,
                "disclosure_requirements": [],
                "overall_impression": {},
                "overall_impression_risk": False,
                "article_aggregation": [],
                "principle_aggregation": [],
                "policy_evidence_chain_counts": {},
            }
        )
    return record


def item_has_violation(record: dict[str, Any]) -> bool:
    """True if the item surfaced any regulatory violation or Track B risk."""
    return bool(record.get("violation_count")) or bool(record.get("overall_impression_risk"))
