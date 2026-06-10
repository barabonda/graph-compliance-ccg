"""JB dataset-derived product and disclosure context for CCG review runs."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from schemas import Claim, ReviewInput


LOGGER = logging.getLogger(__name__)
PRODUCT_GRAPH_SOURCE = "graphcompliance_ccg_product_graph_loader"
DEFAULT_PRODUCT_META_PATH = Path(
    "/Users/barabonda/Downloads/JB금융그룹해커톤_데이터셋/금융상품 데이터셋/전북은행 상품문서 메타데이터.xlsx"
)


DISCLOSURE_REQUIREMENTS: dict[str, list[dict[str, str]]] = {
    "deposit": [
        {
            "id": "disclosure_deposit_rate_basis",
            "label": "금리 범위 및 산정방법",
            "source": "은행 광고심의 기준 제16조/제17조",
            "why": "최고금리, 우대금리, 적용기간, 산정방법을 소비자가 오인하지 않도록 함께 표시해야 합니다.",
        },
        {
            "id": "disclosure_deposit_preferential_conditions",
            "label": "우대조건 및 적용기간",
            "source": "은행 광고심의 기준 제18조",
            "why": "특판, 이벤트, 제휴 혜택은 대상, 자격요건, 기간, 내용을 함께 안내해야 합니다.",
        },
        {
            "id": "disclosure_depositor_protection",
            "label": "예금자보호 부보내용",
            "source": "은행 광고심의 기준 제16조",
            "why": "예금성 상품 광고는 예금자보호법 등에 따른 부보내용을 유지 고지로 관리해야 합니다.",
        },
        {
            "id": "disclosure_review_number",
            "label": "심의필 번호 및 유효기간",
            "source": "은행 광고심의 기준 제9조/제16조",
            "why": "사전승인 또는 연합회 심의 결과를 소비자가 쉽게 인식할 수 있도록 표시해야 합니다.",
        },
    ],
    "loan": [
        {
            "id": "disclosure_loan_rate_range",
            "label": "대출금리 범위 및 산출기준",
            "source": "금융광고규제 가이드라인/은행 광고심의 기준 제16조",
            "why": "대출상품의 핵심 거래조건인 이자율에 대해 오인하지 않도록 범위와 산출기준을 표시해야 합니다.",
        },
        {
            "id": "disclosure_loan_screening_conditions",
            "label": "심사 조건 및 대출 가능 여부",
            "source": "금융광고규제 가이드라인 관련 Q&A",
            "why": "승인 가능성이나 조건을 단정하지 않고 내부 심사에 따라 달라질 수 있음을 안내해야 합니다.",
        },
        {
            "id": "disclosure_loan_fees",
            "label": "수수료 등 부대비용",
            "source": "은행 광고심의 기준 제16조",
            "why": "수수료, 중도상환수수료 등 소비자 부담 비용을 누락하지 않도록 확인해야 합니다.",
        },
        {
            "id": "disclosure_review_number",
            "label": "심의필 번호 및 유효기간",
            "source": "은행 광고심의 기준 제9조/제16조",
            "why": "사전승인 또는 연합회 심의 결과를 소비자가 쉽게 인식할 수 있도록 표시해야 합니다.",
        },
    ],
    "investment": [
        {
            "id": "disclosure_investment_loss_risk",
            "label": "원금손실 가능성 및 투자위험",
            "source": "금융상품 표시·광고 심사지침/금소법 광고규제",
            "why": "투자성 상품은 수익 가능성과 손실 가능성을 균형 있게 표시해야 합니다.",
        },
        {
            "id": "disclosure_past_performance_no_guarantee",
            "label": "과거성과 미래수익 보장 아님",
            "source": "은행 광고심의 기준 제16조",
            "why": "과거 수익률이나 조기상환 실적이 미래 수익을 보장하지 않음을 고지해야 합니다.",
        },
        {
            "id": "disclosure_fees",
            "label": "수수료 등 부대비용",
            "source": "은행 광고심의 기준 제16조",
            "why": "투자자가 부담하는 비용과 제한 조건을 함께 표시해야 합니다.",
        },
    ],
    "insurance": [
        {
            "id": "disclosure_insurance_guarantee_limits",
            "label": "보장 내용과 보험료/해지환급금 조건",
            "source": "금융광고규제 가이드라인",
            "why": "보장성 상품은 보장 범위, 제한 조건, 소비자 부담 비용을 균형 있게 표시해야 합니다.",
        }
    ],
}


def build_product_context(review_input: ReviewInput, claims: list[Claim]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    product_group = normalize_product_group(review_input.product_group, review_input.content_text)
    products = match_products(review_input.content_text, claims, product_group)
    requirements = requirements_for_group(product_group)
    source = "Neo4j Product Graph" if any(product.get("source") == PRODUCT_GRAPH_SOURCE for product in products) else "JB 금융상품 데이터셋 · 전북은행 상품문서 메타데이터.xlsx"
    return (
        {
            "product_group": product_group,
            "matched_products": products[:12],
            "document_count": sum(int(product.get("document_count", 0)) for product in products),
            "source": source,
        },
        requirements,
    )


def normalize_product_group(product_group: str, text: str) -> str:
    value = (product_group or "auto").strip().lower()
    if value in {"deposit", "loan", "investment", "insurance"}:
        return value
    sample = text.lower()
    if any(token in sample for token in ["예금", "적금", "입출금", "통장"]):
        return "deposit"
    if any(token in sample for token in ["els", "펀드", "투자", "수익률", "조기상환"]):
        return "investment"
    if any(token in sample for token in ["대출", "대출금리", "대출한도", "상환방식", "상환기간"]):
        return "loan"
    if any(token in sample for token in ["보험", "보장성"]):
        return "insurance"
    return "auto"


def requirements_for_group(product_group: str) -> list[dict[str, Any]]:
    base = DISCLOSURE_REQUIREMENTS.get(product_group, [])
    review = {
        "id": "disclosure_review_process",
        "label": "준법감시인 사전승인 및 심의필 표시",
        "source": "은행 광고심의 기준 제4조/제9조",
        "why": "은행 광고는 내부통제기준에 따른 사전승인과 심의필 표시 여부를 운영 절차로 확인해야 합니다.",
    }
    return [*base, review]


def match_products(text: str, claims: list[Claim], product_group: str) -> list[dict[str, Any]]:
    graph_matches = match_products_from_neo4j(text, claims, product_group)
    if graph_matches:
        return graph_matches

    rows = load_product_rows()
    if not rows:
        return []
    needles = {text}
    needles.update(claim.text for claim in claims)
    needles.update(entity.name for claim in claims for entity in claim.entities)
    joined = " ".join(needles)
    matches: list[dict[str, Any]] = []
    for product, meta in rows.items():
        if product and product in joined and (product_group == "auto" or meta["product_group"] == product_group):
            matches.append({**meta, "product": product, "match_basis": "exact_product_name"})
    if matches:
        return sorted(matches, key=lambda item: (-int(item["document_count"]), item["product"]))
    group_rows = [meta for meta in rows.values() if product_group != "auto" and meta["product_group"] == product_group]
    return sorted(group_rows, key=lambda item: (-int(item["document_count"]), item["product"]))[:5]


def match_products_from_neo4j(text: str, claims: list[Claim], product_group: str) -> list[dict[str, Any]]:
    if not os.environ.get("NEO4J_URI") or not (os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME")):
        return []
    if not os.environ.get("NEO4J_PASSWORD"):
        return []

    try:
        rows = load_product_rows_from_neo4j()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Neo4j Product Graph lookup failed; falling back to local metadata: %s", exc)
        return []

    if not rows:
        return []

    needles = {text}
    needles.update(claim.text for claim in claims)
    needles.update(entity.name for claim in claims for entity in claim.entities)
    joined = " ".join(needles)

    exact_matches = [
        {**meta, "match_basis": "exact_product_name"}
        for product, meta in rows.items()
        if product and product in joined and (product_group == "auto" or meta["product_group"] == product_group)
    ]
    if exact_matches:
        return sorted(exact_matches, key=lambda item: (-int(item["document_count"]), item["product"]))

    if product_group == "auto":
        return []
    group_rows = [
        {**meta, "match_basis": "product_group_candidate"}
        for meta in rows.values()
        if meta["product_group"] == product_group
    ]
    return sorted(group_rows, key=lambda item: (-int(item["document_count"]), item["product"]))[:5]


@lru_cache(maxsize=1)
def load_product_rows_from_neo4j() -> dict[str, dict[str, Any]]:
    try:
        from neo4j import GraphDatabase
    except Exception:
        return {}

    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not user or not password:
        return {}

    workspace_id = os.environ.get("WORKSPACE_ID") or os.environ.get("GRAPHCOMPLIANCE_WORKSPACE_ID") or "graphcompliance_mvp_jb_20260530"
    database = os.environ.get("NEO4J_DATABASE")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) if database else driver.session() as session:
            result = session.run(
                """
                MATCH (product:Product {workspace_id: $workspace_id})
                WHERE product.source = $source
                OPTIONAL MATCH (product)-[rel:HAS_PRODUCT_DOCUMENT {workspace_id: $workspace_id, source: $source}]->(doc:ProductDocument {workspace_id: $workspace_id})
                WITH product, collect(DISTINCT doc) AS docs
                RETURN
                    product.name AS product,
                    product.product_group AS product_group,
                    product.major AS major,
                    product.subcategory AS subcategory,
                    product.category AS category,
                    size([doc IN docs WHERE doc IS NOT NULL]) AS document_count,
                    [label IN [doc IN docs WHERE doc IS NOT NULL | doc.label] WHERE label IS NOT NULL][0..12] AS document_labels,
                    [source_id IN [doc IN docs WHERE doc IS NOT NULL | doc.id] WHERE source_id IS NOT NULL][0..8] AS source_ids,
                    [doc IN docs WHERE doc IS NOT NULL][0..20] AS documents
                """,
                workspace_id=workspace_id,
                source=PRODUCT_GRAPH_SOURCE,
            )
            rows: dict[str, dict[str, Any]] = {}
            for record in result:
                product_name = str(record.get("product") or "")
                if not product_name:
                    continue
                rows[product_name] = {
                    "product": product_name,
                    "product_group": str(record.get("product_group") or "auto"),
                    "major": str(record.get("major") or ""),
                    "subcategory": str(record.get("subcategory") or ""),
                    "category": str(record.get("category") or ""),
                    "document_count": int(record.get("document_count") or 0),
                    "document_labels": [str(value) for value in (record.get("document_labels") or [])],
                    "source_ids": [str(value) for value in (record.get("source_ids") or [])],
                    "documents": [document_from_neo4j_node(node) for node in (record.get("documents") or [])],
                    "source": PRODUCT_GRAPH_SOURCE,
                }
            return rows
    finally:
        driver.close()


def document_from_neo4j_node(node: Any) -> dict[str, Any]:
    data = dict(node)
    return {
        "source_id": str(data.get("id") or ""),
        "label": str(data.get("label") or ""),
        "extension": str(data.get("extension") or ""),
        "file_name": str(data.get("file_name") or ""),
        "relative_path": str(data.get("relative_path") or ""),
        "original_name": str(data.get("original_name") or ""),
        "exists": bool(data.get("exists", False)),
    }


@lru_cache(maxsize=1)
def load_product_rows() -> dict[str, dict[str, Any]]:
    path = Path(os.environ.get("JB_PRODUCT_METADATA_PATH", str(DEFAULT_PRODUCT_META_PATH)))
    if not path.exists():
        return {}
    try:
        import pandas as pd
    except Exception:
        return {}
    df = pd.read_excel(path, sheet_name="jbbank_product_disclosures_meta")
    rows: dict[str, dict[str, Any]] = {}
    for product, group in df.groupby("product", dropna=True):
        product_name = str(product)
        first = group.iloc[0]
        labels = sorted({str(value) for value in group["label"].dropna().tolist()})
        documents = [
            {
                "source_id": str(row.get("source_id", "")),
                "label": str(row.get("label", "")),
                "extension": str(row.get("extension", "")),
                "file_name": str(row.get("file_name", "")),
                "relative_path": str(row.get("relative_path", "")),
                "original_name": str(row.get("original_name", "")),
            }
            for _, row in group.head(20).iterrows()
        ]
        rows[product_name] = {
            "product": product_name,
            "product_group": major_to_product_group(str(first.get("major", ""))),
            "major": str(first.get("major", "")),
            "subcategory": str(first.get("subcategory", "")),
            "category": str(first.get("category", "")),
            "document_count": int(len(group)),
            "document_labels": labels[:12],
            "source_ids": [str(value) for value in group["source_id"].dropna().head(8).tolist()],
            "documents": documents,
        }
    return rows


def major_to_product_group(major: str) -> str:
    if "예금" in major:
        return "deposit"
    if "대출" in major:
        return "loan"
    if "복합" in major or "펀드" in major:
        return "investment"
    return "auto"
