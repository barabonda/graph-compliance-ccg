"""실행(ReviewRun) 시점 스냅샷 저장소 — 운영 대시보드·디버깅용.

각 심사 실행이 끝나면 그 시점의 전체 ReviewOutput을 그대로 보관한다. Neo4j는
그래프 형태로 분해 저장하지만, 디버깅에는 '그 실행이 무엇을 산출했는가'의 원형이
필요하므로 별도 스냅샷을 둔다.

저장은 두 곳에 한다(둘 다 best-effort, 실패해도 심사는 막지 않음):

- 로컬 파일: runs/<id>.json(전체 ReviewOutput) + runs/index.jsonl(요약). 빠른 로컬 캐시.
- Neo4j: `ReviewRunSnapshot {id, workspace_id}` 노드에 요약 + output_json(전체). 영속.

조회는 두 소스를 병합한다. 따라서 배포 환경에서 로컬 파일시스템이 초기화돼도
(컨테이너 재배포 등) Neo4j에 남은 스냅샷에서 실행 기록이 복원된다. 반대로 Neo4j가
없어도 로컬 파일로 동작한다.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

RUNS_DIR = Path(os.environ.get("CCG_RUNS_DIR", str(Path(__file__).resolve().parent / "runs")))
INDEX_PATH = RUNS_DIR / "index.jsonl"

DEFAULT_WORKSPACE = os.environ.get("CCG_WORKSPACE_ID", "graphcompliance_mvp_jb_20260530")
SNAPSHOT_LABEL = "ReviewRunSnapshot"
# Neo4j 속성에는 리스트(of dict)를 그대로 못 넣으므로 JSON 문자열로 저장/복원한다.
_LIST_FIELDS = ("missing_disclosures", "principles", "cu_ids", "cu_labels")

_driver: Any = None
_driver_failed = False
_driver_lock = threading.Lock()


def _get_driver() -> Any:
    """Neo4j 드라이버를 지연 생성. 자격증명이 없거나 실패하면 None(파일만 사용)."""
    global _driver, _driver_failed
    if _driver is not None:
        return _driver
    if _driver_failed:
        return None
    with _driver_lock:
        if _driver is not None:
            return _driver
        if _driver_failed:
            return None
        uri = os.environ.get("NEO4J_URI")
        user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")
        if not (uri and user and password):
            _driver_failed = True
            return None
        try:
            from neo4j import GraphDatabase

            _driver = GraphDatabase.driver(uri, auth=(user, password))
            return _driver
        except Exception as exc:  # noqa: BLE001 - DB 부재가 심사를 막지 않게.
            LOGGER.warning("run_store neo4j driver init failed err=%s", exc)
            _driver_failed = True
            return None


def _session_kwargs() -> dict[str, str]:
    db = os.environ.get("NEO4J_DATABASE")
    return {"database": db} if db else {}


def _summary(
    output: dict[str, Any],
    *,
    title: str,
    channel: str,
    product_group: str,
    selected_product_name: str,
    selected_product_id: str,
    source_type: str,
    workspace_id: str,
    model: str,
    content_text: str,
    seed: bool,
    actor: str,
    language: str = "",
) -> dict[str, Any]:
    issues = output.get("detected_issues") or []
    checks = ((output.get("product_fact_context") or {}).get("disclosure_checks")) or []
    # 적용범위(gate ON) 내에서 부재인 고지만 '누락'. OFF(상품군/채널 밖)는 누락이 아니다.
    missing = [
        str(c.get("label") or "")
        for c in checks
        if str(c.get("gate_status") or "ON").upper() == "ON" and not c.get("present")
    ]
    cu_plan = output.get("cu_plan") or []
    principles = sorted({str(item.get("principle") or "") for item in cu_plan if item.get("principle")})
    cu_ids = sorted({str(item.get("cu_id") or "") for item in cu_plan if item.get("cu_id")})
    # 사람이 읽는 CU 라벨(해시 id 대신): risk_title > 원칙+조문 > subject.
    cu_labels = sorted(
        {
            str(item.get("risk_title") or item.get("principle") or item.get("subject") or "")
            for item in cu_plan
        }
        - {""}
    )
    track_b = output.get("overall_impression_judgment") or {}
    return {
        "id": str(output.get("review_run_id") or ""),
        "ts": time.time(),
        "title": title,
        "channel": channel,
        "product_group": product_group,
        "selected_product_name": selected_product_name,
        "selected_product_id": selected_product_id,
        "source_type": source_type,
        "workspace_id": workspace_id,
        "language": language,
        "model": model,
        "content_text": content_text,
        "seed": seed,
        "actor": actor,
        "final_verdict": str(output.get("final_verdict") or ""),
        "misleading_verdict": str(track_b.get("verdict") or ""),
        "issue_count": len(issues),
        "missing_disclosures": missing,
        "principles": principles,
        "cu_ids": cu_ids,
        "cu_labels": cu_labels,
    }


def _record_filesystem(output: dict[str, Any], summary: dict[str, Any], run_id: str) -> None:
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (RUNS_DIR / f"{run_id}.json").write_text(
            json.dumps(output, ensure_ascii=False), encoding="utf-8"
        )
        with INDEX_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - 기록 실패가 심사를 막지 않게.
        LOGGER.warning("run_store filesystem record failed run_id=%s err=%s", run_id, exc)


def _record_neo4j(output: dict[str, Any], summary: dict[str, Any], workspace_id: str) -> None:
    driver = _get_driver()
    if driver is None:
        return
    try:
        props = dict(summary)
        for field in _LIST_FIELDS:
            props[field] = json.dumps(props.get(field) or [], ensure_ascii=False)
        props["output_json"] = json.dumps(output, ensure_ascii=False)
        props["workspace_id"] = workspace_id
        with driver.session(**_session_kwargs()) as session:
            session.run(
                f"MERGE (n:{SNAPSHOT_LABEL} {{id: $id, workspace_id: $workspace_id}}) SET n += $props",
                id=summary["id"],
                workspace_id=workspace_id,
                props=props,
            )
    except Exception as exc:  # noqa: BLE001 - DB 기록 실패가 심사를 막지 않게.
        LOGGER.warning("run_store neo4j record failed run_id=%s err=%s", summary.get("id"), exc)


def record_run(
    output: dict[str, Any],
    *,
    title: str = "",
    channel: str = "",
    product_group: str = "",
    selected_product_name: str = "",
    selected_product_id: str = "",
    source_type: str = "",
    model: str = "",
    content_text: str = "",
    seed: bool = False,
    actor: str = "",
    workspace_id: str = "",
    language: str = "",
) -> None:
    """심사 결과 스냅샷을 파일 + Neo4j에 저장(best-effort). seed=True는 데모용 표시.

    이 함수는 어떤 경우에도 예외를 밖으로 던지지 않는다 — 스트림 워커가 result
    이벤트 직후 호출하므로, 저장 실패가 결과 전달을 막아선 안 된다.
    """
    try:
        run_id = str(output.get("review_run_id") or "").strip()
        if not run_id:
            return
        summary = _summary(
            output,
            title=title,
            channel=channel,
            product_group=product_group,
            selected_product_name=selected_product_name,
            selected_product_id=selected_product_id,
            source_type=source_type,
            workspace_id=workspace_id,
            model=model,
            content_text=content_text,
            seed=seed,
            actor=actor,
            language=language,
        )
        _record_filesystem(output, summary, run_id)
        ws = workspace_id or str(output.get("workspace_id") or "") or DEFAULT_WORKSPACE
        _record_neo4j(output, summary, ws)
    except Exception as exc:  # noqa: BLE001 - 저장 실패가 결과 전달/심사를 막지 않게.
        LOGGER.warning("run_store.record_run failed err=%s", exc)


def _list_filesystem() -> list[dict[str, Any]]:
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
        LOGGER.warning("run_store list filesystem failed err=%s", exc)
        return []
    return rows


def _row_from_node(node: Any) -> dict[str, Any]:
    row = dict(node)
    row.pop("output_json", None)
    row.pop("workspace_id", None)
    for field in _LIST_FIELDS:
        value = row.get(field)
        if isinstance(value, str):
            try:
                row[field] = json.loads(value)
            except json.JSONDecodeError:
                row[field] = []
    row["ts"] = float(row.get("ts") or 0)
    row["seed"] = bool(row.get("seed"))
    row["issue_count"] = int(row.get("issue_count") or 0)
    return row


def _list_neo4j(limit: int) -> list[dict[str, Any]]:
    driver = _get_driver()
    if driver is None:
        return []
    try:
        with driver.session(**_session_kwargs()) as session:
            result = session.run(
                f"MATCH (n:{SNAPSHOT_LABEL}) RETURN n ORDER BY n.ts DESC LIMIT $limit",
                limit=limit,
            )
            return [_row_from_node(record["n"]) for record in result]
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("run_store list neo4j failed err=%s", exc)
        return []


def list_runs(limit: int = 100) -> list[dict[str, Any]]:
    """최근 실행 요약 목록(최신순). 파일이 있으면 파일만(빠름), 비었을 때만 Neo4j 복원.

    Neo4j(원격 Aura) 조회는 네트워크에 따라 수초~십수초 걸릴 수 있어, 평상시 대시보드
    로딩을 느리게 만든다. 파일이 진실원천(local)이고 Neo4j는 '파일이 사라졌을 때(재배포)'의
    복구 경로이므로, 파일이 비었을 때만 Neo4j를 조회한다.
    """
    by_id: dict[str, dict[str, Any]] = {}
    filesystem_rows = _list_filesystem()
    for row in filesystem_rows:
        by_id[str(row.get("id") or "")] = row
    if not filesystem_rows:
        for row in _list_neo4j(limit * 3):
            rid = str(row.get("id") or "")
            if rid and rid not in by_id:
                by_id[rid] = row
    by_id.pop("", None)
    ordered = sorted(by_id.values(), key=lambda item: float(item.get("ts") or 0), reverse=True)
    return ordered[:limit]


def _load_neo4j(run_id: str) -> dict[str, Any] | None:
    driver = _get_driver()
    if driver is None:
        return None
    try:
        with driver.session(**_session_kwargs()) as session:
            result = session.run(
                f"MATCH (n:{SNAPSHOT_LABEL} {{id: $id}}) RETURN n.output_json AS output_json LIMIT 1",
                id=run_id,
            )
            record = result.single()
            if record and record["output_json"]:
                return json.loads(record["output_json"])
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("run_store load neo4j failed run_id=%s err=%s", run_id, exc)
    return None


def load_run(run_id: str) -> dict[str, Any] | None:
    """저장된 전체 ReviewOutput(시점 데이터). 파일 우선, 없으면 Neo4j에서 복원."""
    safe = "".join(ch for ch in run_id if ch.isalnum() or ch in {"_", "-"})
    if not safe:
        return None
    path = RUNS_DIR / f"{safe}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("run_store load filesystem failed run_id=%s err=%s", run_id, exc)
    return _load_neo4j(safe)


def backfill_neo4j() -> int:
    """로컬 파일에만 있는 실행 기록을 Neo4j 스냅샷으로 올린다(일회성 마이그레이션).

    재배포로 파일이 사라지기 전에 기존 기록을 영속화하는 용도. 반환값은 올린 건수.
    """
    if _get_driver() is None:
        LOGGER.warning("run_store.backfill_neo4j: neo4j unavailable")
        return 0
    count = 0
    for summary in _list_filesystem():
        run_id = str(summary.get("id") or "").strip()
        if not run_id:
            continue
        output = load_run(run_id) or {"review_run_id": run_id}
        ws = str(summary.get("workspace_id") or "") or DEFAULT_WORKSPACE
        _record_neo4j(output, summary, ws)
        count += 1
    return count
