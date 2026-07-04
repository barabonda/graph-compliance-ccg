"use client";

import { useMemo, useState } from "react";
import { tr, useLocale } from "@/lib/i18n";
import { PRODUCT_GROUPS } from "@/lib/labels";
import { buildRevisionDiff } from "@/lib/revisionDiff";
import {
  type AnnotatedText,
  buildAdLines,
  conditionalDisclosures,
  sentenceTranslationsById,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { Tag } from "../ui";
import { PaneHeader } from "./common";
import { ImageLightbox } from "./ImageLightbox";
import { RevisionDiff } from "./RevisionDiff";

/** 번역이 원문과 사실상 같은지(공백 정규화) — 영어 원문에 EN 줄 중복 방지. */
function sameText(a: string, b: string): boolean {
  const norm = (v: string) => v.replace(/\s+/g, " ").trim().toLowerCase();
  return norm(a) === norm(b);
}

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
  const locale = useLocale();
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
            {isResolved ? tr(locale, "해소 ✓", "Resolved ✓") : chip.label}
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
  // null = 아직 사용자가 안 골랐음 → 수정할 게 있으면 '수정안'이 기본(결론부터),
  // 클린 광고면 원문. 사용자가 토글하면 그 선택을 따른다.
  const locale = useLocale();
  const [modeChoice, setModeChoice] = useState<"original" | "diff" | null>(null);
  const [imageZoomed, setImageZoomed] = useState(false);
  const lines = useMemo(() => buildAdLines(result, reviewedText, locale), [result, reviewedText, locale]);
  // 수정안 diff — GitHub unified diff 형태 (구 '교정본'/수정안 탭 통합)
  const diff = useMemo(() => buildRevisionDiff(result, reviewedText, locale), [result, reviewedText, locale]);
  const diffCount = diff.changedCount + diff.disclosureAddCount;
  const mode = modeChoice ?? (diffCount > 0 ? "diff" : "original");
  const conditional = conditionalDisclosures(result, reviewedText);
  const actionable = (result.anchor_display ?? []).filter((item) => item.display_role === "actionable").length;
  // 참고용 번역(표시 전용) — 비-KR workspace에서만 채워짐. KR이면 null → 아무것도 렌더 안 함.
  const translations = result.ad_translations ?? null;
  // 교차언어 정규화 패널 — 원문 표현 → PolicyHypernym. 번역이 있는(비-KR) 심사에서만 표시.
  const crossLanguageAnchors = useMemo(
    () => (result.context_anchors ?? []).filter((anchor) => (anchor.hypernyms ?? []).length > 0),
    [result],
  );
  // 원문 각 문장 줄 바로 아래 병기할 문장별 번역(sentence_id 기준). KR이면 빈 맵.
  const lineTranslations = useMemo(() => sentenceTranslationsById(result), [result]);
  const productGroup =
    PRODUCT_GROUPS.find((item) => item.value === result.product_context?.product_group)?.label ??
    result.product_context?.product_group ??
    "";
  const matchedProduct = result.product_fact_context?.matched_product;

  return (
    <div className="flex h-full min-w-0 flex-col">
      <PaneHeader
        icon="eye"
        title={tr(locale, "광고 원문", "Ad original")}
        sub={channelLabel}
        right={
          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-line bg-surface-2 p-0.5">
              <button
                type="button"
                onClick={() => setModeChoice("diff")}
                className={`rounded-md px-2.5 py-1 text-[11.5px] font-bold ${mode === "diff" ? "bg-surface text-pass shadow-card" : "text-ink-3"}`}
              >
                {tr(locale, "수정안", "Revision")}{diffCount ? ` ${diffCount}` : ""}
              </button>
              <button
                type="button"
                onClick={() => setModeChoice("original")}
                className={`rounded-md px-2.5 py-1 text-[11.5px] font-bold ${mode === "original" ? "bg-surface text-ink shadow-card" : "text-ink-3"}`}
              >
                {tr(locale, "원문", "Original")}
              </button>
            </div>
            <Tag>
              <Icon name="alert" size={13} color="var(--reject)" style={{ marginRight: 4 }} />
              {tr(locale, `위험 ${actionable}`, `Risks ${actionable}`)}
            </Tag>
          </div>
        }
      />
      <div className="flex-1 overflow-y-auto px-5 pt-4 pb-7">
        {mode === "diff" ? (
          // 수정안 — GitHub unified diff. -/+ 줄 hover 로 위험/수정 이유, 클릭으로 판정 상세.
          <RevisionDiff
            result={result}
            reviewedText={reviewedText}
            reviewTitle={reviewTitle}
            productGroup={productGroup}
            selectedAnchorId={selectedAnchorId}
            onSelectAnchor={onSelectAnchor}
          />
        ) : (
        <>
        {/* 이미지 광고 원본(1~N페이지) — 문안은 아래 추출 텍스트로 심의, 이미지는 대조용 */}
        {result.ad_image?.available && (
          <div className="mb-3 overflow-hidden rounded-[14px] border border-line bg-white shadow-panel">
            <div className="border-b border-line bg-surface-2 px-4 py-2 text-xs font-bold text-ink-2">
              {tr(locale, "접수된 광고 이미지", "Submitted ad image")}
              {(result.ad_image.count ?? 1) > 1
                ? tr(locale, ` · ${result.ad_image.count}페이지`, ` · ${result.ad_image.count} pages`)
                : ""}{" "}
              <span className="font-normal text-ink-4">
                {tr(
                  locale,
                  "아래 문안은 이미지에서 자동 추출됨 · 클릭하면 크게 보기",
                  "Copy below auto-extracted from the image · click to enlarge",
                )}
              </span>
            </div>
            {Array.from({ length: result.ad_image.count ?? 1 }, (_, i) => {
              const kind = i === 0 ? "original" : `original_${i + 1}`;
              return (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={kind}
                  src={`/api/ad-image/${result.review_run_id}/${kind}`}
                  alt={tr(locale, `접수된 광고 이미지 ${i + 1}페이지`, `Submitted ad image, page ${i + 1}`)}
                  className="max-h-105 w-full cursor-zoom-in border-b border-line bg-white object-contain transition last:border-b-0 hover:opacity-95"
                  onClick={() => setImageZoomed(true)}
                />
              );
            })}
            {result.ad_image.layout_notes && (
              <div className="border-t border-line px-4 py-2 text-[12px] leading-relaxed text-ink-3">
                <strong className="text-ink-2">{tr(locale, "레이아웃 소견", "Layout notes")}</strong> · {result.ad_image.layout_notes}
              </div>
            )}
          </div>
        )}
        {/* 광고 크리에이티브 미리보기 */}
        <div className="overflow-hidden rounded-[14px] border border-line bg-white shadow-panel">
          <div className="px-5.5 py-5 text-white" style={{ background: "linear-gradient(135deg,#1d3a6e,#2f6df0)" }}>
            <div className="mb-3 flex items-center justify-between">
              <span className="font-mono text-[11px] tracking-wider opacity-85">
                {tr(locale, "JB금융그룹 · 사전심의 초안", "PPCBank · Pre-review draft")}
              </span>
              <span className="rounded-full bg-white/18 px-2.5 py-0.5 text-[11px] font-bold">{productGroup || tr(locale, "광고", "Ad")}</span>
            </div>
            <div className="text-[21px] leading-snug font-extrabold tracking-tight break-keep">
              {reviewTitle || tr(locale, "광고 문안", "Ad copy")}
            </div>
          </div>

          {/* 원문의 장식성 들여쓰기·중앙정렬 공백은 접고(whitespace 기본 접기),
              문단 경계(공백 전용 줄)는 고정 간격으로 치환해 읽는 흐름만 남긴다. */}
          <div className="space-y-1.5 px-5.5 py-5 text-[15px] leading-[1.55] break-keep text-ink">
            {lines.map((line) => {
              // 문장별 참고 번역(비-KR run 전용) — 하이라이트는 위 원문에만
              const lineT = line.sentenceId ? lineTranslations.get(line.sentenceId) : undefined;
              return line.text.trim() ? (
                <div key={line.key}>
                  <LineText
                    annotated={line.annotated}
                    selectedAnchorId={selectedAnchorId}
                    resolved={resolved}
                    onSelectAnchor={onSelectAnchor}
                  />
                  {lineT && (
                    <div className="mt-0.5 mb-2 space-y-0.5 text-[12px] leading-relaxed text-ink-3">
                      {/* 3개 언어 병기(EN·KM·KO) — 원문과 동일한 언어 줄은 중복이라 생략 */}
                      {lineT.lines
                        .filter((t) => !sameText(t.text, line.text))
                        .map((t) => (
                          <div key={t.label} className="flex gap-1.5 break-keep">
                            <span className="mt-0.5 shrink-0 rounded bg-surface-2 px-1 font-mono text-[11px] font-bold text-ink-4">{t.label}</span>
                            <span>{t.text}</span>
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              ) : (
                <div key={line.key} className="h-1.5" aria-hidden />
              );
            })}
          </div>

          <div className="border-t border-line bg-surface-2 px-5.5 py-2.5 text-[11.5px] leading-relaxed text-ink-3">
            <span>
              {channelLabel}
              {matchedProduct ? tr(locale, ` · 대상 상품: ${matchedProduct}`, ` · Target product: ${matchedProduct}`) : ""}
              {tr(locale, ` · 원문 ${reviewedText.length}자`, ` · Original ${reviewedText.length} chars`)}
            </span>
          </div>
        </div>
        </>
        )}

        {/* 문장별 참고 번역 — 3개 언어(EN·KM·KO) 병기 (표시 전용) */}
        {mode === "original" && translations && (translations.sentences?.length ?? 0) > 0 && (
          <div className="mt-3 overflow-hidden rounded-lg border border-line bg-surface-2">
            <div className="border-b border-line px-3 py-2 text-xs font-bold text-ink-2">
              {tr(locale, "문장별 참고 번역", "Per-sentence reference translation")}
              <span className="ml-2 font-normal text-[11px] text-ink-4">
                {translations.note ??
                  tr(locale, "참고용 번역 — 심사 근거는 원문 기준", "Reference translation — findings are based on the original text")}
              </span>
            </div>
            <div className="divide-y divide-line">
              {translations.sentences!.map((s, i) => (
                <div key={i} className="px-3 py-2.5">
                  {/* 하이라이트는 위 원문 렌더에만 — 여기 번역/원문 재표기는 plain text */}
                  <div className="text-[13px] leading-relaxed font-medium break-keep whitespace-pre-wrap text-ink">
                    {s.original}
                  </div>
                  {([
                    ["EN", s.en],
                    ["KM", s.km ?? null],
                    ["KO", s.ko ?? null],
                  ] as const)
                    .filter(([, text]) => Boolean(text) && !sameText(String(text), s.original))
                    .map(([label, text]) => (
                      <div key={label} className="mt-1 flex gap-1.5 text-[12px] leading-relaxed break-keep text-ink-2">
                        <span className="mt-0.5 shrink-0 rounded bg-surface px-1 font-mono text-[11px] font-bold text-ink-4">{label}</span>
                        <span className="whitespace-pre-wrap">{text}</span>
                      </div>
                    ))}
                </div>
              ))}
            </div>
          </div>
        )}

        {mode === "original" && translations && !(translations.sentences?.length) && (translations.en || translations.km || translations.ko) && (
          <div className="mt-3 space-y-2">
            {translations.en && (
              <details className="rounded-lg border border-line bg-surface-2 px-3 py-2">
                <summary className="cursor-pointer text-xs font-bold text-ink-2 select-none">
                  {tr(locale, "English (참고용 번역)", "English (reference translation)")}
                </summary>
                {/* 표시 전용 — 하이라이트는 원문에만 적용(원문-번역 위치 정렬 불가) */}
                <div className="mt-2 text-[13.5px] leading-relaxed whitespace-pre-wrap text-ink">{translations.en}</div>
                <div className="mt-1.5 text-[11px] text-ink-4">
                  {translations.note ??
                    tr(locale, "참고용 번역 — 심사 근거는 원문 기준", "Reference translation — findings are based on the original text")}
                </div>
              </details>
            )}
            {translations.km && (
              <details className="rounded-lg border border-line bg-surface-2 px-3 py-2">
                <summary className="cursor-pointer text-xs font-bold text-ink-2 select-none">
                  {tr(locale, "ភាសាខ្មែរ · 크메르어 (참고용 번역)", "ភាសាខ្មែរ · Khmer (reference translation)")}
                </summary>
                <div className="mt-2 text-[13.5px] leading-relaxed break-keep whitespace-pre-wrap text-ink">{translations.km}</div>
                <div className="mt-1.5 text-[11px] text-ink-4">
                  {translations.note ??
                    tr(locale, "참고용 번역 — 심사 근거는 원문 기준", "Reference translation — findings are based on the original text")}
                </div>
              </details>
            )}
            {translations.ko && (
              <details className="rounded-lg border border-line bg-surface-2 px-3 py-2">
                <summary className="cursor-pointer text-xs font-bold text-ink-2 select-none">
                  {tr(locale, "한국어 (참고용 번역)", "한국어 · Korean (reference translation)")}
                </summary>
                <div className="mt-2 text-[13.5px] leading-relaxed break-keep whitespace-pre-wrap text-ink">{translations.ko}</div>
                <div className="mt-1.5 text-[11px] text-ink-4">
                  {translations.note ??
                    tr(locale, "참고용 번역 — 심사 근거는 원문 기준", "Reference translation — findings are based on the original text")}
                </div>
              </details>
            )}
          </div>
        )}

        {mode === "original" && translations && crossLanguageAnchors.length > 0 && (
          <details className="mt-2 rounded-lg border border-line bg-surface-2 px-3 py-2">
            <summary className="cursor-pointer text-xs font-bold text-ink-2 select-none">
              {tr(
                locale,
                `원문 표현 → 정규화된 개념 (교차언어 매핑 ${crossLanguageAnchors.length}건)`,
                `Original expressions → normalized concepts (${crossLanguageAnchors.length} cross-language mappings)`,
              )}
            </summary>
            <div className="mt-2 space-y-1.5">
              {crossLanguageAnchors.map((anchor) => (
                <div key={anchor.anchor_id} className="text-[12px] leading-relaxed">
                  <span className="font-mono text-ink-2">“{anchor.span?.text}”</span>
                  <span className="mx-1.5 text-ink-4">→</span>
                  <span className="inline-flex flex-wrap gap-1 align-middle">
                    {anchor.hypernyms.map((proposal) => (
                      <Tag key={proposal.hypernym_id}>{proposal.hypernym}</Tag>
                    ))}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-1.5 text-[11px] text-ink-4">
              {tr(
                locale,
                "원문(외국어) 표현이 정책 개념 사전(PolicyHypernym)으로 정규화된 결과입니다.",
                "Original (foreign-language) expressions normalized against the policy concept dictionary (PolicyHypernym).",
              )}
            </div>
          </details>
        )}

        {mode === "original" && (
          <>
            <div className="mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-ink-3">
              <Icon name="alert" size={14} color="var(--ink-4)" />
              {tr(
                locale,
                "표시 구간을 클릭하면 우측 판정 상세에서 근거와 수정안을 확인할 수 있습니다.",
                "Click a highlighted span to see the evidence and suggested revision in the finding details on the right.",
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-ink-3" aria-label={tr(locale, "범례", "Legend")}>
              <span><i className="legend-token-risk not-italic">{tr(locale, "위반 의심", "Suspected violation")}</i></span>
              <span><i className="legend-token-review not-italic">{tr(locale, "검토 필요", "Review required")}</i></span>
              <span><i className="legend-token-keep not-italic">{tr(locale, "유지 고지", "Disclosure to keep")}</i></span>
            </div>
            {conditional.length > 0 && (
              <div className="mt-3 rounded-lg border border-line bg-surface-2 px-3 py-2 text-xs text-ink-3">
                <strong className="text-ink">{tr(locale, "유지해야 할 고지", "Disclosures to keep")}</strong>
                <span className="ml-2 inline-flex flex-wrap gap-1.5 align-middle">
                  {conditional.map((item) => (
                    <Tag key={item} tone="ok">
                      {item}
                    </Tag>
                  ))}
                </span>
                <span className="ml-2">
                  {tr(
                    locale,
                    "— 초록 표시 구간은 수정 시 삭제하면 안 되는 문구입니다.",
                    "— Green spans mark wording that must not be removed when revising.",
                  )}
                </span>
              </div>
            )}
          </>
        )}
      </div>
      {imageZoomed && result.ad_image?.available && (
        <ImageLightbox
          src={`/api/ad-image/${result.review_run_id}/original`}
          alt={tr(locale, "접수된 광고 이미지 원본", "Submitted original ad image")}
          caption={tr(locale, "접수 원본 광고 이미지", "Submitted original ad image")}
          onClose={() => setImageZoomed(false)}
        />
      )}
    </div>
  );
}
