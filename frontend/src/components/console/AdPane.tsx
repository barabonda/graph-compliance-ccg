"use client";

import { useMemo, useState } from "react";
import { PRODUCT_GROUPS } from "@/lib/labels";
import {
  type AdLine,
  type AnnotatedText,
  buildAdLines,
  buildCorrectedCopy,
  conditionalDisclosures,
  revisionFor,
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
    </>
  );
}

/** 선택된 이슈의 인라인 수정안 카드 — 화살표 아래 before→after. */
function InlineRevision({
  result,
  anchorId,
  resolved,
  onToggleResolve,
}: {
  result: ReviewOutput;
  anchorId: string;
  resolved: Set<string>;
  onToggleResolve: (id: string) => void;
}) {
  const revision = revisionFor(result, anchorId);
  if (!revision) return null;
  const isResolved = resolved.has(anchorId);
  return (
    <div className="mt-1.5 mb-1 flex gap-2.5 pl-1">
      <div className="flex flex-col items-center pt-1">
        <Icon name="arrowR" size={15} color="var(--brand)" style={{ transform: "rotate(90deg)" }} />
      </div>
      <div className="flex-1 overflow-hidden rounded-[11px] border border-brand-tint2 bg-surface">
        <div className="flex items-center justify-between gap-2 border-b border-line bg-brand-tint px-3 py-1.5">
          <span className="flex items-center gap-1.5 text-[11px] font-bold text-brand-2">
            <Icon name="spark" size={13} color="var(--brand)" /> 수정 제안 (권고)
          </span>
          <span className="font-mono text-[10px] text-ink-4">Revision LLM</span>
        </div>
        <div className="space-y-2 px-3 py-2.5">
          <div>
            <div className="mb-0.5 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-reject" />
              <span className="text-[10px] font-bold tracking-wider text-reject">BEFORE</span>
            </div>
            <div className="text-[13px] leading-relaxed text-[#8a2e26] line-through decoration-[#d6453a66]">
              {revision.before}
            </div>
          </div>
          <div>
            <div className="mb-0.5 flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-pass" />
              <span className="text-[10px] font-bold tracking-wider text-pass">AFTER</span>
            </div>
            <div className="text-[13px] leading-relaxed font-medium text-[#0c6b4a]">{revision.after}</div>
          </div>
          <button
            type="button"
            onClick={() => onToggleResolve(anchorId)}
            className={`mt-0.5 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-bold ${
              isResolved ? "bg-surface-3 text-ink-2" : "bg-brand text-white"
            }`}
          >
            <Icon name={isResolved ? "x" : "check"} size={14} />
            {isResolved ? "적용 취소" : "수정안 적용"}
          </button>
        </div>
      </div>
    </div>
  );
}

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
  const corrected = useMemo(
    () => buildCorrectedCopy(result, reviewedText, resolved),
    [result, reviewedText, resolved],
  );
  const selectedSentenceId = useMemo(() => {
    if (!selectedAnchorId) return "";
    const anchor = result.context_anchors?.find((item) => item.anchor_id === selectedAnchorId);
    if (!anchor) return "";
    return result.claims?.find((c) => c.claim_id === anchor.claim_id)?.sentence_id ?? "";
  }, [result, selectedAnchorId]);

  const conditional = conditionalDisclosures(result, reviewedText);
  const actionable = (result.anchor_display ?? []).filter((item) => item.display_role === "actionable").length;
  const productGroup =
    PRODUCT_GROUPS.find((item) => item.value === result.product_context?.product_group)?.label ??
    result.product_context?.product_group ??
    "";
  const matchedProduct = result.product_fact_context?.matched_product;

  // 선택된 이슈가 어느 줄에도 매칭 안 되면(문장 없음) 마지막 줄 뒤에 보여준다.
  const selectionInLines = lines.some((line) => line.sentenceId && line.sentenceId === selectedSentenceId);
  const showRevision = (line: AdLine, isLast: boolean) =>
    mode === "original" &&
    selectedAnchorId &&
    ((line.sentenceId && line.sentenceId === selectedSentenceId) || (!selectionInLines && isLast));

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
              {lines.map((line, index) => (
                <div key={line.key}>
                  <span className="whitespace-pre-wrap">
                    <LineText
                      annotated={line.annotated}
                      selectedAnchorId={selectedAnchorId}
                      resolved={resolved}
                      onSelectAnchor={onSelectAnchor}
                    />
                  </span>
                  {showRevision(line, index === lines.length - 1) && (
                    <InlineRevision
                      result={result}
                      anchorId={selectedAnchorId}
                      resolved={resolved}
                      onToggleResolve={onToggleResolve}
                    />
                  )}
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
              corrected.changedCount ? (
                <span>
                  적용된 수정안 {corrected.changedCount}건이 반영된 교정본입니다. 초록 구간이 변경된 문안입니다.
                </span>
              ) : (
                <span>아직 적용된 수정안이 없습니다. 원문에서 ‘수정안 적용’을 누르면 여기에 반영됩니다.</span>
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
              표시 구간을 클릭하면 그 자리에 수정안이 펼쳐지고, 우측에서 판정 근거를 확인할 수 있습니다.
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
          </>
        )}
      </div>
    </div>
  );
}
