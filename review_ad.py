"""CLI for the LLM-only GraphCompliance CCG reviewer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflow import GraphComplianceCCGWorkflow, review_input_from_payload
from utils import to_jsonable


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="", help="Advertising draft text.")
    parser.add_argument("--input-json", type=Path, default=None, help="JSON file with review payload.")
    parser.add_argument("--dataset-item-id", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--channel", default="bank_event_page_text")
    parser.add_argument("--source-type", default="")
    parser.add_argument("--product-group", default="auto")
    parser.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.input_json:
        payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    else:
        payload = {
            "dataset_item_id": args.dataset_item_id,
            "title": args.title,
            "content_text": args.text,
            "channel": args.channel,
            "source_type": args.source_type,
            "product_group": args.product_group,
            "workspace_id": args.workspace_id,
        }
    review_input = review_input_from_payload(payload)
    output = GraphComplianceCCGWorkflow().review(review_input)
    data = to_jsonable(output)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

