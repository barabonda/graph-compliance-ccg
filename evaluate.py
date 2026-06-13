"""Evaluation harness for GraphCompliance CCG review outputs.

The evaluator intentionally keeps gold labels outside the review workflow.
It consumes either saved review outputs or, when explicitly requested, runs the
live workflow and evaluates only after predictions are produced.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from env_loader import load_local_env


RiskLevel = Literal["low", "medium", "high"]
FAILURE_CODES = {
    "NO_HYPERNYM_MATCH",
    "NO_ACTIVE_CU_AFTER_GATE",
    "RERANK_DROPPED_ALL",
    "MISSING_POLICY_COVERAGE",
    "CU_PLAN_EMPTY",
}
RISKY_VERDICTS = {"NON_COMPLIANT", "INSUFFICIENT"}
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluationLabels:
    violation: bool = False
    violation_types: list[str] = field(default_factory=list)
    articles: list[str] = field(default_factory=list)
    sales_principles: list[str] = field(default_factory=list)
    required_disclosures: list[str] = field(default_factory=list)
    risk_level: RiskLevel = "low"
    expected_routing: str = ""
    review_basis: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvaluationRecord:
    record_id: str
    text: str
    facts: dict[str, Any] = field(default_factory=dict)
    product_group: str = "auto"
    channel: str = "bank_event_page_text"
    language: str = "ko"
    labels: EvaluationLabels = field(default_factory=EvaluationLabels)
    title: str = ""
    source_type: str = "synthetic_eval"


@dataclass(frozen=True)
class PredictionSummary:
    record_id: str
    predicted_articles: list[str]
    predicted_violation: bool
    predicted_violation_types: list[str]
    predicted_sales_principles: list[str]
    predicted_required_disclosures: list[str]
    predicted_risk_level: RiskLevel
    predicted_routing: str
    cu_plan_count: int
    context_triple_count: int
    has_policy_evidence: bool
    has_cu0_failure: bool


def record_from_json(obj: dict[str, Any]) -> EvaluationRecord:
    labels = obj.get("labels") or {}
    return EvaluationRecord(
        record_id=str(obj.get("id") or obj.get("record_id") or obj.get("dataset_item_id") or ""),
        title=str(obj.get("title") or ""),
        text=str(obj.get("text") or obj.get("content_text") or ""),
        facts=dict(obj.get("facts") or {}),
        product_group=str(obj.get("product_group") or "auto"),
        channel=str(obj.get("channel") or "bank_event_page_text"),
        language=str(obj.get("language") or "ko"),
        source_type=str(obj.get("source_type") or "synthetic_eval"),
        labels=EvaluationLabels(
            violation=bool(labels.get("violation", False)),
            violation_types=list_of_str(labels.get("violation_types")),
            articles=list_of_str(labels.get("articles")),
            sales_principles=list_of_str(labels.get("sales_principles")),
            required_disclosures=list_of_str(labels.get("required_disclosures")),
            risk_level=normalize_risk_level(str(labels.get("risk_level") or "low")),
            expected_routing=str(labels.get("expected_routing") or ""),
            review_basis=list_of_str(labels.get("review_basis")),
        ),
    )


def review_payload_for_record(record: EvaluationRecord, *, workspace_id: str) -> dict[str, Any]:
    """Build review input while deliberately excluding gold labels and fact values."""
    selected_product_name = str(record.facts.get("product_name") or "").strip()
    return {
        "dataset_item_id": record.record_id,
        "title": record.title,
        "content_text": record.text,
        "channel": record.channel,
        "source_type": record.source_type,
        "product_group": record.product_group,
        "selected_product_name": selected_product_name,
        "workspace_id": workspace_id,
    }


def summarize_prediction(record_id: str, output: dict[str, Any] | None) -> PredictionSummary:
    output = output or {}
    plan = list(output.get("cu_plan") or [])
    judgments = list(output.get("effective_judgments") or output.get("judgments") or [])
    judgment_by_plan = {item.get("plan_item_id"): item for item in judgments}
    risky_plan_items = [
        item
        for item in plan
        if str(judgment_by_plan.get(item.get("plan_item_id"), {}).get("verdict") or "") in RISKY_VERDICTS
    ]
    predicted_articles = sorted(
        {
            str(item.get("source_article") or "").strip()
            for item in risky_plan_items
            if str(item.get("source_article") or "").strip()
        }
        | {
            # 하위 규정 인용 시 router가 병기한 모법 조문 (legal_hierarchy 참조)
            str(parent).strip()
            for item in risky_plan_items
            for parent in item.get("parent_articles") or []
            if str(parent).strip()
        }
    )
    predicted_sales_principles = sorted(
        {
            str(item.get("principle") or "").strip()
            for item in risky_plan_items
            if str(item.get("principle") or "").strip()
        }
    )
    predicted_violation_types = sorted(
        {
            str(item.get("cu_id") or item.get("risk_code") or "").strip()
            for item in output.get("detected_issues", [])
            if str(item.get("cu_id") or item.get("risk_code") or "").strip()
        }
    )
    predicted_required_disclosures = sorted(
        {
            str(item.get("label") or item.get("name") or "").strip()
            for item in output.get("disclosure_requirements", [])
            if str(item.get("label") or item.get("name") or "").strip()
        }
    )
    final_verdict = str(output.get("final_verdict") or "needs_review")
    return PredictionSummary(
        record_id=record_id,
        predicted_articles=predicted_articles,
        # needs_review routes to a human and must not count as a violation call;
        # cited articles alone are context, not a verdict.
        predicted_violation=final_verdict in {"reject", "revise"},
        predicted_violation_types=predicted_violation_types,
        predicted_sales_principles=predicted_sales_principles,
        predicted_required_disclosures=predicted_required_disclosures,
        predicted_risk_level=risk_level_from_output(output),
        predicted_routing=final_verdict,
        cu_plan_count=len(plan),
        context_triple_count=len(output.get("context_triples") or []),
        has_policy_evidence=prediction_has_policy_evidence(output),
        has_cu0_failure=prediction_has_cu0_failure(output),
    )


def evaluate_records(records: list[EvaluationRecord], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    summaries = [summarize_prediction(record.record_id, predictions.get(record.record_id)) for record in records]
    gold_article_sets = [set(canonical_article(item) for item in record.labels.articles if item) for record in records]
    pred_article_sets = [set(canonical_article(item) for item in summary.predicted_articles if item) for summary in summaries]
    article_metrics = multilabel_metrics(gold_article_sets, pred_article_sets)
    return {
        "record_count": len(records),
        "article_metrics": article_metrics,
        "ccg_metrics": ccg_metrics(records, summaries, gold_article_sets, pred_article_sets),
        "records": [
            {
                "id": record.record_id,
                "gold": {
                    "violation": record.labels.violation,
                    "articles": record.labels.articles,
                    "risk_level": record.labels.risk_level,
                    "expected_routing": record.labels.expected_routing,
                },
                "prediction": summary.__dict__,
            }
            for record, summary in zip(records, summaries, strict=True)
        ],
    }


def multilabel_metrics(gold_sets: list[set[str]], pred_sets: list[set[str]]) -> dict[str, Any]:
    universe = sorted(set().union(*gold_sets, *pred_sets)) if gold_sets or pred_sets else []
    total_tp = total_fp = total_fn = total_tn = 0
    per_article: dict[str, dict[str, float | int]] = {}
    for article in universe:
        tp = fp = fn = tn = 0
        for gold, pred in zip(gold_sets, pred_sets, strict=True):
            in_gold = article in gold
            in_pred = article in pred
            if in_gold and in_pred:
                tp += 1
            elif not in_gold and in_pred:
                fp += 1
            elif in_gold and not in_pred:
                fn += 1
            else:
                tn += 1
        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_tn += tn
        per_article[article] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "f1": fbeta(tp, fp, fn, beta=1.0),
            "f2": fbeta(tp, fp, fn, beta=2.0),
        }
    macro_f1 = mean([float(row["f1"]) for row in per_article.values()])
    macro_f2 = mean([float(row["f2"]) for row in per_article.values()])
    return {
        "article_universe_size": len(universe),
        "micro_f1": fbeta(total_tp, total_fp, total_fn, beta=1.0),
        "macro_f1": macro_f1,
        "micro_f2": fbeta(total_tp, total_fp, total_fn, beta=2.0),
        "macro_f2": macro_f2,
        "mcc": matthews_corrcoef(total_tp, total_fp, total_fn, total_tn),
        "counts": {"tp": total_tp, "fp": total_fp, "fn": total_fn, "tn": total_tn},
        "per_article": per_article,
    }


def ccg_metrics(
    records: list[EvaluationRecord],
    summaries: list[PredictionSummary],
    gold_article_sets: list[set[str]],
    pred_article_sets: list[set[str]],
) -> dict[str, Any]:
    risky_gold_indexes = [index for index, gold in enumerate(gold_article_sets) if gold]
    cuplan_hits = [
        bool(gold_article_sets[index] & pred_article_sets[index])
        for index in risky_gold_indexes
    ]
    risky_predictions = [summary for summary in summaries if summary.predicted_violation]
    normal_records = [
        (record, summary)
        for record, summary in zip(records, summaries, strict=True)
        if not record.labels.violation
    ]
    exception_records = [
        (record, summary)
        for record, summary in normal_records
        if "예금자보호" in record.text or "예금자보호" in " ".join(record.labels.required_disclosures)
    ]
    violation_tp = sum(1 for r, s in zip(records, summaries, strict=True) if r.labels.violation and s.predicted_violation)
    violation_fp = sum(1 for r, s in zip(records, summaries, strict=True) if not r.labels.violation and s.predicted_violation)
    violation_fn = sum(1 for r, s in zip(records, summaries, strict=True) if r.labels.violation and not s.predicted_violation)
    return {
        "cuplan_recall": ratio(sum(cuplan_hits), len(cuplan_hits)),
        "violation_precision": ratio(violation_tp, violation_tp + violation_fp),
        "violation_recall": ratio(violation_tp, violation_tp + violation_fn),
        "evidence_grounding_rate": ratio(
            sum(1 for summary in risky_predictions if summary.has_policy_evidence),
            len(risky_predictions),
        ),
        "cu0_rate": ratio(sum(1 for summary in summaries if summary.has_cu0_failure), len(summaries)),
        "overblocking_rate": ratio(
            sum(1 for _, summary in normal_records if summary.predicted_routing == "reject"),
            len(normal_records),
        ),
        # reject 외에도 클린 광고가 pass_candidate에 못 가면 soft 과차단이다.
        "clean_non_pass_rate": ratio(
            sum(1 for _, summary in normal_records if summary.predicted_routing != "pass_candidate"),
            len(normal_records),
        ),
        "exception_sanity_rate": ratio(
            sum(1 for _, summary in exception_records if summary.predicted_routing != "reject"),
            len(exception_records),
        ),
        "average_context_triples": ratio(sum(summary.context_triple_count for summary in summaries), len(summaries)),
    }


def fbeta(tp: int, fp: int, fn: int, *, beta: float) -> float:
    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    beta_squared = beta * beta
    denominator = (beta_squared * precision) + recall
    if denominator == 0:
        return 0.0
    return ((1 + beta_squared) * precision * recall) / denominator


def matthews_corrcoef(tp: int, fp: int, fn: int, tn: int) -> float:
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denominator == 0:
        return 0.0
    return ((tp * tn) - (fp * fn)) / denominator


def prediction_has_policy_evidence(output: dict[str, Any]) -> bool:
    for judgment in output.get("effective_judgments") or output.get("judgments") or []:
        if judgment.get("used_policy_evidence"):
            return True
    for item in output.get("cu_plan") or []:
        if item.get("legal_evidence_ids") or item.get("evidence_texts"):
            return True
    return False


def prediction_has_cu0_failure(output: dict[str, Any]) -> bool:
    for item in output.get("system_review_items") or []:
        if str(item.get("risk_code") or "") in FAILURE_CODES:
            return True
    for item in (output.get("anchor_display") or []):
        if str(item.get("retrieval_failure_code") or "") in FAILURE_CODES:
            return True
    return False


def risk_level_from_output(output: dict[str, Any]) -> RiskLevel:
    final = str(output.get("final_verdict") or "")
    if final == "reject":
        return "high"
    if final == "revise":
        return "medium"
    if final == "needs_review":
        return "medium"
    return "low"


def normalize_risk_level(value: str) -> RiskLevel:
    value = value.strip().lower()
    if value in {"high", "medium", "low"}:
        return value  # type: ignore[return-value]
    return "low"


def normalize_label(value: str) -> str:
    return "".join(str(value).lower().split())


# Gold labels and model citations name the same statute differently (금소법 vs
# 금융소비자보호에 관한 법률) and at different granularity (조 vs 호·목). Match
# at the statute+조 level so neither difference produces a spurious mismatch.
LAW_ALIASES = [
    ("금소법", "금융소비자보호에관한법률"),
    ("금융소비자보호법", "금융소비자보호에관한법률"),
    ("표시광고법", "표시ㆍ광고의공정화에관한법률"),
    ("표시·광고의공정화에관한법률", "표시ㆍ광고의공정화에관한법률"),
]
ARTICLE_RE = re.compile(r"제\d+조(의\d+)?")


def canonical_article(value: str) -> str:
    text = normalize_label(value)
    for alias, full in LAW_ALIASES:
        if text.startswith(alias) and not text.startswith(full):
            text = full + text[len(alias):]
            break
    match = ARTICLE_RE.search(text)
    if match:
        text = text[: match.end()]
    return text


def list_of_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def mean(values: list[float]) -> float:
    return ratio(sum(values), len(values))


def load_records(path: Path) -> list[EvaluationRecord]:
    return [record_from_json(item) for item in load_json_records(path)]


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    for item in load_json_records(path):
        record_id = str(item.get("dataset_item_id") or item.get("id") or item.get("record_id") or "")
        if not record_id:
            raise ValueError(f"Prediction record missing dataset_item_id/id: {item}")
        predictions[record_id] = item
    return predictions


def load_json_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("records"), list):
        return list(data["records"])
    if isinstance(data, dict) and isinstance(data.get("predictions"), list):
        return list(data["predictions"])
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"Unsupported JSON structure in {path}")


def run_live_predictions(
    records: list[EvaluationRecord],
    *,
    workspace_id: str,
    workers: int = 1,
    save_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text("", encoding="utf-8")
    if workers <= 1:
        return run_live_predictions_sequential(records, workspace_id=workspace_id, save_path=save_path)
    predictions: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_by_id = {
            executor.submit(run_one_live_prediction, record, workspace_id): record.record_id
            for record in records
        }
        completed = 0
        for future in as_completed(future_by_id):
            record_id = future_by_id[future]
            completed += 1
            try:
                predictions[record_id] = future.result()
                LOGGER.info("Reviewed %s/%s: %s", completed, len(records), record_id)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Live review failed for %s", record_id)
                predictions[record_id] = error_prediction(record_id, exc)
            if save_path:
                append_prediction_jsonl(save_path, record_id, predictions[record_id])
    return predictions


def run_live_predictions_sequential(
    records: list[EvaluationRecord],
    *,
    workspace_id: str,
    save_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    from utils import to_jsonable
    from workflow import GraphComplianceCCGWorkflow, review_input_from_payload

    workflow = GraphComplianceCCGWorkflow()
    predictions: dict[str, dict[str, Any]] = {}
    for record in records:
        payload = review_payload_for_record(record, workspace_id=workspace_id)
        output = workflow.review(review_input_from_payload(payload))
        predictions[record.record_id] = to_jsonable(output)
        if save_path:
            append_prediction_jsonl(save_path, record.record_id, predictions[record.record_id])
    return predictions


def run_one_live_prediction(record: EvaluationRecord, workspace_id: str) -> dict[str, Any]:
    from utils import to_jsonable
    from workflow import GraphComplianceCCGWorkflow, review_input_from_payload

    payload = review_payload_for_record(record, workspace_id=workspace_id)
    output = GraphComplianceCCGWorkflow().review(review_input_from_payload(payload))
    return to_jsonable(output)


def error_prediction(record_id: str, exc: Exception) -> dict[str, Any]:
    return {
        "dataset_item_id": record_id,
        "final_verdict": "needs_review",
        "routing": {"error": True},
        "detected_issues": [
            {
                "risk_code": "LIVE_REVIEW_ERROR",
                "severity": "HIGH",
                "problem_span": "",
                "rationale": str(exc),
                "required_action": "라이브 평가 실패 원인을 확인하고 재실행하세요.",
            }
        ],
        "post_approval_required_actions": [],
        "rationale": f"Live review failed: {exc}",
        "review_run_id": "",
        "cu_plan": [],
        "effective_judgments": [],
        "judgments": [],
        "context_triples": [],
        "system_review_items": [{"risk_code": "LIVE_REVIEW_ERROR", "message": str(exc)}],
    }


def write_predictions_jsonl(path: Path, predictions: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record_id in sorted(predictions):
            row = predictions[record_id]
            if not row.get("dataset_item_id"):
                row = {"dataset_item_id": record_id, **row}
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_prediction_jsonl(path: Path, record_id: str, prediction: dict[str, Any]) -> None:
    row = prediction
    if not row.get("dataset_item_id"):
        row = {"dataset_item_id": record_id, **row}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    load_local_env(Path.cwd() / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Evaluation JSONL/JSON records.")
    parser.add_argument("--predictions", type=Path, default=None, help="Saved review outputs JSONL/JSON.")
    parser.add_argument("--run-live", action="store_true", help="Run the live CCG workflow before evaluation.")
    parser.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    parser.add_argument("--workers", type=int, default=1, help="Parallel workers for --run-live. Keep small for OpenAI/Neo4j limits.")
    parser.add_argument("--start", type=int, default=0, help="Start offset for batch live evaluation.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum records to evaluate in this run.")
    parser.add_argument("--save-predictions", type=Path, default=None, help="Optional JSONL path to save live predictions before evaluation.")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    records = load_records(args.input)
    if args.start or args.limit is not None:
        records = records[args.start :]
        if args.limit is not None:
            records = records[: args.limit]
    if args.run_live:
        predictions = run_live_predictions(
            records,
            workspace_id=args.workspace_id,
            workers=args.workers,
            save_path=args.save_predictions,
        )
        if args.save_predictions:
            write_predictions_jsonl(args.save_predictions, predictions)
    elif args.predictions:
        predictions = load_predictions(args.predictions)
    else:
        raise SystemExit("--predictions or --run-live is required.")

    report = evaluate_records(records, predictions)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
