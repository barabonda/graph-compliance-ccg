"""실행(ReviewRun) 시점 스냅샷 저장소 — 운영 대시보드·디버깅용.

각 심사 실행이 끝나면 그 시점의 전체 ReviewOutput을 그대로 보관한다. Neo4j는
그래프 형태로 분해 저장하지만, 디버깅에는 '그 실행이 무엇을 산출했는가'의 원형이
필요하므로 별도 스냅샷을 둔다.

- runs/<review_run_id>.json : 전체 ReviewOutput(시점 데이터)
- runs/index.jsonl          : 한 줄당 요약(목록·집계용)

로컬 파일 기반(가볍게). 실패해도 심사 자체는 막지 않는다(best-effort).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

RUNS_DIR = Path(os.environ.get("CCG_RUNS_DIR", str(Path(__file__).resolve().parent / "runs")))
INDEX_PATH = RUNS_DIR / "index.jsonl"


def _summary(
    output: dict[str, Any], *, title: str, channel: str, product_group: str, model: str, content_text: str
) -> dict[str, Any]:
    issues = output.get("detected_issues") or []
    checks = ((output.get("product_fact_context") or {}).get("disclosure_checks")) or []
    missing = [str(c.get("label") or "") for c in checks if not c.get("present")]
    principles = sorted(
        {str(item.get("principle") or "") for item in (output.get("cu_plan") or []) if item.get("principle")}
    )
    cu_ids = sorted({str(item.get("cu_id") or "") for item in (output.get("cu_plan") or []) if item.get("cu_id")})
    track_b = output.get("overall_impression_judgment") or {}
    return {
        "id": str(output.get("review_run_id") or ""),
        "ts": time.time(),
        "title": title,
        "channel": channel,
        "product_group": product_group,
        "model": model,
        "content_text": content_text,
        "final_verdict": str(output.get("final_verdict") or ""),
        "misleading_verdict": str(track_b.get("verdict") or ""),
        "issue_count": len(issues),
        "missing_disclosures": missing,
        "principles": principles,
        "cu_ids": cu_ids,
    }


def record_run(
    output: dict[str, Any],
    *,
    title: str = "",
    channel: str = "",
    product_group: str = "",
    model: str = "",
    content_text: str = "",
) -> None:
    """심사 결과 스냅샷을 저장(best-effort)."""
    run_id = str(output.get("review_run_id") or "").strip()
    if not run_id:
        return
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (RUNS_DIR / f"{run_id}.json").write_text(
            json.dumps(output, ensure_ascii=False), encoding="utf-8"
        )
        summary = _summary(
            output,
            title=title,
            channel=channel,
            product_group=product_group,
            model=model,
            content_text=content_text,
        )
        with INDEX_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - 기록 실패가 심사를 막지 않게.
        LOGGER.warning("run_store.record_run failed run_id=%s err=%s", run_id, exc)


def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    """최근 실행 요약 목록(최신순)."""
    if not INDEX_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in INDEX_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("run_store.list_runs failed err=%s", exc)
        return []
    # 같은 id가 여러 번이면 최신만(최근 줄이 우선).
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_id[str(row.get("id") or "")] = row
    ordered = sorted(by_id.values(), key=lambda item: float(item.get("ts") or 0), reverse=True)
    return ordered[:limit]


def load_run(run_id: str) -> dict[str, Any] | None:
    """저장된 전체 ReviewOutput(시점 데이터)."""
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in {"_", "-"})
    if not safe:
        return None
    path = RUNS_DIR / f"{safe}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("run_store.load_run failed run_id=%s err=%s", run_id, exc)
        return None
