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
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# 앱 상품군 → 그래프 product_groups 토큰 (그래프는 investment_fund 사용).
PRODUCT_GROUP_TO_GRAPH = {
    "deposit": "deposit",
    "loan": "loan",
    "investment": "investment_fund",
}

@dataclass(frozen=True)
class DisclosureRequirementProfile:
    check_id: str
    check_type: str
    detect_tokens: tuple[str, ...]
    negative_tokens: tuple[str, ...]
    fact_match_tokens: tuple[str, ...]
    required_roles: tuple[str, ...]
    prominence_required: bool
    on_missing: str
    severity: int
    source: str
    product_groups: tuple[str, ...]
    channels: tuple[str, ...] = ()


def profile(
    check_id: str,
    *,
    check_type: str,
    detect_tokens: list[str],
    source: str,
    product_groups: list[str],
    fact_match_tokens: list[str] | None = None,
    negative_tokens: list[str] | None = None,
    required_roles: list[str] | None = None,
    prominence_required: bool = False,
    on_missing: str = "needs_review",
    severity: int = 2,
    channels: list[str] | None = None,
) -> DisclosureRequirementProfile:
    return DisclosureRequirementProfile(
        check_id=check_id,
        check_type=check_type,
        detect_tokens=tuple(detect_tokens),
        negative_tokens=tuple(negative_tokens or []),
        fact_match_tokens=tuple(fact_match_tokens or detect_tokens),
        required_roles=tuple(required_roles or []),
        prominence_required=prominence_required,
        on_missing=on_missing,
        severity=severity,
        source=source,
        product_groups=tuple(product_groups),
        channels=tuple(channels or []),
    )


DISCLOSURE_PROFILES: dict[str, DisclosureRequirementProfile] = {
    "disc_interest_condition": profile(
        "disc_interest_condition",
        check_type="presence_and_prominence",
        detect_tokens=["우대조건", "조건 충족", "가입기간", "계약기간", "고시이자율", "약정이율", "달라질 수 있", "우대금리"],
        negative_tokens=["조건 없음", "조건 없이", "무조건"],
        fact_match_tokens=["우대", "고시이율", "고시 이자율", "고시이자율", "약정이율", "기본이자율", "우대이자율", "가입기간"],
        required_roles=["condition_disclosure"],
        prominence_required=True,
        on_missing="revise",
        severity=3,
        source="은행 광고심의 기준 제16조·제18조 (금리·우대조건)",
        product_groups=["deposit"],
    ),
    "disc_depositor_protection_notice": profile(
        "disc_depositor_protection_notice",
        check_type="presence",
        detect_tokens=["예금자보호", "1억원", "보호법", "예금보험"],
        negative_tokens=["보호 안", "미보호", "보호 대상 아님", "예금자보호 안"],
        fact_match_tokens=["예금자보호", "예금보험", "보호한도", "1억원", "5천만원", "5,000만원"],
        required_roles=["protection_disclosure"],
        on_missing="needs_review",
        severity=2,
        source="은행 광고심의 기준 제16조 (예금자보호 부보내용)",
        product_groups=["deposit"],
    ),
    "disc_tax_and_after_tax_notice": profile(
        "disc_tax_and_after_tax_notice",
        check_type="fact_match",
        detect_tokens=["세전", "세후", "세금"],
        fact_match_tokens=["세전", "세후", "세금"],
        on_missing="needs_review",
        severity=2,
        source="은행 광고심의 기준 (세전/세후 기준 표시)",
        product_groups=["deposit"],
    ),
    "disc_variable_rate_notice": profile(
        "disc_variable_rate_notice",
        check_type="presence_and_prominence",
        detect_tokens=["변동", "달라질 수", "상이", "변동금리"],
        fact_match_tokens=["변동", "달라질 수", "상이", "고시이율", "우대"],
        required_roles=["condition_disclosure", "risk_disclosure"],
        prominence_required=True,
        on_missing="revise",
        severity=3,
        source="금융소비자보호법 광고규제 (금리·수익률 변동 가능성)",
        product_groups=["deposit", "loan", "investment"],
    ),
    "disc_product_terms_notice": profile(
        "disc_product_terms_notice",
        check_type="presence",
        detect_tokens=["상품설명서", "약관", "설명서"],
        required_roles=["condition_disclosure", "risk_disclosure"],
        on_missing="needs_review",
        severity=2,
        source="금융소비자보호법 제19조 (설명서·약관 확인)",
        product_groups=["deposit", "loan", "investment"],
    ),
    "disc_review_approval_notice": profile(
        "disc_review_approval_notice",
        check_type="review_procedure",
        detect_tokens=["심의필", "준법감시인", "유효기간", "협회 심의"],
        required_roles=["review_procedure"],
        on_missing="needs_review",
        severity=1,
        source="은행 광고심의 기준 제4조·제9조 (사전승인·심의필)",
        product_groups=["deposit", "loan", "investment"],
    ),
    "disc_seller_name": profile(
        "disc_seller_name",
        check_type="presence",
        detect_tokens=["전북은행", "JB", "판매업자"],
        on_missing="needs_review",
        severity=1,
        source="금융소비자보호법 광고규제 (판매업자 명칭 표시)",
        product_groups=["deposit", "loan", "investment"],
    ),
    "disc_economic_interest_notice": profile(
        "disc_economic_interest_notice",
        check_type="presence",
        detect_tokens=["추천", "보증", "경제적 이해", "대가"],
        on_missing="needs_review",
        severity=2,
        source="금융소비자보호법 광고규제 (추천·보증 이해관계 표시)",
        product_groups=["deposit", "loan", "investment"],
        channels=["sns", "youtube"],
    ),
    "disc_direct_seller_confirmation": profile(
        "disc_direct_seller_confirmation",
        check_type="presence",
        detect_tokens=["직접판매", "판매업자 확인"],
        on_missing="needs_review",
        severity=2,
        source="금융소비자보호법 광고규제 (직접판매업자 확인)",
        product_groups=["deposit", "loan", "investment"],
        channels=["sns", "youtube"],
    ),
    "disc_loan_conditions": profile(
        "disc_loan_conditions",
        check_type="presence_and_prominence",
        detect_tokens=["대상", "자격", "담보", "심사", "조건"],
        fact_match_tokens=["대상", "자격", "담보", "심사", "상환"],
        required_roles=["condition_disclosure"],
        prominence_required=True,
        on_missing="revise",
        severity=3,
        source="은행 광고심의 기준 (대출 대상·자격·담보 조건)",
        product_groups=["loan"],
    ),
    "disc_overdue_interest_rate": profile(
        "disc_overdue_interest_rate",
        check_type="fact_match",
        detect_tokens=["연체", "연체이자", "연체이자율"],
        fact_match_tokens=["연체", "연체이자", "연체이자율"],
        on_missing="revise",
        severity=3,
        source="은행 광고심의 기준 (연체이자율 표시)",
        product_groups=["loan"],
    ),
    "disc_early_repayment_fee": profile(
        "disc_early_repayment_fee",
        check_type="fact_match",
        detect_tokens=["중도상환", "중도상환수수료"],
        fact_match_tokens=["중도상환", "중도상환수수료", "수수료"],
        on_missing="needs_review",
        severity=2,
        source="은행 광고심의 기준 (중도상환수수료)",
        product_groups=["loan"],
    ),
    "disc_credit_score_impact": profile(
        "disc_credit_score_impact",
        check_type="presence",
        detect_tokens=["신용평점", "신용점수", "신용도"],
        on_missing="needs_review",
        severity=2,
        source="신용정보법/금소법 (신용평점 영향 고지)",
        product_groups=["loan"],
    ),
    "disc_principal_loss_notice": profile(
        "disc_principal_loss_notice",
        check_type="presence_and_prominence",
        detect_tokens=["원금손실", "손실", "투자위험"],
        negative_tokens=["손실 없음", "원금 보장"],
        fact_match_tokens=["원금", "손실", "투자위험"],
        required_roles=["risk_disclosure"],
        prominence_required=True,
        on_missing="reject",
        severity=3,
        source="자본시장법 제57조 (원금손실 가능성)",
        product_groups=["investment"],
    ),
    "disc_past_performance_disclaimer": profile(
        "disc_past_performance_disclaimer",
        check_type="presence_and_prominence",
        detect_tokens=["과거", "실적", "미래 수익", "보장하지"],
        negative_tokens=["미래 수익 보장", "확정 수익"],
        required_roles=["risk_disclosure"],
        prominence_required=True,
        on_missing="revise",
        severity=3,
        source="금융투자회사 영업·업무규정 (과거실적 비보장)",
        product_groups=["investment"],
    ),
    "disc_risk_grade": profile(
        "disc_risk_grade",
        check_type="fact_match",
        detect_tokens=["투자위험등급", "위험등급", "등급"],
        fact_match_tokens=["투자위험등급", "위험등급", "등급"],
        on_missing="revise",
        severity=3,
        source="금융투자상품 위험등급 표시 기준",
        product_groups=["investment"],
    ),
    "disc_fee_notice": profile(
        "disc_fee_notice",
        check_type="fact_match",
        detect_tokens=["수수료", "보수", "판매보수"],
        fact_match_tokens=["수수료", "보수", "판매보수"],
        on_missing="needs_review",
        severity=2,
        source="자본시장법 (수수료·보수 표시)",
        product_groups=["loan", "investment"],
    ),
}

# Backward-compatible alias for call sites that still expect (tokens, source).
DISC_ENRICHMENT: dict[str, tuple[list[str], str]] = {
    check_id: (list(profile.detect_tokens), profile.source)
    for check_id, profile in DISCLOSURE_PROFILES.items()
}


def disclosure_profile(check_id: str) -> DisclosureRequirementProfile | None:
    return DISCLOSURE_PROFILES.get(check_id)


def disclosure_profile_dict(check_id: str) -> dict[str, Any] | None:
    profile_row = disclosure_profile(check_id)
    if not profile_row:
        return None
    return profile_to_dict(profile_row)


def profile_to_dict(profile_row: DisclosureRequirementProfile) -> dict[str, Any]:
    return {
        "check_id": profile_row.check_id,
        "check_type": profile_row.check_type,
        "detect_tokens": list(profile_row.detect_tokens),
        "negative_tokens": list(profile_row.negative_tokens),
        "fact_match_tokens": list(profile_row.fact_match_tokens),
        "required_roles": list(profile_row.required_roles),
        "prominence_required": profile_row.prominence_required,
        "on_missing": profile_row.on_missing,
        "severity": profile_row.severity,
        "source": profile_row.source,
        "product_groups": list(profile_row.product_groups),
        "channels": list(profile_row.channels),
        "profile_supported": True,
    }


def profile_catalog_for_group(product_group: str) -> tuple[dict[str, Any], ...]:
    graph_group = PRODUCT_GROUP_TO_GRAPH.get(product_group, product_group)
    rows = []
    for profile_row in DISCLOSURE_PROFILES.values():
        profile_groups = {PRODUCT_GROUP_TO_GRAPH.get(group, group) for group in profile_row.product_groups}
        if graph_group in profile_groups:
            item = profile_to_dict(profile_row)
            item["label"] = readable_label(profile_row.check_id)
            rows.append(item)
    return tuple(sorted(rows, key=lambda row: str(row["check_id"])))


def profile_catalog_all() -> tuple[dict[str, Any], ...]:
    rows = []
    for profile_row in DISCLOSURE_PROFILES.values():
        item = profile_to_dict(profile_row)
        item["label"] = readable_label(profile_row.check_id)
        rows.append(item)
    return tuple(sorted(rows, key=lambda row: str(row["check_id"])))


def readable_label(check_id: str) -> str:
    labels = {
        "disc_interest_condition": "금리/우대조건 고지",
        "disc_depositor_protection_notice": "예금자보호 고지",
        "disc_tax_and_after_tax_notice": "세전/세후 기준",
        "disc_variable_rate_notice": "변동 가능성 고지",
        "disc_product_terms_notice": "상품설명서·약관 확인",
        "disc_review_approval_notice": "심의필·준법감시인 표시",
        "disc_seller_name": "판매업자 명칭",
        "disc_economic_interest_notice": "경제적 이해관계 표시",
        "disc_direct_seller_confirmation": "직접판매업자 확인",
        "disc_loan_conditions": "대출 조건 고지",
        "disc_overdue_interest_rate": "연체이자율 고지",
        "disc_early_repayment_fee": "중도상환수수료 고지",
        "disc_credit_score_impact": "신용점수 영향 고지",
        "disc_principal_loss_notice": "원금손실 가능성 고지",
        "disc_past_performance_disclaimer": "과거성과 비보장 고지",
        "disc_risk_grade": "투자위험등급 고지",
        "disc_fee_notice": "수수료·보수 고지",
    }
    return labels.get(check_id, check_id)


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

    반환: ({check_id, label, profile fields...}, ...) 정렬된 tuple, 또는 None(폴백).
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
                profile_row = disclosure_profile_dict(disc_id)
                if profile_row:
                    catalog.append({**profile_row, "label": label})
                else:
                    catalog.append(
                        {
                            "check_id": disc_id,
                            "label": label,
                            "source": "금융광고 심의기준",
                            "detect_tokens": [label],
                            "negative_tokens": [],
                            "fact_match_tokens": [label],
                            "required_roles": [],
                            "prominence_required": False,
                            "check_type": "unsupported",
                            "on_missing": "needs_review",
                            "severity": 2,
                            "product_groups": [product_group],
                            "channels": [],
                            "profile_supported": False,
                        }
                    )
    except Exception:
        return None
    finally:
        driver.close()
    return tuple(catalog) or None
