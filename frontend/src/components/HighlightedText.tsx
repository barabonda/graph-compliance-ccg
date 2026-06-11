"use client";

import { useMemo } from "react";
import { PRINCIPLES, type PrincipleKey } from "@/lib/labels";
import {
  annotateText,
  conditionalDisclosures,
  highlightCandidates,
  type HighlightChip,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { EmptyState, Tag } from "./ui";

interface Props {
  result: ReviewOutput | null;
  reviewedText: string;
  selectedAnchorId: string;
  selectedPrinciple: PrincipleKey | "";
  onSelectAnchor: (anchorId: string) => void;
}

/** Color + shape legend. 면(배경) = 문장/Claim 맥락, 점(밑줄) = 판단 대상 표현. */
function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted" aria-label="하이라이트 범례">
      <span>
        <i className="legend-token-risk not-italic">위반 의심</i>
      </span>
      <span>
        <i className="legend-token-review not-italic">검토 필요</i>
      </span>
      <span>
        <i className="legend-token-keep not-italic">유지 고지</i>
      </span>
      <span>
        <i className="legend-area-keep-warning not-italic">고지 있음 · 위계 낮음</i>
      </span>
      <span>
        <i className="legend-area-scope not-italic">범위/검토됨</i>
      </span>
      <span className="text-muted/80">라벨은 선택·고지 구간에만 표시 — 나머지는 hover/클릭으로 확인</span>
    </div>
  );
}

export function HighlightedText({ result, reviewedText, selectedAnchorId, selectedPrinciple, onSelectAnchor }: Props) {
  const annotated = useMemo(() => {
    if (!result || !reviewedText) return null;
    return annotateText(reviewedText, highlightCandidates(result, reviewedText, selectedPrinciple));
  }, [result, reviewedText, selectedPrinciple]);

  if (!result || !annotated) {
    return (
      <div className="space-y-3">
        <Legend />
        <EmptyState>심사할 광고 원문이 여기에 표시됩니다.</EmptyState>
      </div>
    );
  }

  const totalActionable = (result.anchor_display ?? []).filter((item) => item.display_role === "actionable").length;
  const conditional = conditionalDisclosures(result, reviewedText);
  const principleLabel = PRINCIPLES.find((item) => item.key === selectedPrinciple)?.label;

  /**
   * Inline labels stay rare so the copy reads as a document, not an NER demo:
   *   1. the selected issue's claim — its human label at the claim end
   *   2. disclosure areas (유지 고지 / 고지 있음·위계 낮음) — always labelled,
   *      because "지킬 것" must be visible without interaction
   * Everything else is hover tooltip + click-through to the issue panel.
   */
  const visibleLabel = (chip: HighlightChip | null, areaId?: string): HighlightChip | null => {
    if (!chip) return null;
    const isDisclosure = areaId?.startsWith("disclosure_");
    const isSelectedIssue = Boolean(selectedAnchorId) && chip.anchorId === selectedAnchorId;
    if (isDisclosure || chip.tone === "keep" || chip.tone === "keep-warning" || isSelectedIssue) return chip;
    return null;
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        <span>원문 {reviewedText.length}자</span>
        <span>표시 {annotated.visibleCount}</span>
        <span>판단 anchor {totalActionable}</span>
        {annotated.hiddenByOverlap > 0 && <span>겹침 정리 {annotated.hiddenByOverlap}</span>}
        {principleLabel && <span className="font-bold text-accent">필터 {principleLabel}</span>}
      </div>
      <Legend />
      <div className="rounded-lg border border-line bg-panel-soft p-4 text-[15px] leading-8 break-keep whitespace-pre-wrap">
        {annotated.segments.map((segment) => {
          const interactive = segment.area ?? segment.token;
          // Match on area.id (claim areas use the anchor id as their id) so
          // selection doesn't bleed into disclosure areas that merely
          // reference the benefit anchor via anchorId.
          const isSelected = Boolean(
            selectedAnchorId &&
              (segment.area?.id === selectedAnchorId || segment.token?.anchorId === selectedAnchorId),
          );
          const body = interactive ? (
            <button
              key={`${segment.key}_text`}
              type="button"
              title={segment.token?.tooltip ?? segment.area?.tooltip}
              onClick={() => {
                const target = segment.token?.anchorId || segment.area?.anchorId;
                if (target) onSelectAnchor(target);
              }}
              className={[
                "hl",
                segment.area ? `hl-area-${segment.area.tone}` : "",
                segment.token ? `hl-token-${segment.token.tone}` : "",
                isSelected ? "is-selected" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {segment.text}
            </button>
          ) : (
            <span key={`${segment.key}_text`}>{segment.text}</span>
          );
          const label = visibleLabel(segment.areaChip, segment.area?.id);
          const chip = label ? (
            <button
              key={`${segment.key}_label`}
              type="button"
              title={label.tooltip}
              onClick={() => label.anchorId && onSelectAnchor(label.anchorId)}
              className={`ann-label ann-label-${label.tone}`}
            >
              {label.label}
            </button>
          ) : null;
          return chip ? [body, chip] : body;
        })}
      </div>
      <div className="rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-muted">
        {conditional.length ? (
          <>
            <strong className="text-foreground">유지해야 할 고지</strong>
            <span className="ml-2 inline-flex flex-wrap gap-1.5 align-middle">
              {conditional.map((item) => (
                <Tag key={item} tone="ok">
                  {item}
                </Tag>
              ))}
            </span>
            <span className="ml-2">— 원문에서 초록 표시 구간은 수정 시 삭제하면 안 되는 문구입니다.</span>
          </>
        ) : (
          "통과 후보도 완전 면책이 아니라 현재 문안 기준의 1차 검토 결과입니다. 고지 문구가 있는 경우 삭제하지 마세요."
        )}
      </div>
    </div>
  );
}
