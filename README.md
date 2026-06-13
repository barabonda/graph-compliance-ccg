# JB Compliance · CONTENT SAFEGUARD

> Team **JunBub** · JB Fin AI Challenge

금융광고 문안을 **법령·심의기준·상품설명서 사실**과 대조하고, **규칙 기반 판정과
LLM 해석을 결합**해 **설명가능한 사전 검토**를 지원하는 콘솔.

핵심 차별점: 룰베이스가 적용범위를 자르고(상품군별 필수고지 카탈로그·법령 위임
사슬) 기계적 위반을 직접 판정하면, LLM은 *정리된 문제*만 해석한다(단정·오인 등
맥락 판단 + 전체 인상 종합). 모든 판정은 근거 조문 원문까지 추적된다.

## 주요 기능

- **심사 콘솔(3-pane)**: 광고 원문 하이라이트(심각도 색 + 물결 밑줄) · 위험 카드
  (개별 심사 + 종합 심사) · 판정 상세(금감원 회답식 정의→요건→결론→유보).
- **종합 심사(Track B)**: 흩어진 조각을 모아 전체 인상 오인위험을 그래프로
  (혜택 주장 ← 완화/강화). 복잡 위반 탐지.
- **상품 사실 대조**: 광고 주장 ↔ 상품설명서/약관 사실 비교, 누락 필수고지를
  그래프 카탈로그(`disc_*`)에서 데이터 기반으로 산출.
- **수정안**: 광고 전체를 일관되게 재작성한 교정본(원문↔교정본 diff). 제안과
  심사자 조언 분리, 할루시네이션 차단.
- **운영 대시보드**: 실행 기록·집계, 행 클릭 시 그 실행의 시점 데이터를 콘솔에서
  디버깅. 감사 추적 포함.
- **로컬/클라우드 LLM 토글**: 모델 드롭다운에서 클라우드(GPT-5.4-nano)와 로컬
  Ollama 모델(ax-4.0-light/midm-2.0-base/exaone4-32b/qwen3.5:9b/gemma4)을 골라
  요청별로 라우팅. 로컬 경로는 Chat Completions + `response_format=json_schema`.

For the reasoning architecture — how rule/graph (deterministic) and LLM
(interpretive) lanes split the work across data → process → result, with
diagrams — see [docs/REASONING_ARCHITECTURE.md](docs/REASONING_ARCHITECTURE.md).
For implementation state and operating commands, see
[docs/GRAPHCOMPLIANCE_CCG_HANDOFF.md](../../docs/GRAPHCOMPLIANCE_CCG_HANDOFF.md).

이 앱은 결정론 fallback으로 심사를 대체하지 않는다. LLM 자격증명/Neo4j가 없으면
규칙으로 조용히 대체하지 않고 실패한다.

## 로컬 LLM (선택)

`.env`에 아래를 두면 모델 드롭다운에서 로컬 모델 선택 시 그 엔드포인트로 라우팅된다
(클라우드 기본 모드여도). 비우면 클라우드(OpenAI)만 사용.

```bash
LOCAL_LLM_BASE_URL=http://<ollama-host>:11434/v1   # OpenAI 호환 Chat Completions
LOCAL_LLM_API_KEY=ollama
# 전역 로컬 토글(모든 요청을 로컬로)을 원하면:
# LLM_BASE_URL=http://<ollama-host>:11434/v1
```

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
ComplianceUnit -> CULegalElementProfile
ComplianceUnit -> HAS_SUBJECT_HYPERNYM -> PolicyHypernym
```

`LegalChunk` is evidence/provenance, not the primary CU retrieval engine.
Runtime candidate retrieval uses approved `PolicyHypernym` nodes, CU embedding
profiles, legal-element profiles, and overlap scoring before optional
cross-encoder rerank and LLM rerank.
`CULegalElementProfile` records the positive claim evidence required before a
CU can become a candidate. For example, comparison-ad CUs require a comparison
target or superiority claim, while unfair superior-position CUs require coercion,
tie-in-sale, collateral/guarantee demand, or sales-process context.

Optional cross-encoder rerank:

```bash
pip install FlagEmbedding
export CCG_ENABLE_CROSS_ENCODER_RERANKER=true
export CCG_CROSS_ENCODER_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

When enabled, the workflow scores `(ContextAnchor packet, CU candidate packet)`
pairs after graph retrieval and legal-element gating. The cross-encoder only
reorders already eligible candidates; it does not override missing legal
elements. LLM rerank still produces the final `CUPlanItem` explanation.

API:

```bash
PYTHONPATH=examples/graph-compliance-ccg \
uvicorn server:app --app-dir examples/graph-compliance-ccg --port 8770
```

Frontend (Next.js review console, proxies `/api/*` to the FastAPI server):

```bash
cd examples/graph-compliance-ccg/frontend
npm install
npm run dev   # http://localhost:3000
```

The legacy vanilla console remains served by FastAPI at `/console`. See
[frontend/README.md](frontend/README.md) for the new console architecture.

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

- `context_frame`, `sentence_units`, `inter_sentence_relations`, and
  `context_influences` — RLM-style hierarchical context graph evidence. The
  workflow reads the full ad first, creates an overall message/consumer
  impression frame, then decomposes the draft into ordered sentences and
  sentence-to-sentence influence before extracting claim-level details. This
  keeps neutral launch notices such as `JB 특판예금 출시.` separate from risky
  benefit claims, and lets the judge see when one sentence reinforces or
  mitigates another.
- `claims[].qualifiers` — expression-level modeling inside each Claim. Generic
  scope/certainty/guarantee wording such as `누구나`, `조건 없이`, `확정`, and
  `보장` stays inside the parent Claim as `ClaimQualifier` evidence instead of
  becoming a standalone target-consumer judgment anchor.
- `anchor_feature_sets` — 금소법 행위요건 feature layer derived from the
  Context Graph. It maps parent-claim qualifiers and facts to positive features
  such as `universal_scope_expression`, `certainty_expression`,
  `guarantee_expression`, and `unconditional_expression`; these features are
  matched against each CU's `CULegalElementProfile` before LLM rerank.
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
  `SUPPORTED`, `CONTRADICTED`, `CONDITION_MISSING`,
  `PROMINENCE_INSUFFICIENT`, `NO_PRODUCT_FACT`, or
  `NEEDS_PRODUCT_SELECTION`. Ambiguous products stay in
  `NEEDS_PRODUCT_SELECTION`; the system does not invent missing product facts.
- `prominence_analysis`, `disclosure_links`, and `prominence_diagnostics` —
  runtime Disclosure Gate artifacts. They compare benefit claims against
  condition/protection/risk disclosures and flag cases where a disclosure exists
  but is less prominent than the benefit claim. This is evidence engineering for
  the judge and reviewer UI, not a deterministic final verdict path.
- `disclosure_requirements` — required-disclosure candidates from the bank ad
  review standards and financial-ad guideline, such as depositor protection,
  rate/condition basis, fees, and review-number display.
- `system_review_items[].risk_code` — CUPlan 0 diagnostics split into
  `NO_HYPERNYM_MATCH`, `MISSING_POLICY_COVERAGE`,
  `NO_LEGAL_ELEMENT_MATCH`, `NO_ACTIVE_CU_AFTER_GATE`, and
  `RERANK_DROPPED_ALL`.

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

`SUPPORTED` means the product document supports the fact itself. It does not
automatically mean the ad is ready to publish. If conditions, period, tax basis,
depositor-protection scope, or other required disclosures are absent or buried
in a lower prominence tier, the Disclosure Gate may surface
`CONDITION_MISSING` or `PROMINENCE_INSUFFICIENT`.

## Hierarchical Context Graph

The context layer follows the GraphCompliance paper's context engineering idea
and borrows the RLM pattern of recursive decomposition and aggregation:

```text
AdDraft
-> ContextFrame
-> SentenceUnit
-> Claim
-> ClaimQualifier / ClaimFact
-> ConsumerEffect
-> CUPlanItem / ProductFactComparison
-> LLMJudgment
```

The implementation does not run a separate code-execution RLM loop in v1.
Instead, one structured LLM extraction call must produce the same hierarchy:

1. `extract_context_frame`: identify the full-ad message, tone, purpose,
   representative consumer impression, and risk axes.
2. `extract_sentence_units`: split the original text into ordered sentences,
   classify roles such as `launch_notice`, `benefit_claim`,
   `condition_disclosure`, and record local context effects.
3. `extract_claim_details`: decompose each sentence into claims, entities,
   relations, and qualifiers.

Judge evidence windows include the relevant `ContextFrame`, `SentenceUnit`, and
`ContextInfluence` for each anchor. That is what lets the system explain that
`누구나` should be evaluated inside the parent claim `누구나 연 5% 확정 보장`
rather than as an independent target-consumer anchor.

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
