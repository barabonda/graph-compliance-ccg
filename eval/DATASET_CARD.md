# GraphCompliance CCG Smoke Evaluation Dataset Card

## Summary

This smoke set is a synthetic, de-identified Korean financial-advertising
evaluation sample for the GraphCompliance CCG MVP. It is designed to test
article-level multi-label evaluation, Context Graph triple auditing, CUPlan
retrieval, evidence grounding, CUPlan-0 diagnostics, and exception sanity.

The sample is not a benchmark claim. It is a regression and calibration fixture
for local development.

The directory also contains `redteam_korean_financial_ad_12.jsonl`, converted
from the 준법 테스트용 Korean financial-ad violation DOCX. That fixture is
intentionally violation-heavy and should be used as a recall/red-team suite,
not as a balanced production-distribution benchmark.

The directory also contains `approved_noise_jb_routine_deposit.json`, a small
golden regression set derived from a 심의필 통과 deposit ad copy. It keeps one
approved reference record and five targeted noisy mutations. This fixture is
intended to verify that approved disclosures remain recognized as satisfied,
while controlled edits such as depositor-protection removal, stale protection
limit wording, unconditional top-rate claims, low-prominence condition
disclosures, and missing review-approval text are detected.

## Schema

Each JSONL record contains:

- `id`: stable scenario id.
- `title`: short scenario title.
- `text`: advertising draft text sent to the review workflow.
- `facts`: structured scenario facts for evaluation documentation only. These
  are not passed to the agent prompt by `evaluate.py`.
- `product_group`: product scope such as `deposit`, `loan`, `investment`, or
  `card`.
- `channel`: ad channel such as `web_page`, `mobile_push`, or `sns`.
- `language`: currently `ko`.
- `labels.violation`: scenario-level binary judgment.
- `labels.violation_types`: concise issue categories.
- `labels.articles`: provisions expected to be flagged for violation/review.
- `labels.sales_principles`: six-sales-principle categories involved.
- `labels.required_disclosures`: disclosures that should be checked or kept.
- `labels.risk_level`: `low`, `medium`, or `high`.
- `labels.expected_routing`: expected workflow route.
- `labels.review_basis`: source family used for label rationale.

## Labeling Principles

Labels map verifiable ad-text facts to financial-ad review criteria and
statutory principles. Article labels are kept as concise Korean strings so the
evaluation can compare predicted article sets with gold labels after simple
normalization.

The smoke set prioritizes:

- deposit rate and depositor-protection disclosures;
- loan approval and screening-condition claims;
- event benefit condition disclosures;
- investment past-performance and loss-risk disclosures;
- SNS/recommendation disclosure issues.

The DOCX-derived red-team fixture prioritizes deliberately unsafe drafts:

- principal/profit guarantee or compensation wording;
- definitive lowest-rate, approval, or benefit claims;
- missing risk, fee, condition, insurance-exclusion, or depositor-protection
  qualifiers;
- SNS/recommendation-disclosure and unauthorized-review style issues.

The approved-noise fixture prioritizes regression safety around a known-good
bank deposit ad:

- the clean approved record should not be overblocked;
- required disclosures in the clean record should be counted as present;
- noisy mutations should preserve their targeted gold labels;
- product name selection is documented through `facts.product_name` but gold
  labels are still excluded from the review prompt.

## Representativeness And Bias

This set intentionally covers a range of sales principles and channels, but it
is small and synthetic. It does not represent sector frequency, enforcement
frequency, or real complaint distribution. It currently favors bank-ad review
scenarios because the MVP policy graph is strongest there.

Residual limitations:

- limited insurance and card coverage;
- limited temporal variation;
- no real enforcement-case distribution;
- no PDF-derived product `DisclosureFact` labels yet.
- the red-team fixture contains only violating cases, so precision and
  overblocking should be measured with the balanced smoke set or a separate
  normal/exception control set.
- the approved-noise fixture is adapted from a user-provided 심의필 통과 ad and
  is designed for local regression, not as public enforcement evidence.

## Ethics And Legal Safety

The public sample contains no personal data and no real organisation names in
the advertising text. Texts are adapted, condensed examples for research and
development. They are not legal advice and should be used only as a first-pass
quality fixture.

## Evaluation Metrics

`evaluate.py` reports:

- `micro_f1`, `macro_f1`, `micro_f2`, `macro_f2`;
- `mcc` on the flattened article-by-scenario matrix;
- `cuplan_recall`;
- `evidence_grounding_rate`;
- `cu0_rate`;
- `overblocking_rate`;
- `exception_sanity_rate`;
- `average_context_triples`.

Gold labels are read only during evaluation. They must not be included in
Context Graph extraction, CU retrieval, LLM judge, exception override, or
revision-generation prompts.
