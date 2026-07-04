"""Run the KH eval set through the official /api/review endpoint and summarize.

Usage:  python data/cambodia/eval/run_kh_eval.py [--base http://localhost:8770]
Writes per-run raw JSON to data/cambodia/eval/results/ and prints a summary table.
Retries once on HTTP 5xx (Aura idle-connection drops have produced one-off 500s).
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
KR_LAW_TOKENS = ["금소법", "금융소비자보호법", "금융소비자보호", "감독규정", "심의기준", "표시광고"]
KR_ARTICLE = re.compile(r"제\s*\d+\s*조")
CAMBODIA_MARKERS = ["Sub-Decree 232", "Prakas 249", "Consumer Protection", "NBC"]


def post_review(base: str, payload: dict, timeout: int = 580) -> tuple[int, dict | None]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/review", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        return exc.code, None
    except Exception:
        return 0, None


def korean_statute_citations(d: dict) -> list[str]:
    """Korean STATUTE names in judgment basis / issue articles (not style echoes)."""
    hits: list[str] = []
    for j in d.get("judgments") or []:
        text = (j.get("legal_basis") or "") + " " + (j.get("conclusion") or "")
        # style echo '위임사슬에 준하는' is not a citation; flag only statute names
        for tok in ("금소법", "금융소비자보호법"):
            if tok in text:
                hits.append(f"judgment[{j.get('cu_id')}]:{tok}")
    for x in d.get("detected_issues") or []:
        sa = str(x.get("source_article") or "")
        if any(tok in sa for tok in KR_LAW_TOKENS) or KR_ARTICLE.search(sa):
            if not any(m in sa for m in CAMBODIA_MARKERS):
                hits.append(f"issue:{sa}")
    return hits


def summarize(item: dict, run_idx: int, d: dict) -> dict:
    pfc = d.get("product_fact_context") or {}
    comps = pfc.get("comparison_results") or []
    anchors = d.get("context_anchors") or []
    hyp_pairs = [
        (a.get("span", {}).get("text", "")[:38], [p.get("hypernym") for p in (a.get("hypernyms") or [])[:3]])
        for a in anchors
    ]
    t = d.get("ad_translations") or {}
    return {
        "id": item["id"],
        "run": run_idx,
        "verdict": d.get("final_verdict"),
        "fired_cus": sorted({i.get("cu_id", "") for i in (d.get("cu_plan") or [])}),
        "judgments": [(j.get("cu_id"), j.get("verdict")) for j in (d.get("judgments") or [])],
        "kr_statute_citations": korean_statute_citations(d),
        "extraction_status": pfc.get("extraction_status"),
        "comparison_statuses": sorted({c.get("status", "") for c in comps}),
        "comparisons": len(comps),
        "translations": {"en": bool(t.get("en")), "ko": bool(t.get("ko"))},
        "hypernym_mapping": hyp_pairs,
        "track_b": (d.get("overall_impression_judgment") or {}).get("verdict"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8770")
    args = ap.parse_args()

    spec = json.loads((HERE / "kh_eval_v0.json").read_text(encoding="utf-8"))
    ws = spec["meta"]["workspace_id"]
    RESULTS.mkdir(exist_ok=True)
    summaries: list[dict] = []

    for item in spec["items"]:
        for run_idx in range(1, int(item.get("repeat", 1)) + 1):
            payload = {
                "dataset_item_id": f"{item['id']}_run{run_idx}",
                "title": item["title"],
                "content_text": item["content_text"],
                "channel": "bank_event_page_text",
                "product_group": item["product_group"],
                "selected_product_name": item.get("selected_product_name", ""),
                "workspace_id": ws,
                "language": item["language"],
            }
            started = time.time()
            status, data = post_review(args.base, payload)
            if status >= 500 or data is None:
                print(f"  {item['id']} run{run_idx}: HTTP {status} — retrying once (Aura idle-drop guard)")
                time.sleep(3)
                status, data = post_review(args.base, payload)
            elapsed = time.time() - started
            if data is None:
                summaries.append({"id": item["id"], "run": run_idx, "verdict": f"HTTP_{status}", "error": True})
                print(f"  {item['id']} run{run_idx}: FAILED HTTP {status}")
                continue
            (RESULTS / f"{item['id']}_run{run_idx}.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            s = summarize(item, run_idx, data)
            s["seconds"] = round(elapsed)
            summaries.append(s)
            print(f"  {item['id']} run{run_idx}: {s['verdict']} ({elapsed:.0f}s) cus={s['fired_cus']}")

    (RESULTS / "_summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDONE — {len(summaries)} runs, summary at {RESULTS / '_summary.json'}")


if __name__ == "__main__":
    main()
