"""JB 전북은행 실제 광고물(05_jbbank) 라이브 심사 + 로그 영속화.

`05_jbbank/artifacts/<event>/*.md`는 Upstage document-parse로 OCR한 실제 광고물
(이미지 figure 설명 + 본문 텍스트)이다. 이 스크립트는 그 광고들을 라이브 심사
파이프라인에 통과시키고, 각 심사를 ``run_store.record_run``으로 영속화한다
(source_type=jbbank_eval → /api/runs·운영 대시보드 평가 탭에서 조회).

**정답 라벨이 없다** — 실제 승인 광고이므로 위반 gold가 없다. 따라서 정밀도·재현율을
계산하지 않고, 판정 분포·검출 이슈 로그만 배치 리포트로 남긴다(gold_available=false).
결정론 fallback 금지: LLM/Neo4j 부재 시 조용히 대체하지 않고 실패한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_local_env  # noqa: E402

LOGGER = logging.getLogger(__name__)

DEFAULT_WORKSPACE = "graphcompliance_mvp_jb_20260530"

# 상품군 추론 키워드 (제목·본문 기반). 카드/송금/환전 등은 예금/대출 그래프 밖 → 기본 제외.
GROUP_KEYWORDS: dict[str, list[str]] = {
    "deposit": ["적금", "예금", "통장", "입출금", "저축", "계좌"],
    "loan": ["대출", "론", "햇살", "전세자금", "마이너스", "비상금"],
}


def infer_product_group(title: str, text: str) -> str:
    """제목 우선, 없으면 본문으로 상품군 추론. 매칭 없으면 'other'."""
    haystack_title = title
    for group, terms in GROUP_KEYWORDS.items():
        if any(term in haystack_title for term in terms):
            return group
    head = text[:600]
    for group, terms in GROUP_KEYWORDS.items():
        if any(term in head for term in terms):
            return group
    return "other"


def clean_ad_text(markdown: str, *, max_chars: int = 6000) -> str:
    """OCR .md에서 심사 입력 텍스트 구성. 이미지 placeholder는 제거하고 figure 설명은 보존.

    figcaption의 figure-description(비전 판독 결과)은 '이미지'를 텍스트로 전달하는
    핵심이므로 남긴다. HTML 태그만 벗겨 자연어로 만든다.
    """
    text = markdown
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # ![image](/image/placeholder)
    text = re.sub(r'<p class="figure-description">(.*?)</p>', r"[이미지 설명] \1", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)  # 잔여 HTML 태그 제거
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text[:max_chars]


def discover_artifacts(artifacts_dir: Path) -> list[dict[str, Any]]:
    """각 이벤트 폴더에서 대표 .md(없으면 .txt)와 제목을 수집."""
    items: list[dict[str, Any]] = []
    for sub in sorted(p for p in artifacts_dir.iterdir() if p.is_dir()):
        md = next(iter(sorted(sub.glob("parse_*.md"))), None) or next(iter(sorted(sub.glob("*.md"))), None)
        source = md
        if source is None:
            txt = next(iter(sorted(sub.glob("*.txt"))), None)
            source = txt
        if source is None:
            continue
        try:
            raw = source.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("read failed dir=%s err=%s", sub.name, exc)
            continue
        title = _title_from(sub.name, raw)
        text = clean_ad_text(raw) if source.suffix == ".md" else raw[:6000].strip()
        if not text:
            continue
        items.append(
            {
                "id": f"jbbank_{sub.name[:60]}",
                "source_dir": sub.name,
                "title": title,
                "text": text,
                "product_group": infer_product_group(title, text),
            }
        )
    return items


def _title_from(dir_name: str, raw: str) -> str:
    first_line = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")
    if first_line and "figure" not in first_line.lower() and len(first_line) < 120:
        return first_line
    # 폴더명 꼬리(한글 제목)에서 복원
    tail = dir_name.split("_")
    return "_".join(tail[-3:]).replace("_", " ") if tail else dir_name


def review_one(item: dict[str, Any], *, workspace_id: str) -> dict[str, Any]:
    from run_store import record_run
    from utils import to_jsonable
    from workflow import GraphComplianceCCGWorkflow, review_input_from_payload

    payload = {
        "dataset_item_id": item["id"],
        "title": item["title"],
        "content_text": item["text"],
        "channel": "bank_event_page_text",
        "source_type": "jbbank_eval",
        "product_group": item["product_group"],
        "workspace_id": workspace_id,
    }
    output = GraphComplianceCCGWorkflow().review(review_input_from_payload(payload))
    jsonable = to_jsonable(output)
    # 영속화 — /api/runs·평가 탭에서 조회되도록 eval 배치임을 source_type으로 표시.
    record_run(
        jsonable,
        title=item["title"],
        channel="bank_event_page_text",
        product_group=item["product_group"],
        source_type="jbbank_eval",
        content_text=item["text"],
        actor="jbbank_eval",
        workspace_id=workspace_id,
        language="ko",
    )
    return _row_from_output(item, jsonable)


def _row_from_output(item: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    issues = output.get("detected_issues") or []
    checks = ((output.get("product_fact_context") or {}).get("disclosure_checks")) or []
    missing = [
        str(c.get("label") or "")
        for c in checks
        if str(c.get("gate_status") or "ON").upper() == "ON" and not c.get("present")
    ]
    track_b = output.get("overall_impression_judgment") or {}
    return {
        "id": item["id"],
        "source_dir": item["source_dir"],
        "title": item["title"],
        "product_group": item["product_group"],
        "run_id": str(output.get("review_run_id") or ""),
        "final_verdict": str(output.get("final_verdict") or ""),
        "misleading_verdict": str(track_b.get("verdict") or ""),
        "issue_count": len(issues),
        "missing_disclosures": missing,
        "detected_risk_codes": sorted(
            {str(i.get("risk_code") or i.get("cu_id") or "") for i in issues} - {""}
        ),
    }


def build_report(
    rows: list[dict[str, Any]],
    *,
    workspace_id: str,
    review_model: str = "",
    product_selection: str = "product_group_only",
) -> dict[str, Any]:
    verdict_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    for row in rows:
        verdict_counts[row["final_verdict"]] = verdict_counts.get(row["final_verdict"], 0) + 1
        group_counts[row["product_group"]] = group_counts.get(row["product_group"], 0) + 1
    flagged = [r for r in rows if r["final_verdict"] in {"reject", "revise"}]
    return {
        "kind": "jbbank_live_eval",
        "batch": f"jbbank_eval_{int(time.time())}",
        "generated_at": int(time.time()),
        "gold_available": False,
        "review_model": review_model,
        # 실제 광고는 특정 그래프 상품에 결속하지 않고 상품군만 지정해 심사(들어오는 광고를
        # 그대로 심사하는 현실 경로). 합성셋은 selected_product_name으로 상품 선택 심사.
        "product_selection": product_selection,
        "note": "전북은행 실제 승인 광고물 — 위반 gold 없음. 정밀도·재현율 미산출; 판정 분포·검출 이슈 로그만.",
        "workspace_id": workspace_id,
        "record_count": len(rows),
        "flagged_count": len(flagged),
        "verdict_counts": verdict_counts,
        "product_group_counts": group_counts,
        "records": rows,
    }


def main() -> int:
    load_local_env(Path.cwd() / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--product-groups", default="deposit,loan", help="Comma-separated groups to keep (or 'all').")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE)
    parser.add_argument("--report", type=Path, default=Path(__file__).resolve().parent / "jbbank_eval_report.json")
    parser.add_argument("--dry-run", action="store_true", help="Discover + filter only; no live review.")
    args = parser.parse_args()

    items = discover_artifacts(args.artifacts_dir)
    keep = {g.strip() for g in args.product_groups.split(",") if g.strip()}
    if "all" not in keep:
        items = [it for it in items if it["product_group"] in keep]
    items = items[: args.limit]
    LOGGER.info("selected %d ads (groups=%s)", len(items), sorted(keep))

    if args.dry_run:
        for it in items:
            print(f"{it['product_group']:8s} | {it['title'][:70]}")
        print(f"total={len(items)}")
        return 0

    rows: list[dict[str, Any]] = []
    if args.workers <= 1:
        for index, item in enumerate(items, start=1):
            LOGGER.info("review %d/%d: %s", index, len(items), item["title"][:60])
            rows.append(review_one(item, workspace_id=args.workspace_id))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(review_one, it, workspace_id=args.workspace_id): it for it in items}
            done = 0
            for future in as_completed(futures):
                done += 1
                item = futures[future]
                try:
                    rows.append(future.result())
                    LOGGER.info("reviewed %d/%d: %s", done, len(items), item["title"][:50])
                except Exception:  # noqa: BLE001
                    LOGGER.exception("review failed dir=%s", item["source_dir"])

    rows.sort(key=lambda r: r["source_dir"])
    import os
    review_model = os.environ.get("ANTHROPIC_MODEL") if os.environ.get("LLM_PROVIDER", "").lower() == "anthropic" else os.environ.get("OPENAI_MODEL", "gpt-5.4-nano")
    report = build_report(rows, workspace_id=args.workspace_id, review_model=str(review_model or ""))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    LOGGER.info("wrote %s (records=%d, flagged=%d)", args.report, report["record_count"], report["flagged_count"])
    print(json.dumps(report["verdict_counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
