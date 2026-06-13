"use client";

import { useMemo, useState } from "react";
import { PRODUCT_GROUPS } from "@/lib/labels";
import {
  type AnnotatedText,
  buildAdLines,
  buildCorrectedCopy,
  buildDocumentDiff,
  conditionalDisclosures,
  correctedDocument,
} from "@/lib/selectors";
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
  onToggleResolve: (id: string) => void;
}

/** 한 줄(문장) 내부의 하이라이트 렌더링. */
function LineText({
  annotated,
  selectedAnchorId,
  resolved,
  onSelectAnchor,
}: {
  annotated: AnnotatedText;
  selectedAnchorId: string;
  resolved: Set<string>;
  onSelectAnchor: (anchorId: string) => void;
}) {
  return (
    <>
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
        const chip = segment.areaChip;
        // 상시 인라인 라벨은 노이즈 → 선택한 구간에만 라벨을 보여준다.
        const showLabel = chip && selectedAnchorId && chip.anchorId === selectedAnchorId;
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
    </>
  );
}

/** 선택된 이슈의 인라인 수정안 카드 — 화살표 아래 before→after. */
export function AdPane({
  result,
  reviewedText,
  reviewTitle,
  channelLabel,
  selectedAnchorId,
  resolved,
  onSelectAnchor,
  onToggleResolve,
}: Props) {
  const [mode, setMode] = useState<"original" | "corrected">("original");
  const lines = useMemo(() => buildAdLines(result, reviewedText), [result, reviewedText]);
  // 교정본 = 백엔드의 일관 재작성 전체 문서(원문↔교정본 diff). 없으면(구버전 데이터)
  // 기존 per-span 짜깁기로 폴백.
  const correctedDoc = useMemo(() => correctedDocument(result), [result]);
  const corrected = useMemo(
    () =>
      correctedDoc
        ? buildDocumentDiff(reviewedText, correctedDoc)
        : buildCorrectedCopy(result, reviewedText, resolved),
    [result, reviewedText, resolved, correctedDoc],
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
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-line bg-surface-2 p-0.5">
              <button
                type="button"
                onClick={() => setMode("original")}
                className={`rounded-md px-2.5 py-1 text-[11.5px] font-bold ${mode === "original" ? "bg-surface text-ink shadow-card" : "text-ink-3"}`}
              >
                원문
              </button>
              <button
                type="button"
                onClick={() => setMode("corrected")}
                className={`rounded-md px-2.5 py-1 text-[11.5px] font-bold ${mode === "corrected" ? "bg-surface text-pass shadow-card" : "text-ink-3"}`}
              >
                교정본{corrected.changedCount ? ` ${corrected.changedCount}` : ""}
              </button>
            </div>
            <Tag>
              <Icon name="alert" size={13} color="var(--reject)" style={{ marginRight: 4 }} />
              위험 {actionable}
            </Tag>
          </div>
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

          {mode === "original" ? (
            <div className="px-5.5 py-5 text-[16px] leading-[1.95] break-keep text-ink">
              {lines.map((line) => (
                <div key={line.key}>
                  <span className="whitespace-pre-wrap">
                    <LineText
                      annotated={line.annotated}
                      selectedAnchorId={selectedAnchorId}
                      resolved={resolved}
                      onSelectAnchor={onSelectAnchor}
                    />
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="px-5.5 py-5 text-[16px] leading-[1.95] break-keep whitespace-pre-wrap text-ink">
              {corrected.segments.map((seg, index) =>
                seg.changed ? (
                  <mark
                    key={index}
                    className="rounded bg-pass-bg px-0.5 font-medium text-[#0c6b4a] decoration-clone"
                    style={{ boxShadow: "inset 0 -2px 0 var(--pass)" }}
                  >
                    {seg.text}
                  </mark>
                ) : (
                  <span key={index}>{seg.text}</span>
                ),
              )}
            </div>
          )}

          <div className="border-t border-line bg-surface-2 px-5.5 py-2.5 text-[11.5px] leading-relaxed text-ink-3">
            {mode === "corrected" ? (
              correctedDoc ? (
                <span>
                  광고 전체를 일관되게 재작성한 교정본입니다. 초록 구간이 변경된 부분이며{" "}
                  {corrected.changedCount}곳이 수정되었습니다.
                </span>
              ) : corrected.changedCount ? (
                <span>
                  적용된 수정안 {corrected.changedCount}건이 반영된 교정본입니다. 초록 구간이 변경된 문안입니다.
                </span>
              ) : (
                <span>전체 교정본이 아직 생성되지 않았습니다. 원문에서 개별 수정안을 확인하세요.</span>
              )
            ) : (
              <span>
                {channelLabel}
                {matchedProduct ? ` · 대상 상품: ${matchedProduct}` : ""} · 원문 {reviewedText.length}자
              </span>
            )}
          </div>
        </div>

        {mode === "original" && (
          <>
            <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-ink-3">
              <Icon name="alert" size={14} color="var(--ink-4)" />
              표시 구간을 클릭하면 우측 판정 상세에서 근거와 수정안을 확인할 수 있습니다.
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-ink-3" aria-label="범례">
              <span><i className="legend-token-risk not-italic">위반 의심</i></span>
              <span><i className="legend-token-review not-italic">검토 필요</i></span>
              <span><i className="legend-token-keep not-italic">유지 고지</i></span>
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
          </>
        )}
      </div>
    </div>
  );
}
