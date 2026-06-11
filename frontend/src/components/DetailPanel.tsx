"use client";

import { JUDGMENT_STATUS, judgmentBadgeTone, trackBBadgeTone } from "@/lib/labels";
import {
  anchorDisplay,
  chainNodeLabel,
  chainsForAnchor,
  claimFactById,
  claimQualifiers,
  disclosureSignals,
  effectiveJudgmentsForAnchor,
  judgmentsForAnchor,
  planItemsForAnchor,
  productClaimFactsForAnchor,
  productComparisonsForClaimFact,
  productFactById,
  productFactSummary,
  rawJudgment,
  safeAlternative,
  shorten,
} from "@/lib/selectors";
import type {
  AggregationRow,
  AnchorDisplay,
  ContextAnchor,
  CUPlanItem,
  DetectedIssue,
  ExceptionReview,
  LLMJudgment,
  PolicyEvidenceChain,
  ReviewOutput,
} from "@/lib/types";
import { Badge, EmptyState, KeyValueText, Tag } from "./ui";

interface Props {
  result: ReviewOutput | null;
  selectedAnchorId: string;
}

function SectionCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-3.5">
      <h3 className="mb-2 text-[13px] font-bold text-foreground">{title}</h3>
      {children}
    </section>
  );
}

function IssueSummary({
  result,
  anchor,
  judgments,
  issues,
}: {
  result: ReviewOutput;
  anchor: ContextAnchor;
  judgments: LLMJudgment[];
  issues: DetectedIssue[];
}) {
  const risky = judgments.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
  const role = anchorDisplay(result, anchor.anchor_id)?.display_role ?? "actionable";
  if (!risky.length && role === "mitigation") {
    return <p className="text-[13px] text-foreground/90">이 문구는 조건이나 제한사항을 보완하는 완화 근거로 사용됩니다.</p>;
  }
  if (!risky.length) {
    return (
      <p className="text-[13px] text-foreground/90">
        선택 문구 기준 중대한 위반 판단은 없지만, 상품 사실과 필수고지 상태는 별도로 확인해야 합니다.
      </p>
    );
  }
  const first = issues[0];
  return (
    <div className="space-y-2">
      <p className="text-[13px] leading-relaxed text-foreground/90">
        {first?.rationale || risky[0].why || "이 문구는 소비자 오인 가능성이 있어 수정 또는 추가 고지가 필요합니다."}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={judgmentBadgeTone(risky[0].verdict)}>{JUDGMENT_STATUS[risky[0].verdict] ?? risky[0].verdict}</Badge>
        {first?.source_article && <Tag>{first.source_article}</Tag>}
        {first?.risk_title && <Tag>{first.risk_title}</Tag>}
      </div>
    </div>
  );
}

function QualifierPanel({ result, anchor }: { result: ReviewOutput; anchor: ContextAnchor }) {
  const qualifiers = claimQualifiers(result, anchor.claim_id);
  if (!qualifiers.length) {
    return <EmptyState>별도 qualifier 없이 문장 전체를 검토합니다.</EmptyState>;
  }
  return (
    <div className="space-y-2">
      {qualifiers.map((item) => (
        <article key={item.qualifier_id || item.text} className="rounded-md border border-line bg-panel-soft p-3">
          <strong className="text-[13px]">{item.text}</strong>
          <div className="my-1.5 flex flex-wrap gap-1.5">
            <Tag>{item.role}</Tag>
            <Tag>{item.prominence_tier ?? "unknown"}</Tag>
            <Tag>{Number(item.confidence ?? 0).toFixed(2)}</Tag>
          </div>
          <p className="text-xs leading-relaxed text-muted">
            {item.meaning}
            {item.risk_reason ? <><br />{item.risk_reason}</> : null}
          </p>
        </article>
      ))}
    </div>
  );
}

function ComparisonCard({ result, comparisonId }: { result: ReviewOutput; comparisonId: string }) {
  const item = (result.product_fact_context?.comparison_results ?? []).find((row) => row.comparison_id === comparisonId);
  if (!item) return null;
  const claimFact = claimFactById(result, item.claim_fact_id);
  const productFact = productFactById(result, item.product_fact_id);
  return (
    <article className="rounded-md border border-line bg-panel-soft p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <strong className="text-[13px]">{item.status || "NO_PRODUCT_FACT"}</strong>
        <Tag>{Number(item.confidence ?? 0).toFixed(2)}</Tag>
      </div>
      <KeyValueText
        items={[
          ["Claim", claimFact?.evidence_text || item.claim_fact_id || "-"],
          [
            "ProductFact",
            productFact ? `${productFact.fact_type}: ${productFact.value} ${productFact.condition ?? ""}` : "대응 fact 없음",
          ],
          ["판단", item.rationale || "-"],
          ["근거", item.evidence_text || "-"],
        ]}
      />
    </article>
  );
}

function ProductFactComparisonPanel({ result, anchor }: { result: ReviewOutput; anchor: ContextAnchor }) {
  const factContext = result.product_fact_context ?? {};
  const claimFacts = productClaimFactsForAnchor(result, anchor);
  if (factContext.extraction_status === "NEEDS_PRODUCT_SELECTION") {
    return (
      <EmptyState>상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다.</EmptyState>
    );
  }
  if (!claimFacts.length) {
    return <EmptyState>이 문구에서 상품문서와 대조할 ClaimFact가 아직 추출되지 않았습니다.</EmptyState>;
  }
  return (
    <div className="space-y-2.5">
      {claimFacts.map((fact) => {
        const rows = productComparisonsForClaimFact(result, fact.claim_fact_id);
        return (
          <article key={fact.claim_fact_id} className="rounded-md border border-line bg-panel p-3">
            <div className="mb-1 flex items-center justify-between gap-2">
              <strong className="text-[13px]">
                {fact.fact_type || "ClaimFact"} · {fact.value}
              </strong>
              <Tag>{fact.qualifier || "qualifier 없음"}</Tag>
            </div>
            <p className="mb-2 text-xs text-muted">{fact.evidence_text || "-"}</p>
            <div className="space-y-2">
              {rows.length ? (
                rows.map((row) => <ComparisonCard key={row.comparison_id} result={result} comparisonId={row.comparison_id} />)
              ) : (
                <EmptyState>비교 결과 없음</EmptyState>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function ChainGroup({
  title,
  subtitle,
  rows,
  nodeKey,
  emptyText = "FOUND chain 없음",
}: {
  title: string;
  subtitle: string;
  rows: PolicyEvidenceChain[];
  nodeKey: "basis_nodes" | "disclosure_nodes" | "exception_nodes";
  emptyText?: string;
}) {
  return (
    <article className="rounded-md border border-line bg-panel-soft p-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <strong className="text-[13px]">{title}</strong>
        <Tag tone={rows.length ? "ok" : undefined}>{rows.length ? `${rows.length} found` : "not found"}</Tag>
      </div>
      <p className="mb-2 text-xs text-muted">{subtitle}</p>
      {rows.length ? (
        <div className="space-y-2">
          {rows.map((chain, index) => (
            <div key={`${chain.anchor_id}_${index}`} className="space-y-1.5">
              <strong className="text-xs">{chain.summary || chain.chain_type || title}</strong>
              <div className="flex flex-wrap gap-1.5">
                {(chain[nodeKey] ?? []).map((node, nodeIndex) => (
                  <Tag key={nodeIndex}>{chainNodeLabel(node)}</Tag>
                ))}
              </div>
              {(chain.provenance_snippets ?? []).length > 0 && (
                <details className="text-xs text-muted">
                  <summary className="cursor-pointer font-semibold">Provenance snippets</summary>
                  <div className="mt-1 space-y-2">
                    {(chain.provenance_snippets ?? []).map((item, snippetIndex) => (
                      <p key={snippetIndex} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
                        {shorten(item.text || item.summary || "", 360)}
                      </p>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted">{emptyText}</p>
      )}
    </article>
  );
}

function PolicyEvidenceChainPanel({ result, anchor }: { result: ReviewOutput; anchor: ContextAnchor }) {
  const chains = result.policy_evidence_chains ?? {};
  const found = (rows?: PolicyEvidenceChain[]) =>
    chainsForAnchor(rows, anchor.anchor_id).filter((chain) => chain.status === "FOUND");
  const legal = found(chains.legal_basis_chains);
  const disclosures = found(chains.disclosure_chains);
  const exceptions = found(chains.exception_chains);
  const fallbackRows = (result.reference_paths_summary ?? []).filter((row) => row.anchor_id === anchor.anchor_id);

  if (!legal.length && !disclosures.length && !exceptions.length && !fallbackRows.length) {
    return <EmptyState>이 anchor의 목적별 근거 chain이 없습니다. 부족한 chain은 Audit/Trace 진단에 모았습니다.</EmptyState>;
  }
  return (
    <div className="space-y-2.5">
      <ChainGroup
        title="법적 근거 · Legal basis"
        subtitle="어떤 금소법/시행령/감독규정/심의기준 근거에서 왔는가"
        rows={legal}
        nodeKey="basis_nodes"
      />
      <ChainGroup
        title="필수 고지 · Required disclosure"
        subtitle="문안에 무엇을 보완하거나 유지해야 하는가"
        rows={disclosures}
        nodeKey="disclosure_nodes"
      />
      <ChainGroup
        title="예외/완화 · Exception"
        subtitle="어떤 고지/상품사실/승인 근거가 있으면 완화 가능한가"
        rows={exceptions}
        nodeKey="exception_nodes"
        emptyText="현재 문안 기준 명시적 예외/완화 chain 없음"
      />
      {!legal.length && fallbackRows.length > 0 && (
        <div className="space-y-2">
          {fallbackRows.map((row, index) => (
            <article key={index} className="rounded-md border border-line bg-panel-soft p-3">
              <div className="mb-1 flex items-center justify-between gap-2">
                <strong className="text-[13px]">{row.risk_title || row.cu_id || "CU 근거"}</strong>
                <Tag>{row.source_article || "조항 미상"}</Tag>
              </div>
              <div className="mb-2 flex flex-wrap gap-1.5">
                <Tag>{row.principle || "원칙 미상"}</Tag>
                {row.has_disclosure_evidence && <Tag tone="ok">필수고지 evidence</Tag>}
                {row.has_exception_path && <Tag tone="ok">exception path</Tag>}
              </div>
              <KeyValueText
                items={[
                  ["Traversal", (row.path_labels ?? []).join(" → ") || "CU → Premise/LegalChunk evidence"],
                  [
                    "Evidence",
                    (row.legal_evidence ?? [])
                      .map((item) => `${item.id ?? ""} ${shorten(item.text ?? "", 360)}`)
                      .join(" / ") || "-",
                  ],
                ]}
              />
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function ProductDisclosurePanel({ result }: { result: ReviewOutput }) {
  const context = result.product_context ?? {};
  const factContext = result.product_fact_context ?? {};
  const requirements = result.disclosure_requirements ?? [];
  const products = context.matched_products ?? [];
  const summary = productFactSummary(result);
  const checks = factContext.disclosure_checks ?? [];
  const diagnostics = result.prominence_diagnostics ?? [];
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap gap-1.5">
        <Tag>상품군 {context.product_group || "auto"}</Tag>
        <Tag>상품 {products.length}</Tag>
        <Tag>문서 {Number(context.document_count ?? 0)}</Tag>
        <Tag>본문 fact {factContext.extraction_status || "NOT_RUN"}</Tag>
      </div>
      <details open className="rounded-md border border-line bg-panel-soft p-3 text-xs">
        <summary className="cursor-pointer text-[13px] font-bold">본문 fact 대조 상태</summary>
        <div className="mt-2 space-y-2 text-muted">
          <p>
            <b className="text-foreground">matched_product</b>
            <br />
            {factContext.matched_product || "상품 선택 필요"}
          </p>
          <p>
            <b className="text-foreground">comparison</b>
            <br />
            {Object.entries(summary)
              .map(([status, count]) => `${status} ${count}`)
              .join(" · ") || "-"}
          </p>
          <p>
            <b className="text-foreground">prominence</b>
            <br />
            {diagnostics.length
              ? diagnostics.map((item) => `${item.diagnostic_code} · ${item.message ?? ""}`).join(" / ")
              : "현저성 진단 없음"}
          </p>
          {factContext.reason && <p>{String(factContext.reason)}</p>}
        </div>
      </details>
      <details open className="rounded-md border border-line bg-panel-soft p-3 text-xs">
        <summary className="cursor-pointer text-[13px] font-bold">필요 고지 후보</summary>
        <div className="mt-2 space-y-2">
          {checks.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {checks.map((item) => (
                <Tag key={item.check_id} tone={item.present ? "ok" : "review"}>
                  {item.label} · {item.present ? "있음" : "누락"}
                </Tag>
              ))}
            </div>
          )}
          <div className="space-y-2 text-muted">
            {requirements.length ? (
              requirements.map((item, index) => (
                <p key={index} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
                  <b className="text-foreground">{item.label}</b> · {item.source}
                  <br />
                  {item.why}
                </p>
              ))
            ) : (
              <p>-</p>
            )}
          </div>
        </div>
      </details>
      <details className="rounded-md border border-line bg-panel-soft p-3 text-xs">
        <summary className="cursor-pointer text-[13px] font-bold">ProductDocument grounding · Debug</summary>
        <div className="mt-2 space-y-2 text-muted">
          {products.length ? (
            products.map((item, index) => (
              <p key={index} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
                <b className="text-foreground">{item.product}</b>
                <br />
                {item.major} / {item.subcategory} / {item.category}
                <br />
                문서 {Number(item.document_count ?? 0)} · {(item.document_labels ?? []).join(", ")}
              </p>
            ))
          ) : (
            <p>광고 문안과 직접 매칭된 상품명은 없습니다. 상품군 기준 고지 후보만 사용합니다.</p>
          )}
        </div>
      </details>
      <p className="text-xs leading-relaxed text-muted">
        Product Fact Graph는 리뷰 대상 상품이 명확할 때 관련 PDF 본문에서 핵심 상품사실을 추출하고, 광고 ClaimFact와
        비교합니다. 상품이 모호하면 사실을 추정하지 않고 상품 선택 필요 상태로 둡니다.
      </p>
    </div>
  );
}

function OverallImpressionPanel({ result, anchor }: { result: ReviewOutput; anchor: ContextAnchor }) {
  const trackB = result.overall_impression_judgment ?? {};
  if (!trackB.verdict) return <EmptyState>Track B 판단 결과가 없습니다.</EmptyState>;
  const related = (trackB.evidence_paths ?? []).filter((path) => path.claim_id === anchor.claim_id);
  const paths = related.length ? related : (trackB.evidence_paths ?? []);
  return (
    <article className="rounded-md border border-line bg-panel-soft p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <strong className="text-[13px]">{trackB.standard || "전체적 인상 기준"}</strong>
        <Badge tone={trackBBadgeTone(trackB.verdict, trackB.misleading_risk_score)}>
          {trackB.verdict} · {Number(trackB.misleading_risk_score ?? 0).toFixed(2)}
        </Badge>
      </div>
      <KeyValueText
        items={[
          ["대표 소비자 인상", trackB.representative_consumer_impression || "-"],
          ["판단 이유", trackB.why || "-"],
          [
            "오인 요인",
            (trackB.misleading_factors ?? []).map((factor, index) => (
              <span key={index}>
                {factor}
                <br />
              </span>
            )),
          ],
        ]}
      />
      <details open={related.length > 0} className="mt-2 text-xs text-muted">
        <summary className="cursor-pointer font-semibold">Context Graph evidence path</summary>
        <div className="mt-1 space-y-2">
          {paths.map((path, index) => (
            <div key={index} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
              <b className="text-foreground">{path.path || "Claim -> Meaning -> Implicature -> ConsumerEffect"}</b>
              <br />
              Claim: {path.claim || "-"}
              <br />
              Meaning: {path.meaning || "-"}
              <br />
              Implicature: {path.implicature || "-"}
              <br />
              ConsumerEffect: {path.consumer_effect || "-"}
            </div>
          ))}
        </div>
      </details>
    </article>
  );
}

function ExceptionPanel({ anchor, exceptions }: { anchor: ContextAnchor; exceptions: ExceptionReview[] }) {
  const signals = disclosureSignals(anchor);
  if (!signals.length && !exceptions.length) {
    return <EmptyState>명시적 예외/고지 완화 신호가 없습니다.</EmptyState>;
  }
  return (
    <div className="space-y-2">
      {signals.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {signals.map((item) => (
            <Tag key={item} tone="ok">
              {item}
            </Tag>
          ))}
        </div>
      )}
      {exceptions.map((review) => (
        <article key={review.exception_review_id} className="rounded-md border border-line bg-panel-soft p-3">
          <div className="mb-1 flex items-center justify-between gap-2">
            <strong className="text-[13px]">{review.effect}</strong>
            <Tag tone={review.applies ? "ok" : undefined}>{review.applies ? "applies" : "not applied"}</Tag>
          </div>
          <p className="text-xs leading-relaxed text-muted">{review.why}</p>
        </article>
      ))}
    </div>
  );
}

function RevisionPanel({
  result,
  anchor,
  issues,
  judgments,
  display,
}: {
  result: ReviewOutput;
  anchor: ContextAnchor;
  issues: DetectedIssue[];
  judgments: LLMJudgment[];
  display: AnchorDisplay | undefined;
}) {
  if (display?.display_role === "scope") {
    return (
      <article className="rounded-md border border-line bg-panel-soft p-3 text-xs leading-relaxed text-muted">
        <strong className="block text-[13px] text-foreground">범위 정보</strong>이 anchor는 상품군, 고객군, 채널 같은 심사
        범위를 잡기 위한 정보입니다. 문안 수정 제안은 Claim/Risk anchor에서 생성됩니다.
      </article>
    );
  }
  const suggestion = (result.revision_suggestions ?? []).find((item) => item.anchor_id === anchor.anchor_id);
  if (suggestion) {
    return (
      <article className="rounded-md border border-line bg-panel-soft p-3">
        <strong className="text-[13px]">{suggestion.severity} · 수정 제안</strong>
        <div className="mt-2">
          <KeyValueText
            items={[
              ["위험 표현", suggestion.risky_text],
              ["왜 문제인지", suggestion.why_problematic],
              [
                "필요 고지",
                (suggestion.required_disclosures ?? []).map((item, index) => (
                  <span key={index}>
                    {item}
                    <br />
                  </span>
                )),
              ],
              ["Before", suggestion.before],
              ["After", suggestion.after],
              ["Reviewer note", suggestion.notes_for_reviewer || "-"],
            ]}
          />
        </div>
      </article>
    );
  }
  if (display?.system_review_required) {
    const diagnostic = display.retrieval_diagnostic ?? {};
    return (
      <article className="rounded-md border border-line bg-panel-soft p-3 text-xs leading-relaxed text-muted">
        <strong className="block text-[13px] text-foreground">
          정책 매칭 보완 필요 · {display.retrieval_failure_code || "CU_PLAN_EMPTY"}
        </strong>
        {display.system_review_reason || "이 표현은 정책어로 정규화됐지만 후보 CU가 생성되지 않았습니다."}
        <br />
        candidate {Number(diagnostic.candidate_count ?? 0)} · active {Number(diagnostic.active_candidate_count ?? 0)} ·
        hypernym {Number(diagnostic.hypernym_count ?? 0)}
      </article>
    );
  }
  const risky = judgments.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
  if (!risky.length) {
    return <EmptyState>수정 제안이 필요한 위험 판단이 없습니다.</EmptyState>;
  }
  const nonCompliant = risky.filter((item) => item.verdict === "NON_COMPLIANT");
  if (!nonCompliant.length) {
    return (
      <div className="space-y-2">
        <article className="rounded-md border border-line bg-panel-soft p-3 text-xs leading-relaxed text-muted">
          <strong className="block text-[13px] text-foreground">추가 근거 확인 필요</strong>이 anchor는 현재 위반 확정이
          아니라 근거/정책 매칭/고지 충족 여부 확인 대상으로 분류됐습니다. 문구를 바로 대체하기보다 관련 상품조건,
          필수고지, 조문 근거를 확인하세요.
        </article>
        {issues.map((issue, index) => (
          <article key={index} className="rounded-md border border-line bg-panel-soft p-3 text-xs leading-relaxed text-muted">
            <strong className="block text-[13px] text-foreground">{issue.required_action || "확인 필요"}</strong>
            {issue.rationale}
          </article>
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {issues.map((issue, index) => (
        <article key={index} className="rounded-md border border-line bg-panel-soft p-3 text-xs leading-relaxed text-muted">
          <strong className="block text-[13px] text-foreground">{issue.required_action || "문안 수정 필요"}</strong>
          {issue.rationale}
        </article>
      ))}
      <article className="rounded-md border border-line bg-panel-soft p-3">
        <strong className="text-[13px]">대체 문안 예시</strong>
        <div className="mt-2">
          <KeyValueText
            items={[
              ["Before", anchor.span.text],
              ["After", safeAlternative(anchor.span.text)],
            ]}
          />
        </div>
      </article>
    </div>
  );
}

function JudgmentCard({
  result,
  judgment,
  planItem,
}: {
  result: ReviewOutput;
  judgment: LLMJudgment;
  planItem: CUPlanItem | undefined;
}) {
  const raw = rawJudgment(result, judgment.judgment_id);
  const title = planItem?.risk_title
    ? `${planItem.risk_title} · ${planItem.source_article || planItem.principle || "법적 근거 확인"}`
    : planItem
      ? `${planItem.source_article || "근거 조항"} 근거: ${planItem.subject || "광고 표현"} · ${
          planItem.constraint || planItem.context || judgment.cu_id || "준수 여부"
        }`
      : "CU 근거 확인 필요";
  return (
    <article className="rounded-md border border-line bg-panel-soft p-3">
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <strong className="text-[13px]">{title}</strong>
        <Badge tone={judgmentBadgeTone(judgment.verdict)}>{JUDGMENT_STATUS[judgment.verdict] ?? judgment.verdict}</Badge>
      </div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        <Tag>{planItem?.principle || "원칙 미상"}</Tag>
        {planItem?.source_article && <Tag>{planItem.source_article}</Tag>}
        <Tag>score {Number(judgment.score ?? 0).toFixed(2)}</Tag>
        {raw && raw.verdict !== judgment.verdict && <Tag>raw {raw.verdict}</Tag>}
      </div>
      <p className="text-xs leading-relaxed text-foreground/90">{judgment.why}</p>
      <details className="mt-2 text-xs text-muted">
        <summary className="cursor-pointer font-semibold">근거 / Evidence window / Debug</summary>
        <div className="mt-2 space-y-2">
          <KeyValueText
            items={[
              ["cu_id", judgment.cu_id || "-"],
              ["action_type", planItem?.legal_element_profile?.action_type || "-"],
              ["matched_features", (planItem?.matched_required_features ?? []).join(", ") || "-"],
              ["evidence_span", judgment.evidence_span || "-"],
              ["used_policy_evidence", (judgment.used_policy_evidence ?? []).join(", ") || "-"],
            ]}
          />
          <div className="space-y-2">
            {(planItem?.evidence_texts ?? []).map((item, index) => (
              <p key={index} className="border-t border-line pt-2">
                {shorten(item, 520)}
              </p>
            ))}
          </div>
        </div>
      </details>
    </article>
  );
}

function AggregationPanel({ result, anchor }: { result: ReviewOutput; anchor: ContextAnchor }) {
  const forAnchor = (rows: AggregationRow[]) => rows.filter((row) => (row.anchor_spans ?? []).includes(anchor.span.text));
  const articleRows = forAnchor(result.article_aggregation ?? []);
  const principleRows = forAnchor(result.principle_aggregation ?? []).filter(
    (row) => !articleRows.some((item) => item.key === row.key),
  );
  const rows = [...articleRows, ...principleRows];
  if (!rows.length) return <EmptyState>이 anchor가 조항/원칙 집계에 아직 연결되지 않았습니다.</EmptyState>;
  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        <article key={index} className="rounded-md border border-line bg-panel-soft p-3">
          <div className="mb-1.5 flex items-start justify-between gap-2">
            <strong className="text-[13px]">
              {row.axis === "article" ? `${row.key || "근거 조항"} 기준 최종 영향` : `${row.key || "원칙 미상"} 원칙 기준 최종 영향`}
            </strong>
            <Badge tone={judgmentBadgeTone(String(row.effective_verdict ?? ""))}>
              {JUDGMENT_STATUS[String(row.effective_verdict ?? "")] ?? row.effective_verdict}
            </Badge>
          </div>
          <div className="mb-2 flex flex-wrap gap-1.5">
            <Tag>{row.axis || "policy"}</Tag>
            <Tag>CU {Number(row.cu_count ?? 0)}</Tag>
            <Tag>issue {Number(row.issue_count ?? 0)}</Tag>
            <Tag>max {Number(row.max_score ?? 0).toFixed(2)}</Tag>
            {(row.principles ?? []).map((item) => (
              <Tag key={item}>{item}</Tag>
            ))}
          </div>
          <KeyValueText
            items={[
              ["관련 문구", (row.anchor_spans ?? []).join(" / ") || "-"],
              ["연결 CU", (row.cu_titles ?? []).join(" / ") || "-"],
            ]}
          />
        </article>
      ))}
    </div>
  );
}

export function DetailPanel({ result, selectedAnchorId }: Props) {
  const anchor = result?.context_anchors?.find((item) => item.anchor_id === selectedAnchorId);
  if (!result || !anchor) {
    return <EmptyState>하이라이트나 Claim 카드를 선택하면 상세 판단이 표시됩니다.</EmptyState>;
  }
  const judgments = judgmentsForAnchor(result, anchor.anchor_id);
  const effective = effectiveJudgmentsForAnchor(result, anchor.anchor_id);
  const planItems = planItemsForAnchor(result, anchor.anchor_id);
  const exceptions = (result.exception_reviews ?? []).filter((review) =>
    judgments.some((judgment) => judgment.judgment_id === review.judgment_id),
  );
  const issues = (result.detected_issues ?? []).filter((issue) =>
    effective.some((judgment) => judgment.cu_id === issue.risk_code),
  );
  const display = anchorDisplay(result, anchor.anchor_id);
  const featureSet =
    anchor.feature_set ?? (result.anchor_feature_sets ?? []).find((item) => item.anchor_id === anchor.anchor_id);

  return (
    <div className="space-y-3">
      <SectionCard title={anchor.span.text}>
        <div className="mb-2 flex flex-wrap gap-1.5">
          <Tag>
            {display?.display_role === "scope"
              ? "범위 정보"
              : display?.display_role === "mitigation"
                ? "고지/완화 근거"
                : "심사 대상 문구"}
          </Tag>
          {anchor.hypernyms.slice(0, 4).map((item) => (
            <Tag key={item.proposal_id}>{item.hypernym}</Tag>
          ))}
        </div>
        <IssueSummary result={result} anchor={anchor} judgments={effective} issues={issues} />
      </SectionCard>

      <SectionCard title="문제 표현">
        <QualifierPanel result={result} anchor={anchor} />
      </SectionCard>

      <SectionCard title="상품 사실 대조">
        <ProductFactComparisonPanel result={result} anchor={anchor} />
      </SectionCard>

      <SectionCard title="법적 / 정책 근거">
        <PolicyEvidenceChainPanel result={result} anchor={anchor} />
      </SectionCard>

      <SectionCard title="필요한 고지">
        <ProductDisclosurePanel result={result} />
      </SectionCard>

      <SectionCard title="소비자 오인 판단">
        <OverallImpressionPanel result={result} anchor={anchor} />
      </SectionCard>

      <SectionCard title="예외 / 완화 검토">
        <ExceptionPanel anchor={anchor} exceptions={exceptions} />
      </SectionCard>

      <SectionCard title="수정 제안">
        <RevisionPanel result={result} anchor={anchor} issues={issues} judgments={effective} display={display} />
      </SectionCard>

      <section className="rounded-lg border border-line bg-panel p-3.5">
        <details>
          <summary className="cursor-pointer text-[13px] font-bold">Debug · 내부 id / feature / raw evidence</summary>
          <div className="mt-3 space-y-3">
            {featureSet && (
              <details open className="text-xs">
                <summary className="cursor-pointer font-semibold">금소법 행위요건 feature</summary>
                <div className="my-2 flex flex-wrap gap-1.5">
                  {(featureSet.action_types ?? []).map((item) => (
                    <Tag key={item}>{item}</Tag>
                  ))}
                  {(featureSet.positive_features ?? []).map((item) => (
                    <Tag key={item}>{item}</Tag>
                  ))}
                </div>
                <p className="text-muted">{(featureSet.evidence ?? []).join(" / ") || "feature evidence 없음"}</p>
              </details>
            )}
            <details className="text-xs">
              <summary className="cursor-pointer font-semibold">Context facts</summary>
              <p className="mt-1 text-muted">{anchor.facts.join(" / ") || "없음"}</p>
            </details>
            <h4 className="text-[13px] font-bold">CU별 판단</h4>
            {effective.length ? (
              <div className="space-y-2">
                {effective.map((judgment) => (
                  <JudgmentCard
                    key={judgment.judgment_id}
                    result={result}
                    judgment={judgment}
                    planItem={planItems.find((item) => item.plan_item_id === judgment.plan_item_id)}
                  />
                ))}
              </div>
            ) : planItems.length ? (
              <EmptyState>CUPlan은 생성됐지만 이 anchor에 대한 judgment가 없습니다. LLM judgment 단계를 확인하세요.</EmptyState>
            ) : (
              <EmptyState>이 anchor에 매칭된 CU가 없습니다. 정책 매칭 실패로 검토 필요 상태입니다.</EmptyState>
            )}
            <h4 className="text-[13px] font-bold">조항 / 원칙 집계</h4>
            <AggregationPanel result={result} anchor={anchor} />
          </div>
        </details>
      </section>
    </div>
  );
}
