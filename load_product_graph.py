"""Load JB product metadata into the GraphCompliance CCG Neo4j graph.

This loader builds the product-document grounding layer used by Product Fact
Graph review. It intentionally loads metadata only; PDF-derived ProductFact
nodes remain on-demand review artifacts.
"""

from __future__ import annotations

import argparse
import logging
import os
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from neo4j import GraphDatabase

from env_loader import load_local_env
from jb_data_context import DEFAULT_PRODUCT_META_PATH, DISCLOSURE_REQUIREMENTS, requirements_for_group
from utils import stable_id


LOGGER = logging.getLogger(__name__)
SOURCE = "graphcompliance_ccg_product_graph_loader"
DEFAULT_WORKSPACE_ID = "graphcompliance_mvp_jb_20260530"
DEFAULT_DISCLOSURE_ROOT = Path("/Users/barabonda/Downloads/jbbank_product_disclosures_20260528")


def main() -> None:
    load_local_env(Path.cwd() / ".env")
    parser = argparse.ArgumentParser(description="Load JB product metadata graph into Neo4j.")
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--metadata-path", default=str(DEFAULT_PRODUCT_META_PATH))
    parser.add_argument("--disclosure-root", default=str(DEFAULT_DISCLOSURE_ROOT))
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    graph = build_product_graph_payload(
        metadata_path=Path(args.metadata_path),
        disclosure_root=Path(args.disclosure_root),
        workspace_id=args.workspace_id,
    )
    LOGGER.info(
        "product graph payload: groups=%s products=%s documents=%s labels=%s disclosure_requirements=%s",
        len(graph["groups"]),
        len(graph["products"]),
        len(graph["documents"]),
        len(graph["labels"]),
        len(graph["disclosure_requirements"]),
    )
    LOGGER.info("sample products: %s", graph["products"][:5])
    LOGGER.info("sample documents: %s", graph["documents"][:3])
    if args.dry_run:
        return

    loader = ProductGraphLoader()
    try:
        loader.load(workspace_id=args.workspace_id, graph=graph, batch_size=args.batch_size)
    finally:
        loader.close()
    LOGGER.info("product graph loaded into Neo4j workspace=%s", args.workspace_id)


def build_product_graph_payload(*, metadata_path: Path, disclosure_root: Path, workspace_id: str) -> dict[str, list[dict[str, Any]]]:
    if not metadata_path.exists():
        raise FileNotFoundError(f"Product metadata not found: {metadata_path}")
    df = pd.read_excel(metadata_path, sheet_name="jbbank_product_disclosures_meta").fillna("")
    now = datetime.now(UTC).isoformat()

    groups: dict[str, dict[str, Any]] = {}
    products: dict[str, dict[str, Any]] = {}
    documents: dict[str, dict[str, Any]] = {}
    labels: dict[str, dict[str, Any]] = {}

    for row in df.to_dict(orient="records"):
        product_name = clean(row.get("product"))
        if not product_name:
            continue
        major = clean(row.get("major"))
        subcategory = clean(row.get("subcategory"))
        category = clean(row.get("category"))
        label = clean(row.get("label"))
        product_group = product_group_for(major=major, subcategory=subcategory, category=category)
        group_id = f"product_group_{product_group}"
        product_id = stable_id("product", workspace_id, product_name)
        document_id = clean(row.get("source_id")) or stable_id("product_document", product_name, row.get("relative_path", ""))
        label_id = stable_id("document_label", workspace_id, label or "unknown")
        relative_path = clean(row.get("relative_path"))
        resolved_path = resolve_document_path(disclosure_root=disclosure_root, relative_path=relative_path)

        groups.setdefault(
            product_group,
            {
                "id": group_id,
                "name": product_group,
                "workspace_id": workspace_id,
                "source": SOURCE,
                "created_at": now,
                "updated_at": now,
            },
        )
        labels.setdefault(
            label_id,
            {
                "id": label_id,
                "name": label or "unknown",
                "workspace_id": workspace_id,
                "source": SOURCE,
                "created_at": now,
                "updated_at": now,
            },
        )
        products.setdefault(
            product_id,
            {
                "id": product_id,
                "name": product_name,
                "product_group": product_group,
                "major": major,
                "subcategory": subcategory,
                "category": category,
                "workspace_id": workspace_id,
                "source": SOURCE,
                "created_at": now,
                "updated_at": now,
            },
        )
        documents[document_id] = {
            "id": document_id,
            "product_id": product_id,
            "product_name": product_name,
            "product_group": product_group,
            "label_id": label_id,
            "label": label,
            "major": major,
            "subcategory": subcategory,
            "category": category,
            "extension": clean(row.get("extension")),
            "size_bytes": int(row.get("size_bytes") or 0),
            "file_name": clean(row.get("file_name")),
            "relative_path": relative_path,
            "original_name": clean(row.get("original_name")),
            "exists": safe_exists(resolved_path),
            "workspace_id": workspace_id,
            "source": SOURCE,
            "created_at": now,
            "updated_at": now,
        }

    disclosure_requirements: dict[str, dict[str, Any]] = {}
    for group in sorted(groups):
        if group not in DISCLOSURE_REQUIREMENTS:
            continue
        for requirement in requirements_for_group(group):
            disclosure_requirements[requirement["id"]] = {
                **requirement,
                "workspace_id": workspace_id,
                "source": SOURCE,
                "product_group": group,
                "created_at": now,
                "updated_at": now,
            }

    return {
        "groups": list(groups.values()),
        "products": list(products.values()),
        "documents": list(documents.values()),
        "labels": list(labels.values()),
        "disclosure_requirements": list(disclosure_requirements.values()),
    }


class ProductGraphLoader:
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

    def load(self, *, workspace_id: str, graph: dict[str, list[dict[str, Any]]], batch_size: int) -> None:
        with self.driver.session(**self.session_kwargs()) as session:
            write_batches(session, "groups", graph["groups"], batch_size, write_groups, workspace_id)
            write_batches(session, "labels", graph["labels"], batch_size, write_labels, workspace_id)
            write_batches(session, "products", graph["products"], batch_size, write_products, workspace_id)
            write_batches(session, "documents", graph["documents"], batch_size, write_documents, workspace_id)
            write_batches(
                session,
                "disclosure_requirements",
                graph["disclosure_requirements"],
                batch_size,
                write_disclosure_requirements,
                workspace_id,
            )


def write_batches(session: Any, name: str, rows: list[dict[str, Any]], batch_size: int, writer: Any, workspace_id: str) -> None:
    for index in range(0, len(rows), batch_size):
        batch = rows[index : index + batch_size]
        writer(session, workspace_id, batch)
    LOGGER.info("loaded %s rows=%s", name, len(rows))


def write_groups(session: Any, workspace_id: str, rows: list[dict[str, Any]]) -> None:
    session.run(
        """
        UNWIND $rows AS row
        MERGE (group:ProductGroup {id: row.id, workspace_id: $workspace_id})
        SET group += row
        """,
        workspace_id=workspace_id,
        rows=rows,
    )


def write_labels(session: Any, workspace_id: str, rows: list[dict[str, Any]]) -> None:
    session.run(
        """
        UNWIND $rows AS row
        MERGE (label:DocumentLabel {id: row.id, workspace_id: $workspace_id})
        SET label += row
        """,
        workspace_id=workspace_id,
        rows=rows,
    )


def write_products(session: Any, workspace_id: str, rows: list[dict[str, Any]]) -> None:
    session.run(
        """
        UNWIND $rows AS row
        MERGE (product:Product {id: row.id, workspace_id: $workspace_id})
        SET product += row
        WITH product, row
        MATCH (group:ProductGroup {id: 'product_group_' + row.product_group, workspace_id: $workspace_id})
        MERGE (group)-[:HAS_PRODUCT {workspace_id: $workspace_id, source: row.source}]->(product)
        """,
        workspace_id=workspace_id,
        rows=rows,
    )


def write_documents(session: Any, workspace_id: str, rows: list[dict[str, Any]]) -> None:
    session.run(
        """
        UNWIND $rows AS row
        MERGE (doc:ProductDocument {id: row.id, workspace_id: $workspace_id})
        SET doc += row
        WITH doc, row
        MATCH (product:Product {id: row.product_id, workspace_id: $workspace_id})
        MERGE (product)-[:HAS_PRODUCT_DOCUMENT {workspace_id: $workspace_id, source: row.source}]->(doc)
        WITH doc, row
        MATCH (label:DocumentLabel {id: row.label_id, workspace_id: $workspace_id})
        MERGE (doc)-[:HAS_DOCUMENT_LABEL {workspace_id: $workspace_id, source: row.source}]->(label)
        """,
        workspace_id=workspace_id,
        rows=rows,
    )


def write_disclosure_requirements(session: Any, workspace_id: str, rows: list[dict[str, Any]]) -> None:
    session.run(
        """
        UNWIND $rows AS row
        MERGE (req:DisclosureRequirement {id: row.id, workspace_id: $workspace_id})
        SET req += row
        WITH req, row
        MATCH (group:ProductGroup {id: 'product_group_' + row.product_group, workspace_id: $workspace_id})
        MERGE (group)-[:REQUIRES_DISCLOSURE {workspace_id: $workspace_id, source: row.source}]->(req)
        """,
        workspace_id=workspace_id,
        rows=rows,
    )


def product_group_for(*, major: str, subcategory: str, category: str) -> str:
    joined = " ".join([major, subcategory, category])
    if "예금" in joined or "적금" in joined or "입출금" in joined:
        return "deposit"
    if "대출" in joined:
        return "loan"
    if "카드" in joined:
        return "card"
    if "펀드" in joined or "투자" in joined or "복합금융" in joined:
        return "investment"
    return "auto"


def resolve_document_path(*, disclosure_root: Path, relative_path: str) -> Path:
    rel = relative_path.replace("\\", "/")
    for candidate in (rel, unicodedata.normalize("NFD", rel), unicodedata.normalize("NFC", rel)):
        path = disclosure_root / candidate
        if safe_exists(path):
            return path
    return disclosure_root / rel


def safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def clean(value: object) -> str:
    return " ".join(str(value or "").split())


if __name__ == "__main__":
    main()
