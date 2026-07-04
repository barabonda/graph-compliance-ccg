"""PPCBank (KH) product graph + preloaded ProductFacts — CC-6.

Loads Product / ProductDocument / ProductFact nodes for PPCBank products into
the isolated KH workspace so reviews compare ad claims against *preloaded,
page-verified* facts instead of re-extracting from PDFs on every run.

Standalone by design — the KR loader (``load_product_graph.py``) is not touched.
Everything is MERGEd (idempotent) and carries::

    workspace_id = "graphcompliance_cambodia_ppcbank_20260630"

Source markers
--------------
All nodes/edges carry the PoC marker ``ingest_source="ppcbank_poc"`` and, where
no runtime query depends on it, ``source="ppcbank_poc"``. Deviation (required):
``Product.source`` and the ``HAS_PRODUCT_DOCUMENT`` edge ``source`` must equal
``"graphcompliance_ccg_product_graph_loader"`` because
``jb_data_context.load_product_rows_from_neo4j`` hard-filters on it
(jb_data_context.py:483-484) — otherwise ``search_products``/
``selected_product_match`` can never resolve the product from the review form.

Fact provenance (page-verified only — nothing invented)
--------------------------------------------------------
Facts are hand-encoded strictly from the downloaded public pages under
``data/cambodia/products/`` (HTML preserved next to the .md extracts):
- fixed-deposit page: rate tables by term/currency/channel, at-maturity vs
  monthly payment, promotion (5.14% p.a, app-only, May 1-15 2026), eligibility
  document requirements.
- rate-revision announcement (effective 2026-04-01): same tables + "*Terms and
  conditions apply".
NOT found on any fetched page (and therefore NOT preloaded): a fixed-deposit
minimum opening amount ("USD 500" on the site belongs to the *Premier
Installment Deposit*, a different product) and any premature-withdrawal rate
(site search for "premature" returns nothing). PoC — not verified by PPCBank
or a Cambodian lawyer (`poc=true`, `lawyer_verified=false`).
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime

from env_loader import load_local_env
from utils import stable_id

WORKSPACE_ID = "graphcompliance_cambodia_ppcbank_20260630"
POC_SOURCE = "ppcbank_poc"
# jb_data_context.load_product_rows_from_neo4j filters Product.source and the
# HAS_PRODUCT_DOCUMENT edge source on this loader constant (jb_data_context.py:17,483-484).
PRODUCT_GRAPH_SOURCE = "graphcompliance_ccg_product_graph_loader"

FIXED_DEPOSIT = "PPCBank Fixed Deposit"
CAR_LOAN = "PPCBank Car Loan"

DOCS = [
    {
        "key": "fd_page",
        "product": FIXED_DEPOSIT,
        "product_group": "deposit",
        "label": "상품페이지",
        "file_name": "ppcbank_fixed_deposit.md",
        "original_name": "Fixed Deposit Account - PPCBank Cambodia (web page)",
        "source_url": "https://www.ppcbank.com.kh/personal-banking/deposit/fixed-deposit-account/",
    },
    {
        "key": "fd_rates",
        "product": FIXED_DEPOSIT,
        "product_group": "deposit",
        "label": "상품페이지",
        "file_name": "ppcbank_rate_revision.md",
        "original_name": "Announcement on Revision of Interest Rates (effective 2026-04-01)",
        "source_url": "https://www.ppcbank.com.kh/fixed-installment-deposit-rate-revision/",
    },
    {
        "key": "car_page",
        "product": CAR_LOAN,
        "product_group": "loan",
        "label": "상품페이지",
        "file_name": "ppcbank_car_loan.md",
        "original_name": "Car Loan - PPCBank Cambodia (web page)",
        "source_url": "https://www.ppcbank.com.kh/personal-banking/loan/car-loan/",
    },
]

# (doc_key, fact_type, value, unit, condition, evidence_text, confidence)
# evidence_text is quoted from the saved page text — grounding, not invention.
FIXED_DEPOSIT_FACTS = [
    (
        "fd_page",
        "interest_rate_by_term",
        "2.50–4.70 (USD, at maturity); 3.00–4.90 (KHR, up to 24 months)",
        "% p.a",
        "rate varies by term (3–60 months), currency (USD/KHR) and channel (standard vs digital); no single 'highest rate for everyone'",
        "3 months 2.50% p.a … 60 months 4.70% p.a (Fixed Deposit With Interest Payment At Maturity Rate; Standard/Digital, USD/KHR tables)",
        0.95,
    ),
    (
        "fd_page",
        "rate_term_dependency",
        "longer term earns higher rate",
        "",
        "rate is not unconditional — it depends on the committed term",
        "The longer you commit your money to being in the account, the higher the interest rate will be.",
        0.95,
    ),
    (
        "fd_page",
        "interest_payment",
        "at maturity (monthly option pays lower rates)",
        "",
        "monthly-payment option pays lower rates than at-maturity (e.g. 12mo USD 4.00% vs 4.20%)",
        "Fixed Deposit With Interest Payment At Maturity Rate / Fixed Deposit With Monthly Interest Payment (separate, lower table)",
        0.95,
    ),
    (
        "fd_page",
        "promotional_rate",
        "up to 5.14",
        "% p.a",
        "USD Fixed Deposit opened via PPCBank Mobile App or smartBiz only; promotion period May 1–15, 2026",
        "Customers can enjoy a special interest rate of up to 5.14% p.a. when opening a USD Fixed Deposit account via PPCBank Mobile App or smartBiz.",
        0.95,
    ),
    (
        "fd_page",
        "eligibility_requirements",
        "identity/eligibility documents required (not open to 'everyone' unconditionally)",
        "",
        "Cambodian: National ID or valid passport; Foreigner: valid passport (validity ≥ 90 days) plus employment certificate/contract or business certificate",
        "Requirements — Cambodian: National ID Card or Valid Passport / Foreigner: Valid passport (Validity ≥ 90 days), Employment certificate, contract or business certificate(s)",
        0.95,
    ),
    (
        "fd_rates",
        "terms_conditions_apply",
        "terms and conditions apply",
        "",
        "published rates are subject to terms and conditions",
        "*Terms and conditions apply",
        0.9,
    ),
    (
        "fd_page",
        "early_withdrawal_disclosure",
        "premature/early-withdrawal terms are not published on the product page",
        "",
        "no early-withdrawal or premature-termination rate is stated on the public page; 'withdraw anytime with full interest' has no support in the published tables (interest is paid at maturity)",
        "Page publishes only 'Interest Payment At Maturity' and 'Monthly Interest Payment' rate tables; no premature-withdrawal clause appears on the page.",
        0.9,
    ),
]


def build_rows() -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    now = datetime.now(UTC).isoformat()
    root = os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT", "")

    groups: dict[str, dict] = {}
    labels: dict[str, dict] = {}
    products: dict[str, dict] = {}
    documents: list[dict] = []
    doc_id_by_key: dict[str, str] = {}

    for doc in DOCS:
        group = doc["product_group"]
        group_id = f"product_group_{group}"
        groups.setdefault(group_id, {
            "id": group_id, "name": group, "workspace_id": WORKSPACE_ID,
            "source": POC_SOURCE, "ingest_source": POC_SOURCE,
            "created_at": now, "updated_at": now,
        })
        label_id = stable_id("document_label", WORKSPACE_ID, doc["label"])
        labels.setdefault(label_id, {
            "id": label_id, "name": doc["label"], "workspace_id": WORKSPACE_ID,
            "source": POC_SOURCE, "ingest_source": POC_SOURCE,
            "created_at": now, "updated_at": now,
        })
        product_id = stable_id("product", WORKSPACE_ID, doc["product"])
        products.setdefault(product_id, {
            "id": product_id, "name": doc["product"], "product_group": group,
            "major": "PPCBank", "subcategory": group, "category": "personal_banking",
            "workspace_id": WORKSPACE_ID,
            # search_products hard-requires the loader source (see module docstring).
            "source": PRODUCT_GRAPH_SOURCE, "ingest_source": POC_SOURCE,
            "poc": True, "lawyer_verified": False,
            "created_at": now, "updated_at": now,
        })
        rel_path = doc["file_name"]
        file_path = os.path.join(root, rel_path) if root else rel_path
        document_id = stable_id("product_document", doc["product"], rel_path)
        doc_id_by_key[doc["key"]] = document_id
        documents.append({
            "id": document_id, "product_id": product_id, "product_name": doc["product"],
            "product_group": group, "label_id": label_id, "label": doc["label"],
            "major": "PPCBank", "subcategory": group, "category": "personal_banking",
            "extension": ".md",
            "size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            "file_name": doc["file_name"], "relative_path": rel_path,
            "original_name": doc["original_name"],
            "exists": os.path.exists(file_path),
            "metadata_source": POC_SOURCE, "source_url": doc["source_url"],
            "workspace_id": WORKSPACE_ID,
            "source": POC_SOURCE, "ingest_source": POC_SOURCE,
            "created_at": now, "updated_at": now,
        })

    facts: list[dict] = []
    for doc_key, fact_type, value, unit, condition, evidence, confidence in FIXED_DEPOSIT_FACTS:
        source_document_id = doc_id_by_key[doc_key]
        facts.append({
            "id": stable_id("product_fact", FIXED_DEPOSIT, source_document_id, fact_type, value, 0),
            "fact_type": fact_type, "value": value, "unit": unit, "condition": condition,
            "source_document_id": source_document_id,
            "page_or_chunk": "web page (single page)",
            "evidence_text": evidence, "confidence": confidence,
            "matched_product": FIXED_DEPOSIT,
            "workspace_id": WORKSPACE_ID,
            "source": POC_SOURCE, "ingest_source": POC_SOURCE,
            "poc": True, "lawyer_verified": False,
            "poc_note": "Preloaded from public PPCBank pages; not verified by PPCBank or a Cambodian lawyer.",
            "created_at": now, "updated_at": now,
        })
    return list(groups.values()), list(labels.values()), list(products.values()), documents, facts


class ProductIngestor:
    def __init__(self) -> None:
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "")
        user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        password = os.environ.get("NEO4J_PASSWORD", "")
        if not uri or not user or not password:
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, and NEO4J_PASSWORD are required.")
        self.database = os.environ.get("NEO4J_DATABASE")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def _sk(self) -> dict:
        return {"database": self.database} if self.database else {}

    def ingest(self, groups, labels, products, documents, facts) -> None:
        with self.driver.session(**self._sk()) as s:
            s.run(
                "UNWIND $rows AS row MERGE (g:ProductGroup {id: row.id, workspace_id: $ws}) SET g += row",
                rows=groups, ws=WORKSPACE_ID,
            )
            s.run(
                "UNWIND $rows AS row MERGE (l:DocumentLabel {id: row.id, workspace_id: $ws}) SET l += row",
                rows=labels, ws=WORKSPACE_ID,
            )
            s.run(
                """
                UNWIND $rows AS row
                MERGE (p:Product {id: row.id, workspace_id: $ws})
                SET p += row
                WITH p, row
                MATCH (g:ProductGroup {id: 'product_group_' + row.product_group, workspace_id: $ws})
                MERGE (g)-[:HAS_PRODUCT {workspace_id: $ws, source: $poc}]->(p)
                """,
                rows=products, ws=WORKSPACE_ID, poc=POC_SOURCE,
            )
            s.run(
                """
                UNWIND $rows AS row
                MERGE (d:ProductDocument {id: row.id, workspace_id: $ws})
                SET d += row
                WITH d, row
                MATCH (p:Product {id: row.product_id, workspace_id: $ws})
                MERGE (p)-[:HAS_PRODUCT_DOCUMENT {workspace_id: $ws, source: $loader}]->(d)
                WITH d, row
                MATCH (l:DocumentLabel {id: row.label_id, workspace_id: $ws})
                MERGE (d)-[:HAS_DOCUMENT_LABEL {workspace_id: $ws, source: $poc}]->(l)
                """,
                rows=documents, ws=WORKSPACE_ID, loader=PRODUCT_GRAPH_SOURCE, poc=POC_SOURCE,
            )
            s.run(
                """
                UNWIND $rows AS row
                MERGE (f:ProductFact {id: row.id, workspace_id: $ws})
                SET f += row
                WITH f, row
                MATCH (d:ProductDocument {id: row.source_document_id, workspace_id: $ws})
                MERGE (d)-[:CONTAINS_FACT {workspace_id: $ws, source: $poc}]->(f)
                """,
                rows=facts, ws=WORKSPACE_ID, poc=POC_SOURCE,
            )

    def verify(self) -> None:
        with self.driver.session(**self._sk()) as s:
            print("\n=== KH product graph (workspace-scoped) ===")
            for label in ("ProductGroup", "Product", "DocumentLabel", "ProductDocument", "ProductFact"):
                c = s.run(f"MATCH (n:{label} {{workspace_id:$ws}}) RETURN count(n)", ws=WORKSPACE_ID).single()[0]
                print(f"  {label:16} {c}")
            for rel in ("HAS_PRODUCT", "HAS_PRODUCT_DOCUMENT", "HAS_DOCUMENT_LABEL", "CONTAINS_FACT"):
                c = s.run(f"MATCH ()-[r:{rel} {{workspace_id:$ws}}]->() RETURN count(r)", ws=WORKSPACE_ID).single()[0]
                print(f"  [:{rel}] {c}")
            rows = s.run(
                "MATCH (p:Product {workspace_id:$ws})-[:HAS_PRODUCT_DOCUMENT]->(d)"
                " OPTIONAL MATCH (d)-[:CONTAINS_FACT]->(f)"
                " RETURN p.name AS name, count(DISTINCT d) AS docs, count(DISTINCT f) AS facts",
                ws=WORKSPACE_ID,
            )
            for r in rows:
                print(f"  {r['name']}: documents={r['docs']} facts={r['facts']}")
            leak = s.run(
                "MATCH (n {ingest_source:$poc}) WHERE n.workspace_id <> $ws RETURN count(n)",
                poc=POC_SOURCE, ws=WORKSPACE_ID,
            ).single()[0]
            print(f"  isolation: ppcbank_poc nodes outside KH ws = {leak} (must be 0)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest PPCBank (KH) products + preloaded ProductFacts.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_local_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    groups, labels, products, documents, facts = build_rows()
    print(f"workspace_id = {WORKSPACE_ID}")
    print(f"plan: {len(groups)} ProductGroup, {len(products)} Product, {len(labels)} DocumentLabel, "
          f"{len(documents)} ProductDocument, {len(facts)} ProductFact")
    for d in documents:
        print(f"  doc {d['file_name']}: exists={d['exists']} size={d['size_bytes']}")
    if args.dry_run:
        print("[dry-run] no writes.")
        return
    ing = ProductIngestor()
    try:
        ing.ingest(groups, labels, products, documents, facts)
        print("ingested (MERGE, idempotent).")
        ing.verify()
    finally:
        ing.close()


if __name__ == "__main__":
    main()
