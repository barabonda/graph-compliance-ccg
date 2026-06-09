# GraphCompliance CCG Handoff

This document captures the current state, implementation context, operating
commands, Neo4j graph shape, and next goals for the GraphCompliance CCG
prototype.

## Summary

GraphCompliance CCG is an experimental Korean financial-ad compliance review
app under `examples/graph-compliance-ccg/`.

The core design follows the GraphCompliance paper shape:

```text
Policy Graph:
LegalClause / LegalChunk
  -> Premise
  -> PolicyHypernym
  -> ComplianceUnit
  -> CUEmbeddingProfile

Context Graph:
AdDraft
  -> Claim
  -> ContextAnchor
  -> PolicyHypernymProposal
  -> CUPlanItem
  -> LLMJudgment
  -> ExceptionReview
```

The important architectural correction is that `LegalChunk` is now evidence and
provenance, not the main candidate retrieval engine. Candidate CU retrieval is
based on governed `PolicyHypernym` vocabulary, CU embedding profiles, hypernym
overlap, and LLM reranking.

Runtime review is LLM-only. There is no deterministic fallback, no regex review
fallback, and no hardcoded compliance verdict path.

## Current Implementation

Main files:

| File | Purpose |
|---|---|
| `examples/graph-compliance-ccg/policy_compiler.py` | Offline compiler that reads Neo4j legal/CU sources and creates `Premise`, `PolicyHypernym`, `CUEmbeddingProfile`, and CU-hypernym links. |
| `examples/graph-compliance-ccg/vocabulary_governance.py` | Offline governance pass that canonicalizes generated `PolicyHypernym` labels into Korean regulatory labels and stores original labels in aliases. |
| `examples/graph-compliance-ccg/normalizer.py` | LLM policy-guided normalization. It can only select approved Neo4j `PolicyHypernym` ids. Unknown ids fail fast. |
| `examples/graph-compliance-ccg/retriever.py` | Neo4j candidate retrieval using `HAS_SUBJECT_HYPERNYM`, CU embedding profiles, vector similarity, and overlap scoring. |
| `examples/graph-compliance-ccg/planner.py` | LLM reranker that converts candidates into `CUPlanItem`s. |
| `examples/graph-compliance-ccg/judge.py` | LLM judge and exception override review. |
| `examples/graph-compliance-ccg/overall_impression.py` | Track B LLM judgment for consumer misleading risk, grounded in `Claim -> Meaning -> Implicature -> ConsumerEffect` paths. |
| `examples/graph-compliance-ccg/jb_data_context.py` | JB product metadata and required-disclosure context from the hackathon product/ad-review datasets. |
| `examples/graph-compliance-ccg/risk_context.py` | Track C expression/brand-safety extension contract. |
| `examples/graph-compliance-ccg/evaluate.py` | Article-level multi-label evaluation harness with CCG diagnostics. |
| `examples/graph-compliance-ccg/persistence.py` | Persists review runs and context/policy paths to Neo4j. |
| `examples/graph-compliance-ccg/financial-compliance-ad-review.yaml` | Manual Create Context Graph ontology/scaffold contract. |

The Create Context Graph YAML is used as a schema/scaffold/tool/visualization
contract. It is not the compliance engine. The compliance gate remains a custom
backend workflow.

## Neo4j State

Workspace:

```text
graphcompliance_mvp_jb_20260530
```

Current live alignment state after the latest compiler and vocabulary governance
run:

| Metric | Count |
|---|---:|
| `PolicyHypernym` | 212 |
| `Premise` | 317 |
| `CUEmbeddingProfile` | 448 |
| active `ComplianceUnit` | 374 |
| active CU with `HAS_SUBJECT_HYPERNYM` | 374 / 374 |
| `PolicyHypernym` with English or underscore `name` | 0 |
| `PolicyHypernym` without Hangul `name` | 0 |
| `PolicyHypernym` without governance | 0 |

Do not put Neo4j credentials in code or docs. Use only environment variables:

```bash
NEO4J_URI
NEO4J_USER
NEO4J_PASSWORD
OPENAI_API_KEY
```

## Operating Commands

Use the Conda Python that has `openai` and `neo4j` installed, or install the
same packages in your active environment.

Compile or resume the policy alignment layer:

```bash
set -a
source .env
set +a

PYTHONPATH=examples/graph-compliance-ccg \
/opt/anaconda3/bin/python examples/graph-compliance-ccg/policy_compiler.py \
  --workspace-id graphcompliance_mvp_jb_20260530 \
  --batch-size 16
```

If a run is interrupted or quota-limited, resume only missing active CU links:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
/opt/anaconda3/bin/python examples/graph-compliance-ccg/policy_compiler.py \
  --workspace-id graphcompliance_mvp_jb_20260530 \
  --batch-size 16 \
  --missing-active-links-only
```

Canonicalize the vocabulary into Korean labels:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
/opt/anaconda3/bin/python examples/graph-compliance-ccg/vocabulary_governance.py \
  --workspace-id graphcompliance_mvp_jb_20260530 \
  --batch-size 40
```

Run an ad review:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
/opt/anaconda3/bin/python examples/graph-compliance-ccg/review_ad.py \
  --dataset-item-id demo_els_001 \
  --text "지난 3년간 조기상환 성공률이 높았던 ELS, 중위험 투자자에게 좋은 선택입니다."
```

Run focused tests:

```bash
python3 -m py_compile examples/graph-compliance-ccg/*.py
PYTHONPATH=examples/graph-compliance-ccg pytest -q examples/graph-compliance-ccg/tests/test_workflow.py
python3 examples/graph-compliance/smoke_test.py
```

Run the synthetic smoke evaluation with saved predictions:

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

## Latest Smoke Result

After vocabulary governance, the ELS review smoke returned:

```text
final_verdict: revise
anchors: 5
cu_plan: 2
judgments: 2
issues: 1
hypernyms: 금융상품, 오도 광고, 광고 준수, 적합성 평가
```

This confirms the previous failure mode, `cu_plan=0 -> pass_candidate`, is no
longer present. Empty CU plans now route to `needs_review`.

## Quality Guardrails

Current safeguards:

- The compiler validates that every input active CU has exactly one CU profile.
- The compiler rejects undefined hypernym references.
- The compiler rejects English-only or snake_case hypernym labels.
- Vocabulary governance validates one output item for every input hypernym id.
- Runtime normalization rejects unknown `PolicyHypernym` ids.
- Runtime retrieval prefers `canonical_name_ko` when present.
- `cu_plan=0` becomes `needs_review`, not `pass_candidate`.
- `cu_plan=0` diagnostics are split into `NO_HYPERNYM_MATCH`,
  `MISSING_POLICY_COVERAGE`, `NO_ACTIVE_CU_AFTER_GATE`, and
  `RERANK_DROPPED_ALL`.
- Operational nodes such as sanctions, review procedures, review numbers, and
  association review workflow are kept out of normal CUPlan judgment and shown
  as disclosure/procedure context instead.
- Product metadata is treated as `ProductDocument` grounding and required
  disclosure hints only. It is not treated as verified `DisclosureFact` until PDF
  body extraction is implemented.
- Track B adds `overall_impression_judgment`, but remains grounded in context
  graph paths and selected disclosure/policy evidence instead of free-form LLM
  opinion.
- The local FastAPI server loads `.env` at startup, while library code still
  fails fast when required credentials are missing.
- CU rerank payloads are compacted before the LLM call so long LegalChunk or
  Premise text cannot overflow the model context window.

Known quality issue:

- Some canonical labels are now Korean but still semantically broad or duplicated,
  for example similar labels around `금융소비자 보호`, `부당권유 금지`, and
  `광고 준수`.
- Some ad-review standards still compile into broad `광고규제` CUs. The runtime
  now filters procedure/sanction-like candidates, but the next compiler pass
  should split operational procedure nodes from behavior-judgment CUs at source.
- Track B is intentionally conservative. Ads with explicit condition and
  depositor-protection disclosures may still route to `needs_review` when the
  condition details are not fully specified in the draft.
- Context Graph extraction now exposes first-class `context_triples` in the API
  response and Neo4j as audit evidence. These triples support anchoring and
  evaluation only; they are not deterministic verdict fallback.
- Evaluation uses article-level multi-label metrics (`micro_f1`, `macro_f1`,
  `micro_f2`, `macro_f2`, `mcc`) plus CCG diagnostics (`cuplan_recall`,
  `evidence_grounding_rate`, `cu0_rate`, `overblocking_rate`,
  `exception_sanity_rate`). Gold labels are excluded from review payloads.

This is expected for v0. The next governance pass should consolidate duplicate
`merge_key`s into a curated vocabulary while preserving old ids as aliases or
redirects.

## Future Goals

The near-term goal is to turn the working CCG prototype into a reviewable
operating demo for financial-ad pre-review.

Priority order:

1. JB dataset policy normalization
   - Recompile ad-review standards into separated `DisclosureRequirement`,
     `ProhibitedExpression`, `ReviewProcedure`, `ExceptionRule`, and
     `SanctionRule` nodes.
   - Keep only reviewable behavior requirements as `ComplianceUnit`.
   - Link `ComplianceUnit -> DisclosureRequirement -> ArticleClause` and
     `MetaCU -> GATES -> ComplianceUnit`.

2. Vocabulary consolidation
   - Group duplicate `PolicyHypernym.merge_key`s.
   - Decide canonical preferred labels for repeated concepts.
   - Add `SAME_AS` or `CANONICALIZES_TO` relationships instead of deleting old
     nodes.
   - Keep relation history stable for existing review runs.

3. Evidence-window quality
   - Reduce repeated full article text in `EvidenceWindow`.
   - Prefer concise `Premise` first, then `LegalClause`, then `LegalChunk`.
   - Cap long evidence text in API responses while keeping full evidence in Neo4j.

4. Retrieval quality evaluation
   - Expand the new synthetic smoke set into `team_share_v0_3` evaluation.
   - Keep gold labels out of prompts.
   - Track article-level F1/F2/MCC, CUPlan recall, evidence grounding,
     overblocking, CUPlan-0 rate, and exception sanity.
   - Add saved-prediction JSONL snapshots for regression comparisons.

5. Context Graph UI
   - Show the path:
     `Claim -> ContextAnchor -> PolicyHypernym -> CUPlanItem -> ComplianceUnit -> Premise -> LegalChunk`.
   - Show Track B path:
     `Claim -> Meaning -> Implicature -> ConsumerEffect -> OverallImpressionStandard`.
   - Show product grounding:
     `Claim -> Product -> ProductDocument -> RequiredDisclosure`.
   - Highlight non-compliant spans in the ad text.
   - Add a lens for `Policy Graph x Context Graph` and an exception-closure lens.
   - Show canonical Korean vocabulary labels and aliases on hover.

6. Workflow integration
   - Add review queue states: `pass_candidate`, `revise`, `reject`,
     `needs_review`.
   - Add human approval, rejection, and override nodes.
   - Persist manager decisions as `ApprovalDecision` and `AuditEvent`.
   - Keep the system labeled as first-pass compliance support, not legal advice.

6. Regulation/source tracking
   - Add `RegulationVersion`, `source_snapshot`, `effective_date`,
     `supersedes`, and impacted-CU diff.
   - Recompile only impacted `Premise`, `PolicyHypernym`, and CU profiles when a
     law or guideline changes.

7. Opik observability
   - Trace compiler batches, normalization, retrieval scores, rerank, judge, and
     exception override.
   - Include `review_run_id`, `dataset_item_id`, `workspace_id`, and selected
     CU ids in trace metadata.

## Handoff Notes

- Treat `examples/graph-compliance-ccg/` as an experimental app, not production
  SEOCHO runtime.
- Do not move this into production runtime until vocabulary consolidation,
  evaluation metrics, and API response trimming are done.
- Do not replace LLM context engineering with deterministic regex fallback.
- Do not make `LegalChunk` fulltext the primary candidate retrieval path again.
- Use Create Context Graph as ontology/schema/UI/tool scaffold only; keep the
  Compliance Gate as a custom backend workflow.
