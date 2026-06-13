"""Bridge curated ExceptionRule nodes to runtime-eligible ComplianceUnits.

Diagnosis (see chat): the workspace has a well-curated exception chain
(`acu_* -[:HAS_EXCEPTION]-> ExceptionRule -[:REQUIRES_EVIDENCE]-> EvidenceRequirement`,
`ExceptionRule -[:OVERRIDES]-> acu_*`), but the runtime retrieval path uses the
compiled `cu_legal_*` ComplianceUnits, and NONE of the 110 `exception_eligible`
CUs are connected to any ExceptionRule. So `Retriever.exception_closure` never
finds mitigation evidence for an eligible CU, and every NON_COMPLIANT verdict on
those CUs is confirmed without an exception review.

There is no structural or PolicyHypernym bridge between the two CU populations,
so this script links them by *concept*: each ExceptionRule is mapped, by hand,
to the legal-element `action_type`(s) it can mitigate AND a keyword guard on the
CU's `risk_title`/`constraint`. The keyword guard keeps precision high — e.g.
the depositor-protection exception only attaches to CUs whose text is actually
about depositor protection, not to every `required_disclosure_missing` CU.

Every created relationship is tagged `source: 'ccg_exception_bridge_v1'` so the
whole bridge is auditable and reversible with a single DELETE (--rollback).
This is a demo-grade heuristic bridge, not a replacement for compiling per-CU
exceptions in the policy compiler. The runtime still runs the LLM
`review_exception` gate, so a bridged exception only *gives the judge the chance*
to consider it — it does not auto-downgrade a verdict.

Usage:
    python3 bridge_exception_rules.py --workspace-id <ws> --dry-run
    python3 bridge_exception_rules.py --workspace-id <ws> --apply
    python3 bridge_exception_rules.py --workspace-id <ws> --rollback
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from neo4j import GraphDatabase

from env_loader import load_local_env

BRIDGE_SOURCE = "ccg_exception_bridge_v1"

# ExceptionRule id -> (eligible action_types it can mitigate, keyword guard).
# The keyword guard is matched (substring, any token) against the CU's
# risk_title + rationale + constraint so a coarse action_type does not over-link.
EXCEPTION_BRIDGE: dict[str, dict[str, Any]] = {
    "exception_depositor_protection_clarification": {
        "action_types": ["required_disclosure_missing", "guarantee_or_return_misleading"],
        "keywords": ["예금자보호", "보호한도", "부보", "예금보험"],
    },
    "exception_past_performance_disclaimer": {
        # High-precision only: bare 과거/성과/수익률 over-match unrelated CUs
        # (보험설계사 성과, 적정성 제외, 광고 실증), so require the past-return concept.
        "action_types": ["guarantee_or_return_misleading", "required_disclosure_missing", "condition_or_scope_missing"],
        "keywords": ["과거수익", "운용실적", "과거 운용", "미래수익", "과거성과", "과거의 운용"],
    },
    "exception_media_constraint_summary": {
        "action_types": ["required_disclosure_missing"],
        "keywords": ["매체", "지면", "배너", "표시 제약", "요약 표시"],
    },
    "exception_direct_seller_confirmed_agent_ad": {
        "action_types": ["guarantee_or_return_misleading", "required_disclosure_missing", "unfair_superior_position_sales"],
        "keywords": ["대리", "중개", "직접판매업자", "판매대리"],
    },
    "exception_statutory_trust_guarantee": {
        "action_types": ["guarantee_or_return_misleading"],
        "keywords": ["신탁", "손실보전", "이익보장"],
    },
}


def session_kwargs() -> dict[str, str]:
    database = os.environ.get("NEO4J_DATABASE")
    return {"database": database} if database else {}


def existing_rule_ids(driver: Any, workspace_id: str) -> set[str]:
    query = "MATCH (e:ExceptionRule {workspace_id: $ws}) RETURN e.id AS id"
    with driver.session(**session_kwargs()) as session:
        return {record["id"] for record in session.run(query, ws=workspace_id)}


def fetch_candidates(driver: Any, workspace_id: str) -> list[dict[str, Any]]:
    """Eligible CUs paired with the text used for concept matching."""
    query = """
    MATCH (cu:ComplianceUnit {workspace_id: $ws})-[:HAS_LEGAL_ELEMENT_PROFILE]->(p:CULegalElementProfile {workspace_id: $ws})
    WHERE p.exception_eligible = true
    RETURN cu.id AS cu_id, p.action_type AS action_type,
           coalesce(p.risk_title, '') + ' ' + coalesce(p.rationale, '') + ' '
             + coalesce(cu.constraint, '') + ' ' + coalesce(cu.principle, '') + ' ' + coalesce(cu.subject, '') AS text
    """
    with driver.session(**session_kwargs()) as session:
        return [dict(record) for record in session.run(query, ws=workspace_id)]


def plan_links(candidates: list[dict[str, Any]], available_rules: set[str]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for row in candidates:
        haystack = str(row.get("text") or "")
        action_type = row.get("action_type")
        for rule_id, spec in EXCEPTION_BRIDGE.items():
            if rule_id not in available_rules:
                continue
            if action_type not in spec["action_types"]:
                continue
            if not any(token in haystack for token in spec["keywords"]):
                continue
            links.append({"cu_id": row["cu_id"], "rule_id": rule_id, "action_type": action_type or ""})
    return links


def apply_links(driver: Any, workspace_id: str, links: list[dict[str, str]]) -> int:
    query = """
    UNWIND $links AS link
    MATCH (cu:ComplianceUnit {workspace_id: $ws, id: link.cu_id})
    MATCH (e:ExceptionRule {workspace_id: $ws, id: link.rule_id})
    MERGE (cu)-[r:HAS_EXCEPTION {workspace_id: $ws, source: $source}]->(e)
    SET r.bridged_action_type = link.action_type
    RETURN count(r) AS created
    """
    with driver.session(**session_kwargs()) as session:
        record = session.run(query, ws=workspace_id, links=links, source=BRIDGE_SOURCE).single()
        return int(record["created"]) if record else 0


def rollback(driver: Any, workspace_id: str) -> int:
    query = """
    MATCH (:ComplianceUnit {workspace_id: $ws})-[r:HAS_EXCEPTION {source: $source}]->(:ExceptionRule)
    DELETE r
    RETURN count(r) AS removed
    """
    with driver.session(**session_kwargs()) as session:
        record = session.run(query, ws=workspace_id, source=BRIDGE_SOURCE).single()
        return int(record["removed"]) if record else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge curated ExceptionRules to runtime-eligible CUs.")
    parser.add_argument("--workspace-id", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Print the links that would be created.")
    group.add_argument("--apply", action="store_true", help="Create the bridge relationships.")
    group.add_argument("--rollback", action="store_true", help="Delete bridge relationships created by this script.")
    args = parser.parse_args()

    load_local_env()
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not (uri and user and password):
        raise RuntimeError("NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD are required.")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        if args.rollback:
            removed = rollback(driver, args.workspace_id)
            print(f"rollback: removed {removed} bridge relationships")
            return

        available = existing_rule_ids(driver, args.workspace_id)
        missing = set(EXCEPTION_BRIDGE) - available
        if missing:
            print(f"warning: {len(missing)} mapped ExceptionRule(s) not in graph, skipped: {sorted(missing)}")

        candidates = fetch_candidates(driver, args.workspace_id)
        links = plan_links(candidates, available)
        by_rule: dict[str, list[str]] = {}
        for link in links:
            by_rule.setdefault(link["rule_id"], []).append(link["cu_id"])

        print(f"eligible CUs scanned: {len(candidates)} · planned bridge links: {len(links)}")
        for rule_id, cu_ids in sorted(by_rule.items()):
            print(f"\n  {rule_id}  ->  {len(cu_ids)} CU")
            for cu_id in cu_ids:
                print(f"      {cu_id}")

        if args.apply:
            created = apply_links(driver, args.workspace_id, links)
            print(f"\napplied: merged {created} HAS_EXCEPTION relationships (source={BRIDGE_SOURCE})")
        else:
            print("\n(dry-run) nothing written. Re-run with --apply to create, --rollback to undo.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
