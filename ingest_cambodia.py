"""KH (Cambodia) compliance ingestion — CC-2.

Purpose
-------
Load a *Cambodia* proof-of-concept compliance corpus into Neo4j as
``LegalClause`` / ``LegalChunk`` / ``ComplianceUnit`` nodes plus the grounding
edges the policy compiler expects (``GROUNDS_CU`` / ``EVIDENCES_CU``), so that
``policy_compiler.py`` can build the alignment layer (Premise / PolicyHypernym /
CUEmbeddingProfile / CULegalElementProfile) on top of them.

This is a *new, standalone* ingester. It does NOT modify the existing KR
loaders (``load_product_graph.py`` etc.). The upstream repo only MATCHes
ComplianceUnit/LegalClause/LegalChunk (they are created by an external pipeline),
so KH nodes are created directly here.

Isolation guarantee (KR data is never touched)
----------------------------------------------
Every node and relationship written here carries::

    workspace_id = "graphcompliance_cambodia_ppcbank_20260630"
    source       = "cambodia_poc"

``workspace_id`` is the sole partition key across the whole system
(docs/CODE_ANALYSIS.md §8.2), so a distinct KH workspace is fully isolated from
and unconnected to the KR workspace (``graphcompliance_mvp_jb_20260530``). All
MERGE keys include ``workspace_id``; no query here reads or writes any other
workspace. The same KH ``workspace_id`` is reused by every later KH step
(CC-3..CC-6) and by ``policy_compiler.py --workspace-id ...``.

Grounding & provenance
----------------------
LegalClause text is extracted from the *real* downloaded primary source
(Law on Consumer Protection 2019, English PDF) via
``data/cambodia/consumer_protection_law_2019_articles.json``. LegalChunk text is
quoted from the DFDL English *summary* of Sub-Decree 232 / Prakas 249 (a
secondary source, clearly flagged). No legal text is invented. Where a primary
source could not be retrieved (NBC interest-rate ceiling regulation — the NBC
index returned HTTP 403), the clause is created as a citation-only placeholder
with ``primary_source_retrieved = false`` and no fabricated text.

PoC caveat
----------
These ComplianceUnits are a demo encoding and have NOT been reviewed by a
Cambodian lawyer. Every CU node carries ``poc = true`` and
``lawyer_verified = false``.

Date / version tracking (foundation for future regulation-change tracking)
--------------------------------------------------------------------------
Every LegalClause / LegalChunk / ComplianceUnit carries ``effective_date``
(ISO-8601), ``version`` and ``source_date``. Only values confirmed from the
source are filled; unknown values are stored as ``null`` but the fields always
exist, so later revisions can be diffed / audited against this baseline.

Usage
-----
    python ingest_cambodia.py            # MERGE into Neo4j (idempotent)
    python ingest_cambodia.py --dry-run  # print plan, write nothing
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from env_loader import load_local_env

WORKSPACE_ID = "graphcompliance_cambodia_ppcbank_20260630"
SOURCE = "cambodia_poc"

REPO = Path(__file__).resolve().parent
DATA = REPO / "data" / "cambodia"
LAW_JSON = DATA / "consumer_protection_law_2019_articles.json"

# Document-level date/version metadata (only source-confirmed values).
LAW_TITLE = "Law on Consumer Protection (2019)"
LAW_DATES = {
    "effective_date": "2019-11-02",  # Royal Kram NS/RKM/1119/016 (Nov 2019)
    "source_date": "2019-10-08",  # adopted by National Assembly (in the PDF preamble)
    "version": "v1 (NS/RKM/1119/016)",
}
SUBDECREE_TITLE = "Sub-Decree 232 (2022) / Prakas 249 (2022) — DFDL English summary"
SUBDECREE_DATES = {
    "effective_date": "2022-11-04",  # Sub-Decree 232 enacted 4 Nov 2022 (confirmed in summary)
    "source_date": "2022-11-04",
    "version": "v1 (Sub-Decree 232 / Prakas 249)",
}
PRAKAS_DATE = "2022-11-16"  # Prakas 249 issued 16 Nov 2022 (confirmed in summary)
NBC_TITLE = "NBC interest rate ceiling regulation (2017)"


# --------------------------------------------------------------------------- #
# 1. LegalClause / LegalChunk source records
# --------------------------------------------------------------------------- #
def build_legal_nodes() -> tuple[list[dict], list[dict]]:
    """Return (clauses, chunks). Clause text comes from the real law PDF JSON."""
    law = json.loads(LAW_JSON.read_text(encoding="utf-8"))
    articles: dict[str, str] = law["articles"]

    clauses: list[dict] = []
    for art_no, text in articles.items():
        clauses.append(
            {
                "id": f"kh_clause_cpl2019_art{art_no}",
                "text": text,
                "article_no": f"Article {art_no}",
                "document_title": LAW_TITLE,
                "primary_source_retrieved": True,
                **LAW_DATES,
            }
        )

    # NBC interest-rate ceiling: primary source NOT retrieved (index -> HTTP 403).
    # Citation-only placeholder; no fabricated legal text.
    clauses.append(
        {
            "id": "kh_clause_nbc2017_rate_ceiling",
            "text": (
                "[Primary source not retrieved] NBC interest rate ceiling regulation (2017). "
                "The NBC legislation index returned HTTP 403 during ingestion; the primary text "
                "was not downloaded. Scope (believed to be lending/credit only) must be verified "
                "against the official NBC Prakas before any production use."
            ),
            "article_no": "(NBC 2017, unverified)",
            "document_title": NBC_TITLE,
            "primary_source_retrieved": False,
            "effective_date": None,
            "source_date": None,
            "version": "v1 (unverified)",
        }
    )

    # LegalChunk: faithful excerpts from the DFDL *summary* (secondary source).
    chunk_specs = {
        "subdecree232_scope": (
            "Sub-Decree 232 provides the legal framework for the management of commercial "
            "advertising of goods and services for all types, forms and means in Cambodia, "
            "including digital advertising."
        ),
        "subdecree232_license": (
            "Under Sub-Decree 232, before advertising any commercial goods and/or services in "
            "Cambodia, an applicant must apply for an applicable advertising license/permit "
            "issued by the competent authority."
        ),
        "subdecree232_khmer": (
            "Commercial advertising text must be depicted in the Khmer language; if a foreign "
            "language also appears, the Khmer font must be placed above and double the size of "
            "the foreign language font."
        ),
        "subdecree232_prohibited": (
            "Prohibited advertising content includes: content that is misleading, deceptive, "
            "fraudulent or likely to create confusion about the quality and safety of goods and "
            "services; use of 'best', 'only one', 'superior', 'unmatched' or similar words "
            "without prior written confirmation from competent authorities; and content that "
            "violates applicable law."
        ),
        "subdecree232_prizes": (
            "Advertising with prizes must fulfil obligations set out in Sub-Decree 232, such as "
            "confirming the total number of products with the prize, specifying the type and "
            "number of prizes, the period during which the prize will be offered, the locations "
            "at which the prize may be collected, and disclosing the identity of the winner on a "
            "monthly and annual basis."
        ),
        "prakas249_certificate": (
            "A person advertising in Cambodia may apply for a compliance certificate from the "
            "Ministry of Commerce (MOC) certifying that advertising text/content complies with "
            "the Law on Consumer Protection or other applicable regulations (Prakas 249). The "
            "certificate is valid for at most one year, and a new certificate must be applied "
            "for if the advertising text or content changes."
        ),
        "subdecree232_penalties": (
            "Violating Sub-Decree 232 may give rise to a written warning; suspension, revocation "
            "or cancellation of an advertising license and/or compliance certificate; and "
            "suspension, revocation or cancellation of a certificate of incorporation, license "
            "or permit to undertake business activities."
        ),
    }
    chunks: list[dict] = []
    for key, text in chunk_specs.items():
        dates = dict(SUBDECREE_DATES)
        if key.startswith("prakas249"):
            dates = {**SUBDECREE_DATES, "effective_date": PRAKAS_DATE, "source_date": PRAKAS_DATE}
        chunks.append(
            {
                "id": f"kh_chunk_{key}",
                "text": text,
                "article_no": "Sub-Decree 232 / Prakas 249",
                "document_title": SUBDECREE_TITLE,
                "primary_source_retrieved": False,  # secondary (English summary)
                **dates,
            }
        )
    return clauses, chunks


# --------------------------------------------------------------------------- #
# 2. ComplianceUnit records (seed KH-CU-01..05 + expansion, 16 total)
#    principle uses KR vocabulary ("설명의무" / "광고규제") on purpose — retriever
#    hardcodes principle=='제재' filtering (retriever.py:202,416) and gating is
#    tuned to this vocabulary; body text stays English (Cambodia law).
# --------------------------------------------------------------------------- #
def build_compliance_units() -> list[dict]:
    def cu(cid, principle, subject, condition, constraint, context, cu_type, severity,
           source_article, grounds, evidences, dates):
        return {
            "id": cid,
            "principle": principle,
            "subject": subject,
            "condition": condition,
            "constraint": constraint,
            "context": context,
            "cu_type": cu_type,
            "severity": severity,
            "source_article": source_article,
            "source_evidence": f"{source_article} — {constraint}",
            "grounds": grounds,      # -> LegalClause GROUNDS_CU
            "evidences": evidences,  # -> LegalChunk  EVIDENCES_CU
            **dates,
        }

    L = LAW_DATES
    SD = SUBDECREE_DATES
    NBC = {"effective_date": None, "source_date": None, "version": "v1 (unverified)"}

    def c(*ns):
        return [f"kh_clause_cpl2019_art{n}" for n in ns]

    def ch(*keys):
        return [f"kh_chunk_{k}" for k in keys]

    units = [
        cu("KH-CU-01", "설명의무",
           "financial product ad mandatory information",
           "advertising or supplying goods or services to consumers",
           "must disclose the minimum information required by the consumer information standard",
           "Cambodia consumer information standard applies to anyone advertising/supplying goods or services.",
           "disclosure_obligation", "HIGH",
           "Law on Consumer Protection (2019) Art. 23-25",
           c(23, 24, 25), ch("prakas249_certificate"), L),

        cu("KH-CU-02", "광고규제",
           "commercial advertisement content (including digital)",
           "any commercial advertisement of goods or services",
           "must be truthful and not misleading, and must meet MOC advertising compliance-certificate requirements",
           "Sub-Decree 232 covers all forms incl. digital; Prakas 249 sets the MOC compliance-certificate procedure.",
           "advertising_restriction", "HIGH",
           "Sub-Decree 232 (2022) + Prakas 249 (2022)",
           c(12), ch("subdecree232_scope", "subdecree232_prohibited", "prakas249_certificate"), SD),

        cu("KH-CU-03", "광고규제",
           "interest rate / benefit representation",
           "advertising deposit or loan rates or other benefits",
           "conditional or preferential rates must be clearly disclosed as conditional and must not read as unconditional or guaranteed",
           "Combines the consumer information standard with the Sub-Decree 232 ban on misleading representations.",
           "advertising_restriction", "HIGH",
           "Consumer Protection Law (2019) Art. 24-25 + Sub-Decree 232 (2022)",
           c(12, 24), ch("subdecree232_prohibited"), L),

        cu("KH-CU-04", "설명의무",
           "fee / term / eligibility limitations",
           "products with fees, eligibility conditions or term limits",
           "must not omit material information (fees, eligibility, term limits) affecting consumer decisions",
           "Information standard requires disclosure of the minimum consumer-relevant information.",
           "disclosure_obligation", "HIGH",
           "Consumer Protection Law (2019) Art. 23-27",
           c(23, 27), ch(), L),

        cu("KH-CU-05", "광고규제",
           "lending rate advertisement",
           "advertising credit or loan product rates",
           "must respect NBC interest-rate-ceiling limits (scope: lending only — VERIFY)",
           "PoC placeholder: NBC 2017 primary source was not retrieved (HTTP 403); scope must be verified.",
           "interest_rate_restriction", "MEDIUM",
           "NBC interest rate ceiling regulation (2017) — verify scope (lending only)",
           ["kh_clause_nbc2017_rate_ceiling"], ch(), NBC),

        cu("KH-CU-06", "광고규제",
           "misleading representation about goods or services",
           "supplying or promoting goods or services",
           "must not make misleading representations about price, quality, standard, guarantee or benefit",
           "Art. 12 prohibits misleading representations, including false guarantees.",
           "advertising_restriction", "HIGH",
           "Law on Consumer Protection (2019) Art. 12",
           c(12), ch("subdecree232_prohibited"), L),

        cu("KH-CU-07", "광고규제",
           "false or misleading representation about business activities",
           "representations about profitability or characteristics of a business activity",
           "must not make false or misleading representations about the nature or benefits of the activity/product",
           "Art. 18 prohibits false/misleading representations about certain business activities.",
           "advertising_restriction", "MEDIUM",
           "Law on Consumer Protection (2019) Art. 18",
           c(18), ch(), L),

        cu("KH-CU-08", "광고규제",
           "bait advertising",
           "advertising goods or services at a particular price",
           "must not advertise at a price the advertiser does not intend to (or cannot) actually supply",
           "Art. 15 prohibits bait advertising.",
           "advertising_restriction", "MEDIUM",
           "Law on Consumer Protection (2019) Art. 15",
           c(15), ch(), L),

        cu("KH-CU-09", "광고규제",
           "dishonest act misleading the public about goods",
           "promoting the supply or use of goods",
           "must not engage in any dishonest act that misleads or deceives the public about goods",
           "Art. 10 prohibits dishonest acts misleading the public about goods.",
           "advertising_restriction", "MEDIUM",
           "Law on Consumer Protection (2019) Art. 9-10",
           c(9, 10), ch(), L),

        cu("KH-CU-10", "광고규제",
           "dishonest act misleading the public about services",
           "promoting the supply or use of services",
           "must not engage in any dishonest act that misleads or deceives the public about services",
           "Art. 11 prohibits dishonest acts misleading the public about services.",
           "advertising_restriction", "MEDIUM",
           "Law on Consumer Protection (2019) Art. 9, 11",
           c(9, 11), ch(), L),

        cu("KH-CU-11", "광고규제",
           "dishonest sales that mislead consumers",
           "any sale of goods or services",
           "must not conduct sales that mislead consumers when buying the goods or services",
           "Art. 13 prohibits dishonest sales that mislead consumers.",
           "advertising_restriction", "MEDIUM",
           "Law on Consumer Protection (2019) Art. 13",
           c(13), ch(), L),

        cu("KH-CU-12", "광고규제",
           "false trade description",
           "selling goods with an attached trade description",
           "must not sell goods attached with a false trade description",
           "Art. 21 prohibits false trade descriptions.",
           "advertising_restriction", "MEDIUM",
           "Law on Consumer Protection (2019) Art. 21",
           c(21), ch(), L),

        cu("KH-CU-13", "광고규제",
           "advertising license / permit",
           "before advertising any commercial goods or services",
           "must obtain the applicable advertising license/permit from the competent authority before advertising",
           "Sub-Decree 232 requires a permit before advertising.",
           "advertising_restriction", "MEDIUM",
           "Sub-Decree 232 (2022)",
           [], ch("subdecree232_license"), SD),

        cu("KH-CU-14", "광고규제",
           "advertising language requirement",
           "commercial advertising text shown to consumers",
           "advertising text must be in Khmer; a foreign-language font must sit below and be at most half the size of the Khmer font",
           "Sub-Decree 232 sets the Khmer-language and font-size requirement.",
           "advertising_restriction", "LOW",
           "Sub-Decree 232 (2022)",
           [], ch("subdecree232_khmer"), SD),

        cu("KH-CU-15", "광고규제",
           "prize / promotional advertising disclosures",
           "advertising accompanied by prizes, lucky draws or rewards",
           "must disclose prize terms (product/prize count, prize type, offer period, collection locations, and winner identity)",
           "Sub-Decree 232 sets additional obligations for advertising with prizes.",
           "advertising_restriction", "MEDIUM",
           "Sub-Decree 232 (2022)",
           [], ch("subdecree232_prizes"), SD),

        cu("KH-CU-16", "광고규제",
           "absolute / superlative claims",
           "using superlative or absolute claims in advertising",
           "must not use 'best', 'only one', 'superior', 'unmatched' or similar terms without prior written confirmation from the competent authority",
           "Sub-Decree 232 prohibited-content rule on superlatives.",
           "advertising_restriction", "MEDIUM",
           "Sub-Decree 232 (2022) prohibited content",
           c(12), ch("subdecree232_prohibited"), SD),
    ]
    return units


# --------------------------------------------------------------------------- #
# 3. Neo4j writer
# --------------------------------------------------------------------------- #
class CambodiaIngestor:
    def __init__(self) -> None:
        from neo4j import GraphDatabase

        load_local_env(str(REPO / ".env"))
        self.uri = os.environ.get("NEO4J_URI", "")
        self.user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        self.password = os.environ.get("NEO4J_PASSWORD", "")
        if not self.uri or not self.user or not self.password:
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, and NEO4J_PASSWORD are required.")
        self.database = os.environ.get("NEO4J_DATABASE")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))

    def close(self) -> None:
        self.driver.close()

    def _sk(self) -> dict:
        return {"database": self.database} if self.database else {}

    def ingest(self, clauses, chunks, units) -> dict[str, int]:
        grounds_edges = []   # (LegalClause)-[:GROUNDS_CU]->(ComplianceUnit)
        evidence_edges = []  # (LegalChunk)-[:EVIDENCES_CU]->(ComplianceUnit)
        for u in units:
            for gid in u.pop("grounds"):
                grounds_edges.append({"src": gid, "cu": u["id"]})
            for eid in u.pop("evidences"):
                evidence_edges.append({"src": eid, "cu": u["id"]})

        with self.driver.session(**self._sk()) as s:
            # LegalClause
            s.run(
                """
                UNWIND $rows AS row
                MERGE (n:LegalClause {id: row.id, workspace_id: $ws})
                SET n += row, n.workspace_id = $ws, n.source = $source
                """,
                rows=clauses, ws=WORKSPACE_ID, source=SOURCE,
            )
            # LegalChunk
            s.run(
                """
                UNWIND $rows AS row
                MERGE (n:LegalChunk {id: row.id, workspace_id: $ws})
                SET n += row, n.workspace_id = $ws, n.source = $source
                """,
                rows=chunks, ws=WORKSPACE_ID, source=SOURCE,
            )
            # ComplianceUnit (active_for_gate=true so policy_compiler picks it up)
            s.run(
                """
                UNWIND $rows AS row
                MERGE (n:ComplianceUnit {id: row.id, workspace_id: $ws})
                SET n += row,
                    n.workspace_id = $ws,
                    n.source = $source,
                    n.active_for_gate = true,
                    n.poc = true,
                    n.lawyer_verified = false,
                    n.poc_note = 'Cambodia PoC encoding; not reviewed by a Cambodian lawyer.'
                """,
                rows=units, ws=WORKSPACE_ID, source=SOURCE,
            )
            # (LegalClause)-[:GROUNDS_CU]->(ComplianceUnit)  — both endpoints in KH ws
            s.run(
                """
                UNWIND $edges AS e
                MATCH (src:LegalClause {id: e.src, workspace_id: $ws})
                MATCH (cu:ComplianceUnit {id: e.cu, workspace_id: $ws})
                MERGE (src)-[r:GROUNDS_CU {workspace_id: $ws, source: $source}]->(cu)
                """,
                edges=grounds_edges, ws=WORKSPACE_ID, source=SOURCE,
            )
            # (LegalChunk)-[:EVIDENCES_CU]->(ComplianceUnit)
            s.run(
                """
                UNWIND $edges AS e
                MATCH (src:LegalChunk {id: e.src, workspace_id: $ws})
                MATCH (cu:ComplianceUnit {id: e.cu, workspace_id: $ws})
                MERGE (src)-[r:EVIDENCES_CU {workspace_id: $ws, source: $source}]->(cu)
                """,
                edges=evidence_edges, ws=WORKSPACE_ID, source=SOURCE,
            )
        return {
            "LegalClause": len(clauses),
            "LegalChunk": len(chunks),
            "ComplianceUnit": len(units),
            "GROUNDS_CU": len(grounds_edges),
            "EVIDENCES_CU": len(evidence_edges),
        }

    def verify(self) -> None:
        with self.driver.session(**self._sk()) as s:
            print("\n=== KH workspace node counts ===")
            for label in ("ComplianceUnit", "LegalClause", "LegalChunk"):
                c = s.run(
                    f"MATCH (n:{label} {{workspace_id:$ws}}) RETURN count(n) AS c", ws=WORKSPACE_ID
                ).single()["c"]
                print(f"  {label:16} {c}")
            for rel in ("GROUNDS_CU", "EVIDENCES_CU"):
                c = s.run(
                    f"MATCH ()-[r:{rel} {{workspace_id:$ws}}]->() RETURN count(r) AS c", ws=WORKSPACE_ID
                ).single()["c"]
                print(f"  [:{rel}]{'':7} {c}")
            active = s.run(
                "MATCH (cu:ComplianceUnit {workspace_id:$ws}) WHERE coalesce(cu.active_for_gate,false)=true "
                "RETURN count(cu) AS c", ws=WORKSPACE_ID
            ).single()["c"]
            grounded = s.run(
                "MATCH (cu:ComplianceUnit {workspace_id:$ws}) "
                "WHERE (:LegalClause)-[:GROUNDS_CU]->(cu) OR (:LegalChunk)-[:EVIDENCES_CU]->(cu) "
                "RETURN count(DISTINCT cu) AS c", ws=WORKSPACE_ID
            ).single()["c"]
            print(f"  active_for_gate=true CUs: {active}   grounded CUs: {grounded}")

            # Isolation check: nothing tagged cambodia_poc may live outside the KH workspace
            leak = s.run(
                "MATCH (n {source:$source}) WHERE n.workspace_id <> $ws RETURN count(n) AS c",
                source=SOURCE, ws=WORKSPACE_ID,
            ).single()["c"]
            print(f"\n=== isolation: cambodia_poc nodes outside KH workspace = {leak} (must be 0) ===")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest Cambodia (KH) compliance corpus into Neo4j.")
    ap.add_argument("--dry-run", action="store_true", help="print plan, write nothing")
    args = ap.parse_args()

    clauses, chunks = build_legal_nodes()
    units = build_compliance_units()

    print(f"workspace_id = {WORKSPACE_ID}")
    print(f"plan: {len(clauses)} LegalClause, {len(chunks)} LegalChunk, {len(units)} ComplianceUnit")
    n_edges = sum(len(u["grounds"]) + len(u["evidences"]) for u in units)
    print(f"      {n_edges} grounding edges (GROUNDS_CU / EVIDENCES_CU)")
    principles = {}
    for u in units:
        principles[u["principle"]] = principles.get(u["principle"], 0) + 1
    print(f"      principle mix: {principles}")

    if args.dry_run:
        print("\n[dry-run] no writes performed.")
        return

    ing = CambodiaIngestor()
    try:
        counts = ing.ingest(clauses, chunks, units)
        print(f"\ningested (MERGE, idempotent): {counts}")
        ing.verify()
    finally:
        ing.close()
    print("\nDONE. Next: python policy_compiler.py --workspace-id", WORKSPACE_ID, "--batch-size 16")


if __name__ == "__main__":
    main()
