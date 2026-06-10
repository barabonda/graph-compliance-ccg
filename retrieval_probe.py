"""검색(retrieval) 로직 격리 진단 스크립트.

이 스크립트는 전체 리뷰 파이프라인(LLM 추출/정규화/판단)을 돌리지 않고,
**검색 단계만** 떼어내서 실제 Neo4j + 임베딩에 대해 무엇이 일어나는지 보여준다.

측정/출력 항목
  1) assert_policy_alignment_ready  - 그래프 준비 상태(개수 게이트)
  2) policy_context_for_claims      - 정규화기에 들어가는 어휘/전제/유사단편과 그 정렬 방식
  3) candidates_for_anchor          - 핵심 CU 후보검색의 점수 분해 + 게이트가 무엇을 떨어뜨리는지
  4) 순수 벡터 fallback 비교        - hypernym이 비면 후보가 0이 되는 "리콜 구멍"을 실증
  5) 단계별 소요시간 + 활성 CU 전수 스캔 비용

사용 예
  PYTHONPATH=examples/graph-compliance-ccg \
  python3 examples/graph-compliance-ccg/retrieval_probe.py \
    --workspace-id graphcompliance_mvp_jb_20260530 \
    --text "지난 3년간 조기상환 성공률이 높았던 ELS, 중위험 투자자에게 좋은 선택입니다." \
    --product-group investment

핵심 인자
  --hypernym-ids  쉼표구분 PolicyHypernym id. 주면 그 id로 가짜 앵커를 만들어
                  candidates_for_anchor를 직접 호출(=실서비스의 검색 경로).
  --auto-hypernyms N  주지 않으면, 질의 임베딩과 유사한 상위 N개 hypernym을
                  자동 선택(정규화 LLM 흉내). 검색 로직만 보고 싶을 때 편리.
  --json PATH     전체 결과를 JSON으로 저장(웹페이지/공유용).

이 스크립트는 LLM(gpt) 호출을 하지 않는다. 임베딩 호출(text-embedding-3-small)만
필요하므로 비용이 매우 작다.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from env_loader import load_local_env

# .env를 먼저 로드해야 retriever가 NEO4J_*/OPENAI_*를 읽을 수 있다.
load_local_env(Path(__file__).resolve().parent / ".env")

from ccg_embeddings import EmbeddingGateway  # noqa: E402
from retriever import (  # noqa: E402
    ACTIONABLE_VECTOR_THRESHOLD,
    Neo4jPolicyRetriever,
    candidate_allowed_for_anchor,
    is_operational_candidate,
    is_product_scope_mismatch,
    with_scope_gate,
)
from schemas import ContextAnchor, PolicyHypernymProposal, Span  # noqa: E402


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def make_anchor(text: str, hypernyms: list[tuple[str, str]]) -> ContextAnchor:
    """검색 경로 테스트용 가짜 앵커. (정규화 LLM 출력 대용)"""
    proposals = [
        PolicyHypernymProposal(
            proposal_id=f"probe_{i}",
            source_id="probe_anchor",
            hypernym_id=hid,
            hypernym=hname,
            support="STRONG",
            confidence=0.9,
            normalized_score=1.0,
            evidence_ids=[],
            why="probe seed",
        )
        for i, (hid, hname) in enumerate(hypernyms)
    ]
    return ContextAnchor(
        anchor_id="probe_anchor",
        anchor_type="claim_anchor",  # actionable 경로로 테스트
        claim_id="probe_claim",
        span=Span(start=0, end=len(text), text=text),
        facts=[],
        hypernyms=proposals,
    )


def pick_auto_hypernyms(
    retriever: Neo4jPolicyRetriever,
    workspace_id: str,
    query_embedding: list[float],
    top_n: int,
) -> list[tuple[str, str]]:
    """질의 임베딩과 가장 가까운 hypernym을 직접 임베딩이 없을 수 있으므로,
    유사 Premise가 정의/지지하는 hypernym으로 역추적해서 자동 선택한다."""
    cypher = """
    MATCH (p:Premise {workspace_id: $ws})
    WHERE p.embedding IS NOT NULL
    WITH p, vector.similarity.cosine(p.embedding, $emb) AS score
    ORDER BY score DESC
    LIMIT 40
    MATCH (p)-[:DEFINES_HYPERNYM|SUPPORTS_HYPERNYM]->(h:PolicyHypernym {workspace_id: $ws})
    WHERE coalesce(h.status,'approved') = 'approved'
    WITH h, max(score) AS best
    RETURN h.id AS id, coalesce(h.canonical_name_ko, h.name) AS name, best
    ORDER BY best DESC
    LIMIT $top_n
    """
    with retriever.driver.session(**retriever._session_kwargs()) as session:
        rows = [dict(r) for r in session.run(cypher, ws=workspace_id, emb=query_embedding, top_n=top_n)]
    for r in rows:
        print(f"   auto hypernym  {r['best']:.3f}  {r['id']}  {r['name']}")
    return [(r["id"], r["name"]) for r in rows]


def count_active_cus(retriever: Neo4jPolicyRetriever, workspace_id: str) -> int:
    cypher = """
    MATCH (cu:ComplianceUnit {workspace_id:$ws})-[:HAS_EMBEDDING_PROFILE]->(pr:CUEmbeddingProfile)
    WHERE coalesce(cu.active_for_gate,false)=true AND pr.embedding IS NOT NULL
    RETURN count(*) AS n
    """
    with retriever.driver.session(**retriever._session_kwargs()) as session:
        return int(session.run(cypher, ws=workspace_id).single()["n"])


def raw_candidates_with_trace(
    retriever: Neo4jPolicyRetriever,
    workspace_id: str,
    anchor: ContextAnchor,
    product_group: str,
    channel: str,
) -> dict[str, Any]:
    """candidates_for_anchor의 내부를 흉내내되, 게이트가 무엇을 떨어뜨리는지
    한 단계씩 추적한다. (retriever의 공개 함수와 헬퍼를 재사용)"""
    # 1) DB 후보 (점수 포함) — 실제 함수 호출
    t0 = time.perf_counter()
    scored = retriever.candidates_for_anchor(
        workspace_id=workspace_id,
        anchor=anchor,
        product_group=product_group,
        channel=channel,
        limit=1000,  # 게이트 통과 후 남는 전부를 보려고 크게
    )
    elapsed = time.perf_counter() - t0
    return {"final": scored, "elapsed_s": elapsed}


def summarize_candidate(c: Any) -> dict[str, Any]:
    s = c.retrieval_scores
    return {
        "cu_id": c.cu_id,
        "principle": c.principle,
        "subject": (c.subject or "")[:48],
        "cu_type": c.cu_type,
        "active_for_gate": c.active_for_gate,
        "gate_status": c.gate_status,
        "retrieval_basis": c.retrieval_basis,
        "vector_score": round(s.get("vector_score", 0.0), 4),
        "hypernym_overlap": round(s.get("hypernym_overlap", 0.0), 4),
        "active": round(s.get("active_for_gate", 0.0), 4),
        "combined_score": round(s.get("combined_score", 0.0), 4),
        "n_evidence": len(c.legal_evidence_ids),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    ap.add_argument("--text", default="지난 3년간 조기상환 성공률이 높았던 ELS, 중위험 투자자에게 좋은 선택입니다.")
    ap.add_argument("--product-group", default="auto")
    ap.add_argument("--channel", default="bank_event_page_text")
    ap.add_argument("--hypernym-ids", default="", help="쉼표구분 PolicyHypernym id")
    ap.add_argument("--auto-hypernyms", type=int, default=4)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    out: dict[str, Any] = {"workspace_id": args.workspace_id, "query": args.text, "product_group": args.product_group}
    retriever = Neo4jPolicyRetriever()
    embedder = EmbeddingGateway()

    # ---------- 1. 준비 상태 게이트 ----------
    banner("1) assert_policy_alignment_ready  (그래프 준비 게이트)")
    t0 = time.perf_counter()
    try:
        retriever.assert_policy_alignment_ready(workspace_id=args.workspace_id)
        print("   PASS: 그래프 준비 완료")
        out["alignment_ready"] = True
    except Exception as exc:  # noqa: BLE001
        print(f"   FAIL: {exc}")
        out["alignment_ready"] = False
    print(f"   소요 {time.perf_counter()-t0:.3f}s")

    active_cu_n = count_active_cus(retriever, args.workspace_id)
    print(f"   임베딩 보유 활성 CU 수 = {active_cu_n}  (앵커마다 이 전부에 대해 코사인 계산)")
    out["active_cu_count"] = active_cu_n

    # ---------- 2. 정규화기 컨텍스트 ----------
    banner("2) policy_context_for_claims  (정규화기 입력 컨텍스트)")
    t0 = time.perf_counter()
    ctx = retriever.policy_context_for_claims(
        workspace_id=args.workspace_id, query_text=args.text[:1200], limit=80
    )
    print(f"   소요 {time.perf_counter()-t0:.3f}s")
    print(f"   hypernyms={len(ctx['hypernyms'])}  premises={len(ctx['premises'])}  fragments={len(ctx['fragments'])}")
    print("   * hypernyms: priority 정렬(유사도 아님) — 정규화기는 앞 200개만 사용")
    print("   * premises : ORDER BY 없음(임의 순서) LIMIT 80 — 정규화기는 앞 80개 사용")
    print("   * fragments: 유사도 정렬 top-40 (유일하게 질의 관련도로 랭크됨)")
    print("   -- 유사 단편(fragments) 상위 5 (질의와의 코사인) --")
    for f in ctx["fragments"][:5]:
        print(f"      {f.get('score', 0):.3f}  {str(f.get('text',''))[:70]}")
    out["policy_context_counts"] = {
        "hypernyms": len(ctx["hypernyms"]),
        "premises": len(ctx["premises"]),
        "fragments": len(ctx["fragments"]),
    }
    out["top_fragments"] = [
        {"score": round(float(f.get("score", 0)), 4), "text": str(f.get("text", ""))[:120]}
        for f in ctx["fragments"][:10]
    ]

    # ---------- 3. seed hypernym 결정 ----------
    banner("3) seed PolicyHypernym 결정")
    query_embedding = embedder.embed(args.text[:3000])
    if args.hypernym_ids.strip():
        ids = [x.strip() for x in args.hypernym_ids.split(",") if x.strip()]
        name_by_id = {str(h["hypernym_id"]): str(h["name"]) for h in ctx["hypernyms"]}
        seed = [(i, name_by_id.get(i, i)) for i in ids]
        print(f"   사용자 지정 {len(seed)}개")
    else:
        print(f"   자동 선택(유사 Premise -> hypernym 역추적) top {args.auto_hypernyms}:")
        seed = pick_auto_hypernyms(retriever, args.workspace_id, query_embedding, args.auto_hypernyms)
    out["seed_hypernyms"] = [{"id": i, "name": n} for i, n in seed]

    # ---------- 4. 핵심 후보검색 + 게이트 추적 ----------
    banner("4) candidates_for_anchor  (핵심 CU 후보검색)")
    if not seed:
        print("   seed hypernym이 없어 candidates_for_anchor는 즉시 [] 반환 (조기 return).")
        out["candidates"] = []
    else:
        anchor = make_anchor(args.text, seed)
        res = raw_candidates_with_trace(
            retriever, args.workspace_id, anchor, args.product_group, args.channel
        )
        finals = res["final"]
        print(f"   소요 {res['elapsed_s']:.3f}s  -> 게이트 통과 후보 {len(finals)}개")
        print(f"   결합점수 = 0.55*vector + 0.35*hypernym_overlap + 0.10*active   (벡터 임계 {ACTIONABLE_VECTOR_THRESHOLD})")
        print("   순위  combined  vector  overlap  act  basis            gate       cu_id")
        rows = []
        for c in finals[:15]:
            d = summarize_candidate(c)
            rows.append(d)
            print(
                f"   {d['combined_score']:>7.4f}  {d['vector_score']:>6.3f}  {d['hypernym_overlap']:>6.3f}  "
                f"{d['active']:>3.0f}  {d['retrieval_basis']:<16} {d['gate_status']:<9} {d['cu_id']}"
            )
        out["candidates"] = [summarize_candidate(c) for c in finals]

    # ---------- 5. 리콜 구멍 실증: hypernym 없는 앵커 ----------
    banner("5) 리콜 구멍 실증  (hypernym 0개 앵커는 후보 0)")
    empty_anchor = make_anchor(args.text, [])
    empty = retriever.candidates_for_anchor(
        workspace_id=args.workspace_id, anchor=empty_anchor,
        product_group=args.product_group, channel=args.channel, limit=12,
    )
    print(f"   hypernym 0개 앵커 -> 후보 {len(empty)}개")
    print("   => 정규화 LLM이 hypernym을 못 붙이면, 임베딩이 아무리 가까워도 CU 검색은 0건.")
    print("      (candidates_for_anchor 첫 줄 `if not hypernym_ids: return []`)")
    out["empty_anchor_candidates"] = len(empty)

    retriever.close()

    if args.json:
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 저장: {args.json}")


if __name__ == "__main__":
    main()
