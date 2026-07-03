"""가드형 legal-element 프로파일 재컴파일.

naive backfill은 양질(LLM컴파일) 프로파일을 약한 텍스트휴리스틱으로 덮어써 악화된다.
이 스크립트는 엄격히 개선만 한다:
  - 기존 프로파일이 non-empty required_features를 가지면 절대 건드리지 않음(보존).
  - 프로파일이 없거나 요건이 비어있고, 텍스트 추론이 non-empty면 그것만 기록.
  - 추론도 비면 건드리지 않음(데이터 부실 CU → VLM/LLM 재컴파일 대상으로 남김).

Usage: python scripts_guarded_recompile.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os

from env_loader import load_local_env
from legal_elements import infer_legal_profile_from_text
from utils import stable_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_local_env()
    from neo4j import GraphDatabase

    ws = args.workspace_id
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        rows = s.run(
            """
            MATCH (cu:ComplianceUnit {workspace_id:$ws})
            OPTIONAL MATCH (cu)-[:HAS_LEGAL_ELEMENT_PROFILE]->(pr)
            OPTIONAL MATCH (cu)-[:HAS_EMBEDDING_PROFILE]->(e)
            RETURN cu.id AS id, properties(cu) AS p,
                   coalesce(e.profile_summary,"") AS ps, coalesce(e.embedding_text,"") AS et,
                   pr IS NOT NULL AS has_prof, coalesce(pr.required_positive_features,[]) AS cur_req
            """,
            ws=ws,
        ).data()
    dedup = {}
    for r in rows:
        dedup.setdefault(r["id"], r)
    writes = []
    preserved = skipped_empty = 0
    for r in dedup.values():
        if r["has_prof"] and r["cur_req"]:
            preserved += 1
            continue
        text = " ".join(str(r["p"].get(k) or "") for k in ("principle", "subject", "condition", "constraint", "context", "cu_type"))
        text += " " + r["ps"] + " " + r["et"]
        prof = infer_legal_profile_from_text(workspace_id=ws, cu_id=r["id"], text=text)
        if not prof["required_positive_features"]:
            skipped_empty += 1
            continue
        writes.append({
            "cu_id": r["id"],
            "id": stable_id("cu_legal_element_profile", ws, r["id"], prof["action_type"], prof.get("risk_title", "")),
            "action_type": prof["action_type"],
            "required_positive_features": prof["required_positive_features"],
            "applicability_scope": prof.get("applicability_scope", []),
            "risk_title": prof.get("risk_title", ""),
            "exception_eligible": prof.get("exception_eligible", False),
            "rationale": "guarded recompile: filled empty/absent legal-element profile from CU text",
        })
    print(f"보존(양질): {preserved} | 기록 대상(개선): {len(writes)} | 잔여(데이터부실): {skipped_empty}")
    if args.dry_run:
        print("dry-run: 쓰기 없음")
        driver.close()
        return 0
    with driver.session() as s:
        s.run(
            """
            UNWIND $rows AS row
            MATCH (cu:ComplianceUnit {id: row.cu_id, workspace_id: $ws})
            // 빈 요건의 기존 프로파일은 제거 후 생성 — 중복(빈것+찬것 혼재) 방지.
            OPTIONAL MATCH (cu)-[:HAS_LEGAL_ELEMENT_PROFILE]->(old:CULegalElementProfile)
            WHERE size(coalesce(old.required_positive_features, [])) = 0
            DETACH DELETE old
            MERGE (cu)-[:HAS_LEGAL_ELEMENT_PROFILE {workspace_id: $ws, source: 'guarded_recompile'}]->(pr:CULegalElementProfile {id: row.id, workspace_id: $ws})
            SET pr.action_type = row.action_type,
                pr.required_positive_features = row.required_positive_features,
                pr.applicability_scope = row.applicability_scope,
                pr.risk_title = row.risk_title,
                pr.exception_eligible = row.exception_eligible,
                pr.rationale = row.rationale,
                pr.feature_contract = 'canonical_legal_element_v1',
                pr.backfill_source = 'guarded_recompile'
            """,
            rows=writes,
            ws=ws,
        )
        written = s.run(
            "MATCH (:ComplianceUnit)-[:HAS_LEGAL_ELEMENT_PROFILE]->(pr:CULegalElementProfile {workspace_id:$ws}) WHERE size(coalesce(pr.required_positive_features,[]))>0 RETURN count(pr) AS n",
            ws=ws,
        ).single()["n"]
        print(f"기록 완료. 요건보유 프로파일 총계: {written}")
    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
