"""그래프 기반 필수 고지 카탈로그.

어떤 고지가 어느 상품군에 필요한가(적용범위)는 Neo4j의 DisclosureRequirement
정제 카탈로그(`disc_*`, source=agentic_policy_inventory, product_groups 배열)에서
가져온다 — 즉 **데이터 기반**. 카탈로그에 고지를 추가하면 코드 변경 없이 점검 대상이
된다(새 상품군 포함).

다만 그래프 노드에는 (1) 광고 문안에서 존재를 판정할 키워드 토큰, (2) 근거 조문이
없으므로(현재 source는 provenance 태그), id별 보강 맵으로 입힌다. 적용범위는 그래프,
토큰·조문은 보강 — 노드가 조문/토큰을 직접 갖게 되면 보강은 자연 축소된다.

Neo4j 미가용 시 None을 돌려 호출부가 하드코딩으로 폴백하게 한다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

# 앱 상품군 → 그래프 product_groups 토큰 (그래프는 investment_fund 사용).
PRODUCT_GROUP_TO_GRAPH = {
    "deposit": "deposit",
    "loan": "loan",
    "investment": "investment_fund",
}

# disc_* id → (존재 판정 토큰, 근거 조문). 적용범위는 그래프가 정하고, 여기선
# '문안에 있는지'와 '근거 조문'만 보강한다.
DISC_ENRICHMENT: dict[str, tuple[list[str], str]] = {
    "disc_interest_condition": (
        ["우대조건", "조건 충족", "가입기간", "계약기간", "고시이자율", "약정이율", "달라질 수 있", "우대금리"],
        "은행 광고심의 기준 제16조·제18조 (금리·우대조건)",
    ),
    "disc_depositor_protection_notice": (
        ["예금자보호", "1억원", "5천만원", "보호법", "예금보험"],
        "은행 광고심의 기준 제16조 (예금자보호 부보내용)",
    ),
    "disc_tax_and_after_tax_notice": (
        ["세전", "세후", "세금"],
        "은행 광고심의 기준 (세전/세후 기준 표시)",
    ),
    "disc_variable_rate_notice": (
        ["변동", "달라질 수", "상이", "변동금리"],
        "금융소비자보호법 광고규제 (금리·수익률 변동 가능성)",
    ),
    "disc_product_terms_notice": (
        ["상품설명서", "약관", "설명서"],
        "금융소비자보호법 제19조 (설명서·약관 확인)",
    ),
    "disc_review_approval_notice": (
        ["심의필", "준법감시인", "유효기간", "협회 심의"],
        "은행 광고심의 기준 제4조·제9조 (사전승인·심의필)",
    ),
    "disc_seller_name": (
        ["전북은행", "JB", "판매업자"],
        "금융소비자보호법 광고규제 (판매업자 명칭 표시)",
    ),
    "disc_economic_interest_notice": (
        ["추천", "보증", "경제적 이해", "대가"],
        "금융소비자보호법 광고규제 (추천·보증 이해관계 표시)",
    ),
    "disc_direct_seller_confirmation": (
        ["직접판매", "판매업자 확인"],
        "금융소비자보호법 광고규제 (직접판매업자 확인)",
    ),
    "disc_loan_conditions": (
        ["대상", "자격", "담보", "심사", "조건"],
        "은행 광고심의 기준 (대출 대상·자격·담보 조건)",
    ),
    "disc_overdue_interest_rate": (
        ["연체", "연체이자", "연체이자율"],
        "은행 광고심의 기준 (연체이자율 표시)",
    ),
    "disc_early_repayment_fee": (
        ["중도상환", "중도상환수수료"],
        "은행 광고심의 기준 (중도상환수수료)",
    ),
    "disc_credit_score_impact": (
        ["신용평점", "신용점수", "신용도"],
        "신용정보법/금소법 (신용평점 영향 고지)",
    ),
    "disc_principal_loss_notice": (
        ["원금손실", "손실", "투자위험", "원금"],
        "자본시장법 제57조 (원금손실 가능성)",
    ),
    "disc_past_performance_disclaimer": (
        ["과거", "실적", "미래 수익", "보장하지"],
        "금융투자회사 영업·업무규정 (과거실적 비보장)",
    ),
    "disc_risk_grade": (
        ["투자위험등급", "위험등급", "등급"],
        "금융투자상품 위험등급 표시 기준",
    ),
    "disc_fee_notice": (
        ["수수료", "보수", "판매보수"],
        "자본시장법 (수수료·보수 표시)",
    ),
}


def _neo4j_config() -> tuple[str, str, str, str | None] | None:
    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not user or not password:
        return None
    return uri, user, password, os.environ.get("NEO4J_DATABASE")


@lru_cache(maxsize=32)
def disclosure_catalog_for_group(
    workspace_id: str, product_group: str
) -> tuple[dict[str, Any], ...] | None:
    """상품군별 필수 고지 카탈로그를 그래프에서 가져온다(데이터 기반 적용범위).

    반환: ({check_id, label, source, tokens}, ...) 정렬된 tuple, 또는 None(폴백).
    """
    graph_group = PRODUCT_GROUP_TO_GRAPH.get(product_group)
    if not graph_group:
        return None
    config = _neo4j_config()
    if not config:
        return None
    try:
        from neo4j import GraphDatabase
    except Exception:
        return None
    uri, user, password, database = config
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with (driver.session(database=database) if database else driver.session()) as session:
            rows = session.run(
                """
                MATCH (req:DisclosureRequirement {workspace_id: $workspace_id})
                WHERE req.source = 'agentic_policy_inventory' AND $group IN req.product_groups
                RETURN req.id AS id, req.label AS label
                ORDER BY req.id
                """,
                workspace_id=workspace_id,
                group=graph_group,
            )
            catalog: list[dict[str, Any]] = []
            for row in rows:
                disc_id = str(row.get("id") or "")
                label = str(row.get("label") or disc_id)
                tokens, source = DISC_ENRICHMENT.get(disc_id, ([label], "금융광고 심의기준"))
                catalog.append(
                    {"check_id": disc_id, "label": label, "source": source, "tokens": list(tokens)}
                )
    except Exception:
        return None
    finally:
        driver.close()
    return tuple(catalog) or None
