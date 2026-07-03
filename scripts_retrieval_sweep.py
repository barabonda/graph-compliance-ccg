"""agent_input_660 retrieval 스윕 → CU 소환 빈도 랭킹.

LLM 호출 없이(임베딩만) retrieval 경로를 660건 광고에 돌려, 실전에서 자주
소환되는 CU를 랭킹한다. 요건(required_positive_features)이 빈 CU가 상위에
있으면 그것이 (c) 데이터 보강의 1순위다 — "실제 걸리는 것부터 탄탄하게".

Usage:
  python scripts_retrieval_sweep.py --input <jsonl> [--limit 120] [--out sweep.json]
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from env_loader import load_local_env
from ccg_embeddings import EmbeddingGateway
from retrieval_probe import make_anchor, pick_auto_hypernyms
from retriever import Neo4jPolicyRetriever


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--top-candidates", type=int, default=12, help="레코드당 상위 후보 N개만 집계")
    ap.add_argument("--out", default="eval/retrieval_sweep_660.json")
    args = ap.parse_args()
    load_local_env()

    rows = [json.loads(l) for l in open(args.input, encoding="utf-8") if l.strip()]
    # orig/risk_job 균형 샘플
    orig = [r for r in rows if "orig" in r["dataset_item_id"]]
    risk = [r for r in rows if "risk" in r["dataset_item_id"]]
    half = args.limit // 2
    sample = orig[:half] + risk[: args.limit - half]
    print(f"입력 {len(rows)}건 중 스윕 대상 {len(sample)}건 (orig {min(half,len(orig))} + risk {len(sample)-min(half,len(orig))})")

    embedder = EmbeddingGateway()
    retriever = Neo4jPolicyRetriever()
    cu_hits: Counter[str] = Counter()
    cu_meta: dict[str, dict] = {}
    cu_records: defaultdict[str, set] = defaultdict(set)
    errors = 0
    t0 = time.perf_counter()
    for i, rec in enumerate(sample):
        text = str(rec["input"].get("content_text") or "")[:1500]
        if not text.strip():
            continue
        try:
            emb = embedder.embed(text)
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                hyps = pick_auto_hypernyms(retriever, args.workspace_id, emb, 4)
            if not hyps:
                continue
            anchor = make_anchor(text, hyps)
            cands = retriever.candidates_for_anchor(
                workspace_id=args.workspace_id,
                anchor=anchor,
                product_group="auto",
                channel=str(rec["input"].get("channel") or "bank_event_page_text"),
                limit=50,
            )
        except Exception as exc:  # noqa: BLE001
            errors += 1
            if errors <= 3:
                print(f"  [err] {rec['dataset_item_id']}: {type(exc).__name__}: {str(exc)[:60]}")
            continue
        ranked = sorted(cands, key=lambda c: c.retrieval_scores.get("combined_score", 0.0), reverse=True)
        for c in ranked[: args.top_candidates]:
            cu_hits[c.cu_id] += 1
            cu_records[c.cu_id].add(rec["dataset_item_id"])
            if c.cu_id not in cu_meta:
                cu_meta[c.cu_id] = {
                    "principle": c.principle,
                    "subject": (c.subject or "")[:60],
                    "source_article": c.source_article,
                    "has_req": bool(c.legal_element_profile and c.legal_element_profile.required_positive_features),
                    "action_type": c.legal_element_profile.action_type if c.legal_element_profile else "",
                }
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(sample)} ({time.perf_counter()-t0:.0f}s)")
    retriever.close()

    ranking = [
        {"cu_id": cid, "hits": n, "records": len(cu_records[cid]), **cu_meta.get(cid, {})}
        for cid, n in cu_hits.most_common()
    ]
    empty_top = [r for r in ranking if not r.get("has_req")]
    out = {
        "swept": len(sample), "errors": errors,
        "distinct_cus_retrieved": len(ranking),
        "empty_req_among_retrieved": len(empty_top),
        "ranking": ranking,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== 결과: 소환된 CU {len(ranking)}종 (요건 빈 것 {len(empty_top)}종) → {args.out} ===")
    print("\n[요건 비어있는데 자주 소환되는 CU — 보강 1순위 TOP 15]")
    for r in empty_top[:15]:
        print(f"  {r['hits']:4}회/{r['records']:3}건 [{r.get('action_type','')[:24]:24}] {str(r.get('source_article',''))[:34]:36} {r.get('subject','')[:34]}")
    print("\n[요건 있는 CU TOP 5 (참고)]")
    for r in [x for x in ranking if x.get("has_req")][:5]:
        print(f"  {r['hits']:4}회 [{r.get('action_type','')[:24]:24}] {str(r.get('source_article',''))[:34]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
