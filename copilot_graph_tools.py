"""심사 코파일럿용 Neo4j 조회 도구 — 에이전트 데이터 거버넌스 레이어.

거버넌스 원칙:
1. 읽기 전용 — execute_read 만 사용. T2C 생성 쿼리는 write 키워드 차단 후 실행.
2. 워크스페이스 격리 — 모든 쿼리에 workspace_id($ws) 필터 강제(T2C 도 검증).
3. 결과 상한 — 행 수 LIMIT + 텍스트 클립으로 컨텍스트/토큰 폭주 방지.
4. 감사 추적 — T2C 는 생성된 Cypher 를 결과에 포함해 답변에서 인용·검증 가능.
5. 템플릿 우선 — 고빈도 질의는 결정론 템플릿 도구, 롱테일만 T2C.
   (Neo4j Text2Cypher 가이드의 complexity-frequency matrix 권고)
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from langchain_core.tools import tool
from neo4j import GraphDatabase, unit_of_work

LOGGER = logging.getLogger(__name__)

WS = os.environ.get("CCG_WORKSPACE_ID", "graphcompliance_mvp_jb_20260530")
QUERY_TIMEOUT_S = 15.0
T2C_MAX_ROWS = 15
CELL_CLIP = 350

_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )
    return _driver


def _read(cypher: str, **params) -> list[dict[str, Any]]:
    @unit_of_work(timeout=QUERY_TIMEOUT_S)
    def work(tx):
        return [record.data() for record in tx.run(cypher, ws=WS, **params)]

    with _get_driver().session() as session:
        return session.execute_read(work)


def _clip_value(value: Any, limit: int = CELL_CLIP) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    if isinstance(value, list):
        return [_clip_value(item, limit) for item in value[:6]]
    if isinstance(value, dict):
        return {k: _clip_value(v, limit) for k, v in value.items()}
    return value


def _dumps(rows: list[dict[str, Any]], limit: int = CELL_CLIP) -> str:
    return json.dumps([_clip_value(row, limit) for row in rows], ensure_ascii=False)


# ---------------------------------------------------------------------------
# 템플릿 도구 — 고빈도 질의는 변수만 채우는 결정론 쿼리로.
# ---------------------------------------------------------------------------


@tool
def search_regulations(keyword: str, tier: str = "") -> str:
    """법령·시행령·감독규정·고시·가이드라인·심의기준 조문을 키워드로 검색한다.

    keyword: 본문/조문 제목/문서명에서 찾을 한국어 키워드 (예: '세전', '예금자보호', '단정적')
    tier: '' = 전체, 'law' = 법령(법적 구속력), 'guideline' = 가이드라인·심의기준(자율규제)
    반환: 문서명, 조문, 권위 계층, 원문 검수 여부, 본문 발췌.
    """
    rows = _read(
        """
        MATCH (a:LawArticle)
        WHERE a.workspace_id = $ws
          AND (a.text CONTAINS $kw OR a.heading CONTAINS $kw OR a.document_title CONTAINS $kw)
          AND ($tier = '' OR coalesce(a.authority_tier, 'law') = $tier)
        RETURN a.document_title AS 문서, a.heading AS 조문,
               coalesce(a.authority_tier, 'law') AS 권위계층,
               coalesce(a.ocr_verified, true) AS 원문검수됨,
               left(a.text, 400) AS 본문발췌
        LIMIT 8
        """,
        kw=keyword,
        tier=tier,
    )
    return _dumps(rows) if rows else "검색 결과 없음"


_CIRCLED = "⓪①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def _extract_clause(text: str, clause: int) -> str | None:
    """조문 전문에서 ①∼⑮ 항 하나를 결정론적으로 발췌한다."""
    if not 1 <= clause < len(_CIRCLED):
        return None
    parts = re.split(r"(?=[①-⑮])", text)
    matched = [p.strip() for p in parts if p.strip().startswith(_CIRCLED[clause])]
    # 원문에 항 번호가 "② ②"처럼 중복 표기된 경우 빈 조각이 먼저 잡힌다 — 가장 긴 조각 선택.
    return max(matched, key=len) if matched else None


@tool
def get_regulation_article(document_keyword: str, article_no: str, clause_no: str = "") -> str:
    """특정 규정 문서의 특정 조문 원문을 가져온다. 항 단위 발췌 가능.

    document_keyword: 문서명 일부 (예: '광고심의 기준', '금융소비자 보호에 관한 법률', '심사지침')
    article_no: 조 번호 (예: '제17조', '제22조'). '제22조 제2항'처럼 넣어도 항을 분리 처리한다.
    clause_no: 항 번호 (예: '2' 또는 '제2항'). 지정하면 그 항만 발췌해 반환.
    """
    # '제22조 제2항' / '제22조제2항' 형태 → 조/항 분리 (조문은 조 단위로 저장돼 있음)
    match = re.match(r"\s*(제\d+조(?:의\d+)?)\s*(?:제?\s*(\d+)\s*항)?", article_no)
    base_no = match.group(1) if match else article_no
    clause_digits = re.sub(r"\D", "", clause_no) or (match.group(2) if match and match.group(2) else "")

    rows = _read(
        """
        MATCH (a:LawArticle)
        WHERE a.workspace_id = $ws
          AND a.document_title CONTAINS $doc
          AND (a.article_no = $no OR a.heading CONTAINS $no)
        RETURN a.document_title AS 문서, a.heading AS 조문,
               coalesce(a.authority_tier, 'law') AS 권위계층,
               coalesce(a.ocr_verified, true) AS 원문검수됨,
               left(a.text, 4500) AS 원문
        LIMIT 3
        """,
        doc=document_keyword,
        no=base_no,
    )
    if not rows:
        return "해당 조문을 찾지 못함"
    if clause_digits:
        clause = int(clause_digits)
        for row in rows:
            excerpt = _extract_clause(row.get("원문") or "", clause)
            if excerpt:
                row["원문"] = excerpt
                row["발췌"] = f"제{clause}항"
            else:
                row["발췌"] = f"제{clause}항을 찾지 못해 조문 전문을 반환"
    # 조문 원문은 인용이 목적이므로 일반 셀 클립(350자)보다 넉넉하게.
    return _dumps(rows, limit=2500)


@tool
def search_compliance_units(keyword: str) -> str:
    """정책 그래프의 심의 기준 단위(ComplianceUnit)를 키워드로 검색한다.

    광고 심의에서 어떤 기준이 존재하는지, 그 기준의 근거 조문이 무엇인지 찾을 때 사용.
    keyword 예: '확정', '보장', '누구나', '수수료', '예금자보호'
    """
    rows = _read(
        """
        MATCH (cu:ComplianceUnit)
        WHERE cu.workspace_id = $ws
          AND (cu.subject CONTAINS $kw OR cu.constraint CONTAINS $kw
               OR cu.context CONTAINS $kw OR cu.principle CONTAINS $kw)
        OPTIONAL MATCH (g:LawArticle)-[:GROUNDS_CU]->(cu)
        WHERE g.workspace_id = $ws
        RETURN cu.subject AS 대상, left(cu.constraint, 300) AS 기준_내용,
               cu.principle AS 판매원칙, cu.modality AS 성격,
               cu.source_article AS 근거_조문,
               collect(DISTINCT g.document_title + ' ' + g.heading)[0..2] AS 그라운딩_조문
        LIMIT 8
        """,
        kw=keyword,
    )
    return _dumps(rows) if rows else "검색 결과 없음"


@tool
def get_product_facts(product_name: str) -> str:
    """상품 그래프에서 특정 상품의 상품설명서 사실(금리·기간·조건·보호 한도 등)을 조회한다.

    product_name: 상품명 일부 (예: 'JUMP UP', '시니어우대예금')
    """
    rows = _read(
        """
        MATCH (f:ProductFact)
        WHERE f.workspace_id = $ws AND f.matched_product CONTAINS $name
        RETURN f.matched_product AS 상품, f.fact_type AS 항목, f.value AS 값,
               f.condition AS 조건, left(coalesce(f.evidence_text, ''), 200) AS 근거_문구
        LIMIT 12
        """,
        name=product_name,
    )
    if rows:
        return _dumps(rows)
    products = _read(
        """
        MATCH (p:Product)
        WHERE p.workspace_id = $ws AND p.name CONTAINS $name
        RETURN p.name AS 상품명, p.product_group AS 상품군 LIMIT 8
        """,
        name=product_name,
    )
    return (
        "상품설명서 사실 없음. 등록된 상품 후보: " + _dumps(products)
        if products
        else "해당 상품을 찾지 못함"
    )


@tool
def list_regulation_documents() -> str:
    """적재된 규정 문서 목록(문서명·조문 수·권위 계층)을 조회한다. 어떤 규정이 있는지 물을 때 사용."""
    rows = _read(
        """
        MATCH (a:LawArticle)
        WHERE a.workspace_id = $ws
        RETURN a.document_title AS 문서, count(a) AS 조문수,
               collect(DISTINCT coalesce(a.authority_tier, 'law'))[0] AS 권위계층
        ORDER BY 조문수 DESC
        LIMIT 30
        """
    )
    return _dumps(rows)


# ---------------------------------------------------------------------------
# Text2Cypher — 템플릿이 못 덮는 롱테일 질의. 결정론 검증 + 1회 재생성 루프.
# ---------------------------------------------------------------------------

_SCHEMA_SUMMARY = """노드 (모두 workspace_id 속성 보유 — 반드시 workspace_id = $ws 필터):
- LawArticle: document_title, article_no, article_title, heading, text, authority_tier('law'|'guideline'), ocr_verified
- ComplianceUnit: subject, constraint, condition, context, principle, cu_type, modality, source_article
- CULegalElementProfile: action_type, required_positive_features
- PolicyHypernym: name, description, domain, status
- Product: name, product_group
- ProductFact: fact_type, value, condition, unit, evidence_text, matched_product
- MandatoryDisclosure: label, source
- ProhibitedExpression: label, source
관계:
- (LawArticle)-[:GROUNDS_CU]->(ComplianceUnit)   // 조문이 심의 기준을 그라운딩
- (ComplianceUnit)-[:GROUNDED_IN]->(LegalClause)
- (ComplianceUnit)-[:HAS_SUBJECT_HYPERNYM]->(PolicyHypernym)
- (ComplianceUnit)-[:HAS_LEGAL_ELEMENT_PROFILE]->(CULegalElementProfile)
- (ComplianceUnit)-[:DERIVES_PREMISE]->(Premise), (Premise)-[:SUPPORTS_CU]->(ComplianceUnit)
- (ComplianceUnit)-[:PROHIBITS_EXPRESSION]->(ProhibitedExpression)"""

_WRITE_RE = re.compile(
    r"(?i)\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV)\b|apoc\.(?!meta|text|coll)"
)


def _validate_cypher(cypher: str) -> str:
    text = cypher.strip().removeprefix("```cypher").removeprefix("```").removesuffix("```").strip()
    if _WRITE_RE.search(text):
        raise ValueError("읽기 전용 쿼리만 허용됩니다 (쓰기 키워드 감지)")
    if "$ws" not in text:
        raise ValueError("모든 노드 매치에 workspace_id = $ws 필터가 필요합니다")
    if not re.search(r"(?i)\bLIMIT\s+\d+", text):
        text += f"\nLIMIT {T2C_MAX_ROWS}"
    return text


def _generate_cypher(question: str, error_feedback: str = "") -> str:
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-5.4-nano"))
    prompt = f"""당신은 Cypher 쿼리 생성기입니다. 아래 그래프 스키마에서 질문에 답하는 읽기 전용 Cypher 하나만 출력하세요.

{_SCHEMA_SUMMARY}

규칙:
- MATCH/OPTIONAL MATCH/WHERE/RETURN/ORDER BY/LIMIT 만 사용 (쓰기 절 금지)
- 모든 노드 매치에 workspace_id = $ws 필터 (파라미터 $ws 는 실행기가 주입)
- LIMIT {T2C_MAX_ROWS} 이하
- RETURN 별칭은 한국어로
- 설명 없이 Cypher 만 출력

질문: {question}"""
    if error_feedback:
        prompt += f"\n\n직전 시도 오류(수정해서 다시): {error_feedback}"
    return str(model.invoke(prompt).content)


@tool
def graph_query(question: str) -> str:
    """정책·상품·가이드라인 그래프에 대한 자유 질의. 다른 검색 도구로 답이 안 나올 때만 사용.

    자연어 질문을 읽기 전용 Cypher 로 변환해 실행한다 (Text2Cypher).
    question 예: '가이드라인 계층 조문이 그라운딩하는 심의 기준이 몇 개야?'
    """
    error = ""
    for _ in range(2):  # 생성 → 실패 시 오류 피드백으로 1회 재생성
        try:
            cypher = _validate_cypher(_generate_cypher(question, error))
            rows = _read(cypher)[:T2C_MAX_ROWS]
            LOGGER.info("graph_query 실행: %s", cypher.replace("\n", " ")[:200])
            return json.dumps(
                {"실행한_쿼리": cypher, "결과": [_clip_value(r) for r in rows]},
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:300]
    return f"그래프 질의 실패: {error}"


GRAPH_TOOLS = [
    search_regulations,
    get_regulation_article,
    search_compliance_units,
    get_product_facts,
    list_regulation_documents,
    graph_query,
]
