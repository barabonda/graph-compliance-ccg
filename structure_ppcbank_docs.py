"""Decompose PPCBank product documents into a structured graph (hybrid GraphRAG).

Not a `full_text` blob — the document is loaded AS a graph: ordered typed
sections, structured table rows (rates / loan conditions / eligibility / fees)
as first-class queryable nodes, and prose as chained chunks. So a remote client
can traverse the document AND run precise queries (e.g. "12-month USD digital
fixed-deposit rate?") without any local file.

    python3 structure_ppcbank_docs.py --structure   # Claude Opus 4.8 -> _doc_structure.json
    python3 structure_ppcbank_docs.py --ingest       # MERGE the doc graph into KH ws
    python3 structure_ppcbank_docs.py --verify
    python3 structure_ppcbank_docs.py --all

Schema (workspace-scoped, MERGE idempotent, source=ppcbank_poc):
    (:ProductDocument)-[:HAS_SECTION]->(:DocSection {type,title,order})
    (:DocSection)-[:HAS_CHUNK]->(:DocChunk {index,text})-[:NEXT]->(:DocChunk)
    (:DocSection)-[:HAS_RATE]->(:RateEntry {term_months,currency,channel,payment,rate_pa})
    (:DocSection)-[:HAS_ELIGIBILITY]->(:EligibilityItem {applicant,document})
    (:DocSection)-[:HAS_CONDITION]->(:LoanCondition {category,field,value})
    (:DocSection)-[:HAS_FEE]->(:FeeItem {name,value,condition})

Complements (does not replace) the existing Product/ProductDocument/ProductFact
graph. Live review pipeline untouched (OpenAI); Claude used only here (offline).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from env_loader import load_local_env
from utils import stable_id
from build_ppcbank_product_graph import (
    CLAUDE_MODEL, POC_SOURCE, PRODUCTS_DIR, WORKSPACE_ID, FACTS_JSON,
    MAX_TEXT_CHARS, clean_doc_text,
)

STRUCT_JSON = PRODUCTS_DIR / "_doc_structure.json"

SECTION_TYPES = ["overview", "promotion", "rate_table", "conditions",
                 "requirements", "fees", "benefits", "apply", "contact", "other"]

_S = lambda: {"type": "string"}
STRUCT_TOOL = {
    "name": "record_document_structure",
    "description": "Record the PPCBank product page decomposed into an ordered graph of sections and structured rows.",
    "input_schema": {
        "type": "object", "additionalProperties": False,
        "properties": {"sections": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {
                "type": {"type": "string", "enum": SECTION_TYPES},
                "title": {"type": "string"},
                "order": {"type": "integer"},
                "chunks": {"type": "array", "items": {"type": "string"},
                           "description": "prose paragraphs of this section, verbatim; [] for pure tables"},
                "rates": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "term_months": {"type": "integer", "description": "term in months; 0 if the rate depends on balance amount, not term"},
                        "currency": {"type": "string", "description": "USD or KHR"},
                        "channel": {"type": "string", "description": "standard | digital | '' if page does not split"},
                        "payment": {"type": "string", "description": "at_maturity | monthly | '' "},
                        "rate_kind": {"type": "string", "description": "standard | pre_maturity (early-withdrawal) | '' "},
                        "holding_period": {"type": "string", "description": "for pre_maturity cells, the holding-period range e.g. '6-11 months'; '' otherwise"},
                        "amount_tier": {"type": "string", "description": "for balance/amount-tier tables, the balance range verbatim e.g. '10,000-30,000 USD'; '' if term-based"},
                        "rate_pa": {"type": "number", "description": "annual % rate; skip cells shown as '-'"},
                    }, "required": ["term_months", "currency", "channel", "payment", "rate_kind", "holding_period", "amount_tier", "rate_pa"]}},
                "conditions": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"category": _S(), "field": _S(), "value": _S()},
                    "required": ["category", "field", "value"]},
                    "description": "loan condition table: category e.g. 'New Cars', field e.g. 'loan_amount', value verbatim"},
                "eligibility": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"applicant": _S(), "document": _S()},
                    "required": ["applicant", "document"]},
                    "description": "requirements: applicant type (Cambodian/Foreigner/Business Entity/NGO) + one required document"},
                "fees": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"name": _S(), "value": _S(), "condition": _S()},
                    "required": ["name", "value", "condition"]}},
            },
            "required": ["type", "title", "order", "chunks", "rates", "conditions", "eligibility", "fees"],
        }}},
        "required": ["sections"],
    },
}

STRUCT_SYSTEM = """You convert a single PPCBank product web page (plain text, table cells flattened with '|') into a STRUCTURED graph decomposition for a knowledge graph. You do NOT summarize — you segment and structure the page faithfully.

Return, via the record_document_structure tool, an ordered list of sections. For each section choose a `type`, a short `title`, and an `order` (0-based, in page order). Fill ONLY the arrays that apply; leave the others as [].

- chunks: the section's prose paragraphs, copied verbatim (one paragraph per string). Use for overview/promotion/benefits/apply/contact narrative. Pure table sections have chunks: [].
- rates (for `rate_table` sections): emit ONE row per rate cell — EVERY populated cell, never drop a column. rate_pa is the number only (e.g. 4.40); skip cells shown as "–"/"-"/empty.
  * Term-based tables: PAYMENT from the section header ("...At Maturity" => "at_maturity"; "...Monthly Interest Payment" => "monthly"); channel from columns ("Standard Rate" => "standard", "Digital Channel" => "digital"); currency from "Interest USD"/"Interest KHR". Set term_months, rate_kind="standard", holding_period="", amount_tier="".
  * PRE-MATURITY / early-withdrawal columns: some deposit tables add columns of pre-maturity (early-withdrawal) rates keyed by a holding-period range (e.g. "6-11", "12-17", "18-23" months) NEXT TO the Standard rate. Emit a RateEntry for EACH such cell with rate_kind="pre_maturity" and holding_period = that column's range; the standard column is rate_kind="standard", holding_period="". NEVER drop these columns.
  * BALANCE/AMOUNT-tier tables: when the rate depends on the deposit BALANCE ("10,000 – 30,000" => 1.50%, "More than 30,000" => 1.00%), set term_months=0, amount_tier = the balance range verbatim, currency from the column, rate_kind="standard". Store these as RATES, not conditions.
- conditions (for loan `conditions` sections): the conditions/comparison table. category = the column header (e.g. "New Cars", "Used Cars"); field = the row label normalized snake_case (loan_amount, interest_rate, loan_ratio, loan_term); value = the cell verbatim.
- eligibility (for `requirements` sections): one {applicant, document} per required document. applicant = the group heading (Cambodian, Foreigner, Business Entity, NGOs/NPOs); document = one required document line verbatim.
- fees (for card/account `fees` sections): {name, value, condition} per fee line.

Rules: ground everything in the page; copy numbers/text verbatim; never invent. Cover the whole page (nav/footer already stripped). Prefer several precise sections over one big blob."""


def _doc_list(data: dict):
    for entry in data.values():
        product = entry["attach_product"]
        rel = entry["text_file"]
        yield {
            "key": product + "::" + rel,
            "product": product,
            "group": entry.get("group", ""),
            "text_file": rel,
            "document_id": stable_id("product_document", product, rel),
        }


# ── phase: structure (Claude Opus 4.8) ────────────────────────────────────────
def structure() -> None:
    import anthropic

    client = anthropic.Anthropic()
    data = json.loads(FACTS_JSON.read_text(encoding="utf-8"))
    results: dict[str, dict] = {}
    if STRUCT_JSON.exists():
        results = json.loads(STRUCT_JSON.read_text(encoding="utf-8"))

    for doc in _doc_list(data):
        text = clean_doc_text(PRODUCTS_DIR / doc["text_file"])[:MAX_TEXT_CHARS]
        if len(text) < 40:
            print(f"  !! text too short, skip: {doc['text_file']}")
            continue
        print(f"  structure [{CLAUDE_MODEL}] {doc['product']} <- {doc['text_file']} ({len(text)} chars)")
        try:
            msg = client.messages.create(
                model=CLAUDE_MODEL, max_tokens=8192,
                system=[{"type": "text", "text": STRUCT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                tools=[STRUCT_TOOL], tool_choice={"type": "tool", "name": "record_document_structure"},
                messages=[{"role": "user", "content": f"[product] {doc['product']} ({doc['group']})\n[file] {doc['text_file']}\n\n[page text]\n{text}"}],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"    !! failed: {exc}")
            continue
        sections = []
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_document_structure":
                sections = list(block.input.get("sections", []))
        n_rates = sum(len(s.get("rates", [])) for s in sections)
        n_chunks = sum(len(s.get("chunks", [])) for s in sections)
        cache = msg.usage.cache_read_input_tokens or 0
        print(f"    -> {len(sections)} sections, {n_rates} rates, {n_chunks} chunks (cache={cache} out={msg.usage.output_tokens})")
        results[doc["key"]] = {"product": doc["product"], "text_file": doc["text_file"],
                               "document_id": doc["document_id"], "sections": sections}
        STRUCT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    tot_s = sum(len(v["sections"]) for v in results.values())
    print(f"\n  wrote {STRUCT_JSON.name}: {len(results)} docs, {tot_s} sections")


# ── phase: ingest ─────────────────────────────────────────────────────────────
def build_structure_rows(data: dict):
    now = datetime.now(timezone.utc).isoformat()
    base = {"workspace_id": WORKSPACE_ID, "source": POC_SOURCE, "ingest_source": POC_SOURCE,
            "created_at": now, "updated_at": now}
    sections, chunks, chunk_links, rates, eligibility, conditions, fees = [], [], [], [], [], [], []

    for entry in data.values():
        doc_id = entry["document_id"]
        product = entry["product"]
        for sec in entry["sections"]:
            order = int(sec.get("order") or 0)
            stype = str(sec.get("type") or "other")
            section_id = stable_id("doc_section", doc_id, str(order), stype)
            sections.append({"doc_id": doc_id, "props": {
                "id": section_id, "type": stype, "title": str(sec.get("title") or ""),
                "order": order, "product": product, **base}})
            prev = None
            for i, ch in enumerate(sec.get("chunks") or []):
                ch = str(ch).strip()
                if not ch:
                    continue
                cid = stable_id("doc_chunk", section_id, str(i))
                chunks.append({"section_id": section_id, "props": {
                    "id": cid, "index": i, "text": ch, "product": product, **base}})
                if prev:
                    chunk_links.append({"a": prev, "b": cid})
                prev = cid
            for i, r in enumerate(sec.get("rates") or []):
                rid = stable_id("rate_entry", section_id, str(r.get("term_months")),
                                str(r.get("currency")), str(r.get("channel")), str(r.get("payment")),
                                str(r.get("rate_kind")), str(r.get("holding_period")), str(r.get("amount_tier")))
                rates.append({"section_id": section_id, "props": {
                    "id": rid, "term_months": int(r.get("term_months") or 0),
                    "currency": str(r.get("currency") or ""), "channel": str(r.get("channel") or ""),
                    "payment": str(r.get("payment") or ""),
                    "rate_kind": str(r.get("rate_kind") or ""), "holding_period": str(r.get("holding_period") or ""),
                    "amount_tier": str(r.get("amount_tier") or ""),
                    "rate_pa": float(r.get("rate_pa") or 0.0),
                    "product": product, **base}})
            for i, e in enumerate(sec.get("eligibility") or []):
                eid = stable_id("eligibility_item", section_id, str(e.get("applicant")), str(e.get("document")), str(i))
                eligibility.append({"section_id": section_id, "props": {
                    "id": eid, "applicant": str(e.get("applicant") or ""),
                    "document": str(e.get("document") or ""), "product": product, **base}})
            for i, c in enumerate(sec.get("conditions") or []):
                cid = stable_id("loan_condition", section_id, str(c.get("category")), str(c.get("field")), str(i))
                conditions.append({"section_id": section_id, "props": {
                    "id": cid, "category": str(c.get("category") or ""), "field": str(c.get("field") or ""),
                    "value": str(c.get("value") or ""), "product": product, **base}})
            for i, f in enumerate(sec.get("fees") or []):
                fid = stable_id("fee_item", section_id, str(f.get("name")), str(i))
                fees.append({"section_id": section_id, "props": {
                    "id": fid, "name": str(f.get("name") or ""), "value": str(f.get("value") or ""),
                    "condition": str(f.get("condition") or ""), "product": product, **base}})
    return sections, chunks, chunk_links, rates, eligibility, conditions, fees


class StructIngestor:
    def __init__(self) -> None:
        from neo4j import GraphDatabase
        uri = os.environ.get("NEO4J_URI", "")
        user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        pw = os.environ.get("NEO4J_PASSWORD", "")
        if not (uri and user and pw):
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, NEO4J_PASSWORD required.")
        self.database = os.environ.get("NEO4J_DATABASE")
        self.driver = GraphDatabase.driver(uri, auth=(user, pw))

    def close(self): self.driver.close()
    def _sk(self): return {"database": self.database} if self.database else {}

    def ingest(self, sections, chunks, chunk_links, rates, eligibility, conditions, fees, replace: bool):
        ws, poc = WORKSPACE_ID, POC_SOURCE
        with self.driver.session(**self._sk()) as s:
            if replace:
                for lbl in ("DocSection", "DocChunk", "RateEntry", "EligibilityItem", "LoanCondition", "FeeItem"):
                    s.run(f"MATCH (n:{lbl} {{workspace_id:$ws, ingest_source:$poc}}) DETACH DELETE n", ws=ws, poc=poc)
            s.run("""UNWIND $rows AS row
                MATCH (d:ProductDocument {id: row.doc_id, workspace_id: $ws})
                MERGE (x:DocSection {id: row.props.id, workspace_id: $ws}) SET x += row.props
                MERGE (d)-[:HAS_SECTION {workspace_id: $ws, source: $poc}]->(x)""", rows=sections, ws=ws, poc=poc)
            for rows, child, rel in [
                (chunks, "DocChunk", "HAS_CHUNK"), (rates, "RateEntry", "HAS_RATE"),
                (eligibility, "EligibilityItem", "HAS_ELIGIBILITY"),
                (conditions, "LoanCondition", "HAS_CONDITION"), (fees, "FeeItem", "HAS_FEE")]:
                s.run(f"""UNWIND $rows AS row
                    MATCH (sec:DocSection {{id: row.section_id, workspace_id: $ws}})
                    MERGE (x:{child} {{id: row.props.id, workspace_id: $ws}}) SET x += row.props
                    MERGE (sec)-[:{rel} {{workspace_id: $ws, source: $poc}}]->(x)""", rows=rows, ws=ws, poc=poc)
            s.run("""UNWIND $rows AS row
                MATCH (a:DocChunk {id: row.a, workspace_id: $ws}), (b:DocChunk {id: row.b, workspace_id: $ws})
                MERGE (a)-[:NEXT {workspace_id: $ws}]->(b)""", rows=chunk_links, ws=ws)

    def verify(self):
        ws = WORKSPACE_ID
        with self.driver.session(**self._sk()) as s:
            print("\n=== document graph (KH workspace) ===")
            for lbl in ("DocSection", "DocChunk", "RateEntry", "EligibilityItem", "LoanCondition", "FeeItem"):
                c = s.run(f"MATCH (n:{lbl} {{workspace_id:$ws}}) RETURN count(n)", ws=ws).single()[0]
                print(f"  {lbl:16} {c}")
            for rel in ("HAS_SECTION", "HAS_CHUNK", "NEXT", "HAS_RATE", "HAS_ELIGIBILITY", "HAS_CONDITION", "HAS_FEE"):
                c = s.run(f"MATCH ()-[r:{rel} {{workspace_id:$ws}}]->() RETURN count(r)", ws=ws).single()[0]
                print(f"  [:{rel}] {c}")
            print("\n  spot-check — 12mo USD digital at-maturity fixed-deposit rate:")
            rec = s.run("""MATCH (:Product {workspace_id:$ws, name:'PPCBank Fixed Deposit'})
                -[:HAS_PRODUCT_DOCUMENT]->(:ProductDocument)-[:HAS_SECTION]->(:DocSection {type:'rate_table'})
                -[:HAS_RATE]->(r:RateEntry {term_months:12, currency:'USD', channel:'digital', payment:'at_maturity'})
                RETURN r.rate_pa AS rate LIMIT 1""", ws=ws).single()
            print(f"    RateEntry.rate_pa = {rec['rate'] if rec else '(none)'}  (expected 4.40)")
            leak = s.run("MATCH (n:DocSection {ingest_source:$poc}) WHERE n.workspace_id<>$ws RETURN count(n)",
                         poc=POC_SOURCE, ws=ws).single()[0]
            print(f"  isolation: DocSection ppcbank_poc outside KH = {leak} (must be 0)")


def ingest(replace: bool) -> None:
    if not STRUCT_JSON.exists():
        sys.exit(f"{STRUCT_JSON} not found — run --structure first.")
    data = json.loads(STRUCT_JSON.read_text(encoding="utf-8"))
    rows = build_structure_rows(data)
    labels = ["DocSection", "DocChunk", "chunk_links", "RateEntry", "EligibilityItem", "LoanCondition", "FeeItem"]
    print("plan: " + ", ".join(f"{len(r)} {l}" for r, l in zip(rows, labels)))
    ing = StructIngestor()
    try:
        ing.ingest(*rows, replace=replace)
        print("ingested (MERGE, idempotent).")
        ing.verify()
    finally:
        ing.close()


def verify_only() -> None:
    ing = StructIngestor()
    try:
        ing.verify()
    finally:
        ing.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Structure PPCBank product docs into a graph.")
    ap.add_argument("--structure", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--replace", action="store_true", help="delete prior doc-graph nodes before MERGE")
    args = ap.parse_args()
    load_local_env(str(REPO / ".env"))
    ran = False
    if args.structure or args.all:
        print("== structure =="); structure(); ran = True
    if args.ingest or args.all:
        print("== ingest =="); ingest(replace=args.replace or args.all); ran = True
    if args.verify and not args.all:
        print("== verify =="); verify_only(); ran = True
    if not ran:
        ap.print_help()


if __name__ == "__main__":
    main()
