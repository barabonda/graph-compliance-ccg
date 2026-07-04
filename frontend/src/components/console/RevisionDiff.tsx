"use client";

import { useMemo, useState } from "react";
import { abbreviateLawNames } from "@/lib/labels";
import { buildRevisionDiff, correctedTextFromDiff, type RevisionDiffLine } from "@/lib/revisionDiff";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";

/**
 * 수정안 unified diff — GitHub 코드리뷰 문법.
 * 원문 모드와 같은 크리에이티브 카드(그라데이션 배너) 안에 diff 를 담는다.
 * `-` 줄에 커서를 올리면 위험 이유, `+` 줄은 수정 이유가 뜨고,
 * 클릭하면 해당 문구의 판정 상세(우측 패널)로 연결된다.
 * 줄 안에서 실제 바뀐 단어 구간은 word-diff 로 한 번 더 강조한다.
 */
const LINE_STYLE: Record<RevisionDiffLine["type"], { symbol: string; bg: string; gutter: string }> = {
  context: { symbol: "", bg: "transparent", gutter: "var(--ink-4)" },
  del: { symbol: "−", bg: "var(--reject-bg)", gutter: "var(--reject)" },
  add: { symbol: "+", bg: "var(--pass-bg)", gutter: "var(--pass)" },
};

const STRONG_STYLE: Record<"del" | "add", React.CSSProperties> = {
  del: { background: "color-mix(in srgb, var(--reject) 22%, transparent)", borderRadius: 3 },
  add: { background: "color-mix(in srgb, var(--pass) 24%, transparent)", borderRadius: 3 },
};

function LineBody({ line }: { line: RevisionDiffLine }) {
  if (line.segments && (line.type === "del" || line.type === "add")) {
    return (
      <>
        {line.segments.map((segment, index) =>
          segment.strong ? (
            <mark key={index} className="px-0.5 font-bold text-inherit" style={STRONG_STYLE[line.type as "del" | "add"]}>
              {segment.text}
            </mark>
          ) : (
            <span key={index}>{segment.text}</span>
          ),
        )}
      </>
    );
  }
  return <>{line.text || " "}</>;
}

function DiffLine({
  line,
  selected,
  onSelectAnchor,
}: {
  line: RevisionDiffLine;
  selected: boolean;
  onSelectAnchor: (anchorId: string) => void;
}) {
  const style = LINE_STYLE[line.type];
  const interactive = Boolean(line.anchorId);
  const hasTooltip = Boolean(line.reason || line.basis);

  return (
    <div
      className={`group relative flex ${interactive ? "cursor-pointer" : ""}`}
      style={{
        background: style.bg,
        boxShadow: selected ? "inset 3px 0 0 var(--brand)" : undefined,
      }}
      onClick={interactive ? () => onSelectAnchor(line.anchorId!) : undefined}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      onKeyDown={interactive ? (e) => e.key === "Enter" && onSelectAnchor(line.anchorId!) : undefined}
    >
      <span
        className="w-7 shrink-0 pt-[4px] text-center font-mono text-[13px] font-bold select-none"
        style={{ color: style.gutter }}
        aria-hidden
      >
        {style.symbol}
      </span>
      <span
        className={`min-w-0 flex-1 py-[4px] pr-3 leading-[1.65] break-keep ${
          line.type === "context" ? "text-[12.5px] text-ink-4" : "text-[13.5px] font-medium text-ink"
        } ${line.type === "del" ? "line-through decoration-[color:var(--reject)]/40" : ""}`}
      >
        <LineBody line={line} />
      </span>
      {hasTooltip && (
        <div className="pointer-events-none absolute top-full right-2 left-8 z-30 hidden group-hover:block">
          <div className="mt-0.5 rounded-[10px] border border-line bg-surface px-3 py-2 shadow-panel">
            <div className="text-[10px] font-bold tracking-wider text-ink-4">
              {line.type === "del" ? "위험 이유" : "수정 이유"}
              {line.label ? ` · ${line.label}` : ""}
            </div>
            {line.reason && <p className="m-0 mt-1 text-[12px] leading-relaxed break-keep text-ink-2">{line.reason}</p>}
            {line.basis && (
              <div className="mt-1 text-[11px] text-ink-4">{abbreviateLawNames(line.basis)}</div>
            )}
            {interactive && <div className="mt-1 text-[10.5px] font-semibold text-brand-2">클릭하면 판정 상세로 이동</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export function RevisionDiff({
  result,
  reviewedText,
  reviewTitle,
  productGroup,
  selectedAnchorId,
  onSelectAnchor,
}: {
  result: ReviewOutput;
  reviewedText: string;
  reviewTitle?: string;
  productGroup?: string;
  selectedAnchorId: string;
  onSelectAnchor: (anchorId: string) => void;
}) {
  const diff = useMemo(() => buildRevisionDiff(result, reviewedText), [result, reviewedText]);
  const hasChanges = diff.changedCount > 0 || diff.disclosureAddCount > 0;
  const [copied, setCopied] = useState(false);
  // 이미지 수정안(멀티모달) — 접수 이미지가 있는 run 에서만 노출.
  const [imageGenState, setImageGenState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [revisedImage, setRevisedImage] = useState<string | null>(null);
  const [imageGenError, setImageGenError] = useState("");

  const generateRevisedImage = async () => {
    if (imageGenState === "loading") return;
    setImageGenState("loading");
    setImageGenError("");
    try {
      const response = await fetch("/api/revision-image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_run_id: result.review_run_id,
          corrected_text: correctedTextFromDiff(diff),
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: { message?: string } } | null;
        throw new Error(body?.detail?.message ?? `이미지 생성 실패 (HTTP ${response.status})`);
      }
      const data = (await response.json()) as { image_base64: string; media_type: string };
      setRevisedImage(`data:${data.media_type};base64,${data.image_base64}`);
      setImageGenState("done");
    } catch (error) {
      setImageGenError(error instanceof Error ? error.message : "이미지 생성에 실패했습니다.");
      setImageGenState("error");
    }
  };

  const copyCorrected = async () => {
    const text = correctedTextFromDiff(diff);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // clipboard API 가 막힌 컨텍스트(권한/비보안) 폴백
      const textarea = document.createElement("textarea");
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div
      className="overflow-hidden rounded-[14px] border border-line bg-white shadow-panel"
      style={{ animation: "nodeIn .25s" }}
    >
      {/* 크리에이티브 배너 — 원문 모드와 동일한 블루 그라데이션 */}
      <div className="px-5.5 py-5 text-white" style={{ background: "linear-gradient(135deg,#1d3a6e,#2f6df0)" }}>
        <div className="mb-3 flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-wider opacity-85">JB금융그룹 · AI 교정안</span>
          <span className="rounded-full bg-white/18 px-2.5 py-0.5 text-[11px] font-bold">{productGroup || "광고"}</span>
        </div>
        <div className="text-[21px] leading-snug font-extrabold tracking-tight break-keep">
          {reviewTitle || "광고 문안"}
        </div>
        {hasChanges && (
          <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-bold">
                위험 문구 {diff.changedCount}곳 완화
                {diff.disclosureAddCount ? ` · 필수 고지 ${diff.disclosureAddCount}건 추가` : ""}
              </div>
              <div className="mt-0.5 text-[11px] opacity-80">
                근거 조문 기반 최소 수정 — 최종 확정 책임은 심사자에게 있습니다.
              </div>
            </div>
            <button
              type="button"
              onClick={copyCorrected}
              className="flex shrink-0 items-center gap-1.5 rounded-[10px] bg-white/16 px-3 py-2 text-[12.5px] font-bold text-white transition hover:bg-white/28"
            >
              <Icon name={copied ? "check" : "clause"} size={14} color="#fff" />
              {copied ? "복사됨" : "교정안 복사"}
            </button>
            {result.ad_image?.available && (
              <button
                type="button"
                onClick={() => void generateRevisedImage()}
                disabled={imageGenState === "loading"}
                className="flex shrink-0 items-center gap-1.5 rounded-[10px] bg-white/16 px-3 py-2 text-[12.5px] font-bold text-white transition hover:bg-white/28 disabled:cursor-wait disabled:opacity-70"
              >
                <Icon name="alert" size={14} color="#fff" />
                {imageGenState === "loading" ? "가이드 생성 중…" : revisedImage ? "가이드 다시 생성" : "이미지 수정 가이드"}
              </button>
            )}
          </div>
        )}
      </div>

      {/* 이미지 수정안 — 교정 문안을 원본 배너 레이아웃에 반영해 생성 */}
      {result.ad_image?.available && (imageGenState === "error" || revisedImage) && (
        <div className="border-b border-line bg-surface-2 px-4 py-3">
          {imageGenState === "error" && (
            <p className="text-[12.5px] font-semibold text-reject">{imageGenError}</p>
          )}
          {revisedImage && (
            <div className="grid gap-3 md:grid-cols-2">
              <figure>
                <figcaption className="mb-1 text-[11px] font-bold text-ink-4">BEFORE · 접수 원본</figcaption>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/ad-image/${result.review_run_id}/original`}
                  alt="원본 광고 이미지"
                  className="w-full rounded-md border border-line bg-white object-contain"
                />
              </figure>
              <figure>
                <figcaption className="mb-1 text-[11px] font-bold text-pass">AFTER · AI 수정 가이드</figcaption>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={revisedImage} alt="교정 위치를 표시한 이미지 수정 가이드" className="w-full rounded-md border border-pass/50 bg-white object-contain" />
              </figure>
              <p className="md:col-span-2 text-[11px] leading-relaxed text-ink-4">
                수정 가이드는 완성 시안이 아니라 어느 자리에 어떤 문구를 반영해야 하는지 표시한 검수 마크업입니다 —
                실제 반영 문구는 좌측 교정안(diff)을 기준으로 디자이너가 적용합니다.
              </p>
            </div>
          )}
        </div>
      )}

      {/* diff 헤더 — GitHub 파일 헤더 오마주 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface-2 px-4 py-2.5">
        <span className="font-mono text-[12px] font-bold text-ink-2">광고 문안</span>
        <span className="font-mono text-[11.5px]">
          <span className="font-bold text-reject">−{diff.changedCount}</span>{" "}
          <span className="font-bold text-pass">+{diff.changedCount + diff.disclosureAddCount}</span>
        </span>
        <span className="ml-auto text-[11px] text-ink-4">
          줄에 커서를 올리면 이유, 클릭하면 판정 상세
        </span>
      </div>
      {hasChanges ? (
        <div className="py-2">
          {diff.lines.map((line, index) => (
            <DiffLine
              key={`${line.type}_${index}`}
              line={line}
              selected={Boolean(line.anchorId && line.anchorId === selectedAnchorId)}
              onSelectAnchor={onSelectAnchor}
            />
          ))}
        </div>
      ) : (
        <div className="px-4 py-6 text-[13px] text-ink-4">수정이 필요한 표현이 없습니다 — 원문 그대로 게시 가능합니다.</div>
      )}
    </div>
  );
}
