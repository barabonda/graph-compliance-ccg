"use client";

import { buildIssueCards, planItemsForAnchor, type HighlightTone } from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState, Tag } from "../ui";
import { PaneHeader } from "./common";

interface Props {
  result: ReviewOutput;
  selectedAnchorId: string;
  resolved: Set<string>;
  onSelectAnchor: (anchorId: string) => void;
}

export const TONE_COLOR: Record<HighlightTone, string> = {
  risk: "var(--reject)",
  review: "var(--revise)",
  "keep-warning": "var(--revise)",
  keep: "var(--pass)",
  scope: "var(--ink-4)",
};

export const TONE_BG: Record<HighlightTone, string> = {
  risk: "var(--reject-bg)",
  review: "var(--revise-bg)",
  "keep-warning": "var(--revise-bg)",
  keep: "var(--pass-bg)",
  scope: "var(--surface-3)",
};

export const TONE_WORD_SHORT: Record<HighlightTone, string> = {
  risk: "위반 의심",
  review: "검토 필요",
  "keep-warning": "위계 낮음",
  keep: "고지",
  scope: "범위",
};

function SevPill({ tone }: { tone: HighlightTone }) {
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11px] font-bold whitespace-nowrap"
      style={{ color: TONE_COLOR[tone], background: TONE_BG[tone] }}
    >
      {TONE_WORD_SHORT[tone]}
    </span>
  );
}

export function RiskList({ result, selectedAnchorId, resolved, onSelectAnchor }: Props) {
  const cards = buildIssueCards(result);
  const resolvedCount = cards.filter((card) => resolved.has(card.id)).length;

  return (
    <div className="flex h-full flex-col border-r border-l border-line">
      <PaneHeader
        icon="review"
        title="위험 카드"
        sub="Claim 단위 판정"
        right={<Tag tone={resolvedCount ? "ok" : undefined}>{resolvedCount}건 조치</Tag>}
      />
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {cards.length ? (
          cards.map((card) => {
            const selected = card.anchorId ? card.anchorId === selectedAnchorId : card.id === selectedAnchorId;
            const isResolved = resolved.has(card.id);
            const color = TONE_COLOR[card.tone];
            const principles = card.anchorId
              ? [...new Set(planItemsForAnchor(result, card.anchorId).map((item) => item.principle).filter(Boolean))]
              : [];
            return (
              <button
                key={card.id}
                type="button"
                onClick={() => onSelectAnchor(card.anchorId ?? card.id)}
                className="relative rounded-[11px] p-3 pl-3.5 text-left transition"
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
                {/* 헤더 행: 코드 · 심각도 · 판정 */}
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="font-mono text-[11px] font-bold text-ink-4">{card.code}</span>
                  {isResolved ? (
                    <Tag tone="ok">
                      <Icon name="check" size={12} style={{ marginRight: 3 }} /> 수정안 적용
                    </Tag>
                  ) : (
                    <SevPill tone={card.tone} />
                  )}
                  <span
                    className="ml-auto text-[11.5px] font-bold"
                    style={{ color: isResolved ? "var(--pass)" : color }}
                  >
                    {isResolved ? "해소" : card.kind === "trackB" ? "Track B" : card.kind === "disclosure" ? "누락" : ""}
                  </span>
                </div>
                {/* 인용 문구 */}
                <div
                  className={`text-[13.5px] leading-[1.45] font-semibold break-keep text-ink ${
                    isResolved ? "line-through decoration-ink-4" : ""
                  }`}
                >
                  “{card.quote}”
                </div>
                {/* 위반 유형 */}
                <div className="mt-1 text-[12.5px] text-ink-2">{card.label}</div>
                {/* 원칙 태그 + 근거 */}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {principles.slice(0, 3).map((principle) => (
                    <Tag key={principle}>{principle}</Tag>
                  ))}
                  <span className="ml-auto max-w-[55%] truncate font-mono text-[10.5px] text-ink-4">
                    {card.basis.split(" · ")[0]}
                  </span>
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
