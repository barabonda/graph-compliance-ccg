"""Product-document fact extraction and claim comparison for CCG reviews."""

from __future__ import annotations

import os
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from llm_gateway import LLMGateway
from schemas import Claim, ReviewInput
from utils import stable_id, to_jsonable


DEFAULT_DISCLOSURE_ROOT = Path("/Users/barabonda/Downloads/jbbank_product_disclosures_20260528")
DEFAULT_DISCLOSURE_META = DEFAULT_DISCLOSURE_ROOT / "jbbank_product_disclosures_metadata_20260528.csv"
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


class ProductFactAnalyzer:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def analyze(
        self,
        *,
        review_input: ReviewInput,
        claims: list[Claim],
        product_context: dict[str, Any],
    ) -> dict[str, Any]:
        matched_products = product_context.get("matched_products", []) or []
        exact_products = [item for item in matched_products if item.get("match_basis") == "exact_product_name"]
        if len(exact_products) != 1:
            return empty_product_fact_context(
                status="NEEDS_PRODUCT_SELECTION",
                matched_products=matched_products,
                reason="광고 문안에서 특정 상품명이 하나로 확정되지 않아 상품문서 본문 fact 대조를 수행하지 않았습니다.",
            )

        product = str(exact_products[0].get("product") or "")
        documents = select_product_documents(product)
        if not documents:
            return empty_product_fact_context(
                status="NO_PRODUCT_DOCUMENT",
                matched_products=matched_products,
                matched_product=product,
                reason="선택된 상품의 상품주요내용/상품설명서/약관 PDF를 찾지 못했습니다.",
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
        return {
            "matched_product": product,
            "selected_documents": selected_documents,
            "extraction_status": status,
            "product_facts": product_facts,
            "claim_facts": claim_facts,
            "comparison_results": comparisons,
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
        for index, row in enumerate(result.get("claim_facts", [])):
            claim_facts.append(
                {
                    "claim_fact_id": stable_id(
                        "claim_fact",
                        row.get("claim_id", ""),
                        row.get("fact_type", ""),
                        row.get("value", ""),
                        index,
                    ),
                    "claim_id": str(row.get("claim_id", "")),
                    "fact_type": str(row.get("fact_type", "")),
                    "value": str(row.get("value", "")),
                    "unit": str(row.get("unit", "")),
                    "qualifier": str(row.get("qualifier", "")),
                    "evidence_text": str(row.get("evidence_text", "")),
                    "confidence": float(row.get("confidence") or 0.0),
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
) -> dict[str, Any]:
    return {
        "matched_product": matched_product,
        "candidate_products": matched_products[:8],
        "selected_documents": [],
        "extraction_status": status,
        "product_facts": [],
        "claim_facts": [],
        "comparison_results": [],
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
        "reason": reason,
    }


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
    root = Path(os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT", str(DEFAULT_DISCLOSURE_ROOT)))
    rel = relative_path.replace("\\", "/")
    for candidate in (rel, unicodedata.normalize("NFD", rel), unicodedata.normalize("NFC", rel)):
        path = root / candidate
        if path.exists():
            return path
    return root / rel


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
        return []
    try:
        import pandas as pd
    except Exception:
        return []
    df = pd.read_csv(path)
    return [{str(key): value for key, value in row.items()} for row in df.fillna("").to_dict(orient="records")]
