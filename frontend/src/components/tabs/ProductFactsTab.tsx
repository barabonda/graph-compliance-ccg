"use client";

import { productFactStatusTone } from "@/lib/labels";
import { claimFactById, productFactById, productFactSummary } from "@/lib/selectors";
import type { ComparisonResult, ReviewOutput } from "@/lib/types";
import { Badge, Card, EmptyState, KeyValueText, Tag } from "../ui";

function ComparisonCard({ result, item }: { result: ReviewOutput; item: ComparisonResult }) {
  const claimFact = claimFactById(result, item.claim_fact_id);
  const productFact = productFactById(result, item.product_fact_id);
  return (
    <article className="rounded-md border border-line bg-surface-2 p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <Badge tone={productFactStatusTone(item.status)}>{item.status || "NO_PRODUCT_FACT"}</Badge>
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

export function ProductFactsTab({ result }: { result: ReviewOutput | null }) {
  if (!result) {
    return <EmptyState>Review를 실행하면 상품문서 fact 대조가 여기에 표시됩니다.</EmptyState>;
  }
  const context = result.product_fact_context ?? {};
  const claimFacts = context.claim_facts ?? [];
  const productFacts = context.product_facts ?? [];
  const comparisons = context.comparison_results ?? [];
  const documents = context.selected_documents ?? [];
  const summary = productFactSummary(result);
  const diagnostics = result.prominence_diagnostics ?? [];
  const candidates = result.product_context?.matched_products ?? [];

  return (
    <div className="space-y-3">
      <section className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-line bg-surface p-4">
        <div className="min-w-60 flex-1">
          <h3 className="text-sm font-bold">Product Fact Graph</h3>
          <p className="mt-1 text-xs text-ink-3">
            광고 ClaimFact와 상품문서 ProductFact를 대조해 조건 누락, 충돌, 근거 부재를 분리합니다.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={productFactStatusTone(context.extraction_status)}>{context.extraction_status || "NOT_RUN"}</Badge>
          <Tag>상품 {context.matched_product || "선택 필요"}</Tag>
          <Tag>문서 {documents.length}</Tag>
          <Tag>ProductFact {productFacts.length}</Tag>
          <Tag>ClaimFact {claimFacts.length}</Tag>
          <Tag>현저성 {diagnostics.length}</Tag>
        </div>
      </section>

      {context.extraction_status === "NEEDS_PRODUCT_SELECTION" && (
        <Card title="상품 선택 필요">
          <p className="mb-2 text-xs leading-relaxed text-ink-3">
            상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다. 광고 claim과 실제
            상품문서 fact를 대조하려면 리뷰 대상 상품을 먼저 확정해야 합니다.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {candidates.slice(0, 8).map((item, index) => (
              <Tag key={index}>{item.product || item.name || "상품 후보"}</Tag>
            ))}
            {!candidates.length && <Tag>상품 후보 없음</Tag>}
          </div>
        </Card>
      )}

      {context.reason ? (
        <div className="rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink-3">{String(context.reason)}</div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-3">
        <section className="space-y-2">
          <h3 className="text-sm font-bold">광고 ClaimFact</h3>
          {claimFacts.length ? (
            claimFacts.map((item) => (
              <article key={item.claim_fact_id} className="rounded-lg border border-line bg-surface p-3">
                <strong className="text-[13px]">{item.fact_type || "fact"}</strong>
                <div className="my-1.5 flex flex-wrap gap-1.5">
                  <Tag>{item.value || "-"}</Tag>
                  <Tag>{item.qualifier || "qualifier 없음"}</Tag>
                  <Tag>{item.prominence_tier || "unknown"}</Tag>
                </div>
                <p className="text-xs text-ink-3">{item.evidence_text || "-"}</p>
              </article>
            ))
          ) : (
            <EmptyState>상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다.</EmptyState>
          )}
        </section>
        <section className="space-y-2">
          <h3 className="text-sm font-bold">상품문서 ProductFact</h3>
          {productFacts.length ? (
            productFacts.map((item) => (
              <article key={item.fact_id} className="rounded-lg border border-line bg-surface p-3">
                <strong className="text-[13px]">{item.fact_type || "fact"}</strong>
                <div className="my-1.5 flex flex-wrap gap-1.5">
                  <Tag>{item.value || "-"}</Tag>
                  {item.unit && <Tag>{item.unit}</Tag>}
                  <Tag>{item.condition || "조건 없음"}</Tag>
                </div>
                <p className="text-xs text-ink-3">{item.evidence_text || "-"}</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {item.source_document_id && <Tag>{item.source_document_id}</Tag>}
                  {item.page_or_chunk && <Tag>{item.page_or_chunk}</Tag>}
                </div>
              </article>
            ))
          ) : (
            <EmptyState>선택 상품 PDF에서 ProductFact가 추출되지 않았습니다. 상품 선택 또는 문서 경로를 확인하세요.</EmptyState>
          )}
        </section>
        <section className="space-y-2">
          <h3 className="text-sm font-bold">비교 결과</h3>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(summary).map(([status, count]) => (
              <Tag key={status} tone={productFactStatusTone(status) === "pass" ? "ok" : productFactStatusTone(status) === "reject" ? "danger" : "review"}>
                {status} {count}
              </Tag>
            ))}
          </div>
          {comparisons.length ? (
            comparisons.map((item) => <ComparisonCard key={item.comparison_id} result={result} item={item} />)
          ) : (
            <EmptyState>비교 결과가 없습니다.</EmptyState>
          )}
        </section>
      </div>

      <Card title="고지 현저성 진단">
        <div className="space-y-2 text-xs text-ink-3">
          {diagnostics.length ? (
            diagnostics.map((item, index) => (
              <p key={index} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
                <b className="text-ink">{item.diagnostic_code}</b> · {item.severity || ""}
                <br />
                {item.message || ""}
                <br />
                {item.evidence || ""}
              </p>
            ))
          ) : (
            <p>혜택 문구 대비 고지 위계 부족 신호가 없습니다.</p>
          )}
        </div>
      </Card>

      <Card title="선택 문서">
        <div className="space-y-2 text-xs text-ink-3">
          {documents.length ? (
            documents.map((doc, index) => (
              <p key={index} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
                <b className="text-ink">{doc.label || "문서"}</b> ·{" "}
                {doc.file_name || doc.original_name || doc.document_id}
                <br />
                {doc.relative_path || ""}
                <br />
                exists {String(doc.exists)}
              </p>
            ))
          ) : (
            <p>상품명이 확정되지 않아 문서를 선택하지 않았습니다.</p>
          )}
        </div>
      </Card>
    </div>
  );
}
