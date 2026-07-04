"use client";

import { useMemo, useState } from "react";
import { abbreviateLawNames } from "@/lib/labels";
import { buildRevisionDiff, correctedTextFromDiff, type RevisionDiffLine } from "@/lib/revisionDiff";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { ImageLightbox } from "./ImageLightbox";

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
      className={`group/line relative flex ${interactive ? "cursor-pointer" : ""}`}
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
      {/* group/line 네임드 그룹 — 부모 details(.group)와의 중첩 호버 충돌 방지
          (일반 group-hover 는 조상 group 호버에도 반응해 툴팁이 전부 떴다). */}
      {hasTooltip && (
        <div className="pointer-events-none absolute top-full right-2 left-8 z-30 hidden group-hover/line:block">
          <div className="mt-0.5 rounded-[10px] border border-line bg-surface px-3 py-2 shadow-panel">
            <div className="text-[11px] font-bold tracking-wider text-ink-4">
              {line.type === "del" ? "위험 이유" : "수정 이유"}
              {line.label ? ` · ${line.label}` : ""}
            </div>
            {line.reason && <p className="m-0 mt-1 text-[12px] leading-relaxed break-keep text-ink-2">{line.reason}</p>}
            {line.basis && (
              <div className="mt-1 text-[11px] text-ink-4">{abbreviateLawNames(line.basis)}</div>
            )}
            {interactive && <div className="mt-1 text-[11px] font-semibold text-brand-2">클릭하면 판정 상세로 이동</div>}
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
  const [zoomed, setZoomed] = useState<{ src: string; caption: string; downloadName?: string } | null>(null);
  // 개선 지시(반복 루프) — 직전 가이드를 베이스로 재편집.
  const [feedback, setFeedback] = useState("");

  const generateRevisedImage = async (feedbackText?: string) => {
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
          feedback: feedbackText || undefined,
        }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: { message?: string } } | null;
        throw new Error(body?.detail?.message ?? `이미지 생성 실패 (HTTP ${response.status})`);
      }
      const data = (await response.json()) as { image_base64: string; media_type: string };
      setRevisedImage(`data:${data.media_type};base64,${data.image_base64}`);
      setImageGenState("done");
      if (feedbackText) setFeedback("");
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
            {/* min-w 를 확보해야 좁은 컬럼에서 낱글자 세로 줄바꿈으로 깨지지 않는다
                (버튼들이 flex 폭을 잠식하면 텍스트가 1글자 폭까지 줄어드는 문제). */}
            <div className="min-w-[180px] flex-1 break-keep">
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
            {/* 첫 생성 CTA 는 아래 이미지 영역이 담당 — 배너 버튼은 재생성 전용 */}
            {result.ad_image?.available && revisedImage && (
              <button
                type="button"
                onClick={() => void generateRevisedImage()}
                disabled={imageGenState === "loading"}
                className="flex shrink-0 items-center gap-1.5 rounded-[10px] bg-white/16 px-3 py-2 text-[12.5px] font-bold text-white transition hover:bg-white/28 disabled:cursor-wait disabled:opacity-70"
              >
                <Icon name="alert" size={14} color="#fff" />
                {imageGenState === "loading" ? "가이드 생성 중…" : "가이드 다시 생성"}
              </button>
            )}
          </div>
        )}
      </div>

      {/* 이미지 런의 수정안 = 이미지가 주인공. 원본 이미지 → 생성 이미지(가이드)
          흐름을 먼저 보여주고, 추출 문안 diff는 아래 접이식 보조로 내린다. */}
      {result.ad_image?.available && !revisedImage && (
        <div className="border-b border-line bg-surface-2 px-4 py-4">
          {imageGenState === "error" && (
            <p className="mb-2 text-[12.5px] font-semibold text-reject">{imageGenError}</p>
          )}
          <figure>
            <figcaption className="mb-1 text-[11px] font-bold text-ink-3">접수 원본 (이미지 광고)</figcaption>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`/api/ad-image/${result.review_run_id}/original`}
              alt="원본 광고 이미지"
              className="w-full cursor-zoom-in rounded-md border border-line bg-white object-contain"
              onClick={() =>
                setZoomed({ src: `/api/ad-image/${result.review_run_id}/original`, caption: "접수 원본 광고 이미지" })
              }
            />
          </figure>
          <button
            type="button"
            onClick={() => void generateRevisedImage()}
            disabled={imageGenState === "loading"}
            className="mt-3 w-full rounded-[10px] bg-brand py-2.5 text-[13.5px] font-bold text-white transition hover:bg-brand/90 disabled:cursor-wait disabled:opacity-70"
          >
            {imageGenState === "loading" ? "이미지 수정 가이드 생성 중… (약 1분)" : "이미지 수정 가이드 생성 — 교정 위치를 원본 위에 표시"}
          </button>
        </div>
      )}
      {result.ad_image?.available && revisedImage && (
        <div className="border-b border-line bg-surface-2 px-4 py-3">
          {imageGenState === "error" && (
            <p className="text-[12.5px] font-semibold text-reject">{imageGenError}</p>
          )}
          {revisedImage && (
            <div className="space-y-3">
              <figure>
                <figcaption className="mb-1 flex items-center justify-between text-[11px] font-bold text-pass">
                  <span>AFTER · AI 수정 가이드</span>
                  <span className="font-normal text-ink-4">클릭하면 크게 보기 · 다운로드</span>
                </figcaption>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={revisedImage}
                  alt="교정 위치를 표시한 이미지 수정 가이드"
                  className="w-full cursor-zoom-in rounded-md border border-pass/50 bg-white object-contain transition hover:shadow-panel"
                  onClick={() =>
                    setZoomed({
                      src: revisedImage,
                      caption: "AI 수정 가이드 — 교정 위치 마크업",
                      downloadName: `${result.review_run_id}_revision_guide.png`,
                    })
                  }
                />
                {/* 개선 지시 — 직전 가이드를 베이스로 재편집하는 반복 루프 */}
                <form
                  className="mt-2 flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (feedback.trim() && imageGenState !== "loading") void generateRevisedImage(feedback.trim());
                  }}
                >
                  <input
                    type="text"
                    value={feedback}
                    onChange={(event) => setFeedback(event.target.value)}
                    placeholder="가이드 개선 지시 — 예: 고지 영역 박스를 더 크게, ① 콜아웃을 오른쪽으로"
                    className="min-w-0 flex-1 bg-transparent text-[12.5px] text-ink outline-none placeholder:text-ink-4"
                    disabled={imageGenState === "loading"}
                  />
                  <button
                    type="submit"
                    disabled={imageGenState === "loading" || !feedback.trim()}
                    className="shrink-0 rounded-full bg-brand px-3 py-1 text-[12px] font-bold text-white transition hover:bg-brand/90 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {imageGenState === "loading" ? "적용 중…" : "개선 적용"}
                  </button>
                </form>
              </figure>
              <figure>
                <figcaption className="mb-1 text-[11px] font-bold text-ink-4">BEFORE · 접수 원본</figcaption>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/api/ad-image/${result.review_run_id}/original`}
                  alt="원본 광고 이미지"
                  className="w-full cursor-zoom-in rounded-md border border-line bg-white object-contain transition hover:shadow-panel"
                  onClick={() =>
                    setZoomed({
                      src: `/api/ad-image/${result.review_run_id}/original`,
                      caption: "접수 원본 광고 이미지",
                    })
                  }
                />
              </figure>
              <p className="text-[11px] leading-relaxed text-ink-4">
                수정 가이드는 완성 시안이 아니라 어느 자리에 어떤 문구를 반영해야 하는지 표시한 검수 마크업입니다 —
                실제 반영 문구는 아래 교정안(diff)을 기준으로 디자이너가 적용합니다.
              </p>
            </div>
          )}
        </div>
      )}
      {zoomed && (
        <ImageLightbox
          src={zoomed.src}
          alt={zoomed.caption}
          caption={zoomed.caption}
          downloadName={zoomed.downloadName}
          onClose={() => setZoomed(null)}
        />
      )}

      {/* 텍스트 diff — 텍스트 런에서는 본문(주인공), 이미지 런에서는 접이식 보조.
          이미지 런의 수정본은 '생성 이미지'이고, diff 는 그 재료(추출 문안 교정)다. */}
      {result.ad_image?.available ? (
        <details className="group">
          <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface-2 px-4 py-2.5 select-none">
            <span className="font-mono text-[12px] font-bold text-ink-2">추출 문안 교정 (diff)</span>
            <span className="font-mono text-[11.5px]">
              <span className="font-bold text-reject">−{diff.changedCount}</span>{" "}
              <span className="font-bold text-pass">+{diff.changedCount + diff.disclosureAddCount}</span>
            </span>
            <span className="ml-auto text-[11px] text-ink-4">
              <span className="group-open:hidden">펼치기 — 가이드에 반영된 문구 교정 내역</span>
              <span className="hidden group-open:inline">줄에 커서를 올리면 이유, 클릭하면 판정 상세</span>
            </span>
          </summary>
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
        </details>
      ) : (
        <>
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
        </>
      )}
    </div>
  );
}
