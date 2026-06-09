# GraphCompliance CCG

LLM-only Policy-Guided Context Engineering app for Korean financial-ad pre-review.

For the current implementation state, Neo4j graph counts, operating commands,
quality guardrails, and future goals, see
[docs/GRAPHCOMPLIANCE_CCG_HANDOFF.md](../../docs/GRAPHCOMPLIANCE_CCG_HANDOFF.md).

This app does not use deterministic review fallback. If `OPENAI_API_KEY` or Neo4j
credentials are missing, the run fails instead of silently replacing LLM context
engineering with rules.

## Run

```bash
export OPENAI_API_KEY="..."
export NEO4J_URI="neo4j+s://..."
export NEO4J_USER="..."
export NEO4J_PASSWORD="..."

PYTHONPATH=examples/graph-compliance-ccg \
python3 examples/graph-compliance-ccg/policy_compiler.py \
  --workspace-id graphcompliance_mvp_jb_20260530 \
  --batch-size 16

PYTHONPATH=examples/graph-compliance-ccg \
python3 examples/graph-compliance-ccg/vocabulary_governance.py \
  --workspace-id graphcompliance_mvp_jb_20260530 \
  --batch-size 40

PYTHONPATH=examples/graph-compliance-ccg \
python3 examples/graph-compliance-ccg/review_ad.py \
  --text "지난 3년간 조기상환 성공률이 높았던 ELS, 중위험 투자자에게 좋은 선택입니다."
```

The compiler creates the policy alignment layer:

```text
LegalClause/LegalChunk -> Premise -> PolicyHypernym
Premise -> ComplianceUnit -> CUEmbeddingProfile
ComplianceUnit -> HAS_SUBJECT_HYPERNYM -> PolicyHypernym
```

`LegalChunk` is evidence/provenance, not the primary CU retrieval engine.
Runtime candidate retrieval uses approved `PolicyHypernym` nodes, CU embedding
profiles, and overlap scoring before LLM rerank.

API:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
uvicorn server:app --app-dir examples/graph-compliance-ccg --port 8770
```

`POST /api/review` accepts:

```json
{
  "dataset_item_id": "demo_001",
  "title": "ELS 광고 초안",
  "content_text": "...",
  "channel": "bank_event_page_text",
  "source_type": "pre_review_draft",
  "product_group": "auto",
  "workspace_id": "graphcompliance_mvp_jb_20260530"
}
```

The response is compatible with the `team_share_v0_3` agent output shape and
adds `review_run_id`, `context_anchors`, `cu_plan`, `judgments`,
`exception_reviews`, `context_triples`, `graph_paths`, `highlight_spans`, and
`product_fact_context`.

JB dataset extensions add:

- `claims[].qualifiers` — expression-level modeling inside each Claim. Generic
  scope/certainty/guarantee wording such as `누구나`, `조건 없이`, `확정`, and
  `보장` stays inside the parent Claim as `ClaimQualifier` evidence instead of
  becoming a standalone target-consumer judgment anchor.
- `overall_impression_judgment` — Track B consumer-misleading review grounded in
  `Claim -> Meaning -> Implicature -> ConsumerEffect` paths and the overall
  impression standard.
- `product_context` — metadata grounding from the JB product disclosure manifest.
  This is not treated as extracted `DisclosureFact`; it identifies product
  groups, candidate products, and available product documents.
- `product_fact_context` — on-demand Product Fact Graph context. When one exact
  product name is resolved, the workflow reads the top product PDFs
  (`상품주요내용 > 상품설명서 > 약관`), extracts `ProductFact` evidence with
  structured LLM output, extracts advertising `ClaimFact`, and compares them as
  `SUPPORTED`, `CONTRADICTED`, `CONDITION_MISSING`, `NO_PRODUCT_FACT`, or
  `NEEDS_PRODUCT_SELECTION`. Ambiguous products stay in
  `NEEDS_PRODUCT_SELECTION`; the system does not invent missing product facts.
- `disclosure_requirements` — required-disclosure candidates from the bank ad
  review standards and financial-ad guideline, such as depositor protection,
  rate/condition basis, fees, and review-number display.
- `system_review_items[].risk_code` — CUPlan 0 diagnostics split into
  `NO_HYPERNYM_MATCH`, `MISSING_POLICY_COVERAGE`,
  `NO_ACTIVE_CU_AFTER_GATE`, and `RERANK_DROPPED_ALL`.

Track C expression/brand-safety risk is intentionally exposed as an extension
slot (`track_c_summary`) until a dedicated precedent/risk-pattern dataset is
loaded. It should not drive legal verdicts in this v1 path.

## Product Fact Graph

The Product Fact Graph is the demo path for fact-grounded compliance review:

```text
Claim -> ClaimFact -> Product -> ProductDocument -> ProductFact -> ComparisonResult
```

It is intentionally on-demand. The app does not pre-extract all 6,098 JB
product documents. It resolves the reviewed product from the ad text and JB
product metadata, reads only the selected PDF documents for that product, and
stores the extracted `ProductFact`, `ClaimFact`, and `ComparisonResult` nodes
under the current `review_run_id`.

Configure local disclosure data when it is outside the default Downloads path:

```bash
export JB_PRODUCT_DISCLOSURE_ROOT="/path/to/jbbank_product_disclosures_20260528"
export JB_PRODUCT_DISCLOSURE_METADATA_PATH="/path/to/jbbank_product_disclosures_metadata_20260528.csv"
```

## Evaluation

The evaluation harness follows the GraphCompliance paper's article-level
multi-label framing. Gold labels live in evaluation JSONL records and are not
sent to context extraction, CU retrieval, LLM judgment, exception override, or
revision prompts.

Smoke dataset:

```bash
cat examples/graph-compliance-ccg/eval/smoke_financial_ad_review.jsonl
```

Red-team recall dataset converted from the Korean financial-ad violation DOCX:

```bash
cat examples/graph-compliance-ccg/eval/redteam_korean_financial_ad_12.jsonl
```

Dataset card:

```bash
open examples/graph-compliance-ccg/eval/DATASET_CARD.md
```

Evaluate saved review outputs:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
python3 examples/graph-compliance-ccg/evaluate.py \
  --input examples/graph-compliance-ccg/eval/smoke_financial_ad_review.jsonl \
  --predictions output/ccg_predictions.jsonl
```

Run live reviews and evaluate in one pass:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
python3 examples/graph-compliance-ccg/evaluate.py \
  --input examples/graph-compliance-ccg/eval/smoke_financial_ad_review.jsonl \
  --run-live \
  --output output/ccg_eval_report.json
```

For red-team regression, use the DOCX-derived fixture instead:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
python3 examples/graph-compliance-ccg/evaluate.py \
  --input examples/graph-compliance-ccg/eval/redteam_korean_financial_ad_12.jsonl \
  --run-live \
  --output output/ccg_redteam_eval_report.json
```

Reported metrics:

- `micro_f1`, `macro_f1`, `micro_f2`, `macro_f2`, and `mcc` over the
  article-by-scenario matrix.
- `cuplan_recall`, `evidence_grounding_rate`, `cu0_rate`,
  `overblocking_rate`, `exception_sanity_rate`, and
  `average_context_triples` for CCG-specific diagnostics.

## Create Context Graph ontology

`financial-compliance-ad-review.yaml` is a manual CCG ontology/scaffold
contract. It defines stable entity, relationship, visualization, and read-only
agent-tool shapes. Individual policy terms such as "과거성과표시" or
"파생결합증권" are not YAML enums; they are governed as Neo4j
`PolicyHypernym` nodes produced by the policy compiler.

`vocabulary_governance.py` canonicalizes generated `PolicyHypernym` names into
Korean regulatory labels while preserving original labels in `aliases`. Runtime
normalization uses `canonical_name_ko` when present.
