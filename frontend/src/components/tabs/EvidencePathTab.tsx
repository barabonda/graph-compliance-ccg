"use client";

import {
  chainNodeLabel,
  chainsForAnchor,
  claimById,
  claimQualifiers,
  planItemsForAnchor,
  productClaimFactsForAnchor,
  productComparisonsForClaimFact,
  prominenceDiagnosticsForAnchor,
  safeAlternative,
  sentenceById,
  shorten,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { EmptyState, Tag } from "../ui";

interface Props {
  result: ReviewOutput | null;
  selectedAnchorId: string;
}

interface EvidenceStep {
  label: string;
  text: string;
  caption: string;
}

export function EvidencePathTab({ result, selectedAnchorId }: Props) {
  const anchor = result?.context_anchors?.find((item) => item.anchor_id === selectedAnchorId);
  if (!result || !anchor) {
    return <EmptyState>선택된 경로가 없습니다. 하이라이트나 Claim 카드를 먼저 선택하세요.</EmptyState>;
  }

  const claim = claimById(result, anchor.claim_id);
  const sentence = claim?.sentence_id ? sentenceById(result, claim.sentence_id) : undefined;
  const claimFacts = productClaimFactsForAnchor(result, anchor).slice(0, 2);
  const comparisons = claimFacts
    .flatMap((fact) => productComparisonsForClaimFact(result, fact.claim_fact_id))
    .slice(0, 2);
  const diagnostics = prominenceDiagnosticsForAnchor(result, anchor);
  const plans = planItemsForAnchor(result, anchor.anchor_id).slice(0, 2);
  const legalChains = chainsForAnchor(result.policy_evidence_chains?.legal_basis_chains, anchor.anchor_id).filter(
    (item) => item.status === "FOUND",
  );
  const revision = (result.revision_suggestions ?? []).find((item) => item.anchor_id === anchor.anchor_id);

  const qualifierAndFactText =
    [
      ...claimQualifiers(result, anchor.claim_id).map((item) => item.text),
      ...claimFacts.map((item) => `${item.fact_type}: ${item.value} ${item.qualifier ?? ""}`.trim()),
    ]
      .filter(Boolean)
      .join("\n") || anchor.hypernyms.map((item) => item.hypernym).join("\n");

  const comparisonText =
    result.product_fact_context?.extraction_status === "NEEDS_PRODUCT_SELECTION"
      ? "상품을 선택하지 않아 금리/우대조건/예금자보호 문구의 사실 대조가 완료되지 않았습니다."
      : comparisons.map((item) => `${item.status}: ${item.rationale || item.evidence_text || ""}`.trim()).join("\n") ||
        "대응 ProductFact/Disclosure 비교 결과 없음";

  const prominence = diagnostics.length
    ? diagnostics.map((item) => `${item.diagnostic_code}: ${item.message || item.evidence || ""}`).join("\n")
    : claim?.sentence_id
      ? "선택 문구 기준 현저성 부족 신호 없음"
      : "문장 위계 정보 없음";

  const steps: EvidenceStep[] = [
    { label: "Claim", text: anchor.span.text, caption: "심사 대상 문구" },
    { label: "Qualifier / ClaimFact", text: qualifierAndFactText, caption: "문제 표현과 fact-like 주장" },
    { label: "ProductFact / Disclosure", text: comparisonText, caption: "상품문서 사실 또는 필수고지 상태" },
    { label: "Prominence", text: prominence, caption: "고지 존재와 표시 위계" },
    {
      label: "ConsumerEffect",
      text:
        claim?.consumer_effect ||
        result.overall_impression_judgment?.representative_consumer_impression ||
        "소비자 영향 미상",
      caption: "대표 소비자 인상",
    },
    {
      label: "CU",
      text: plans.map((item) => item.risk_title || item.subject || item.principle).filter(Boolean).join("\n") || "CUPlan 없음",
      caption: "정책 판단 단위",
    },
    {
      label: "LegalBasis",
      text:
        legalChains.flatMap((chain) => chain.basis_nodes ?? []).map(chainNodeLabel).join("\n") ||
        plans.map((item) => item.source_article).filter(Boolean).join("\n") ||
        "법적 근거 미연결",
      caption: "금소법/감독규정/심의기준",
    },
    { label: "Revision", text: revision?.after || safeAlternative(anchor.span.text), caption: "수정 또는 유지 조치" },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Tag>선택 Claim</Tag>
        <strong className="text-sm">{anchor.span.text}</strong>
        {sentence && <Tag>{sentence.role || "sentence"}</Tag>}
      </div>
      <ol className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, index) => (
          <li key={step.label} className="relative rounded-lg border border-line bg-panel p-3">
            <div className="mb-1 flex items-center gap-2">
              <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-accent text-[11px] font-bold text-white">
                {index + 1}
              </span>
              <strong className="text-[13px]">{step.label}</strong>
            </div>
            <p className="text-xs leading-relaxed whitespace-pre-line text-foreground/90">{shorten(step.text, 180)}</p>
            <span className="mt-1 block text-[11px] text-muted">{step.caption}</span>
            {index < steps.length - 1 && (
              <span className="absolute top-1/2 -right-2 hidden -translate-y-1/2 text-line-strong xl:inline">→</span>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
