"use client";

import { principleColor, REVIEW_LAYER } from "@/lib/labels";
import { buildIssueCards, planItemsForAnchor, translationForQuote, type HighlightTone, type IssueCardModel } from "@/lib/selectors";
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

const GRADE_COLOR: Record<IssueCardModel["grade"], string> = {
  높음: "var(--reject)",
  중간: "var(--revise)",
  낮음: "var(--pass)",
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

function IssueCard({
  card,
  result,
  selected,
  isResolved,
  onSelectAnchor,
}: {
  card: IssueCardModel;
  result: ReviewOutput;
  selected: boolean;
  isResolved: boolean;
  onSelectAnchor: (anchorId: string) => void;
}) {
  const color = TONE_COLOR[card.tone];
  const principles = card.anchorId
    ? [...new Set(planItemsForAnchor(result, card.anchorId).map((item) => item.principle).filter(Boolean))]
    : [];
  // 인용 문장의 참고 번역(비-KR 심사에서만 존재). 표시 전용.
  const quoteTranslation = translationForQuote(result, card.quote);
  return (
    <button
      type="button"
      onClick={() => onSelectAnchor(card.anchorId ?? card.id)}
      className="relative w-full rounded-[11px] p-3 pl-3.5 text-left transition"
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
      {/* 헤더 행: 코드 · 심각도 · 엔진 · 위반 가능성 */}
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
          className="ml-auto text-[11px] font-bold whitespace-nowrap"
          style={{ color: isResolved ? "var(--pass)" : GRADE_COLOR[card.grade] }}
          title={card.score != null ? `위반 가능성 ${(card.score * 100).toFixed(0)}%` : undefined}
        >
          {isResolved ? "해소" : `위반 가능성 ${card.grade}`}
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
      {/* 인용 문장의 참고 번역 — 심사 근거는 원문 기준 */}
      {quoteTranslation && (
        <div className="mt-1 space-y-0.5 text-[11px] leading-relaxed text-ink-3">
          {quoteTranslation.en && (
            <div className="flex gap-1.5">
              <span className="mt-0.5 shrink-0 rounded bg-surface-2 px-1 font-mono text-[8.5px] font-bold text-ink-4">EN</span>
              <span>{quoteTranslation.en}</span>
            </div>
          )}
          {quoteTranslation.ko && (
            <div className="flex gap-1.5 break-keep">
              <span className="mt-0.5 shrink-0 rounded bg-surface-2 px-1 font-mono text-[8.5px] font-bold text-ink-4">KO</span>
              <span>{quoteTranslation.ko}</span>
            </div>
          )}
        </div>
      )}
      {/* 위반 유형 + 요건 요약 */}
      <div className="mt-1 flex items-baseline gap-2 text-[12.5px] text-ink-2">
        <span>{card.label}</span>
        {card.criteriaSummary ? (
          <span className="text-[11px] text-ink-4">· {card.criteriaSummary}</span>
        ) : null}
      </div>
      {/* 원칙 태그 + 근거 */}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {principles.slice(0, 3).map((principle) => (
          <Tag key={principle} color={principleColor(principle)}>
            {principle}
          </Tag>
        ))}
        <span className="ml-auto max-w-[55%] truncate font-mono text-[10.5px] text-ink-4">
          {card.basis.split(" · ")[0]}
        </span>
      </div>
    </button>
  );
}

/** 종합 심사 밴드 — 개별 심사 카드와 다른 층임을 시각적으로 구분. */
function HolisticBand({
  card,
  selected,
  onSelectAnchor,
}: {
  card: IssueCardModel;
  selected: boolean;
  onSelectAnchor: (anchorId: string) => void;
}) {
  const color = TONE_COLOR[card.tone];
  return (
    <button
      type="button"
      onClick={() => onSelectAnchor(card.id)}
      className="relative w-full rounded-[11px] p-3.5 text-left transition"
      style={{
        border: `1.5px solid ${selected ? color : "var(--line)"}`,
        background: TONE_BG[card.tone],
        boxShadow: "var(--shadow-card)",
      }}
    >
      <div className="mb-1.5 flex items-center gap-2">
        <span className="font-mono text-[11px] font-bold text-ink-4">{card.code}</span>
        <SevPill tone={card.tone} />
        <span
          className="ml-auto text-[11px] font-bold whitespace-nowrap"
          style={{ color: GRADE_COLOR[card.grade] }}
          title={card.score != null ? `오인 위험 ${(card.score * 100).toFixed(0)}%` : undefined}
        >
          오인 위험 {card.grade}
        </span>
      </div>
      <div className="text-[13.5px] leading-[1.45] font-semibold break-keep text-ink">
        광고 전체를 종합한 소비자 인상
      </div>
      {/* 개별 표현이 모두 통과해도, 전체 인상에서 오인 위험이 생길 수 있음 */}
      {card.rationale ? (
        <div className="mt-1 line-clamp-3 text-[12.5px] leading-[1.5] text-ink-2 break-keep">
          {card.rationale}
        </div>
      ) : null}
      <div className="mt-2 flex items-center gap-1.5">
        <Tag>전체 문맥</Tag>
        <span className="ml-auto max-w-[60%] truncate font-mono text-[10.5px] text-ink-4">
          {card.basis}
        </span>
      </div>
    </button>
  );
}

function SectionHeader({ title, sub, count }: { title: string; sub: string; count: number }) {
  return (
    <div className="flex items-baseline gap-2 px-1 pt-1">
      <span className="text-[12px] font-bold text-ink">{title}</span>
      <span className="text-[11px] text-ink-4">{sub}</span>
      <span className="ml-auto text-[11px] font-mono text-ink-4">{count}</span>
    </div>
  );
}

export function RiskList({ result, selectedAnchorId, resolved, onSelectAnchor }: Props) {
  const cards = buildIssueCards(result);
  const resolvedCount = cards.filter((card) => resolved.has(card.id)).length;
  const trackA = cards.filter((card) => card.track === "A");
  const trackB = cards.filter((card) => card.track === "B");

  const isSelected = (card: IssueCardModel) =>
    card.anchorId ? card.anchorId === selectedAnchorId : card.id === selectedAnchorId;

  return (
    <div className="flex h-full flex-col border-r border-l border-line">
      <PaneHeader
        icon="review"
        title="위험 카드"
        sub={`${REVIEW_LAYER.individual.name} + ${REVIEW_LAYER.holistic.name}`}
        right={<Tag tone={resolvedCount ? "ok" : undefined}>{resolvedCount}건 조치</Tag>}
      />
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {cards.length ? (
          <>
            {/* 개별 심사 — 각 표현·고지를 조항별로 */}
            <SectionHeader
              title={REVIEW_LAYER.individual.name}
              sub={REVIEW_LAYER.individual.sub}
              count={trackA.length}
            />
            {trackA.length ? (
              trackA.map((card) => (
                <IssueCard
                  key={card.id}
                  card={card}
                  result={result}
                  selected={isSelected(card)}
                  isResolved={resolved.has(card.id)}
                  onSelectAnchor={onSelectAnchor}
                />
              ))
            ) : (
              <div className="px-1 pb-1 text-[12px] text-ink-4">조각 단위 이슈 없음.</div>
            )}

            {/* 종합 심사 — 광고 전체 인상 (전체적·궁극적 인상 기준) */}
            {trackB.length ? (
              <div className="mt-2 border-t border-dashed border-line pt-3">
                <SectionHeader
                  title={REVIEW_LAYER.holistic.name}
                  sub={REVIEW_LAYER.holistic.sub}
                  count={trackB.length}
                />
                {trackB.map((card) => (
                  <div key={card.id} className="mt-2">
                    <HolisticBand card={card} selected={isSelected(card)} onSelectAnchor={onSelectAnchor} />
                  </div>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <EmptyState>현재 문안 기준 별도 이슈가 없습니다.</EmptyState>
        )}
      </div>
    </div>
  );
}
