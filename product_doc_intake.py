"""상품 문서 시점 인식 접수 — KG 버전 적재 + 변경 추적.

새 심사에서 상품설명서/약관 문서를 접수하면:
1. 문서에서 시점(시행일·기준일)과 핵심 사실(금리·조건·한도)을 LLM으로 구조화 추출
2. Neo4j 에 (Product)-[:HAS_DOC_VERSION]->(ProductDocVersion) 버전 노드로 적재,
   직전 버전과 (new)-[:SUPERSEDES]->(old) 체인 연결
3. 직전 버전 대비 사실 변경점(무엇이 언제 어떻게 바뀌었나)을 계산해 반환

심사 파이프라인의 사실 대조(HAS_PRODUCT_FACT 경로)와는 독립적인 데모 레이어 —
노드에 ingest_source='doc_intake' 마커를 남겨 격리하고, 언제든 지울 수 있다.
LLM/Neo4j 부재 시 조용한 대체 없이 명시적으로 실패한다(no fallback).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
from typing import Any

from llm_gateway import LLMGateway
from utils import stable_id

LOGGER = logging.getLogger(__name__)

# 추출 스키마 — 시점과 사실을 함께. effective_date 는 문서에 명시된 시행/적용/기준일
# (YYYY-MM-DD). 명시가 없으면 빈 문자열(추정 금지 — 시점 인식이 이 기능의 본질).
DOC_INTAKE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_name": {"type": "string", "description": "문서가 설명하는 상품의 정식 명칭."},
        "doc_type": {
            "type": "string",
            "enum": ["상품설명서", "약관", "상품주요내용", "금리안내", "기타"],
        },
        "effective_date": {
            "type": "string",
            "description": "문서에 명시된 시행일/적용일/기준일(YYYY-MM-DD). 명시가 없으면 빈 문자열 — 추정 금지.",
        },
        "date_evidence": {
            "type": "string",
            "description": "시행일을 인식한 근거 문구(원문 그대로). 없으면 빈 문자열.",
        },
        "facts": {
            "type": "array",
            "description": "심사 대조에 쓰이는 핵심 사실 — 금리·우대조건·가입기간·한도·수수료·예금자보호 등.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string", "description": "사실 항목명(예: 기본금리, 최고금리, 가입기간, 월 납입한도)."},
                    "value": {"type": "string", "description": "값(원문 표기 그대로, 예: '연 2.0%', '12개월')."},
                    "evidence": {"type": "string", "description": "근거 원문 발췌."},
                },
                "required": ["field", "value", "evidence"],
            },
        },
    },
    "required": ["product_name", "doc_type", "effective_date", "date_evidence", "facts"],
}


def extract_document_text(file_base64: str, media_type: str) -> str:
    """업로드 문서에서 텍스트 추출 — PDF 는 pypdf, 텍스트류는 그대로 디코드."""
    raw = base64.b64decode(file_base64)
    if "pdf" in media_type:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        pages = [(page.extract_text() or "") for page in reader.pages[:20]]
        text = "\n".join(pages).strip()
        if not text:
            raise RuntimeError("PDF에서 텍스트를 추출하지 못했습니다(스캔본이면 이미지 광고 접수를 사용하세요).")
        return text
    return raw.decode("utf-8", errors="replace").strip()


def extract_doc_metadata(text: str, llm: LLMGateway | None = None) -> dict[str, Any]:
    """LLM 구조화 추출 — 시점·문서유형·핵심 사실. 원문 인용 필수, 창작 금지."""
    gateway = llm or LLMGateway()
    result = gateway.structured(
        name="graphcompliance_product_doc_intake",
        schema=DOC_INTAKE_SCHEMA,
        system=(
            "당신은 금융 상품 문서(상품설명서·약관·금리안내)를 심사 그래프에 적재하기 위해 "
            "구조화하는 분석기입니다. 반드시 문서에 적힌 내용만 추출하세요 — 값·날짜를 "
            "추정하거나 만들어내지 마세요. effective_date는 문서에 명시된 시행일/적용일/"
            "기준일만 인정하며(YYYY-MM-DD로 정규화), 명시가 없으면 빈 문자열로 두세요. "
            "facts의 field명은 반드시 다음 표준명만 사용하세요(변경 추적을 위해 버전 간 "
            "동일해야 함): 기본금리, 우대금리, 최고금리, 가입기간, 가입금액, 가입대상, "
            "납입한도, 중도해지이율, 수수료, 예금자보호, 대출한도, 대출금리, 연체이자율. "
            "항목을 세분화하지 마세요(예: '우대금리_급여이체' 금지 — 우대금리 하나에 조건을 "
            "value로 병기). 표준명에 없는 항목은 문서 표기 그대로 간결한 명사형으로 쓰세요."
        ),
        user=f"[상품 문서 원문]\n{text[:12000]}",
    )
    return result


def _neo4j_driver():
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not (uri and user and password):
        raise RuntimeError("NEO4J_URI/USER/PASSWORD is required for document intake; no fallback.")
    return GraphDatabase.driver(uri, auth=(user, password)), os.environ.get("NEO4J_DATABASE")


def ingest_doc_version(
    *,
    workspace_id: str,
    metadata: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    """버전 노드 적재 + SUPERSEDES 체인 + 변경점 계산.

    반환: {version_id, product_name, effective_date, facts, changes, timeline}
    """
    product_name = str(metadata.get("product_name") or "").strip()
    effective_date = str(metadata.get("effective_date") or "").strip()
    facts = [
        {"field": str(f.get("field") or ""), "value": str(f.get("value") or ""), "evidence": str(f.get("evidence") or "")}
        for f in (metadata.get("facts") or [])
        if str(f.get("field") or "").strip()
    ]
    if not product_name:
        raise RuntimeError("문서에서 상품명을 인식하지 못했습니다.")
    version_id = stable_id("product_doc_version", workspace_id, product_name, effective_date or source_name, str(time.time()))

    driver, database = _neo4j_driver()
    try:
        with (driver.session(database=database) if database else driver.session()) as session:
            # 기존 버전 목록(시행일 순) — 변경 비교 대상은 '이 문서보다 앞선 가장 최근 버전'.
            rows = session.run(
                """
                MATCH (p:Product {name: $name, workspace_id: $ws})-[:HAS_DOC_VERSION]->(v:ProductDocVersion)
                RETURN v.id AS id, v.effective_date AS effective_date, v.doc_type AS doc_type,
                       v.facts_json AS facts_json, v.source_name AS source_name
                ORDER BY v.effective_date
                """,
                name=product_name,
                ws=workspace_id,
            ).data()
            previous = None
            if effective_date:
                older = [r for r in rows if (r.get("effective_date") or "") < effective_date]
                previous = older[-1] if older else None
            elif rows:
                previous = rows[-1]

            session.run(
                """
                MERGE (p:Product {name: $name, workspace_id: $ws})
                  ON CREATE SET p.ingest_source = 'doc_intake'
                CREATE (v:ProductDocVersion {
                  id: $vid, workspace_id: $ws, doc_type: $doc_type,
                  effective_date: $effective_date, date_evidence: $date_evidence,
                  facts_json: $facts_json, source_name: $source_name,
                  ingest_source: 'doc_intake', ingested_at: datetime()
                })
                MERGE (p)-[:HAS_DOC_VERSION]->(v)
                """,
                name=product_name,
                ws=workspace_id,
                vid=version_id,
                doc_type=str(metadata.get("doc_type") or "기타"),
                effective_date=effective_date,
                date_evidence=str(metadata.get("date_evidence") or ""),
                facts_json=json.dumps(facts, ensure_ascii=False),
                source_name=source_name,
            )
            if previous:
                session.run(
                    "MATCH (a:ProductDocVersion {id: $new}), (b:ProductDocVersion {id: $old}) MERGE (a)-[:SUPERSEDES]->(b)",
                    new=version_id,
                    old=previous["id"],
                )

            timeline_rows = session.run(
                """
                MATCH (p:Product {name: $name, workspace_id: $ws})-[:HAS_DOC_VERSION]->(v:ProductDocVersion)
                RETURN v.id AS id, v.effective_date AS effective_date, v.doc_type AS doc_type,
                       v.source_name AS source_name
                ORDER BY v.effective_date
                """,
                name=product_name,
                ws=workspace_id,
            ).data()
    finally:
        driver.close()

    changes = compute_changes(previous, facts) if previous else []
    return {
        "version_id": version_id,
        "product_name": product_name,
        "doc_type": str(metadata.get("doc_type") or "기타"),
        "effective_date": effective_date,
        "date_evidence": str(metadata.get("date_evidence") or ""),
        "facts": facts,
        "previous_effective_date": (previous or {}).get("effective_date") or "",
        "changes": changes,
        "timeline": timeline_rows,
    }


def _field_key(field: str) -> str:
    """field명 정규화 키 — 버전 간 표기 편차('중도해지 이율' vs '중도해지이율',
    '가입금액(최소)' vs '가입금액_최소')를 같은 항목으로 매칭한다."""
    import re

    return re.sub(r"[\s_()\[\]·/-]", "", field).lower()


def compute_changes(previous: dict[str, Any], new_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """직전 버전 대비 field 단위 변경점 — 변경/신설/삭제를 심사자 언어로.

    비교는 정규화 키 기준(표기 편차 흡수), 표시는 새 문서의 field명 기준.
    """
    try:
        old_facts = json.loads(previous.get("facts_json") or "[]")
    except Exception:  # noqa: BLE001
        old_facts = []
    old_by_key: dict[str, tuple[str, str]] = {
        _field_key(str(f.get("field"))): (str(f.get("field")), str(f.get("value") or "")) for f in old_facts
    }
    new_by_key: dict[str, tuple[str, str]] = {
        _field_key(str(f.get("field"))): (str(f.get("field")), str(f.get("value") or "")) for f in new_facts
    }
    changes: list[dict[str, Any]] = []
    for key, (field, new_value) in new_by_key.items():
        if key not in old_by_key:
            changes.append({"field": field, "kind": "added", "old": "", "new": new_value})
            continue
        old_value = old_by_key[key][1]
        if old_value.strip() != new_value.strip():
            changes.append({"field": field, "kind": "changed", "old": old_value, "new": new_value})
    for key, (field, old_value) in old_by_key.items():
        if key not in new_by_key:
            changes.append({"field": field, "kind": "removed", "old": old_value, "new": ""})
    return changes
