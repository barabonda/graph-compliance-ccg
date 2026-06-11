"""Quality report for ProductFact-grounded synthetic evaluation JSONL.

This script checks the generated dataset package, not model predictions. It is
intended to run after ``build_synthetic_eval_dataset.py`` and before using the
records as gold labels.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description="Report quality checks for synthetic ProductFact eval JSONL.")
    parser.add_argument("--input", required=True, help="Synthetic eval JSONL path.")
    parser.add_argument("--output", default="", help="Optional JSON report output path.")
    parser.add_argument("--fail-on-errors", action="store_true", help="Exit non-zero when blocking quality errors exist.")
    args = parser.parse_args()

    records = load_jsonl(Path(args.input))
    report = build_quality_report(records)
    print_report(report)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.fail_on_errors and report["blocking_error_count"]:
        raise SystemExit(1)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_no}: {exc}") from exc
    return records


def build_quality_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(record.get("id") or "") for record in records]
    duplicate_ids = sorted([record_id for record_id, count in Counter(ids).items() if count > 1 and record_id])
    source_type_counts = Counter(str(record.get("source_type") or "unknown") for record in records)
    product_group_counts = Counter(str(record.get("product_group") or "unknown") for record in records)
    channel_counts = Counter(str(record.get("channel") or "unknown") for record in records)
    violation_counts = Counter()
    risk_counts = Counter()
    routing_counts = Counter()

    span_errors: list[dict[str, Any]] = []
    product_fact_errors: list[dict[str, Any]] = []
    label_errors: list[dict[str, Any]] = []
    product_fact_total = 0
    source_document_total = 0
    mutation_count = 0
    hard_case_count = 0
    clean_count = 0

    for record in records:
        record_id = str(record.get("id") or "")
        text = str(record.get("text") or "")
        facts = record.get("facts") or {}
        labels = record.get("labels") or {}
        source_type = str(record.get("source_type") or "")
        violation_types = [str(item) for item in labels.get("violation_types") or []]
        expected_spans = [str(item) for item in facts.get("expected_problem_spans") or [] if str(item)]
        product_facts = facts.get("product_facts") or []
        source_documents = facts.get("source_product_documents") or []

        product_fact_total += len(product_facts)
        source_document_total += len(source_documents)
        for code in violation_types:
            violation_counts[code] += 1
        risk_counts[str(labels.get("risk_level") or "unknown")] += 1
        routing_counts[str(labels.get("expected_routing") or "unknown")] += 1
        if source_type == "synthetic_product_fact_clean":
            clean_count += 1
        elif source_type == "synthetic_product_fact_hard_case":
            hard_case_count += 1
        elif source_type == "synthetic_product_fact_mutation":
            mutation_count += 1

        if source_type == "synthetic_product_fact_mutation" and not expected_spans:
            span_errors.append({"record_id": record_id, "error": "MISSING_EXPECTED_PROBLEM_SPAN"})
        for span in expected_spans:
            if span not in text:
                span_errors.append({"record_id": record_id, "error": "SPAN_NOT_IN_TEXT", "span": span})

        if labels.get("violation") and not violation_types:
            label_errors.append({"record_id": record_id, "error": "VIOLATION_TRUE_WITHOUT_TYPES"})
        if not labels.get("violation") and violation_types:
            label_errors.append({"record_id": record_id, "error": "VIOLATION_FALSE_WITH_TYPES", "violation_types": violation_types})

        if not product_facts:
            product_fact_errors.append({"record_id": record_id, "error": "NO_PRODUCT_FACTS"})
        if not source_documents:
            product_fact_errors.append({"record_id": record_id, "error": "NO_SOURCE_DOCUMENTS"})
        known_doc_ids = {str(document.get("document_id") or "") for document in source_documents}
        for fact in product_facts:
            fact_id = str(fact.get("fact_id") or "")
            source_document_id = str(fact.get("source_document_id") or "")
            confidence = fact.get("confidence")
            if source_document_id not in known_doc_ids:
                product_fact_errors.append(
                    {
                        "record_id": record_id,
                        "fact_id": fact_id,
                        "error": "FACT_SOURCE_DOCUMENT_NOT_SELECTED",
                        "source_document_id": source_document_id,
                    }
                )
            if not str(fact.get("evidence_text") or "").strip():
                product_fact_errors.append({"record_id": record_id, "fact_id": fact_id, "error": "FACT_MISSING_EVIDENCE_TEXT"})
            if not isinstance(confidence, int | float) or confidence < 0 or confidence > 1:
                product_fact_errors.append({"record_id": record_id, "fact_id": fact_id, "error": "FACT_CONFIDENCE_OUT_OF_RANGE"})

    blocking_errors = [
        *({"category": "duplicate_id", "detail": duplicate_id} for duplicate_id in duplicate_ids),
        *({"category": "span", **error} for error in span_errors),
        *({"category": "product_fact", **error} for error in product_fact_errors),
        *({"category": "label", **error} for error in label_errors),
    ]
    return {
        "record_count": len(records),
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "product_group_counts": dict(sorted(product_group_counts.items())),
        "channel_counts": dict(sorted(channel_counts.items())),
        "violation_type_counts": dict(sorted(violation_counts.items())),
        "risk_level_counts": dict(sorted(risk_counts.items())),
        "expected_routing_counts": dict(sorted(routing_counts.items())),
        "clean_count": clean_count,
        "mutation_count": mutation_count,
        "hard_case_count": hard_case_count,
        "product_fact_total": product_fact_total,
        "source_document_total": source_document_total,
        "average_product_facts_per_record": round(product_fact_total / len(records), 2) if records else 0,
        "average_source_documents_per_record": round(source_document_total / len(records), 2) if records else 0,
        "duplicate_ids": duplicate_ids,
        "span_errors": span_errors,
        "product_fact_errors": product_fact_errors,
        "label_errors": label_errors,
        "blocking_error_count": len(blocking_errors),
        "blocking_errors": blocking_errors[:100],
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"records: {report['record_count']}")
    print(f"clean/mutation/hard_case: {report['clean_count']} / {report['mutation_count']} / {report['hard_case_count']}")
    print(f"avg product facts: {report['average_product_facts_per_record']}")
    print(f"avg source docs: {report['average_source_documents_per_record']}")
    print(f"source_type_counts: {json.dumps(report['source_type_counts'], ensure_ascii=False)}")
    print(f"product_group_counts: {json.dumps(report['product_group_counts'], ensure_ascii=False)}")
    print(f"channel_counts: {json.dumps(report['channel_counts'], ensure_ascii=False)}")
    print(f"violation_type_counts: {json.dumps(report['violation_type_counts'], ensure_ascii=False)}")
    print(f"risk_level_counts: {json.dumps(report['risk_level_counts'], ensure_ascii=False)}")
    print(f"expected_routing_counts: {json.dumps(report['expected_routing_counts'], ensure_ascii=False)}")
    print(f"blocking_errors: {report['blocking_error_count']}")
    for error in report["blocking_errors"][:10]:
        print(f"- {json.dumps(error, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
