"use client";

import { useEffect, useRef } from "react";
import {
  buildIssueCards,
  chainNodeLabel,
  chainsForAnchor,
  effectiveJudgmentsForAnchor,
  planItemsForAnchor,
  safeAlternative,
  shorten,
  type HighlightTone,
  type IssueCardModel,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { EmptyState, KeyValueText, Tag } from "./ui";

interface Props {
  result: ReviewOutput | null;
  selectedAnchorId: string;
  onSelectAnchor: (anchorId: string) => void;
}

const CARD_RING: Record<HighlightTone, string> = {
  risk: "border-danger/60 ring-1 ring-danger/30",
  review: "border-warn/60 ring-1 ring-warn/30",
  "keep-warning": "border-warn/60 ring-1 ring-warn/30",
  keep: "border-ok/60 ring-1 ring-ok/30",
  scope: "border-line-strong ring-1 ring-line",
};

const TONE_TEXT: Record<HighlightTone, string> = {
  risk: "text-danger",
  review: "text-warn",
  "keep-warning": "text-warn",
  keep: "text-ok",
  scope: "text-muted",
};

/** 근거 조문 — compact legal basis for the selected anchor card. */
function LegalBasis({ result, anchorId }: { result: ReviewOutput; anchorId: string }) {
  const judgments = effectiveJudgmentsForAnchor(result, anchorId).filter((item) =>
    ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict),
  );
  const plans = planItemsForAnchor(result, anchorId);
  const chains = chainsForAnchor(result.policy_evidence_chains?.legal_basis_chains, anchorId).filter(
    (chain) => chain.status === "FOUND",
  );
  if (!judgments.length && !chains.length) {
    return <p className="text-xs text-muted">연결된 근거 조문이 없습니다. 감사 추적 탭의 진단을 확인하세요.</p>;
  }
  return (
    <div className="space-y-2">
      {judgments.map((judgment) => {
        const plan = plans.find((item) => item.plan_item_id === judgment.plan_item_id);
        return (
          <div key={judgment.judgment_id} className="rounded-md border border-line bg-panel-soft p-2.5 text-xs">
            <div className="mb-1 flex flex-wrap gap-1.5">
              <Tag>{plan?.source_article || "조항 미상"}</Tag>
              <Tag>{plan?.principle || "원칙 미상"}</Tag>
              <Tag>score {Number(judgment.score ?? 0).toFixed(2)}</Tag>
            </div>
            {plan?.risk_title && <strong className="block text-foreground">{plan.risk_title}</strong>}
            <p className="mt-1 leading-relaxed text-muted">{shorten(judgment.why, 240)}</p>
          </div>
        );
      })}
      {chains.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {chains
            .flatMap((chain) => chain.basis_nodes ?? [])
            .slice(0, 6)
            .map((node, index) => (
              <Tag key={index}>{chainNodeLabel(node)}</Tag>
            ))}
        </div>
      )}
    </div>
  );
}

/** 수정안 — before/after for the selected anchor card. */
function Revision({ result, anchorId }: { result: ReviewOutput; anchorId: string }) {
  const suggestion = (result.revision_suggestions ?? []).find((item) => item.anchor_id === anchorId);
  const anchor = result.context_anchors?.find((item) => item.anchor_id === anchorId);
  const before = suggestion?.before ?? anchor?.span.text ?? "";
  const after = suggestion?.after ?? safeAlternative(before);
  return (
    <div className="space-y-2 text-xs">
      <KeyValueText
        items={[
          ["Before", before],
          ["After", after],
        ]}
      />
      {suggestion?.required_disclosures?.length ? (
        <div>
          <b className="text-foreground">필요 고지</b>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {suggestion.required_disclosures.map((item, index) => (
              <Tag key={index} tone="ok">
                {item}
              </Tag>
            ))}
          </div>
        </div>
      ) : null}
      {suggestion?.notes_for_reviewer && (
        <p className="leading-relaxed text-muted">{suggestion.notes_for_reviewer}</p>
      )}
    </div>
  );
}

function TrackBDetail({ result }: { result: ReviewOutput }) {
  const trackB = result.overall_impression_judgment ?? {};
  return (
    <div className="space-y-2 text-xs">
      <p className="leading-relaxed text-muted">{trackB.representative_consumer_impression}</p>
      {(trackB.misleading_factors ?? []).length > 0 && (
        <ul className="list-disc space-y-1 pl-4 text-muted">
          {(trackB.misleading_factors ?? []).map((factor, index) => (
            <li key={index}>{factor}</li>
          ))}
        </ul>
      )}
      <details>
        <summary className="cursor-pointer font-semibold text-foreground">근거 경로 (Claim → ConsumerEffect)</summary>
        <div className="mt-1.5 space-y-2 text-muted">
          {(trackB.evidence_paths ?? []).map((path, index) => (
            <p key={index} className="border-t border-line pt-1.5 first:border-t-0 first:pt-0">
              <b className="text-foreground">{path.claim}</b>
              <br />
              {path.implicature || path.meaning}
              <br />→ {path.consumer_effect}
            </p>
          ))}
        </div>
      </details>
    </div>
  );
}

function IssueCard({
  result,
  card,
  selected,
  onSelect,
}: {
  result: ReviewOutput;
  card: IssueCardModel;
  selected: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selected]);

  return (
    <div
      ref={ref}
      className={`rounded-lg border bg-panel p-3.5 transition ${
        selected ? CARD_RING[card.tone] : "border-line hover:border-line-strong"
      }`}
    >
      <button type="button" onClick={onSelect} className="block w-full text-left">
        <strong className={`text-[13.5px] leading-snug ${selected ? TONE_TEXT[card.tone] : "text-foreground"}`}>
          {card.title}
        </strong>
        <p className="mt-0.5 text-xs text-muted">{card.basis}</p>
      </button>
      {selected && (
        <div className="mt-2.5 space-y-2.5 border-t border-line pt-2.5">
          {card.rationale && <p className="text-xs leading-relaxed text-foreground/90">{card.rationale}</p>}
          {card.kind === "anchor" && card.anchorId && (
            <>
              <details>
                <summary className="cursor-pointer text-xs font-bold text-foreground">근거 조문</summary>
                <div className="mt-1.5">
                  <LegalBasis result={result} anchorId={card.anchorId} />
                </div>
              </details>
              <details>
                <summary className="cursor-pointer text-xs font-bold text-foreground">수정안 보기</summary>
                <div className="mt-1.5">
                  <Revision result={result} anchorId={card.anchorId} />
                </div>
              </details>
            </>
          )}
          {card.kind === "trackB" && <TrackBDetail result={result} />}
        </div>
      )}
    </div>
  );
}

export function IssuePanel({ result, selectedAnchorId, onSelectAnchor }: Props) {
  if (!result) {
    return <EmptyState>Review를 실행하면 이슈 카드가 여기에 표시됩니다.</EmptyState>;
  }
  const cards = buildIssueCards(result);
  if (!cards.length) {
    return <EmptyState>현재 문안 기준 별도 이슈 카드가 없습니다. 상품 사실/필수 고지 상태는 탭에서 확인하세요.</EmptyState>;
  }
  return (
    <div className="space-y-2">
      {cards.map((card) => (
        <IssueCard
          key={card.id}
          result={result}
          card={card}
          selected={card.anchorId ? card.anchorId === selectedAnchorId : card.id === selectedAnchorId}
          onSelect={() => onSelectAnchor(card.anchorId ?? card.id)}
        />
      ))}
      <p className="pt-1 text-[11px] leading-relaxed text-muted">
        카드를 선택하면 원문에서 해당 구간이 강조됩니다. 전체 판단·예외·집계는 아래 이슈 상세 탭에서 확인하세요.
      </p>
    </div>
  );
}
