"use client";

import { buildIssueCards, planItemsForAnchor, type HighlightTone } from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { EmptyState, Tag } from "../ui";
import { PaneHeader } from "./common";

interface Props {
  result: ReviewOutput;
  selectedAnchorId: string;
  resolved: Set<string>;
  onSelectAnchor: (anchorId: string) => void;
}

const TONE_COLOR: Record<HighlightTone, string> = {
  risk: "var(--reject)",
  review: "var(--revise)",
  "keep-warning": "var(--revise)",
  keep: "var(--pass)",
  scope: "var(--ink-4)",
};

const TONE_BG: Record<HighlightTone, string> = {
  risk: "var(--reject-bg)",
  review: "var(--revise-bg)",
  "keep-warning": "var(--revise-bg)",
  keep: "var(--pass-bg)",
  scope: "var(--surface-3)",
};

const TONE_WORD_SHORT: Record<HighlightTone, string> = {
  risk: "위반 의심",
  review: "검토 필요",
  "keep-warning": "위계 낮음",
  keep: "고지",
  scope: "범위",
};

export function RiskList({ result, selectedAnchorId, resolved, onSelectAnchor }: Props) {
  const cards = buildIssueCards(result);
  const resolvedCount = cards.filter((card) => resolved.has(card.id)).length;

  return (
    <div className="flex h-full flex-col border-r border-l border-line">
      <PaneHeader
        title="위험 카드"
        sub="Claim 단위 판정"
        right={<Tag tone={resolvedCount ? "ok" : undefined}>{resolvedCount}건 조치</Tag>}
      />
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {cards.length ? (
          cards.map((card) => {
            const selected =
              card.anchorId ? card.anchorId === selectedAnchorId : card.id === selectedAnchorId;
            const isResolved = resolved.has(card.id);
            const color = TONE_COLOR[card.tone];
            const [title, quote] = card.title.split(" — ");
            return (
              <button
                key={card.id}
                type="button"
                onClick={() => onSelectAnchor(card.anchorId ?? card.id)}
                className="relative rounded-[11px] p-3 text-left transition"
                style={{
                  border: selected ? `1.5px solid ${color}` : "1px solid var(--line)",
                  background: selected ? TONE_BG[card.tone] : "var(--surface)",
                  boxShadow: selected ? "none" : "var(--shadow-card)",
                  opacity: isResolved ? 0.72 : 1,
                }}
              >
                <span
                  className="absolute top-3 bottom-3 left-0 w-[3px] rounded-full"
                  style={{ background: isResolved ? "var(--pass)" : color }}
                />
                <div className="mb-1.5 flex items-center gap-2">
                  {isResolved ? (
                    <Tag tone="ok">✓ 수정안 적용</Tag>
                  ) : (
                    <span className="text-[11px] font-bold" style={{ color }}>
                      {TONE_WORD_SHORT[card.tone]}
                    </span>
                  )}
                  <span className="ml-auto text-[11px] font-bold" style={{ color: isResolved ? "var(--pass)" : color }}>
                    {isResolved ? "해소" : card.kind === "trackB" ? "Track B" : ""}
                  </span>
                </div>
                <div
                  className={`text-[13px] leading-snug font-semibold break-keep text-ink ${isResolved ? "line-through decoration-ink-4" : ""}`}
                >
                  {quote ?? title}
                </div>
                <div className="mt-1 text-[12px] text-ink-2">{quote ? title : ""}</div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {card.anchorId &&
                    [...new Set(planItemsForAnchor(result, card.anchorId).map((item) => item.principle).filter(Boolean))]
                      .slice(0, 3)
                      .map((principle) => <Tag key={principle}>{principle}</Tag>)}
                  {!card.anchorId && <Tag>{card.basis.split(" · ")[0]}</Tag>}
                </div>
              </button>
            );
          })
        ) : (
          <EmptyState>현재 문안 기준 별도 이슈가 없습니다.</EmptyState>
        )}
      </div>
    </div>
  );
}
