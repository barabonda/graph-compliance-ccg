"""합성 gold 평가의 유형별·상품군별 정밀도·재현율 분해 리포트.

evaluate.py의 레코드 로딩·예측 요약을 재사용한다. 각 위반 레코드의
``facts.injected_violation_code``를 택소노미 ``type``으로 매핑해 유형별 재현율을,
상품군(deposit/loan)별로 정밀도·재현율을 계산한다. 클린·하드케이스(대조군)는
violation=false이므로 정밀도(오탐)의 근거가 된다.

gold 라벨은 이미 생성 시점에 확정돼 있고, 이 스크립트는 예측(라이브 심사 결과)과
대조만 한다 — 자기충족 평가가 되지 않도록 검출 코드를 참조하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluate import (  # noqa: E402
    EvaluationRecord,
    load_predictions,
    load_records,
    summarize_prediction,
)


def code_to_type(taxonomy_path: Path) -> dict[str, str]:
    tax = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    return {str(c["code"]): str(c.get("type") or "기타") for c in tax.get("codes", [])}


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def build(
    records: list[EvaluationRecord],
    predictions: dict[str, dict[str, Any]],
    code_type: dict[str, str],
) -> dict[str, Any]:
    overall_tp = overall_fp = overall_fn = overall_tn = 0
    per_type: dict[str, dict[str, int]] = {}
    per_group: dict[str, dict[str, int]] = {}

    for record in records:
        summary = summarize_prediction(record.record_id, predictions.get(record.record_id))
        gold = record.labels.violation
        pred = summary.predicted_violation
        group = record.product_group or "auto"
        per_group.setdefault(group, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        if gold and pred:
            overall_tp += 1
            per_group[group]["tp"] += 1
        elif not gold and pred:
            overall_fp += 1
            per_group[group]["fp"] += 1
        elif gold and not pred:
            overall_fn += 1
            per_group[group]["fn"] += 1
        else:
            overall_tn += 1
            per_group[group]["tn"] += 1

        if gold:
            code = str(record.facts.get("injected_violation_code") or "")
            vtype = code_type.get(code, "기타")
            bucket = per_type.setdefault(vtype, {"tp": 0, "fn": 0})
            if pred:
                bucket["tp"] += 1
            else:
                bucket["fn"] += 1

    return {
        "record_count": len(records),
        "overall": {
            "counts": {"tp": overall_tp, "fp": overall_fp, "fn": overall_fn, "tn": overall_tn},
            **_prf(overall_tp, overall_fp, overall_fn),
        },
        "per_violation_type_recall": {
            vtype: {
                "mutations": b["tp"] + b["fn"],
                "detected": b["tp"],
                "recall": round(b["tp"] / (b["tp"] + b["fn"]), 4) if (b["tp"] + b["fn"]) else 0.0,
            }
            for vtype, b in sorted(per_type.items())
        },
        "per_product_group": {
            group: {"counts": b, **_prf(b["tp"], b["fp"], b["fn"])}
            for group, b in sorted(per_group.items())
        },
    }


def to_markdown(report: dict[str, Any], *, title: str) -> str:
    o = report["overall"]
    lines = [
        f"# {title}",
        "",
        f"- 총 레코드: **{report['record_count']}**",
        f"- 전체 위반 판정 — 정밀도 **{o['precision']:.3f}** · 재현율 **{o['recall']:.3f}** · F1 **{o['f1']:.3f}**",
        f"- counts: TP {o['counts']['tp']} / FP {o['counts']['fp']} / FN {o['counts']['fn']} / TN {o['counts']['tn']}",
        "",
        "## 위반 유형별 재현율 (변이 레코드)",
        "",
        "| 유형 | 변이 수 | 검출 | 재현율 |",
        "|------|--------:|-----:|-------:|",
    ]
    for vtype, b in report["per_violation_type_recall"].items():
        lines.append(f"| {vtype} | {b['mutations']} | {b['detected']} | {b['recall']:.3f} |")
    lines += [
        "",
        "## 상품군별 정밀도·재현율",
        "",
        "| 상품군 | TP | FP | FN | TN | 정밀도 | 재현율 | F1 |",
        "|--------|---:|---:|---:|---:|-------:|-------:|---:|",
    ]
    for group, b in report["per_product_group"].items():
        c = b["counts"]
        lines.append(
            f"| {group} | {c['tp']} | {c['fp']} | {c['fn']} | {c['tn']} | "
            f"{b['precision']:.3f} | {b['recall']:.3f} | {b['f1']:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, default=Path(__file__).resolve().parent / "violation_taxonomy_v0_2.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "synth_v0_2_report.md")
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--title", default="합성 v0.2 평가 — 유형별·상품군별 정밀도·재현율")
    args = parser.parse_args()

    records = load_records(args.records)
    predictions = load_predictions(args.predictions)
    report = build(records, predictions, code_to_type(args.taxonomy))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(to_markdown(report, title=args.title), encoding="utf-8")
    if args.json_output:
        args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["overall"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
