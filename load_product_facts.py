"""Extract and load product-document facts for one JB product into Neo4j.

This is a product-level loader, separate from review-run persistence. It builds
the stable grounding layer used by Product Fact Graph demos:

    Product -> ProductDocument -> ProductFact

Review-specific ClaimFact/ComparisonResult nodes are still produced at review
time because they depend on the submitted ad copy.
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from env_loader import load_local_env
from jb_data_context import search_products
from llm_gateway import LLMGateway
from product_facts import ProductFactAnalyzer, extract_document_snippet, select_product_documents
from schemas import ReviewInput
from utils import stable_id


LOGGER = logging.getLogger(__name__)
SOURCE = "graphcompliance_ccg_product_fact_loader"
DEFAULT_WORKSPACE_ID = "graphcompliance_mvp_jb_20260530"


def main() -> None:
    module_dir = Path(__file__).resolve().parent
    load_local_env(module_dir / ".env")
    load_local_env(Path.cwd() / ".env")

    parser = argparse.ArgumentParser(description="Load ProductFact nodes for one product into Neo4j.")
    parser.add_argument("--product-name", required=True)
    parser.add_argument("--product-group", default="deposit")
    parser.add_argument("--workspace-id", default=os.environ.get("WORKSPACE_ID", DEFAULT_WORKSPACE_ID))
    parser.add_argument("--limit-documents", type=int, default=3)
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    bundle = build_product_fact_bundle(
        product_name=args.product_name,
        product_group=args.product_group,
        workspace_id=args.workspace_id,
        limit_documents=args.limit_documents,
        model=args.model or None,
    )
    LOGGER.info(
        "product fact bundle product=%s documents=%s facts=%s",
        bundle["product"]["name"],
        len(bundle["documents"]),
        len(bundle["product_facts"]),
    )
    for fact in bundle["product_facts"][:8]:
        LOGGER.info(
            "sample fact type=%s value=%s condition=%s source=%s",
            fact.get("fact_type"),
            fact.get("value"),
            fact.get("condition"),
            fact.get("source_document_id"),
        )
    if args.dry_run:
        return

    loader = ProductFactGraphLoader()
    try:
        loader.load(bundle=bundle, workspace_id=args.workspace_id)
        counts = loader.product_fact_counts(product_id=bundle["product"]["id"], workspace_id=args.workspace_id)
    finally:
        loader.close()
    LOGGER.info("loaded ProductFacts into Neo4j counts=%s", counts)


def build_product_fact_bundle(
    *,
    product_name: str,
    product_group: str,
    workspace_id: str,
    limit_documents: int,
    model: str | None = None,
) -> dict[str, Any]:
    product = resolve_product(product_name=product_name, product_group=product_group)
    documents = select_product_documents(product["product"])[: max(1, limit_documents)]
    if not documents:
        raise RuntimeError(f"No PDF product documents found for product: {product['product']}")
    missing = [document for document in documents if not document.get("exists")]
    if missing:
        missing_paths = ", ".join(str(document.get("file_path") or document.get("relative_path") or "") for document in missing)
        raise RuntimeError(f"Product document file not found: {missing_paths}")

    snippets = [extract_document_snippet(document) for document in documents]
    review_input = ReviewInput(
        workspace_id=workspace_id,
        product_group=product_group,
        selected_product_name=product["product"],
        title=product["product"],
        content_text=f"{product['product']} 상품문서 ProductFact 선제 적재",
    )
    analyzer = ProductFactAnalyzer(LLMGateway(model=model))
    facts = analyzer.extract_product_facts(
        review_input=review_input,
        product=product["product"],
        document_snippets=snippets,
    )
    now = datetime.now(UTC).isoformat()
    product_id = stable_id("product", workspace_id, product["product"])
    return {
        "workspace_id": workspace_id,
        "source": SOURCE,
        "created_at": now,
        "product": {
            "id": product_id,
            "name": product["product"],
            "product_group": product.get("product_group") or product_group,
            "major": product.get("major") or "",
            "subcategory": product.get("subcategory") or "",
            "category": product.get("category") or "",
            "workspace_id": workspace_id,
            "source": SOURCE,
            "updated_at": now,
        },
        "documents": [
            {
                "id": str(document.get("document_id") or ""),
                "product_id": product_id,
                "product_name": product["product"],
                "product_group": product.get("product_group") or product_group,
                "label": str(document.get("label") or ""),
                "file_name": str(document.get("file_name") or ""),
                "relative_path": str(document.get("relative_path") or ""),
                "original_name": str(document.get("original_name") or ""),
                "exists": bool(document.get("exists")),
                "workspace_id": workspace_id,
                "source": SOURCE,
                "updated_at": now,
            }
            for document in documents
        ],
        "product_facts": [
            {
                **fact,
                "product_id": product_id,
                "product_name": product["product"],
                "workspace_id": workspace_id,
                "source": SOURCE,
                "updated_at": now,
            }
            for fact in facts
        ],
    }


def resolve_product(*, product_name: str, product_group: str) -> dict[str, Any]:
    matches = search_products(product_name, product_group, limit=10)
    exact = [
        match
        for match in matches
        if str(match.get("product") or "") == product_name
    ]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    candidates = ", ".join(str(match.get("product") or "") for match in matches[:8])
    raise RuntimeError(
        f"Product name is ambiguous or not found: {product_name}. "
        f"Use an exact product name. Candidates: {candidates}"
    )


class ProductFactGraphLoader:
    def __init__(self) -> None:
        uri = os.environ.get("NEO4J_URI", "")
        user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        password = os.environ.get("NEO4J_PASSWORD", "")
        if not uri or not user or not password:
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, and NEO4J_PASSWORD are required.")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = os.environ.get("NEO4J_DATABASE")

    def close(self) -> None:
        self.driver.close()

    def session_kwargs(self) -> dict[str, str]:
        return {"database": self.database} if self.database else {}

    def load(self, *, bundle: dict[str, Any], workspace_id: str) -> None:
        with self.driver.session(**self.session_kwargs()) as session:
            session.execute_write(write_product_fact_bundle, workspace_id, bundle)

    def product_fact_counts(self, *, product_id: str, workspace_id: str) -> dict[str, Any]:
        with self.driver.session(**self.session_kwargs()) as session:
            record = session.run(
                """
                MATCH (product:Product {id: $product_id, workspace_id: $workspace_id})
                OPTIONAL MATCH (product)-[:HAS_PRODUCT_DOCUMENT]->(doc:ProductDocument {workspace_id: $workspace_id})
                OPTIONAL MATCH (product)-[:HAS_PRODUCT_FACT]->(fact:ProductFact {workspace_id: $workspace_id})
                RETURN
                    product.name AS product,
                    count(DISTINCT doc) AS documents,
                    count(DISTINCT fact) AS facts,
                    collect(DISTINCT fact.fact_type)[0..12] AS fact_types
                """,
                product_id=product_id,
                workspace_id=workspace_id,
            ).single()
        return dict(record) if record else {}


def write_product_fact_bundle(tx: Any, workspace_id: str, bundle: dict[str, Any]) -> None:
    product = bundle["product"]
    documents = bundle["documents"]
    facts = bundle["product_facts"]
    tx.run(
        """
        MERGE (product:Product {id: $product.id, workspace_id: $workspace_id})
        SET product += $product
        WITH product
        MERGE (group:ProductGroup {id: 'product_group_' + $product.product_group, workspace_id: $workspace_id})
        SET group.name = $product.product_group,
            group.product_group = $product.product_group,
            group.workspace_id = $workspace_id,
            group.source = coalesce(group.source, $product.source)
        MERGE (group)-[:HAS_PRODUCT {workspace_id: $workspace_id, source: $product.source}]->(product)
        """,
        workspace_id=workspace_id,
        product=product,
    )
    tx.run(
        """
        UNWIND $documents AS row
        MATCH (product:Product {id: row.product_id, workspace_id: $workspace_id})
        MERGE (doc:ProductDocument {id: row.id, workspace_id: $workspace_id})
        SET doc += row
        MERGE (product)-[:HAS_PRODUCT_DOCUMENT {workspace_id: $workspace_id, source: row.source}]->(doc)
        """,
        workspace_id=workspace_id,
        documents=documents,
    )
    tx.run(
        """
        UNWIND $facts AS row
        MATCH (product:Product {id: row.product_id, workspace_id: $workspace_id})
        MERGE (fact:ProductFact {id: row.fact_id, workspace_id: $workspace_id})
        SET fact += row,
            fact.product_level = true
        MERGE (product)-[:HAS_PRODUCT_FACT {workspace_id: $workspace_id, source: row.source}]->(fact)
        WITH row, fact
        OPTIONAL MATCH (doc:ProductDocument {id: row.source_document_id, workspace_id: $workspace_id})
        FOREACH (_ IN CASE WHEN doc IS NULL THEN [] ELSE [1] END |
            MERGE (doc)-[:CONTAINS_FACT {workspace_id: $workspace_id, source: row.source}]->(fact)
        )
        """,
        workspace_id=workspace_id,
        facts=facts,
    )


if __name__ == "__main__":
    main()
