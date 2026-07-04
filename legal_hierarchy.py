"""Parent-law (모법) lookup for cited sub-regulation articles.

CU가 시행령·감독규정 조문을 인용할 때, build_cross_law_citations.py 가 만든
법령 간 CITES_ARTICLE 엣지를 따라 광고·권유 규제의 모법 조문(금소법 제21조·
제22조 등)을 찾아 병기한다. 모법 조문 누락이 article recall 손실의 대부분을
차지했기 때문이다.

Neo4j 미설정/접속 실패 시에는 빈 매핑으로 동작해 파이프라인을 막지 않는다.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache

from env_loader import load_local_env

logger = logging.getLogger(__name__)

ARTICLE_RE = re.compile(r"제\d+조(의\d+)?")

# 모법 후보를 광고·권유 규제 조문으로 한정한다. 위임 인용을 무제한 펼치면
# 기본권리·청약철회 같은 무관 조문까지 병기되어 정밀도를 깎는다.
PARENT_TITLE_FILTER = ("광고", "권유")

PARENT_MAP_QUERY = """
MATCH (sub:LawArticle {workspace_id: $ws})-[:CITES_ARTICLE*1..2]->(parent:LawArticle {workspace_id: $ws})
WHERE sub.document_title <> parent.document_title
  AND NOT parent.document_title CONTAINS '시행령'
  AND NOT parent.document_title CONTAINS '감독규정'
  AND any(token IN $title_tokens WHERE parent.article_title CONTAINS token)
RETURN sub.document_title AS sub_law, sub.article_no AS sub_no,
       collect(DISTINCT parent.document_title + ' ' + parent.article_no) AS parents
"""


def normalize_key(text: str) -> str:
    return "".join(str(text or "").split())


def _creds_for_workspace(workspace_id: str) -> tuple[str, str, str]:
    """팀 공용 Aura(KR 코퍼스) 읽기 전용 라우팅 — retriever/copilot_tools와 동일 규칙."""
    team = {t.strip() for t in os.environ.get("TEAM_NEO4J_WORKSPACES", "").replace(",", " ").split() if t.strip()}
    if workspace_id in team:
        uri = os.environ.get("TEAM_NEO4J_URI", "")
        user = os.environ.get("TEAM_NEO4J_USER", "")
        password = os.environ.get("TEAM_NEO4J_PASSWORD", "")
        if uri and user and password:
            return uri, user, password
    return (
        os.environ.get("NEO4J_URI", ""),
        os.environ.get("NEO4J_USER") or "",
        os.environ.get("NEO4J_PASSWORD", ""),
    )


@lru_cache(maxsize=4)
def load_parent_map(workspace_id: str) -> dict[tuple[str, str], tuple[str, ...]]:
    """(정규화된 법령명, 제N조) → 병기할 모법 조문 목록. 실패 시 빈 dict."""
    load_local_env()
    uri, user, password = _creds_for_workspace(workspace_id)
    if not uri or not user or not password:
        logger.info("legal_hierarchy: NEO4J env not set; parent-article enrichment disabled")
        return {}
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            rows = list(
                session.run(PARENT_MAP_QUERY, ws=workspace_id, title_tokens=list(PARENT_TITLE_FILTER))
            )
        driver.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("legal_hierarchy: parent map load failed (%s); enrichment disabled", exc)
        return {}
    mapping: dict[tuple[str, str], tuple[str, ...]] = {}
    for row in rows:
        key = (normalize_key(row["sub_law"]), str(row["sub_no"]))
        mapping[key] = tuple(sorted(str(item) for item in row["parents"]))
    logger.info("legal_hierarchy: loaded %d sub-article parent mappings", len(mapping))
    return mapping


def parent_articles_for(source_article: str, *, workspace_id: str) -> list[str]:
    """CU의 source_article 표기("...감독규정 제19조 ①-1")에서 모법 조문을 찾는다."""
    text = str(source_article or "")
    match = ARTICLE_RE.search(text)
    if not match:
        return []
    article_no = match.group(0)
    doc_part = normalize_key(text[: match.start()])
    if not doc_part:
        return []
    mapping = load_parent_map(workspace_id)
    for (sub_law, sub_no), parents in mapping.items():
        if sub_no == article_no and (doc_part == sub_law or doc_part in sub_law or sub_law in doc_part):
            return list(parents)
    return []
