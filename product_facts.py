"""Product-document fact extraction and claim comparison for CCG reviews."""

from __future__ import annotations

import os
import csv
import logging
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from applicability_gate import gate_disclosure_catalog
from disclosure_catalog import (
    DISCLOSURE_PROFILES,
    disclosure_catalog_for_group,
    disclosure_profile,
    profile_catalog_all,
    resolve_representative_basis,
)
from llm_gateway import LLMGateway
from schemas import Claim, ReviewInput, SentenceUnit
from utils import stable_id, to_jsonable, uses_korean_law_context


LOGGER = logging.getLogger(__name__)
MODULE_DIR = Path(__file__).resolve().parent
BUNDLED_DISCLOSURE_ROOT = MODULE_DIR / "data" / "demo_product_documents"
BUNDLED_DISCLOSURE_META = BUNDLED_DISCLOSURE_ROOT / "jbbank_product_disclosures_metadata_20260528.csv"
# Default disclosure source is the repo-bundled demo set so product-document
# lookup/serving works out-of-the-box on any deployment. Point
# JB_PRODUCT_DISCLOSURE_ROOT / JB_PRODUCT_DISCLOSURE_METADATA_PATH at the full
# 6,098-row JB dataset export to use it instead. No external absolute path is
# hardcoded as a default.
DEFAULT_DISCLOSURE_ROOT = BUNDLED_DISCLOSURE_ROOT
DEFAULT_DISCLOSURE_META = BUNDLED_DISCLOSURE_META
MAX_DOCUMENTS = 3
MAX_PAGES_PER_DOCUMENT = 8
MAX_DOCUMENT_CHARS = 16000
MAX_TOTAL_CHARS = 36000

DOCUMENT_LABEL_PRIORITY = {
    "상품주요내용": 0,
    "상품설명서": 1,
    "약관": 2,
}


PRODUCT_FACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "fact_type": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "condition": {"type": "string"},
                    "source_document_id": {"type": "string"},
                    "page_or_chunk": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "fact_type",
                    "value",
                    "unit",
                    "condition",
                    "source_document_id",
                    "page_or_chunk",
                    "evidence_text",
                    "confidence",
                ],
            },
        }
    },
    "required": ["product_facts"],
}


CLAIM_FACT_COMPARISON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "claim_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim_id": {"type": "string"},
                    "fact_type": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "qualifier": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["claim_id", "fact_type", "value", "unit", "qualifier", "evidence_text", "confidence"],
            },
        },
        "comparison_results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim_fact_index": {"type": "integer"},
                    "product_fact_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "SUPPORTED",
                            "CONTRADICTED",
                            "CONDITION_MISSING",
                            "PROMINENCE_INSUFFICIENT",
                            "NO_PRODUCT_FACT",
                            "NEEDS_PRODUCT_SELECTION",
                        ],
                    },
                    "rationale": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "claim_fact_index",
                    "product_fact_id",
                    "status",
                    "rationale",
                    "evidence_text",
                    "confidence",
                ],
            },
        },
    },
    "required": ["claim_facts", "comparison_results"],
}


# 단일 상품 확정 우선순위. 사용자가 명시적으로 선택한 상품(selected_product)은 퍼지
# 패밀리 매칭이 함께 잡혀도 우선한다 — 선택 상품이 퍼지 매칭에 묻혀 모호 처리되던 버그 방지.
PRODUCT_MATCH_PRIORITY = ("selected_product", "exact_product_name", "exact_product_family")


def resolve_single_product(matched_products: list[dict[str, Any]]) -> dict[str, Any] | None:
    """우선순위 등급을 차례로 보며 해당 등급에 정확히 1개면 그 상품으로 확정한다.
    같은 등급에서 다수가 잡히면(진짜 모호) None → NEEDS_PRODUCT_SELECTION."""
    for tier in PRODUCT_MATCH_PRIORITY:
        same = [item for item in matched_products if item.get("match_basis") == tier]
        if len(same) == 1:
            return same[0]
        if len(same) > 1:
            return None
    return None


class ProductFactAnalyzer:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def analyze(
        self,
        *,
        review_input: ReviewInput,
        claims: list[Claim],
        product_context: dict[str, Any],
        sentence_units: list[SentenceUnit] | None = None,
    ) -> dict[str, Any]:
        matched_products = product_context.get("matched_products", []) or []
        resolved = resolve_single_product(matched_products)
        if resolved is None:
            return empty_product_fact_context(
                status="NEEDS_PRODUCT_SELECTION",
                matched_products=matched_products,
                reason="광고 문안에서 특정 상품명이 하나로 확정되지 않아 상품문서 본문 fact 대조를 수행하지 않았습니다.",
                disclosure_checks=build_disclosure_checks(review_input, sentence_units=sentence_units),
            )

        product = str(resolved.get("product") or "")

        # 선적재 사실 우선 경로 — 로더가 워크스페이스에 따라 둘:
        # · env CCG_PRELOADED_PRODUCT_FACTS_WORKSPACES 등록 workspace(예: KH PoC)는
        #   kunwoo 로더(ProductDocument→CONTAINS_FACT 토폴로지)
        # · 그 외(KR)는 main 로더(Product→HAS_PRODUCT_FACT). 각자 검증된 경로 유지.
        preloaded_facts: list[dict[str, Any]] | None = None
        preloaded_documents: list[dict[str, Any]] = []
        preloaded_status = ""
        preloaded_reason = ""
        if preloaded_facts_enabled(review_input.workspace_id):
            kh_loaded = load_preloaded_product_facts(product=product, workspace_id=review_input.workspace_id)
            if kh_loaded is not None:
                preloaded_facts, preloaded_documents = kh_loaded
                preloaded_status = "PRELOADED"
                preloaded_reason = "Neo4j에 선적재된 검증 ProductFact를 사용했습니다(문서 재추출 생략)."
        else:
            kr_loaded = load_preloaded_product_facts_from_neo4j(
                product=product,
                workspace_id=review_input.workspace_id,
            )
            if kr_loaded and kr_loaded.get("product_facts"):
                preloaded_facts = list(kr_loaded.get("product_facts") or [])
                preloaded_documents = list(kr_loaded.get("selected_documents") or [])
                preloaded_status = "PRELOADED_PRODUCT_FACTS"
                preloaded_reason = "Neo4j에 선제 적재된 ProductFact를 사용했습니다."
        if preloaded_facts is not None:
            product_facts = preloaded_facts
            try:
                claim_facts, comparisons = self.compare_claims(
                    review_input=review_input,
                    claims=claims,
                    product=product,
                    product_facts=product_facts,
                )
            except Exception as exc:
                return {
                    **context_with_documents(
                        status="COMPARISON_FAILED",
                        matched_product=product,
                        selected_documents=preloaded_documents,
                        reason=str(exc),
                    ),
                    "product_facts": product_facts,
                }
            disclosure_checks = build_disclosure_checks(
                review_input,
                product_facts,
                sentence_units=sentence_units,
            )
            return {
                "matched_product": product,
                "selected_documents": preloaded_documents,
                "extraction_status": preloaded_status,
                "product_facts": product_facts,
                "claim_facts": claim_facts,
                "comparison_results": comparisons,
                "disclosure_checks": disclosure_checks,
                "applicability_gate": disclosure_gate_summary_from_checks(disclosure_checks),
                "reason": preloaded_reason,
            }

        documents = select_product_documents(product)
        if not documents:
            return empty_product_fact_context(
                status="NO_PRODUCT_DOCUMENT",
                matched_products=matched_products,
                matched_product=product,
                reason="선택된 상품의 상품주요내용/상품설명서/약관 PDF를 찾지 못했습니다.",
                disclosure_checks=build_disclosure_checks(review_input, sentence_units=sentence_units),
            )
        selected_documents = documents[:MAX_DOCUMENTS]
        for document in selected_documents:
            if not document.get("exists"):
                return context_with_documents(
                    status="DOCUMENT_NOT_FOUND",
                    matched_product=product,
                    selected_documents=selected_documents,
                    reason="상품문서 메타데이터는 있으나 로컬 PDF 파일이 없습니다.",
                )

        snippets: list[dict[str, str]] = []
        try:
            for document in selected_documents:
                snippets.append(extract_document_snippet(document))
        except Exception as exc:
            return context_with_documents(
                status="TEXT_EXTRACTION_FAILED",
                matched_product=product,
                selected_documents=selected_documents,
                reason=str(exc),
            )

        try:
            product_facts = self.extract_product_facts(
                review_input=review_input,
                product=product,
                document_snippets=snippets,
            )
        except Exception as exc:
            return context_with_documents(
                status="FACT_EXTRACTION_FAILED",
                matched_product=product,
                selected_documents=selected_documents,
                reason=str(exc),
            )

        try:
            claim_facts, comparisons = self.compare_claims(
                review_input=review_input,
                claims=claims,
                product=product,
                product_facts=product_facts,
            )
        except Exception as exc:
            return {
                **context_with_documents(
                    status="COMPARISON_FAILED",
                    matched_product=product,
                    selected_documents=selected_documents,
                    reason=str(exc),
                ),
                "product_facts": product_facts,
            }

        status = "EXTRACTED" if product_facts else "NO_PRODUCT_FACT"
        disclosure_checks = build_disclosure_checks(
            review_input,
            product_facts,
            sentence_units=sentence_units,
        )
        return {
            "matched_product": product,
            "selected_documents": selected_documents,
            "extraction_status": status,
            "product_facts": product_facts,
            "claim_facts": claim_facts,
            "comparison_results": comparisons,
            "disclosure_checks": disclosure_checks,
            "applicability_gate": disclosure_gate_summary_from_checks(disclosure_checks),
            "reason": "",
        }

    def extract_product_facts(
        self,
        *,
        review_input: ReviewInput,
        product: str,
        document_snippets: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        result = self.llm.structured(
            name="graphcompliance_product_fact_extraction",
            schema=PRODUCT_FACT_SCHEMA,
            system=(
                "You extract Korean financial product facts from product documents for compliance review. "
                "Use only the provided document snippets. Do not infer missing facts. Prefer facts that can "
                "verify advertising claims: rates, conditions, eligibility, periods, limits, fees, risks, "
                "depositor protection, loss risk, and review-relevant cautions. Quote the shortest supporting "
                "evidence_text from the snippets."
            ),
            user=(
                "[review_context]\n"
                f"product_group={review_input.product_group}\nproduct={product}\n\n"
                "[document_snippets]\n"
                f"{document_snippets}"
            ),
        )
        facts = []
        for index, row in enumerate(result.get("product_facts", [])):
            facts.append(
                {
                    "fact_id": stable_id(
                        "product_fact",
                        product,
                        row.get("source_document_id", ""),
                        row.get("fact_type", ""),
                        row.get("value", ""),
                        index,
                    ),
                    "fact_type": str(row.get("fact_type", "")),
                    "value": str(row.get("value", "")),
                    "unit": str(row.get("unit", "")),
                    "condition": str(row.get("condition", "")),
                    "source_document_id": str(row.get("source_document_id", "")),
                    "page_or_chunk": str(row.get("page_or_chunk", "")),
                    "evidence_text": str(row.get("evidence_text", "")),
                    "confidence": float(row.get("confidence") or 0.0),
                }
            )
        return facts

    def compare_claims(
        self,
        *,
        review_input: ReviewInput,
        claims: list[Claim],
        product: str,
        product_facts: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        result = self.llm.structured(
            name="graphcompliance_claim_fact_comparison",
            schema=CLAIM_FACT_COMPARISON_SCHEMA,
            system=(
                "You compare advertising claim facts against extracted ProductFact evidence. "
                "Use only the provided ad claims and product_facts. Extract fact-like assertions from claims "
                "such as rates, 누구나, 조건 없이, 확정 보장, 수수료 없음, 예금자보호 전액, 원금손실, "
                "eligibility, period, limits, fees, and risk warnings. If the product fact is absent, return "
                "NO_PRODUCT_FACT rather than guessing. If a number matches but required conditions, target, "
                "period, or limits are missing from the ad claim, return CONDITION_MISSING."
            ),
            user=(
                "[ad]\n"
                f"{review_input.content_text}\n\n"
                "[product]\n"
                f"{product}\n\n"
                "[claims]\n"
                f"{to_jsonable(claims)}\n\n"
                "[product_facts]\n"
                f"{product_facts}"
        ),
        )
        claim_facts = []
        claim_by_id = {claim.claim_id: claim for claim in claims}
        sentence_prominence_by_claim = {claim.claim_id: claim.qualifiers[0].prominence_tier if claim.qualifiers else "unknown" for claim in claims}
        for index, row in enumerate(result.get("claim_facts", [])):
            claim_id = str(row.get("claim_id", ""))
            claim_facts.append(
                {
                    "claim_fact_id": stable_id(
                        "claim_fact",
                        claim_id,
                        row.get("fact_type", ""),
                        row.get("value", ""),
                        index,
                    ),
                    "claim_id": claim_id,
                    "fact_type": str(row.get("fact_type", "")),
                    "value": str(row.get("value", "")),
                    "unit": str(row.get("unit", "")),
                    "qualifier": str(row.get("qualifier", "")),
                    "evidence_text": str(row.get("evidence_text", "")),
                    "confidence": float(row.get("confidence") or 0.0),
                    "prominence_tier": sentence_prominence_by_claim.get(claim_id) or ("body" if claim_by_id.get(claim_id) else "unknown"),
                }
            )
        comparisons = []
        product_fact_ids = {fact["fact_id"] for fact in product_facts}
        for index, row in enumerate(result.get("comparison_results", [])):
            claim_index = int(row.get("claim_fact_index") or 0)
            claim_fact_id = claim_facts[claim_index]["claim_fact_id"] if 0 <= claim_index < len(claim_facts) else ""
            product_fact_id = str(row.get("product_fact_id") or "")
            if product_fact_id and product_fact_id not in product_fact_ids:
                product_fact_id = ""
            status = str(row.get("status") or "NO_PRODUCT_FACT")
            comparisons.append(
                {
                    "comparison_id": stable_id("comparison", claim_fact_id, product_fact_id, status, index),
                    "claim_fact_id": claim_fact_id,
                    "product_fact_id": product_fact_id,
                    "status": status,
                    "rationale": str(row.get("rationale", "")),
                    "evidence_text": str(row.get("evidence_text", "")),
                    "confidence": float(row.get("confidence") or 0.0),
                }
            )
        return claim_facts, comparisons


def empty_product_fact_context(
    *,
    status: str,
    matched_products: list[dict[str, Any]],
    reason: str,
    matched_product: str = "",
    disclosure_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checks = disclosure_checks or []
    return {
        "matched_product": matched_product,
        "candidate_products": matched_products[:8],
        "selected_documents": [],
        "extraction_status": status,
        "product_facts": [],
        "claim_facts": [],
        "comparison_results": [],
        "disclosure_checks": checks,
        "applicability_gate": disclosure_gate_summary_from_checks(checks),
        "reason": reason,
    }


def context_with_documents(
    *,
    status: str,
    matched_product: str,
    selected_documents: list[dict[str, Any]],
    reason: str,
) -> dict[str, Any]:
    return {
        "matched_product": matched_product,
        "selected_documents": selected_documents,
        "extraction_status": status,
        "product_facts": [],
        "claim_facts": [],
        "comparison_results": [],
        "disclosure_checks": [],
        "applicability_gate": {},
        "reason": reason,
    }


def load_preloaded_product_facts_from_neo4j(*, product: str, workspace_id: str) -> dict[str, Any] | None:
    """Read product-level ProductFact grounding preloaded into Neo4j.

    This is intentionally optional: if Neo4j is unavailable or no ProductFact
    exists for the product, review runtime falls back to on-demand PDF
    extraction. It should never fabricate ProductFact evidence.
    """
    if not product:
        return None
    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not user or not password:
        return None
    try:
        from neo4j import GraphDatabase
    except Exception:
        return None

    database = os.environ.get("NEO4J_DATABASE")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) if database else driver.session() as session:
            record = session.run(
                """
                MATCH (product:Product {workspace_id: $workspace_id})
                WHERE product.name = $product
                OPTIONAL MATCH (product)-[:HAS_PRODUCT_DOCUMENT]->(doc:ProductDocument {workspace_id: $workspace_id})
                OPTIONAL MATCH (product)-[:HAS_PRODUCT_FACT]->(fact:ProductFact {workspace_id: $workspace_id})
                WITH collect(DISTINCT doc) AS docs, collect(DISTINCT fact) AS facts
                RETURN
                    [doc IN docs WHERE doc IS NOT NULL | doc][0..10] AS documents,
                    [fact IN facts WHERE fact IS NOT NULL | fact] AS product_facts
                """,
                workspace_id=workspace_id,
                product=product,
            ).single()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("preloaded ProductFact lookup failed product=%s err=%s", product, exc)
        return None
    finally:
        driver.close()

    if not record:
        return None
    facts = [product_fact_from_neo4j_node(node) for node in (record.get("product_facts") or [])]
    if not facts:
        return None
    return {
        "selected_documents": [product_document_from_neo4j_node(node) for node in (record.get("documents") or [])],
        "product_facts": facts,
    }


def product_document_from_neo4j_node(node: Any) -> dict[str, Any]:
    data = dict(node)
    return {
        "document_id": str(data.get("id") or ""),
        "product": str(data.get("product_name") or ""),
        "label": str(data.get("label") or ""),
        "original_name": str(data.get("original_name") or ""),
        "file_name": str(data.get("file_name") or ""),
        "relative_path": str(data.get("relative_path") or ""),
        "exists": bool(data.get("exists", False)),
        "source": str(data.get("source") or ""),
    }


def product_fact_from_neo4j_node(node: Any) -> dict[str, Any]:
    data = dict(node)
    return {
        "fact_id": str(data.get("fact_id") or data.get("id") or ""),
        "fact_type": str(data.get("fact_type") or ""),
        "value": str(data.get("value") or ""),
        "unit": str(data.get("unit") or ""),
        "condition": str(data.get("condition") or ""),
        "source_document_id": str(data.get("source_document_id") or ""),
        "page_or_chunk": str(data.get("page_or_chunk") or ""),
        "evidence_text": str(data.get("evidence_text") or ""),
        "confidence": float(data.get("confidence") or 0.0),
        "source": str(data.get("source") or ""),
    }


def build_disclosure_checks(
    review_input: ReviewInput,
    product_facts: list[dict[str, Any]] | None = None,
    sentence_units: list[SentenceUnit] | None = None,
) -> list[dict[str, Any]]:
    """광고 텍스트의 필수 고지 존재/부재를 판정하고, 가능하면 상품설명서
    (product_facts)의 근거 fact를 각 고지에 직접 연결해 내려준다.

    'present'는 광고 문안 기준(토큰 매칭)이고, 'product_doc_evidence'/
    'in_product_doc'는 상품문서 기준이다. 둘을 분리해, '광고엔 없지만
    상품설명서엔 있음'을 프론트 휴리스틱이 아니라 단일 출처로 표현한다.
    """
    text = review_input.content_text
    product_group = review_input.product_group
    if product_group == "auto":
        lowered = text.lower()
        if any(token in lowered for token in ["예금", "적금", "특판"]):
            product_group = "deposit"
        elif any(token in lowered for token in ["대출", "한도", "승인"]):
            product_group = "loan"
        elif any(token in lowered for token in ["els", "펀드", "투자", "수익률"]):
            product_group = "investment"
    # 데이터 기반: 어떤 고지가 필요한가는 그래프 카탈로그(disc_*) 또는 코드
    # profile catalog에서 가져오고, check_type별 검사 방식은 profile이 결정한다.
    graph_catalog = disclosure_catalog_for_group(review_input.workspace_id, product_group)
    # 코드 내장 profile 카탈로그는 한국 법령·심의기준(금소법·신용정보법·자본시장법 등)
    # 기준이므로 KR 관할에서만 병합한다. 비-KR(예: 캄보디아)은 해당 워크스페이스의
    # 그래프 카탈로그(disc_*)만 사용해 타 관할 고지 의무가 주입되지 않게 한다.
    profile_catalog = profile_catalog_all() if uses_korean_law_context(review_input.workspace_id) else []
    catalog = merge_profile_and_graph_catalog(profile_catalog, graph_catalog)
    if catalog:
        enabled, skipped, gate_summary = gate_disclosure_catalog(review_input=review_input, catalog=catalog)
        checks = [
            build_profile_disclosure_check(
                review_input=review_input,
                item=item,
                product_facts=product_facts,
                sentence_units=sentence_units,
                gate_status="ON",
            )
            for item in enabled
        ]
        checks.extend(
            build_skipped_disclosure_check(item)
            for item in skipped
        )
        for check in checks:
            check["applicability_gate"] = {
                "product_group": gate_summary.get("product_group"),
                "channel": gate_summary.get("channel"),
            }
        return checks
    if product_group == "deposit":
        return attach_product_doc_evidence([
            # 조건 고지는 "우대조건" 같은 정형 문구 외에 계약기간별 약정이율·고시
            # 이자율 안내 형태로도 충족된다. 존재 여부만 보고, 현저성(혜택 문구
            # 대비 표시 위계)은 prominence 모듈이 별도로 판단한다.
            disclosure_check(
                "deposit_rate_condition",
                "최고금리 적용 조건",
                any_token(
                    text,
                    [
                        "우대조건", "조건 충족", "조건에 따라", "가입기간",
                        "계약기간별", "유형별 약정이율", "약정이율 적용",
                        "고시 이자율", "고시이자율", "달라질 수 있",
                    ],
                ),
            ),
            disclosure_check("deposit_term", "가입기간", any_token(text, ["개월", "년", "가입기간", "만기"])),
            disclosure_check("deposit_tax_basis", "세전/세후 기준", any_token(text, ["세전", "세후"])),
            disclosure_check("depositor_protection_limit", "예금자보호 한도", any_token(text, ["1억원", "예금자보호", "보호법"])),
            disclosure_check("product_document_notice", "상품설명서·약관 확인", any_token(text, ["상품설명서", "약관", "설명서"])),
        ], product_facts)
    if product_group == "loan":
        return attach_product_doc_evidence([
            disclosure_check("loan_rate_range", "대출금리 범위", any_token(text, ["연 ", "%", "금리"])),
            disclosure_check("loan_screening", "심사 조건", any_token(text, ["심사", "신용도", "상환능력"])),
            disclosure_check("loan_fee", "수수료/부대비용", any_token(text, ["수수료", "부대비용", "중도상환"])),
            disclosure_check("product_document_notice", "상품설명서·약관 확인", any_token(text, ["상품설명서", "약관", "설명서"])),
        ], product_facts)
    if product_group == "investment":
        return attach_product_doc_evidence([
            disclosure_check("investment_loss_risk", "원금손실 가능성", any_token(text, ["원금손실", "손실", "투자위험"])),
            disclosure_check("past_performance_warning", "과거성과 미래수익 보장 아님", any_token(text, ["미래 수익을 보장", "보장하지 않습니다", "과거"])),
            disclosure_check("product_document_notice", "투자설명서·약관 확인", any_token(text, ["투자설명서", "상품설명서", "약관"])),
        ], product_facts)
    return []


def merge_profile_and_graph_catalog(
    profile_catalog: tuple[dict[str, Any], ...],
    graph_catalog: tuple[dict[str, Any], ...] | None,
) -> tuple[dict[str, Any], ...]:
    rows = {str(row.get("check_id") or ""): dict(row) for row in profile_catalog}
    for graph_row in graph_catalog or ():
        check_id = str(graph_row.get("check_id") or "")
        if not check_id:
            continue
        if check_id in rows:
            rows[check_id] = {**rows[check_id], "label": graph_row.get("label") or rows[check_id].get("label")}
        else:
            rows[check_id] = dict(graph_row)
    return tuple(sorted(rows.values(), key=lambda row: str(row.get("check_id") or "")))


def disclosure_gate_summary_from_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    enabled = [row for row in checks if row.get("gate_status") != "OFF"]
    skipped = [row for row in checks if row.get("gate_status") == "OFF"]
    return {
        "enabled_requirements": [
            {
                "check_id": row.get("check_id"),
                "label": row.get("label"),
                "status": row.get("status"),
                "check_type": row.get("check_type"),
                "severity": row.get("severity"),
                "gate_reason": row.get("gate_reason"),
            }
            for row in enabled
        ],
        "skipped_requirements": [
            {
                "check_id": row.get("check_id"),
                "label": row.get("label"),
                "gate_reason": row.get("gate_reason"),
            }
            for row in skipped
        ],
        "gate_diagnostics": [
            {
                "diagnostic_code": "DISCLOSURE_REQUIREMENT_SKIPPED",
                "check_id": row.get("check_id"),
                "reason": row.get("gate_reason"),
            }
            for row in skipped
        ],
    }


def disclosure_check(check_id: str, label: str, present: bool, source: str = "") -> dict[str, Any]:
    return {
        "check_id": check_id,
        "label": label,
        "status": "PRESENT" if present else "MISSING",
        "present": present,
        "source": source,
        "check_type": "presence",
        "severity": 2,
        "on_missing": "needs_review",
        "gate_status": "ON",
        "gate_reason": "legacy fallback",
    }


def normalize_match_text(value: str) -> str:
    """Normalize user/PDF text before lightweight evidence token checks.

    Korean ad copy often arrives from PDF/OCR/clipboard in mixed Unicode forms
    (NFD/NFC compatibility jamo, full-width punctuation, non-breaking spaces).
    Disclosure presence checks should not miss an explicit notice such as
    "준법감시인 심의필" solely because of that representation drift.
    """
    normalized = unicodedata.normalize("NFKC", unicodedata.normalize("NFC", value or ""))
    return " ".join(normalized.split())


def any_token(text: str, tokens: list[str] | tuple[str, ...]) -> bool:
    haystack = normalize_match_text(text)
    return any(normalize_match_text(token) in haystack for token in tokens)


def matched_tokens(text: str, tokens: list[str] | tuple[str, ...]) -> list[str]:
    haystack = normalize_match_text(text)
    return [token for token in tokens if normalize_match_text(token) in haystack]


def build_profile_disclosure_check(
    *,
    review_input: ReviewInput,
    item: dict[str, Any],
    product_facts: list[dict[str, Any]] | None,
    sentence_units: list[SentenceUnit] | None,
    gate_status: str,
) -> dict[str, Any]:
    check_id = str(item.get("check_id") or "")
    label = str(item.get("label") or check_id)
    profile_row = disclosure_profile(check_id)
    if not profile_row or item.get("profile_supported") is False:
        return {
            "check_id": check_id,
            "label": label,
            "status": "UNSUPPORTED_DISCLOSURE_CHECK",
            "present": False,
            "source": str(item.get("source") or ""),
            "check_type": str(item.get("check_type") or "unsupported"),
            "severity": int(item.get("severity") or 2),
            "on_missing": str(item.get("on_missing") or "needs_review"),
            "gate_status": gate_status,
            "gate_reason": str(item.get("gate_reason") or "프로파일이 없어 검사하지 않았습니다."),
            "product_doc_evidence": [],
            "in_product_doc": False,
            "required_roles": list(item.get("required_roles") or []),
            "prominence_required": bool(item.get("prominence_required")),
        }
    text = review_input.content_text
    positive = any_token(text, profile_row.detect_tokens)
    negated = any_token(text, profile_row.negative_tokens)
    role_present = sentence_role_present(sentence_units or [], profile_row.required_roles)
    evidence = link_disclosure_to_facts(check_id, product_facts)
    status = disclosure_status(
        check_type=profile_row.check_type,
        positive=positive,
        negated=negated,
        role_present=role_present,
        has_product_facts=bool(product_facts),
        has_product_doc_evidence=bool(evidence),
    )
    # 권위 계층: 부재 시 어느 규범이 대표 근거인가 (법령 위반 vs 심의기준 미흡).
    basis = resolve_representative_basis(profile_row, situation="missing")
    return {
        "check_id": check_id,
        "label": label,
        "status": status,
        "present": status == "PRESENT",
        "source": profile_row.source,
        "authority_tier": basis["authority_tier"],
        "representative_basis": basis["representative_basis"] or profile_row.source,
        "co_basis": basis.get("co_basis", ""),
        "tier_note": basis.get("tier_note", ""),
        "check_type": profile_row.check_type,
        "severity": profile_row.severity,
        "on_missing": profile_row.on_missing,
        "gate_status": gate_status,
        "gate_reason": str(item.get("gate_reason") or "상품군/채널 적용범위에 해당합니다."),
        "product_doc_evidence": evidence,
        "in_product_doc": bool(evidence),
        "required_roles": list(profile_row.required_roles),
        "prominence_required": profile_row.prominence_required,
        "detected_tokens": matched_tokens(text, profile_row.detect_tokens),
        "negative_detected_tokens": matched_tokens(text, profile_row.negative_tokens),
    }


def disclosure_status(
    *,
    check_type: str,
    positive: bool,
    negated: bool,
    role_present: bool,
    has_product_facts: bool,
    has_product_doc_evidence: bool,
) -> str:
    if positive and negated:
        return "PRESENT_BUT_NEGATED"
    if positive or role_present:
        return "PRESENT"
    if check_type == "fact_match" and not has_product_facts:
        return "NOT_TESTED"
    if has_product_doc_evidence:
        return "IN_PRODUCT_DOC_ONLY"
    return "MISSING"


def sentence_role_present(sentence_units: list[SentenceUnit], roles: tuple[str, ...]) -> bool:
    if not roles:
        return False
    return any(sentence.role in roles for sentence in sentence_units)


def build_skipped_disclosure_check(item: dict[str, Any]) -> dict[str, Any]:
    profile_row = disclosure_profile(str(item.get("check_id") or ""))
    return {
        "check_id": str(item.get("check_id") or ""),
        "label": str(item.get("label") or item.get("check_id") or ""),
        "status": "SKIPPED_BY_GATE",
        "present": False,
        "source": str(item.get("source") or (profile_row.source if profile_row else "")),
        "check_type": str(item.get("check_type") or (profile_row.check_type if profile_row else "presence")),
        "severity": 0,
        "on_missing": "pass_candidate",
        "gate_status": "OFF",
        "gate_reason": str(item.get("gate_reason") or "적용범위 밖 기준입니다."),
        "product_doc_evidence": [],
        "in_product_doc": False,
        "required_roles": list(item.get("required_roles") or (profile_row.required_roles if profile_row else [])),
        "prominence_required": bool(item.get("prominence_required") or (profile_row.prominence_required if profile_row else False)),
    }


# 각 필수 고지를 상품설명서 product_fact에 연결하기 위한 fact_type/조건 토큰.
# 광고 텍스트가 아니라 추출된 product_fact(fact_type·condition·value·evidence)를 본다.
# '상품설명서·약관 확인'은 문서 내용이 아니라 메타 고지이므로 제외한다.
DISCLOSURE_FACT_TOKENS: dict[str, list[str]] = {
    "deposit_rate_condition": [
        "우대", "고시이율", "고시 이자율", "고시이자율", "약정이율", "기본이자율", "우대이자율",
    ],
    "deposit_term": ["계약기간", "가입기간", "만기", "기간"],
    "deposit_tax_basis": ["세전", "세후", "세금"],
    "depositor_protection_limit": ["예금자보호", "예금보험", "보호한도", "5천만원", "5,000만원", "1억원"],
    "loan_rate_range": ["대출금리", "금리", "연이율"],
    "loan_screening": ["심사", "승인", "신용"],
    "loan_fee": ["수수료", "중도상환", "부대비용"],
    "investment_loss_risk": ["원금", "손실", "투자위험"],
    "past_performance_warning": ["과거", "수익률", "실적"],
}


def link_disclosure_to_facts(
    check_id: str, product_facts: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """누락/존재 고지의 주제가 상품설명서에 있는지 product_fact로 직접 연결한다."""
    if not product_facts:
        return []
    # 그래프 카탈로그(disc_*) 체크는 profile fact_match_tokens를, 하드코딩 폴백
    # 체크는 기존 토큰을 쓴다. 없는 경우 빈 evidence를 반환해 NOT_TESTED/
    # UNSUPPORTED 상태가 조용히 통과로 바뀌지 않게 한다.
    tokens = DISCLOSURE_FACT_TOKENS.get(check_id)
    profile_row = DISCLOSURE_PROFILES.get(check_id)
    if not tokens and profile_row:
        tokens = list(profile_row.fact_match_tokens)
    if not tokens:
        return []
    evidence: list[dict[str, Any]] = []
    for fact in product_facts:
        haystack = " ".join(
            str(fact.get(key) or "")
            for key in ("fact_type", "condition", "value", "evidence_text")
        )
        if any(token in haystack for token in tokens):
            evidence.append(
                {
                    "fact_id": str(fact.get("fact_id") or ""),
                    "fact_type": str(fact.get("fact_type") or ""),
                    "value": str(fact.get("value") or ""),
                    "page_or_chunk": str(fact.get("page_or_chunk") or ""),
                }
            )
    return evidence[:4]


def attach_product_doc_evidence(
    checks: list[dict[str, Any]], product_facts: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """각 고지에 상품설명서 근거 fact를 직접 연결(in_product_doc/product_doc_evidence)."""
    for check in checks:
        evidence = link_disclosure_to_facts(str(check.get("check_id") or ""), product_facts)
        check["product_doc_evidence"] = evidence
        check["in_product_doc"] = bool(evidence)
    return checks


def preloaded_facts_enabled(workspace_id: str) -> bool:
    """Preloaded-ProductFact path is opt-in per workspace via env.

    ``CCG_PRELOADED_PRODUCT_FACTS_WORKSPACES`` is a comma/space separated list.
    Unset (the KR default) => always False => the legacy on-demand PDF
    extraction path runs unchanged.
    """
    raw = os.environ.get("CCG_PRELOADED_PRODUCT_FACTS_WORKSPACES", "")
    allowed = {token.strip() for token in raw.replace(",", " ").split() if token.strip()}
    return workspace_id in allowed


def load_preloaded_product_facts(
    *, product: str, workspace_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Load pre-ingested ProductFacts (and their documents) from Neo4j.

    Returns (product_facts, selected_documents) in exactly the shapes the
    on-demand extractor produces, or None to fall through to the legacy path
    (workspace not opted in, Neo4j unavailable, or no facts stored).
    """
    if not preloaded_facts_enabled(workspace_id):
        return None
    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not user or not password:
        return None
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        database = os.environ.get("NEO4J_DATABASE")
        try:
            with driver.session(database=database) if database else driver.session() as session:
                records = [
                    dict(record)
                    for record in session.run(
                        """
                        MATCH (p:Product {name: $product, workspace_id: $ws})
                              -[:HAS_PRODUCT_DOCUMENT]->(d:ProductDocument {workspace_id: $ws})
                        OPTIONAL MATCH (d)-[:CONTAINS_FACT]->(f:ProductFact {workspace_id: $ws})
                        // DISTINCT: 심사 영속화가 run마다 병렬 엣지를 MERGE하므로
                        // (persistence.py:516,595 — 엣지 props에 review_run_id 포함)
                        // 경로 곱으로 fact가 중복 수집되는 것을 막는다.
                        RETURN DISTINCT d AS doc, collect(DISTINCT f) AS facts
                        """,
                        product=product,
                        ws=workspace_id,
                    )
                ]
        finally:
            driver.close()
    except Exception as exc:  # noqa: BLE001 — 실패 시 조용히 기존 경로로 폴백.
        import logging

        logging.getLogger(__name__).warning("preloaded product-fact lookup failed; falling back: %s", exc)
        return None

    documents: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for record in records:
        doc = dict(record["doc"])
        path = resolve_document_path(str(doc.get("relative_path") or ""))
        documents.append(
            {
                "document_id": str(doc.get("id") or ""),
                "product": product,
                "label": str(doc.get("label") or ""),
                "original_name": str(doc.get("original_name") or ""),
                "file_name": str(doc.get("file_name") or ""),
                "relative_path": str(doc.get("relative_path") or ""),
                "file_path": str(path),
                "exists": bool(doc.get("exists", path.exists())),
            }
        )
        for node in record["facts"] or []:
            fact = dict(node)
            facts.append(
                {
                    "fact_id": str(fact.get("id") or ""),
                    "fact_type": str(fact.get("fact_type") or ""),
                    "value": str(fact.get("value") or ""),
                    "unit": str(fact.get("unit") or ""),
                    "condition": str(fact.get("condition") or ""),
                    "source_document_id": str(fact.get("source_document_id") or ""),
                    "page_or_chunk": str(fact.get("page_or_chunk") or ""),
                    "evidence_text": str(fact.get("evidence_text") or ""),
                    "confidence": float(fact.get("confidence") or 0.0),
                }
            )
    if not facts:
        return None
    return facts, documents[:MAX_DOCUMENTS]


def select_product_documents(product: str) -> list[dict[str, Any]]:
    rows = [row for row in load_disclosure_metadata() if str(row.get("product") or "") == product]
    rows = [row for row in rows if str(row.get("extension") or "").lower() == ".pdf"]
    rows.sort(
        key=lambda row: (
            DOCUMENT_LABEL_PRIORITY.get(str(row.get("label") or ""), 99),
            str(row.get("file_name") or ""),
        )
    )
    return [document_from_row(row) for row in rows]


def document_from_row(row: dict[str, Any]) -> dict[str, Any]:
    path = resolve_document_path(str(row.get("relative_path") or ""))
    return {
        "document_id": str(row.get("source_id") or ""),
        "product": str(row.get("product") or ""),
        "label": str(row.get("label") or ""),
        "original_name": str(row.get("original_name") or ""),
        "file_name": str(row.get("file_name") or ""),
        "relative_path": str(row.get("relative_path") or ""),
        "file_path": str(path),
        "exists": path.exists(),
    }


def resolve_document_path(relative_path: str) -> Path:
    configured_root = Path(os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT", str(DEFAULT_DISCLOSURE_ROOT)))
    roots = [configured_root]
    if BUNDLED_DISCLOSURE_ROOT not in roots:
        roots.append(BUNDLED_DISCLOSURE_ROOT)
    rel = relative_path.replace("\\", "/")
    candidates = (rel, unicodedata.normalize("NFD", rel), unicodedata.normalize("NFC", rel))
    for root in roots:
        for candidate in candidates:
            path = root / candidate
            if path.exists():
                return path
    return configured_root / rel


def extract_document_snippet(document: dict[str, Any]) -> dict[str, str]:
    path = Path(str(document.get("file_path") or ""))
    text = extract_pdf_text(path)
    return {
        "source_document_id": str(document.get("document_id") or ""),
        "label": str(document.get("label") or ""),
        "file_name": str(document.get("file_name") or ""),
        "text": text[:MAX_DOCUMENT_CHARS],
    }


def extract_pdf_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("pypdf is required for ProductFact extraction.") from exc
    reader = PdfReader(str(path))
    chunks = []
    total = 0
    for page_index, page in enumerate(reader.pages[:MAX_PAGES_PER_DOCUMENT], start=1):
        page_text = page.extract_text() or ""
        if not page_text.strip():
            continue
        chunk = f"[page {page_index}]\n{page_text.strip()}"
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_TOTAL_CHARS:
            break
    text = "\n\n".join(chunks).strip()
    if not text:
        raise RuntimeError(f"No text extracted from PDF: {path}")
    return text[:MAX_TOTAL_CHARS]


@lru_cache(maxsize=1)
def load_disclosure_metadata() -> list[dict[str, Any]]:
    path = Path(os.environ.get("JB_PRODUCT_DISCLOSURE_METADATA_PATH", str(DEFAULT_DISCLOSURE_META)))
    if not path.exists():
        LOGGER.warning(
            "Disclosure metadata not found at %s; product-document lookup returns empty. "
            "Set JB_PRODUCT_DISCLOSURE_METADATA_PATH to a valid metadata file (default is the bundled demo CSV).",
            path,
        )
        return []
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [{str(key): value for key, value in row.items()} for row in csv.DictReader(handle)]
    try:
        import pandas as pd
    except Exception:
        return []
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, sheet_name="dataset_index")
    else:
        df = pd.read_csv(path)
    return [{str(key): value for key, value in row.items()} for row in df.fillna("").to_dict(orient="records")]
