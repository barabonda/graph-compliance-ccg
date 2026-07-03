"""JB dataset-derived product and disclosure context for CCG review runs."""

from __future__ import annotations

import logging
import csv
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from schemas import Claim, ReviewInput


LOGGER = logging.getLogger(__name__)
PRODUCT_GRAPH_SOURCE = "graphcompliance_ccg_product_graph_loader"
MODULE_DIR = Path(__file__).resolve().parent
BUNDLED_PRODUCT_DISCLOSURE_ROOT = MODULE_DIR / "data" / "demo_product_documents"
BUNDLED_PRODUCT_DISCLOSURE_META_PATH = (
    BUNDLED_PRODUCT_DISCLOSURE_ROOT / "jbbank_product_disclosures_metadata_20260528.csv"
)
DEFAULT_PRODUCT_META_PATH = Path(
    "/Users/barabonda/Downloads/JB금융그룹해커톤_데이터셋/금융상품 데이터셋/전북은행 상품문서 메타데이터.xlsx"
)
DEFAULT_PRODUCT_DISCLOSURE_META_PATH = Path(
    "/Users/barabonda/Downloads/jbbank_product_disclosures_20260528/jbbank_product_disclosures_metadata_20260528.csv"
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
    selected_product = selected_product_match(review_input, products, product_group)
    if selected_product:
        products = [selected_product, *[product for product in products if product.get("product") != selected_product.get("product")]]
    requirements = requirements_for_group(product_group)
    source = "Neo4j Product Graph" if any(product.get("source") == PRODUCT_GRAPH_SOURCE for product in products) else "JB 금융상품 데이터셋 · 전북은행 상품문서 메타데이터.xlsx"
    return (
        {
            "product_group": product_group,
            "selected_product_id": review_input.selected_product_id,
            "selected_product_name": review_input.selected_product_name,
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
    family_matches: list[dict[str, Any]] = []
    for product, meta in rows.items():
        if product and product in joined and (product_group == "auto" or meta["product_group"] == product_group):
            matches.append({**meta, "product": product, "match_basis": "exact_product_name"})
    if matches:
        return sorted(matches, key=lambda item: (-int(item["document_count"]), item["product"]))
    for product, meta in rows.items():
        family_name = product_family_name(product)
        if (
            family_name
            and family_name != product
            and family_name in joined
            and (product_group == "auto" or meta["product_group"] == product_group)
        ):
            family_matches.append({**meta, "product": product, "match_basis": "exact_product_family"})
    if family_matches:
        return [preferred_product_variant(family_matches, joined)]
    group_rows = [meta for meta in rows.values() if product_group != "auto" and meta["product_group"] == product_group]
    return sorted(group_rows, key=lambda item: (-int(item["document_count"]), item["product"]))[:5]


def selected_product_match(
    review_input: ReviewInput,
    current_matches: list[dict[str, Any]],
    product_group: str,
) -> dict[str, Any] | None:
    selected_name = review_input.selected_product_name.strip()
    selected_id = review_input.selected_product_id.strip()
    if not selected_name and not selected_id:
        return None

    if selected_name:
        search_matches = search_products(selected_name, product_group=product_group, limit=1)
        if search_matches and float(search_matches[0].get("score") or 0) >= 55:
            return selected_product_payload(search_matches[0], product_group)

    candidates = [*current_matches]
    rows = load_product_rows()
    candidates.extend({**meta, "match_basis": "selected_product"} for meta in rows.values())

    for candidate in candidates:
        candidate_name = str(candidate.get("product") or "")
        candidate_ids = {str(value) for value in candidate.get("source_ids", [])}
        if selected_name and candidate_name == selected_name:
            return selected_product_payload(candidate, product_group)
        if selected_id and selected_id in candidate_ids:
            return selected_product_payload(candidate, product_group)

    if selected_name:
        family_matches = [
            candidate
            for candidate in candidates
            if selected_product_matches_family(selected_name, str(candidate.get("product") or ""))
        ]
        scoped_family_matches = [
            candidate
            for candidate in family_matches
            if product_group == "auto" or candidate.get("product_group") in {product_group, "", None}
        ]
        if scoped_family_matches:
            return selected_product_payload(
                preferred_product_variant(scoped_family_matches, f"{review_input.content_text} {selected_name}"),
                product_group,
            )
    return {
        "product": selected_name or selected_id,
        "product_group": product_group,
        "major": "",
        "subcategory": "",
        "category": "",
        "document_count": 0,
        "document_labels": [],
        "source_ids": [selected_id] if selected_id else [],
        "documents": [],
        "match_basis": "selected_product_not_found",
    }


def selected_product_payload(candidate: dict[str, Any], product_group: str) -> dict[str, Any]:
    return {
        **candidate,
        "product_group": candidate.get("product_group") or product_group,
        "match_basis": "selected_product",
        "selected_product_alias": product_family_name(str(candidate.get("product") or "")),
    }


def product_family_name(product_name: str) -> str:
    """Return the consumer-facing family name before product variant suffixes."""
    return re.sub(r"\([^)]*\)", "", product_name).strip()


def normalized_product_name(product_name: str) -> str:
    return re.sub(r"[\s()（）·._-]+", "", product_name).lower()


def product_query_variants(query: str) -> list[str]:
    """Return normalized product-name variants for user-facing search.

    Marketing users often type a shorter alias such as ``JB도전루틴적금`` even
    when the product graph stores ``도전 루틴 적금``.  Search should absorb that
    prefix noise, while the final selected value still comes from the DB row.
    """

    normalized = normalized_product_name(query)
    if not normalized:
        return []
    variants = {normalized}
    for prefix in ("jb", "jbbank", "전북은행", "전북"):
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            variants.add(normalized[len(prefix) :])
    return [variant for variant in variants if variant]


def product_search_score(query_variants: list[str], product: str, meta: dict[str, Any]) -> tuple[float, str]:
    product_norm = normalized_product_name(product)
    family_norm = normalized_product_name(product_family_name(product))
    metadata_norm = normalized_product_name(
        " ".join(
            [
                product,
                str(meta.get("major") or ""),
                str(meta.get("subcategory") or ""),
                str(meta.get("category") or ""),
                " ".join(str(label) for label in (meta.get("document_labels") or [])),
            ]
        )
    )
    best_score = 0.0
    best_basis = ""
    for query in query_variants:
        if not query:
            continue
        candidates: list[tuple[float, str]] = []
        if query == product_norm:
            candidates.append((100.0, "exact_product_name"))
        if family_norm and query == family_norm:
            candidates.append((96.0, "exact_product_family"))
        if query in product_norm:
            candidates.append((86.0 + min(len(query), 20) / 10, "product_name_contains"))
        if product_norm and product_norm in query:
            candidates.append((82.0, "query_contains_product_name"))
        if family_norm and query in family_norm:
            candidates.append((78.0 + min(len(query), 20) / 20, "product_family_contains"))
        if family_norm and family_norm in query:
            candidates.append((74.0, "query_contains_product_family"))
        if query in metadata_norm:
            candidates.append((58.0, "metadata_contains"))
        if candidates:
            score, basis = max(candidates, key=lambda item: item[0])
            if score > best_score:
                best_score = score
                best_basis = basis
    return best_score, best_basis


def all_product_rows() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    try:
        rows.update(load_product_rows_from_neo4j())
    except Exception as exc:  # noqa: BLE001 - search should degrade to local metadata.
        LOGGER.warning("Neo4j Product Graph search failed; falling back to local metadata: %s", exc)
    return merge_product_rows_with_local_documents(rows, load_product_rows())


def merge_product_rows_with_local_documents(
    primary_rows: dict[str, dict[str, Any]],
    local_rows: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Merge local ProductDocument metadata into Product Graph rows.

    The Product Graph may contain the selected Product node before its PDF
    document edges are populated.  In that case the UI search succeeds, but
    ProductFact extraction later sees ``document_count=0`` and is skipped.
    Local disclosure metadata is the authoritative PDF locator for the MVP, so
    enrich graph rows with local documents for the same product/family.
    """

    merged = {product: dict(meta) for product, meta in primary_rows.items()}
    local_by_product = {normalized_product_name(product): meta for product, meta in local_rows.items()}
    local_by_family: dict[str, list[dict[str, Any]]] = {}
    for product, meta in local_rows.items():
        family_key = normalized_product_name(product_family_name(product))
        if family_key:
            local_by_family.setdefault(family_key, []).append(meta)

    def matching_local_meta(product: str) -> dict[str, Any] | None:
        product_key = normalized_product_name(product)
        if product_key in local_by_product:
            return local_by_product[product_key]
        family_key = normalized_product_name(product_family_name(product))
        family_matches = local_by_family.get(family_key, [])
        if family_matches:
            return preferred_product_variant(family_matches, product)
        return None

    for product, local_meta in local_rows.items():
        merged.setdefault(product, local_meta)

    for product, meta in list(merged.items()):
        if int(meta.get("document_count") or 0) > 0 and meta.get("documents"):
            continue
        local_meta = matching_local_meta(product)
        if not local_meta:
            continue
        enriched = {**meta}
        for key in ("document_count", "document_labels", "source_ids", "documents"):
            enriched[key] = local_meta.get(key, enriched.get(key))
        for key in ("major", "subcategory", "category", "product_group"):
            if not enriched.get(key) or enriched.get(key) == "auto":
                enriched[key] = local_meta.get(key, enriched.get(key))
        if meta.get("source") and local_meta.get("documents"):
            enriched["source"] = f"{meta.get('source')}+local_product_metadata"
        merged[product] = enriched
    return merged


def search_products(query: str = "", product_group: str = "auto", limit: int = 12) -> list[dict[str, Any]]:
    """Search product metadata for UI selection and selected-product resolution."""

    capped_limit = max(1, min(int(limit or 12), 50))
    group = normalize_product_group(product_group, "")
    rows = all_product_rows()
    if not rows:
        return []

    scoped_rows = [
        meta
        for meta in rows.values()
        if group == "auto" or meta.get("product_group") in {group, "", None}
    ]
    variants = product_query_variants(query)
    results: list[dict[str, Any]] = []
    for meta in scoped_rows:
        product = str(meta.get("product") or "")
        if not product:
            continue
        if variants:
            score, basis = product_search_score(variants, product, meta)
            if score <= 0:
                continue
        else:
            score = min(50.0, 20.0 + float(meta.get("document_count") or 0))
            basis = "product_group_top"
        results.append(
            {
                **meta,
                "product": product,
                "score": round(score, 2),
                "match_basis": basis,
                "source": meta.get("source") or "local_product_metadata",
            }
        )

    return sorted(
        results,
        key=lambda item: (
            -float(item.get("score") or 0),
            -int(item.get("document_count") or 0),
            str(item.get("product") or ""),
        ),
    )[:capped_limit]


def selected_product_matches_family(selected_name: str, candidate_name: str) -> bool:
    selected = normalized_product_name(selected_name)
    candidate = normalized_product_name(candidate_name)
    family = normalized_product_name(product_family_name(candidate_name))
    return bool(selected and (selected == candidate or selected == family))


def preferred_product_variant(candidates: list[dict[str, Any]], context_text: str) -> dict[str, Any]:
    def score(candidate: dict[str, Any]) -> tuple[int, int, int, str]:
        name = str(candidate.get("product") or "")
        context = context_text.lower()
        variant_score = 0
        if "월이자" in context and "월이자" in name:
            variant_score += 20
        if ("만기" in context or "일시" in context) and "만기일시" in name:
            variant_score += 20
        if "만기일시" in name:
            variant_score += 5
        return (
            variant_score,
            int(candidate.get("document_count") or 0),
            len(candidate.get("source_ids") or []),
            name,
        )

    return sorted(candidates, key=score, reverse=True)[0]


def match_products_from_neo4j(text: str, claims: list[Claim], product_group: str) -> list[dict[str, Any]]:
    if not os.environ.get("NEO4J_URI") or not (os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME")):
        return []
    if not os.environ.get("NEO4J_PASSWORD"):
        return []

    try:
        rows = merge_product_rows_with_local_documents(load_product_rows_from_neo4j(), load_product_rows())
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

    family_matches = [
        {**meta, "match_basis": "exact_product_family"}
        for product, meta in rows.items()
        if product_family_name(product)
        and product_family_name(product) != product
        and product_family_name(product) in joined
        and (product_group == "auto" or meta["product_group"] == product_group)
    ]
    if family_matches:
        return [preferred_product_variant(family_matches, joined)]

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
    configured_path = Path(os.environ.get("JB_PRODUCT_METADATA_PATH", str(DEFAULT_PRODUCT_META_PATH)))
    metadata_paths = [
        configured_path,
        DEFAULT_PRODUCT_DISCLOSURE_META_PATH,
        BUNDLED_PRODUCT_DISCLOSURE_META_PATH,
    ]
    records: list[dict[str, Any]] = []
    for path in metadata_paths:
        if not path.exists():
            continue
        records = load_product_metadata_records(path)
        if records:
            break
    return product_rows_from_records(records)


def load_product_metadata_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [{str(key): value for key, value in row.items()} for row in csv.DictReader(handle)]
    try:
        import pandas as pd
    except Exception:
        LOGGER.warning("pandas is unavailable; falling back to disclosure CSV metadata for product rows.")
        if path != DEFAULT_PRODUCT_DISCLOSURE_META_PATH:
            return load_product_metadata_records(DEFAULT_PRODUCT_DISCLOSURE_META_PATH)
        return []
    sheet_name = "jbbank_product_disclosures_meta"
    if path.name == DEFAULT_PRODUCT_DISCLOSURE_META_PATH.with_suffix(".xlsx").name:
        sheet_name = "dataset_index"
    df = pd.read_excel(path, sheet_name=sheet_name)
    return [{str(key): value for key, value in row.items()} for row in df.fillna("").to_dict(orient="records")]


def product_rows_from_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        product_name = str(record.get("product") or "").strip()
        if not product_name:
            continue
        grouped.setdefault(product_name, []).append(record)
    for product_name, group in grouped.items():
        first = group[0]
        labels = sorted({str(row.get("label") or "") for row in group if row.get("label")})
        documents = [
            {
                "source_id": str(row.get("source_id", "")),
                "label": str(row.get("label", "")),
                "extension": str(row.get("extension", "")),
                "file_name": str(row.get("file_name", "")),
                "relative_path": str(row.get("relative_path", "")),
                "original_name": str(row.get("original_name", "")),
            }
            for row in group[:20]
        ]
        rows[product_name] = {
            "product": product_name,
            "product_group": major_to_product_group(str(first.get("major", ""))),
            "major": str(first.get("major", "")),
            "subcategory": str(first.get("subcategory", "")),
            "category": str(first.get("category", "")),
            "document_count": int(len(group)),
            "document_labels": labels[:12],
            "source_ids": [str(row.get("source_id") or "") for row in group[:8] if row.get("source_id")],
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
