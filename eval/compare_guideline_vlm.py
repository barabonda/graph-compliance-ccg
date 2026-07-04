"""가이드라인 판단사례 정답셋 vs 서비스 검출 사례별 대조 (Phase 3).

기존 evaluate.py 의 canonical_article / summarize_prediction 을 재사용하여
regulator_cases_full.jsonl(정답) 과 regulator_predictions_vlm_full.jsonl(서비스 검출)
을 사례별로 대조한다.

판정 규칙 (spec_guideline_eval.md):
- 적중: 지적 취지와 같은 원칙/조문 계열을 검출
- 부분: 위반(routing revise/reject)은 잡았으나 취지/조문·유형이 불일치
- 누락: 위반을 못 잡음(pass_candidate/needs_review)
- 추가 검출: 지적 외 서비스가 추가로 든 조문/이슈(오탐 단정 금지)

조문은 위임사슬 계열 단위로 동일시한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluate import canonical_article, record_from_json, summarize_prediction  # noqa: E402


# 금소법 광고규제 위임사슬 계열 (§22 ↔ 시행령 §18/§20 ↔ 감독규정 §17 ↔ 은행 광고심의 기준 §16/§17)
FMLA_ADSCOPE = "금소법_광고규제_위임사슬"
# 공정위 표시·광고 공정화법 계열 (§3 부당표시광고, §5 실증)
FMLA_FAIR = "표시광고공정화법_계열"


def article_family(article: str) -> str:
    """조문 문자열을 위임사슬 계열 키로 사상.

    canonical_article() 은 공백을 제거하고 '금소법' 별칭을
    '금융소비자보호에관한법률' 로 전개하므로, 계열 키워드도 공백 없는
    정규화 형태로 비교한다.
    """
    text = canonical_article(article).replace(" ", "")
    if "공정화" in text and "광고" in text:
        return FMLA_FAIR
    keys = [
        "금융소비자보호에관한법률",  # 금소법 본법 + 시행령(전개형)
        "금융소비자보호감독규정",
        "금융소비자보호에관한감독규정",
        "은행광고심의기준",
        "은행연합회",
    ]
    if any(k in text for k in keys):
        return FMLA_ADSCOPE
    return text  # 그 외는 원문 유지


# 사례별 취지 키워드(적중 판정용) + 유형 버킷
CASE_META: dict[str, dict[str, Any]] = {
    "reg_guideline_p16_case1_apt_loan_rate": {
        "type": "이자율(필수고지)",
        "intent_keywords": ["산출기준", "이자율의 범위", "금리 범위", "대출금리 범위", "범위 및 산출"],
        "disclosure_keywords": ["대출금리 범위", "이자율", "산출기준"],
    },
    "reg_guideline_p16_case2_universal_scope": {
        "type": "적용범위/조건오인",
        "intent_keywords": ["누구에게나", "조건", "적용", "대상", "자격", "오인", "제한"],
        "disclosure_keywords": ["대상", "자격", "조건"],
    },
    "reg_guideline_p16_case3_savings_insurance_mislead": {
        "type": "상품성격오인(보험)",
        "intent_keywords": ["종신", "저축성", "보장성", "목돈", "상품 성격", "오인", "보험"],
        "disclosure_keywords": ["보험", "보장성"],
    },
    "reg_guideline_p16_case4_fintech_child_savings": {
        "type": "이자율/수익률오인",
        "intent_keywords": ["선불충전", "이자", "금리", "제휴", "핀테크", "혜택", "오인", "최대"],
        "disclosure_keywords": ["금리", "이자율"],
    },
}


def pred_evidence_text(pred: dict[str, Any]) -> str:
    """검출 근거 텍스트 전체를 취지 키워드 매칭용으로 합친다."""
    parts: list[str] = []
    for it in pred.get("detected_issues") or []:
        for k in ("risk_title", "constraint", "rationale", "problem_span"):
            if it.get(k):
                parts.append(str(it[k]))
    for it in pred.get("disclosure_requirements") or []:
        for k in ("label", "why"):
            if it.get(k):
                parts.append(str(it[k]))
    for it in pred.get("revision_suggestions") or []:
        if it.get("why_problematic"):
            parts.append(str(it["why_problematic"]))
        for d in it.get("required_disclosures") or []:
            parts.append(str(d))
    for it in pred.get("article_aggregation") or []:
        for t in it.get("cu_titles") or []:
            parts.append(str(t))
    oi = pred.get("overall_impression_judgment") or {}
    for k in ("why", "representative_consumer_impression"):
        if oi.get(k):
            parts.append(str(oi[k]))
    return " \n".join(parts)


def pred_articles(pred: dict[str, Any]) -> list[str]:
    arts: set[str] = set()
    for it in pred.get("detected_issues") or []:
        if it.get("source_article"):
            arts.add(str(it["source_article"]).strip())
    for it in pred.get("article_aggregation") or []:
        if it.get("article"):
            arts.add(str(it["article"]).strip())
    return sorted(a for a in arts if a)


def classify(case: dict[str, Any], pred: dict[str, Any] | None) -> dict[str, Any]:
    cid = case["id"]
    meta = CASE_META.get(cid, {"type": "기타", "intent_keywords": [], "disclosure_keywords": []})
    gold_articles = list((case.get("labels") or {}).get("articles") or [])
    gold_families = {article_family(a) for a in gold_articles}

    if pred is None:
        return {
            "id": cid, "type": meta["type"], "status": "누락(예측없음)",
            "gold_verdict": "violation", "pred_verdict": "MISSING",
            "gold_articles": gold_articles, "pred_article_families": [],
            "matched_families": [], "extra_families": [],
            "intent_matched": False, "note": "예측 레코드 없음(실행 실패)",
        }

    final_verdict = str(pred.get("final_verdict") or "")
    predicted_violation = final_verdict in {"reject", "revise"}
    p_articles = pred_articles(pred)
    p_families = {article_family(a) for a in p_articles}
    matched_families = sorted(gold_families & p_families)
    extra_families = sorted(p_families - gold_families)

    ev = pred_evidence_text(pred)
    intent_matched = any(kw in ev for kw in meta["intent_keywords"])

    surfaced = intent_matched or bool(matched_families)
    if predicted_violation:
        # revise/reject = 서비스가 위반으로 확정 판정
        if intent_matched:
            status = "적중"          # 지적 취지와 동일한 원칙/조문 계열 검출
        elif matched_families:
            status = "부분"          # 위반은 잡았으나 취지 불일치(조문계열만 겹침)
        else:
            status = "부분"          # 위반은 잡았으나 취지·조문 모두 불일치
    elif final_verdict == "needs_review" and surfaced:
        # 관련 이슈는 검출했으나 확정 판정을 인간 심사로 유보 → 부분
        status = "부분(needs_review)"
    else:
        status = "누락"             # 지적사항을 검출하지 못함

    return {
        "id": cid, "type": meta["type"], "status": status,
        "gold_verdict": "violation",
        "pred_verdict": final_verdict,
        "gold_articles": gold_articles,
        "pred_article_families": sorted(p_families),
        "matched_families": matched_families,
        "extra_families": extra_families,
        "intent_matched": intent_matched,
        "note": "",
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, default=Path("eval/regulator_cases_full.jsonl"))
    ap.add_argument("--predictions", type=Path, default=Path("eval/regulator_predictions_vlm_full.jsonl"))
    ap.add_argument("--md-out", type=Path, default=Path("eval/guideline_vlm_report.md"))
    ap.add_argument("--csv-out", type=Path, default=Path("eval/guideline_vlm_report.csv"))
    args = ap.parse_args()

    cases = load_jsonl(args.cases)
    preds_raw = load_jsonl(args.predictions) if args.predictions.exists() else []
    preds = {str(p.get("dataset_item_id") or p.get("id") or ""): p for p in preds_raw}

    rows = [classify(c, preds.get(c["id"])) for c in cases]

    hit = sum(1 for r in rows if r["status"] == "적중")
    part = sum(1 for r in rows if r["status"].startswith("부분"))
    miss = sum(1 for r in rows if r["status"].startswith("누락"))
    total = len(rows)

    # 유형별 적중
    by_type: dict[str, dict[str, int]] = {}
    for r in rows:
        b = by_type.setdefault(r["type"], {"적중": 0, "부분": 0, "누락": 0, "total": 0})
        b["total"] += 1
        if r["status"] == "적중":
            b["적중"] += 1
        elif r["status"].startswith("부분"):
            b["부분"] += 1
        else:
            b["누락"] += 1

    # CSV
    with args.csv_out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "유형", "판정", "gold_verdict", "pred_verdict",
                    "gold_articles", "pred_article_families", "matched_families",
                    "extra_detections", "intent_matched", "note"])
        for r in rows:
            w.writerow([
                r["id"], r["type"], r["status"], r["gold_verdict"], r["pred_verdict"],
                " | ".join(r["gold_articles"]), " | ".join(r["pred_article_families"]),
                " | ".join(r["matched_families"]), " | ".join(r["extra_families"]),
                r["intent_matched"], r["note"],
            ])

    # Markdown
    lines: list[str] = []
    lines.append("# 금융광고규제 가이드라인 판단사례 대조 보고서 (VLM 전사 정답셋)")
    lines.append("")
    lines.append(f"- 정답 사례: **{total}건** (참고3 광고 위법여부 판단사례 전수)")
    lines.append(f"- 예측 레코드: **{len(preds_raw)}건**")
    lines.append(f"- 적중률: **{hit}/{total} = {hit/total*100:.0f}%** (적중), 부분 {part}, 누락 {miss}")
    lines.append("")
    lines.append("## 요약 지표")
    lines.append("")
    lines.append("| 지표 | 값 |")
    lines.append("|------|-----|")
    lines.append(f"| 사례 적중률(적중) | {hit}/{total} ({hit/total*100:.0f}%) |")
    lines.append(f"| 위반 검출률(적중+부분) | {hit+part}/{total} ({(hit+part)/total*100:.0f}%) |")
    lines.append(f"| 누락 | {miss}/{total} |")
    lines.append("")
    lines.append("## 유형별 적중")
    lines.append("")
    lines.append("| 유형 | 적중 | 부분 | 누락 | 계 |")
    lines.append("|------|------|------|------|----|")
    for t, b in by_type.items():
        lines.append(f"| {t} | {b['적중']} | {b['부분']} | {b['누락']} | {b['total']} |")
    lines.append("")
    lines.append("## 사례별 대조")
    lines.append("")
    lines.append("| id | 유형 | 판정 | pred_verdict | 취지일치 | 매칭 조문계열 | 추가 검출 |")
    lines.append("|----|------|------|--------------|----------|----------------|-----------|")
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['type']} | {r['status']} | {r['pred_verdict']} | "
            f"{'O' if r['intent_matched'] else 'X'} | "
            f"{', '.join(r['matched_families']) or '-'} | "
            f"{', '.join(r['extra_families']) or '-'} |"
        )
    lines.append("")
    lines.append("### 상세")
    lines.append("")
    for c, r in zip(cases, rows):
        gf = (c.get("facts") or {}).get("gold_finding") or ""
        lines.append(f"#### {r['id']} — {r['status']}")
        lines.append(f"- 광고문안: {c.get('text','')}")
        lines.append(f"- 규제 지적(gold_finding): {gf}")
        lines.append(f"- gold 조문: {' | '.join(r['gold_articles']) or '-'}")
        lines.append(f"- 서비스 verdict: {r['pred_verdict']} / 취지일치={r['intent_matched']}")
        lines.append(f"- 매칭 조문계열: {', '.join(r['matched_families']) or '-'}")
        lines.append(f"- 추가 검출 조문계열(오탐 단정 금지): {', '.join(r['extra_families']) or '-'}")
        lines.append("")

    args.md_out.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "total": total, "hit": hit, "partial": part, "miss": miss,
        "by_type": by_type,
        "md": str(args.md_out), "csv": str(args.csv_out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
