"""Expand the PPCBank (KH) product-fact graph with Claude (Opus 4.8).

Four phases (run any subset; ``--all`` runs crawl → extract → ingest → verify):

    python3 build_ppcbank_product_graph.py --crawl     # fetch product pages
    python3 build_ppcbank_product_graph.py --extract   # Opus 4.8 fact extraction
    python3 build_ppcbank_product_graph.py --ingest     # MERGE into KH workspace
    python3 build_ppcbank_product_graph.py --verify     # counts + isolation

Why Claude here (and only here)
-------------------------------
Product-fact extraction is an *offline ingestion* step, not part of the live
review loop. The live pipeline stays OpenAI-only (``llm_gateway.py`` untouched),
so KR review behaviour is unchanged. This script is the sole Anthropic caller
and writes nothing to the team Neo4j (base ``NEO4J_URI`` = my sandbox; team DB is
under separate ``TEAM_NEO4J_*`` keys and is never opened here).

Isolation & routing (must match ``ingest_cambodia_products.py``)
----------------------------------------------------------------
- Everything is workspace-scoped to ``WORKSPACE_ID`` (KH) and MERGEd (idempotent).
- ``Product.source`` and the ``HAS_PRODUCT_DOCUMENT`` edge ``source`` MUST equal
  ``PRODUCT_GRAPH_SOURCE`` — ``jb_data_context.load_product_rows_from_neo4j``
  hard-filters on it (jb_data_context.py:483-484), otherwise ``search_products``
  can never resolve the product from the review form.
- The PoC marker lives in ``ingest_source="ppcbank_poc"``; facts additionally
  carry ``extraction_method="claude:claude-opus-4-8"`` + ``poc/lawyer_verified``.

Grounding
---------
Facts are extracted strictly from the fetched public pages under
``data/cambodia/products/`` (HTML + a whitespace-collapsed .txt). The prompt
forbids invention and requires a verbatim ``evidence_text`` span. It also records
review-critical *absences* (e.g. a deposit page that markets rates but publishes
no early-withdrawal clause) as ``*_disclosure`` facts, grounded in what the page
does show. PoC — not verified by PPCBank or a Cambodian lawyer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from env_loader import load_local_env
from utils import stable_id

WORKSPACE_ID = "graphcompliance_cambodia_ppcbank_20260630"
POC_SOURCE = "ppcbank_poc"
PRODUCT_GRAPH_SOURCE = "graphcompliance_ccg_product_graph_loader"
CLAUDE_MODEL = "claude-opus-4-8"
DOC_LABEL = "상품페이지"  # keep KR label parity with the baseline loader

MODULE_DIR = Path(__file__).resolve().parent
PRODUCTS_DIR = MODULE_DIR / "data" / "cambodia" / "products"
FACTS_JSON = PRODUCTS_DIR / "_claude_facts.json"
MAX_TEXT_CHARS = 24000  # ~6k tokens/page — cost is negligible at this volume
USER_AGENT = "Mozilla/5.0 (compatible; JB-Compliance-KH-PoC/1.0; product-fact crawler)"

# Each product page → a Product node + a ProductDocument. ``text_file`` is the
# preferred clean-text source (existing .md extracts reused where present).
#   (slug, group, product_name, original_name, text_file_override_or_None)
PRODUCTS: list[dict] = [
    # ── deposit ─────────────────────────────────────────────────────────────
    {"slug": "fixed-deposit-account", "group": "deposit", "name": "PPCBank Fixed Deposit",
     "original_name": "Fixed Deposit Account — PPCBank Cambodia", "text_file": "ppcbank_fixed_deposit.md"},
    {"slug": "saving-account", "group": "deposit", "name": "PPCBank Savings Account",
     "original_name": "Savings Account — PPCBank Cambodia"},
    {"slug": "current-account", "group": "deposit", "name": "PPCBank Current Account",
     "original_name": "Current Account — PPCBank Cambodia"},
    {"slug": "installment-deposit-account", "group": "deposit", "name": "PPCBank Installment Deposit",
     "original_name": "Installment Deposit Account — PPCBank Cambodia"},
    {"slug": "junior-savings-account", "group": "deposit", "name": "PPCBank Junior Savings Account",
     "original_name": "Junior Savings Account — PPCBank Cambodia"},
    {"slug": "vip-saving", "group": "deposit", "name": "PPCBank VIP Savings",
     "original_name": "VIP Savings — PPCBank Cambodia"},
    {"slug": "piggy-bank", "group": "deposit", "name": "PPCBank Piggy Bank",
     "original_name": "Piggy Bank — PPCBank Cambodia"},
    {"slug": "buddy-bank", "group": "deposit", "name": "PPCBank Buddy Bank",
     "original_name": "Buddy Bank — PPCBank Cambodia"},
    {"slug": "heng-heng-account", "group": "deposit", "name": "PPCBank Heng Heng Account",
     "original_name": "Heng Heng Account — PPCBank Cambodia"},
    {"slug": "songkhoem-installment", "group": "deposit", "name": "PPCBank Songkhoem Installment Deposit",
     "original_name": "Songkhoem Installment Deposit — PPCBank Cambodia"},
    # ── loan ────────────────────────────────────────────────────────────────
    {"slug": "car-loan", "group": "loan", "name": "PPCBank Car Loan",
     "original_name": "Car Loan — PPCBank Cambodia", "text_file": "ppcbank_car_loan.md"},
    {"slug": "home-loan", "group": "loan", "name": "PPCBank Home Loan",
     "original_name": "Home Loan — PPCBank Cambodia"},
    {"slug": "home-improvement-loan", "group": "loan", "name": "PPCBank Home Improvement Loan",
     "original_name": "Home Improvement Loan — PPCBank Cambodia"},
    {"slug": "car-for-cash", "group": "loan", "name": "PPCBank Car for Cash",
     "original_name": "Car for Cash — PPCBank Cambodia"},
    {"slug": "loan-against-deposit", "group": "loan", "name": "PPCBank Loan Against Deposit",
     "original_name": "Loan Against Deposit — PPCBank Cambodia"},
    {"slug": "songkhoem-loan", "group": "loan", "name": "PPCBank Songkhoem Loan",
     "original_name": "Songkhoem Loan — PPCBank Cambodia"},
    {"slug": "annatean-rohas", "group": "loan", "name": "PPCBank Annatean Rohas Loan",
     "original_name": "Annatean Rohas Loan — PPCBank Cambodia"},
    # ── card ────────────────────────────────────────────────────────────────
    {"slug": "visa-credit-card", "group": "card", "name": "PPCBank Visa Credit Card",
     "original_name": "Visa Credit Card — PPCBank Cambodia", "subpath": "card"},
    {"slug": "visa-debit-card", "group": "card", "name": "PPCBank Visa Debit Card",
     "original_name": "Visa Debit Card — PPCBank Cambodia", "subpath": "card"},
    {"slug": "css-card", "group": "card", "name": "PPCBank CSS Card",
     "original_name": "CSS Card — PPCBank Cambodia", "subpath": "card"},
]

# Extra standalone documents attached to an existing product (not its own page).
EXTRA_DOCS: list[dict] = [
    {"product": "PPCBank Fixed Deposit", "group": "deposit", "text_file": "ppcbank_rate_revision.md",
     "original_name": "Announcement on Revision of Interest Rates (effective 2026-04-01)",
     "source_url": "https://www.ppcbank.com.kh/fixed-installment-deposit-rate-revision/"},
]


def product_url(p: dict) -> str:
    sub = p.get("subpath", p["group"])
    return f"https://www.ppcbank.com.kh/personal-banking/{sub}/{p['slug']}/"


def html_file(p: dict) -> Path:
    return PRODUCTS_DIR / f"ppcbank_{p['slug'].replace('-', '_')}.html"


def text_file(p: dict) -> Path:
    if p.get("text_file"):
        return PRODUCTS_DIR / p["text_file"]
    return PRODUCTS_DIR / f"ppcbank_{p['slug'].replace('-', '_')}.txt"


# ── HTML → readable text (keeps table rows/cells legible for rate tables) ──────
class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form"}
    _NEWLINE = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}
    _CELL = {"td", "th"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._CELL:
            self._parts.append(" | ")
        elif tag in self._NEWLINE:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [re.sub(r"[ \t]+", " ", ln).strip(" |").strip() for ln in raw.split("\n")]
        out: list[str] = []
        for ln in lines:
            if ln and not (out and out[-1] == ln):  # drop blank + consecutive dupes
                out.append(ln)
        return "\n".join(out)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


# ── phase: crawl ──────────────────────────────────────────────────────────────
def crawl(force: bool = False) -> None:
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    for p in PRODUCTS:
        hpath = html_file(p)
        # Reuse the existing curated crawl for FD/car-loan; fetch the rest.
        if p.get("text_file") and (PRODUCTS_DIR / p["text_file"]).exists() and not force:
            print(f"  skip (curated .md present): {p['name']}")
            continue
        if hpath.exists() and not force:
            html = hpath.read_text(encoding="utf-8", errors="ignore")
        else:
            url = product_url(p)
            print(f"  GET {url}")
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    html = resp.read().decode("utf-8", errors="ignore")
            except Exception as exc:  # noqa: BLE001
                print(f"    !! fetch failed: {exc}")
                continue
            hpath.write_text(html, encoding="utf-8")
            time.sleep(1.0)  # be polite to the origin
        tpath = text_file(p)
        tpath.write_text(html_to_text(html), encoding="utf-8")
        print(f"    text -> {tpath.name} ({tpath.stat().st_size} bytes)")


# ── phase: extract (Opus 4.8) ─────────────────────────────────────────────────
FACT_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fact_type": {"type": "string", "description": "snake_case category, reused across products, e.g. interest_rate_by_term, promotional_rate, rate_term_dependency, eligibility_requirements, minimum_amount, loan_amount_limit, loan_interest_rate, loan_to_value, loan_term, fees, early_withdrawal_disclosure, terms_conditions_apply, deposit_protection"},
        "value": {"type": "string", "description": "the concrete fact value, verbatim numbers/ranges where possible"},
        "unit": {"type": "string", "description": "e.g. '% p.a', 'USD', 'KHR', 'months', '%'; empty string if none"},
        "condition": {"type": "string", "description": "the qualifier that makes the fact conditional (term/currency/channel/eligibility/period). Empty string if unconditional."},
        "page_or_chunk": {"type": "string", "description": "where on the page, e.g. 'rate table', 'Requirements section', 'promotion banner', 'web page'"},
        "evidence_text": {"type": "string", "description": "shortest VERBATIM span copied from the page text that supports this fact"},
        "confidence": {"type": "number", "description": "0-1, how directly the page states this fact"},
    },
    "required": ["fact_type", "value", "unit", "condition", "page_or_chunk", "evidence_text", "confidence"],
}

RECORD_TOOL = {
    "name": "record_product_facts",
    "description": "Record the structured, page-grounded facts extracted from one PPCBank product page.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"product_facts": {"type": "array", "items": FACT_ITEM_SCHEMA}},
        "required": ["product_facts"],
    },
}

# The extraction prompt is written in ENGLISH because PPCBank Cambodia's product
# language is English. It is compliance-oriented: it targets the facts a Cambodian
# financial-ad reviewer needs to confirm or challenge an ad claim, demands verbatim
# evidence, forbids invention, and explicitly asks for review-critical absences.
EXTRACTION_SYSTEM = """You are a financial-product fact extractor for advertising compliance pre-review at a Cambodian bank (PPCBank). You read one product web page (plain text, tables flattened with '|' between cells) and return structured, page-grounded facts a reviewer can use to verify or challenge advertising claims.

RULES
1. Ground every fact ONLY in the provided page text. Never infer, complete, or import outside knowledge. If the page does not state it, do not assert it.
2. evidence_text MUST be the shortest verbatim span copied from the page that supports the fact. Do not paraphrase inside evidence_text.
3. Prefer facts that let a reviewer check an ad claim:
   - interest / deposit rates and APRs, broken out by term, currency (USD/KHR), and channel (branch vs app/digital) when the page distinguishes them
   - how the rate depends on conditions (longer term -> higher rate; at-maturity vs monthly payment; standard vs promotional)
   - promotional / special rates AND their exact conditions, channel, and period
   - eligibility and required documents (who can open; ID/passport/employment/business requirements)
   - minimum / maximum amounts, loan amount limits, loan-to-value / financing ratio, tenor / term ranges
   - fees, penalties, prepayment / early-withdrawal terms
   - tax basis, deposit insurance / protection, guarantees, risk statements
   - "terms and conditions apply" style caveats
4. Put the limiting qualifier in `condition` (e.g. "rate varies by term/currency/channel; no single rate for everyone"). This is how a reviewer catches unconditional ad claims ("highest rate for everyone, no conditions").
5. ALSO record review-critical ABSENCES as facts whose fact_type ends in "_disclosure". If the page markets a benefit but does NOT publish a commonly-expected limiting term, say so, grounded in what the page DOES show. Examples: a deposit page that publishes only at-maturity / monthly interest tables and no premature-withdrawal clause; a loan page that states "from X% p.a" but never states a maximum rate or the approval conditions. In evidence_text for an absence fact, quote the closest relevant text or name the tables/sections that ARE present.
6. Use consistent snake_case fact_type names across products so facts are comparable.
7. Do not extract navigation, marketing slogans, or SEO text unless they carry a concrete, checkable fact. Quality over quantity: 5-15 solid facts beat 40 vague ones.
8. Return results ONLY by calling the record_product_facts tool. If the page genuinely contains no checkable facts, return an empty product_facts array."""


def extract() -> None:
    import anthropic

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    results: dict[str, dict] = {}
    if FACTS_JSON.exists():
        results = json.loads(FACTS_JSON.read_text(encoding="utf-8"))

    targets = [(p["slug"], p, text_file(p)) for p in PRODUCTS]
    targets += [(f"extra::{d['text_file']}", d, PRODUCTS_DIR / d["text_file"]) for d in EXTRA_DOCS]

    for key, meta, tpath in targets:
        if not tpath.exists():
            print(f"  !! missing text, skip: {tpath.name}")
            continue
        page_text = tpath.read_text(encoding="utf-8", errors="ignore").strip()[:MAX_TEXT_CHARS]
        if len(page_text) < 40:
            print(f"  !! text too short, skip: {tpath.name}")
            continue
        product_name = meta.get("name") or meta.get("product") or key
        print(f"  extract [{CLAUDE_MODEL}] {product_name} <- {tpath.name} ({len(page_text)} chars)")
        try:
            msg = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=[{"type": "text", "text": EXTRACTION_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                tools=[RECORD_TOOL],
                tool_choice={"type": "tool", "name": "record_product_facts"},
                messages=[{
                    "role": "user",
                    "content": (
                        f"[product]\nname: {product_name}\ngroup: {meta.get('group', '')}\n\n"
                        f"[page text]\n{page_text}"
                    ),
                }],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    !! extraction failed: {exc}")
            continue
        facts = _tool_facts(msg)
        cache = msg.usage.cache_read_input_tokens or 0
        print(f"    -> {len(facts)} facts (in={msg.usage.input_tokens} cache={cache} out={msg.usage.output_tokens})")
        results[key] = {
            "product": product_name,
            "group": meta.get("group", ""),
            "original_name": meta.get("original_name", ""),
            "source_url": meta.get("source_url") or (product_url(meta) if meta.get("slug") else ""),
            "text_file": tpath.name,
            "is_extra_doc": key.startswith("extra::"),
            "attach_product": meta.get("product") or product_name,
            "facts": facts,
        }
        FACTS_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    total = sum(len(v["facts"]) for v in results.values())
    print(f"\n  wrote {FACTS_JSON.name}: {len(results)} documents, {total} facts total")


def _tool_facts(msg) -> list[dict]:
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_product_facts":
            return list(block.input.get("product_facts", []))
    return []


# ── phase: ingest (MERGE into KH Neo4j sandbox) ───────────────────────────────
def clean_doc_text(path: Path) -> str:
    """Return the product page body as clean text for the ProductDocument.full_text
    property, so the graph is self-contained for remote clients / text2cypher
    (no dependency on local files). Strips the markdown title + PoC provenance
    header (.md) and the site nav/footer chrome (.txt), keeping the page body
    verbatim."""
    if not path.exists():
        return ""
    out: list[str] = []
    for ln in path.read_text(encoding="utf-8", errors="ignore").split("\n"):
        s = ln.strip()
        if s == "About PPCBank":  # footer begins — stop
            break
        if s == "Skip to main content" or s.startswith("# ") or s.startswith("> "):
            continue
        out.append(ln.rstrip())
    while out and not out[0].strip():
        out.pop(0)
    return "\n".join(out).strip()


def build_rows(data: dict) -> tuple[list, list, list, list, list]:
    now = datetime.now(timezone.utc).isoformat()
    root = os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT", "")
    groups: dict[str, dict] = {}
    labels: dict[str, dict] = {}
    products: dict[str, dict] = {}
    documents: dict[str, dict] = {}
    facts: list[dict] = []

    label_id = stable_id("document_label", WORKSPACE_ID, DOC_LABEL)
    labels[label_id] = {
        "id": label_id, "name": DOC_LABEL, "workspace_id": WORKSPACE_ID,
        "source": POC_SOURCE, "ingest_source": POC_SOURCE, "created_at": now, "updated_at": now,
    }

    for entry in data.values():
        product = entry["attach_product"]
        group = entry["group"] or "deposit"
        group_id = f"product_group_{group}"
        groups.setdefault(group_id, {
            "id": group_id, "name": group, "workspace_id": WORKSPACE_ID,
            "source": POC_SOURCE, "ingest_source": POC_SOURCE, "created_at": now, "updated_at": now,
        })
        product_id = stable_id("product", WORKSPACE_ID, product)
        products.setdefault(product_id, {
            "id": product_id, "name": product, "product_group": group,
            "major": "PPCBank", "subcategory": group, "category": "personal_banking",
            "workspace_id": WORKSPACE_ID,
            "source": PRODUCT_GRAPH_SOURCE, "ingest_source": POC_SOURCE,  # loader source: routing requirement
            "poc": True, "lawyer_verified": False, "created_at": now, "updated_at": now,
        })
        rel_path = entry["text_file"]
        file_path = os.path.join(root, rel_path) if root else str(PRODUCTS_DIR / rel_path)
        document_id = stable_id("product_document", product, rel_path)
        # Embed the full page text INTO the graph so remote clients / text2cypher
        # can read the source without access to local files.
        full_text = clean_doc_text(PRODUCTS_DIR / rel_path)
        documents.setdefault(document_id, {
            "id": document_id, "product_id": product_id, "product_name": product,
            "product_group": group, "label_id": label_id, "label": DOC_LABEL,
            "major": "PPCBank", "subcategory": group, "category": "personal_banking",
            "extension": os.path.splitext(rel_path)[1] or ".txt",
            "size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            "file_name": rel_path, "relative_path": rel_path,
            "original_name": entry["original_name"], "exists": os.path.exists(file_path),
            "metadata_source": POC_SOURCE, "source_url": entry["source_url"],
            "full_text": full_text, "content_chars": len(full_text),
            "workspace_id": WORKSPACE_ID,
            "source": POC_SOURCE, "ingest_source": POC_SOURCE, "created_at": now, "updated_at": now,
        })
        for index, row in enumerate(entry["facts"]):
            value = str(row.get("value", ""))
            fact_type = str(row.get("fact_type", ""))
            facts.append({
                "id": stable_id("product_fact", product, document_id, fact_type, value, index),
                "fact_type": fact_type, "value": value,
                "unit": str(row.get("unit", "")), "condition": str(row.get("condition", "")),
                "source_document_id": document_id,
                "page_or_chunk": str(row.get("page_or_chunk", "") or "web page"),
                "evidence_text": str(row.get("evidence_text", "")),
                "confidence": float(row.get("confidence") or 0.0),
                "matched_product": product, "workspace_id": WORKSPACE_ID,
                "source": POC_SOURCE, "ingest_source": POC_SOURCE,
                "extraction_method": f"claude:{CLAUDE_MODEL}", "extraction_run": now,
                "poc": True, "lawyer_verified": False,
                "poc_note": "Extracted by Claude Opus 4.8 from public PPCBank pages; not verified by PPCBank or a Cambodian lawyer.",
                "created_at": now, "updated_at": now,
            })
    return list(groups.values()), list(labels.values()), list(products.values()), list(documents.values()), facts


class Ingestor:
    def __init__(self) -> None:
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "")
        user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        password = os.environ.get("NEO4J_PASSWORD", "")
        if not uri or not user or not password:
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, NEO4J_PASSWORD required.")
        self.database = os.environ.get("NEO4J_DATABASE")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self.driver.close()

    def _sk(self) -> dict:
        return {"database": self.database} if self.database else {}

    def replace_poc_facts(self) -> int:
        """Detach-delete prior ppcbank_poc ProductFacts in KH so re-extraction
        yields a clean graph instead of accumulating stale (hand + Claude) facts.
        Scoped to KH workspace + ingest_source=ppcbank_poc; touches nothing else."""
        with self.driver.session(**self._sk()) as s:
            n = s.run(
                "MATCH (f:ProductFact {workspace_id:$ws, ingest_source:$poc}) "
                "WITH count(f) AS n RETURN n", ws=WORKSPACE_ID, poc=POC_SOURCE,
            ).single()[0]
            s.run(
                "MATCH (f:ProductFact {workspace_id:$ws, ingest_source:$poc}) DETACH DELETE f",
                ws=WORKSPACE_ID, poc=POC_SOURCE,
            )
            return n

    def ingest(self, groups, labels, products, documents, facts) -> None:
        with self.driver.session(**self._sk()) as s:
            s.run("UNWIND $rows AS row MERGE (g:ProductGroup {id: row.id, workspace_id: $ws}) SET g += row",
                  rows=groups, ws=WORKSPACE_ID)
            s.run("UNWIND $rows AS row MERGE (l:DocumentLabel {id: row.id, workspace_id: $ws}) SET l += row",
                  rows=labels, ws=WORKSPACE_ID)
            s.run(
                """
                UNWIND $rows AS row
                MERGE (p:Product {id: row.id, workspace_id: $ws}) SET p += row
                WITH p, row
                MATCH (g:ProductGroup {id: 'product_group_' + row.product_group, workspace_id: $ws})
                MERGE (g)-[:HAS_PRODUCT {workspace_id: $ws, source: $poc}]->(p)
                """, rows=products, ws=WORKSPACE_ID, poc=POC_SOURCE)
            s.run(
                """
                UNWIND $rows AS row
                MERGE (d:ProductDocument {id: row.id, workspace_id: $ws}) SET d += row
                WITH d, row
                MATCH (p:Product {id: row.product_id, workspace_id: $ws})
                MERGE (p)-[:HAS_PRODUCT_DOCUMENT {workspace_id: $ws, source: $loader}]->(d)
                WITH d, row
                MATCH (l:DocumentLabel {id: row.label_id, workspace_id: $ws})
                MERGE (d)-[:HAS_DOCUMENT_LABEL {workspace_id: $ws, source: $poc}]->(l)
                """, rows=documents, ws=WORKSPACE_ID, loader=PRODUCT_GRAPH_SOURCE, poc=POC_SOURCE)
            s.run(
                """
                UNWIND $rows AS row
                MERGE (f:ProductFact {id: row.id, workspace_id: $ws}) SET f += row
                WITH f, row
                MATCH (d:ProductDocument {id: row.source_document_id, workspace_id: $ws})
                MERGE (d)-[:CONTAINS_FACT {workspace_id: $ws, source: $poc}]->(f)
                """, rows=facts, ws=WORKSPACE_ID, poc=POC_SOURCE)

    def verify(self) -> None:
        with self.driver.session(**self._sk()) as s:
            print("\n=== KH product graph (workspace-scoped) ===")
            for label in ("ProductGroup", "Product", "DocumentLabel", "ProductDocument", "ProductFact"):
                c = s.run(f"MATCH (n:{label} {{workspace_id:$ws}}) RETURN count(n)", ws=WORKSPACE_ID).single()[0]
                print(f"  {label:16} {c}")
            rows = s.run(
                "MATCH (p:Product {workspace_id:$ws})-[:HAS_PRODUCT_DOCUMENT]->(d) "
                "OPTIONAL MATCH (d)-[:CONTAINS_FACT]->(f) "
                "RETURN p.name AS name, count(DISTINCT d) AS docs, count(DISTINCT f) AS facts "
                "ORDER BY facts DESC", ws=WORKSPACE_ID)
            for r in rows:
                print(f"  {r['name']:42} docs={r['docs']} facts={r['facts']}")
            leak = s.run(
                "MATCH (n {ingest_source:$poc}) WHERE n.workspace_id <> $ws RETURN count(n)",
                poc=POC_SOURCE, ws=WORKSPACE_ID).single()[0]
            print(f"  isolation: ppcbank_poc nodes outside KH ws = {leak} (must be 0)")


def ingest(replace_facts: bool) -> None:
    if not FACTS_JSON.exists():
        sys.exit(f"{FACTS_JSON} not found — run --extract first.")
    data = json.loads(FACTS_JSON.read_text(encoding="utf-8"))
    groups, labels, products, documents, facts = build_rows(data)
    print(f"plan: {len(groups)} ProductGroup, {len(products)} Product, {len(documents)} ProductDocument, {len(facts)} ProductFact")
    ing = Ingestor()
    try:
        if replace_facts:
            removed = ing.replace_poc_facts()
            print(f"  --replace-facts: detached-deleted {removed} prior ppcbank_poc ProductFacts")
        ing.ingest(groups, labels, products, documents, facts)
        print("ingested (MERGE, idempotent).")
        ing.verify()
    finally:
        ing.close()


def verify_only() -> None:
    ing = Ingestor()
    try:
        ing.verify()
    finally:
        ing.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Build/expand the PPCBank (KH) product-fact graph with Claude.")
    ap.add_argument("--crawl", action="store_true")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--all", action="store_true", help="crawl -> extract -> ingest -> verify")
    ap.add_argument("--force-crawl", action="store_true", help="re-fetch even if HTML exists")
    ap.add_argument("--replace-facts", action="store_true", help="delete prior ppcbank_poc facts before MERGE")
    args = ap.parse_args()

    load_local_env(str(MODULE_DIR / ".env"))
    ran = False
    if args.crawl or args.all:
        print("== crawl =="); crawl(force=args.force_crawl); ran = True
    if args.extract or args.all:
        print("== extract =="); extract(); ran = True
    if args.ingest or args.all:
        print("== ingest =="); ingest(replace_facts=args.replace_facts or args.all); ran = True
    if args.verify and not args.all:
        print("== verify =="); verify_only(); ran = True
    if not ran:
        ap.print_help()


if __name__ == "__main__":
    main()
