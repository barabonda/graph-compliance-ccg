"use client";

import { useMemo } from "react";
import { PRODUCT_GROUPS } from "@/lib/labels";
import { annotateText, conditionalDisclosures, highlightCandidates } from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { Tag } from "../ui";
import { PaneHeader } from "./common";

interface Props {
  result: ReviewOutput;
  reviewedText: string;
  reviewTitle: string;
  channelLabel: string;
  selectedAnchorId: string;
  resolved: Set<string>;
  onSelectAnchor: (anchorId: string) => void;
}

export function AdPane({
  result,
  reviewedText,
  reviewTitle,
  channelLabel,
  selectedAnchorId,
  resolved,
  onSelectAnchor,
}: Props) {
  const annotated = useMemo(
    () => annotateText(reviewedText, highlightCandidates(result, reviewedText, "")),
    [result, reviewedText],
  );
  const conditional = conditionalDisclosures(result, reviewedText);
  const actionable = (result.anchor_display ?? []).filter((item) => item.display_role === "actionable").length;
  const productGroup =
    PRODUCT_GROUPS.find((item) => item.value === result.product_context?.product_group)?.label ??
    result.product_context?.product_group ??
    "";
  const matchedProduct = result.product_fact_context?.matched_product;

  return (
    <div className="flex h-full min-w-0 flex-col">
      <PaneHeader
        icon="eye"
        title="광고 원문"
        sub={channelLabel}
        right={
          <Tag>
            <Icon name="alert" size={13} color="var(--reject)" style={{ marginRight: 4 }} />
            위험 표현 {actionable}
          </Tag>
        }
      />
      <div className="flex-1 overflow-y-auto px-5 pt-4 pb-7">
        {/* 광고 크리에이티브 미리보기 */}
        <div className="overflow-hidden rounded-[14px] border border-line bg-white shadow-panel">
          <div className="px-5.5 py-5 text-white" style={{ background: "linear-gradient(135deg,#1d3a6e,#2f6df0)" }}>
            <div className="mb-3 flex items-center justify-between">
              <span className="font-mono text-[11px] tracking-wider opacity-85">JB금융그룹 · 사전심의 초안</span>
              <span className="rounded-full bg-white/18 px-2.5 py-0.5 text-[11px] font-bold">{productGroup || "광고"}</span>
            </div>
            <div className="text-[21px] leading-snug font-extrabold tracking-tight break-keep">
              {reviewTitle || "광고 문안"}
            </div>
          </div>
          <div className="px-5.5 py-5 text-[16px] leading-[1.95] break-keep whitespace-pre-wrap text-ink">
            {annotated.segments.map((segment) => {
              const interactive = segment.area ?? segment.token;
              const anchorId = segment.token?.anchorId || segment.area?.anchorId || "";
              const isSelected = Boolean(
                selectedAnchorId &&
                  (segment.area?.id === selectedAnchorId || segment.token?.anchorId === selectedAnchorId),
              );
              const isResolved = Boolean(anchorId && resolved.has(anchorId));
              const body = interactive ? (
                <button
                  key={`${segment.key}_text`}
                  type="button"
                  title={segment.token?.tooltip ?? segment.area?.tooltip}
                  onClick={() => anchorId && onSelectAnchor(anchorId)}
                  className={[
                    "hl",
                    segment.area ? `hl-area-${segment.area.tone}` : "",
                    segment.token ? `hl-token-${segment.token.tone}` : "",
                    isSelected ? "is-selected" : "",
                    isResolved ? "is-resolved" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {segment.text}
                </button>
              ) : (
                <span key={`${segment.key}_text`}>{segment.text}</span>
              );
              // 인라인 라벨은 선택된 이슈와 고지 구간에만 — 원문은 문서로 읽혀야 한다.
              const chip = segment.areaChip;
              const showLabel =
                chip &&
                (segment.area?.id?.startsWith("disclosure_") ||
                  chip.tone === "keep" ||
                  chip.tone === "keep-warning" ||
                  (selectedAnchorId && chip.anchorId === selectedAnchorId));
              const label = showLabel ? (
                <button
                  key={`${segment.key}_label`}
                  type="button"
                  title={chip.tooltip}
                  onClick={() => chip.anchorId && onSelectAnchor(chip.anchorId)}
                  className={`ann-label ann-label-${chip.tone}`}
                >
                  {isResolved ? "해소 ✓" : chip.label}
                </button>
              ) : null;
              return label ? [body, label] : body;
            })}
          </div>
          <div className="border-t border-line bg-surface-2 px-5.5 py-2.5 text-[11.5px] leading-relaxed text-ink-3">
            {channelLabel}
            {matchedProduct ? ` · 대상 상품: ${matchedProduct}` : ""} · 원문 {reviewedText.length}자
            {annotated.hiddenByOverlap > 0 ? ` · 겹침 정리 ${annotated.hiddenByOverlap}` : ""}
          </div>
        </div>

        {/* 힌트 + 범례 */}
        <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-ink-3">
          <Icon name="alert" size={14} color="var(--ink-4)" />
          표시 구간을 클릭하면 우측에서 해당 Claim의 판정 근거를 확인할 수 있습니다.
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-ink-3" aria-label="범례">
          <span><i className="legend-token-risk not-italic">위반 의심</i></span>
          <span><i className="legend-token-review not-italic">검토 필요</i></span>
          <span><i className="legend-token-keep not-italic">유지 고지</i></span>
          <span><i className="legend-area-keep-warning not-italic">고지 있음 · 위계 낮음</i></span>
        </div>

        {conditional.length > 0 && (
          <div className="mt-3 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink-3">
            <strong className="text-ink">유지해야 할 고지</strong>
            <span className="ml-2 inline-flex flex-wrap gap-1.5 align-middle">
              {conditional.map((item) => (
                <Tag key={item} tone="ok">
                  {item}
                </Tag>
              ))}
            </span>
            <span className="ml-2">— 초록 표시 구간은 수정 시 삭제하면 안 되는 문구입니다.</span>
          </div>
        )}
      </div>
    </div>
  );
}
