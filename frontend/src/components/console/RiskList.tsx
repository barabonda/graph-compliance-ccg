"use client";

import { abbreviateLawNames, AUTHORITY_GROUP, principleColor, REVIEW_LAYER } from "@/lib/labels";
import { buildIssueCards, planItemsForAnchor, type HighlightTone, type IssueCardModel } from "@/lib/selectors";
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
  const isGuideline = !isResolved && card.authorityTier === "guideline";
  // 색 예산: 카드당 semantic color는 왼쪽 심각도 바 + 상태 텍스트 한 곳에만.
  // 심각도를 테두리·배경·pill로 중복 인코딩하면 목록 전체가 경보가 되어
  // 정작 봐야 할 카드가 묻힌다(alert fatigue). tier 구분은 그룹 헤더가 담당.
  const statusColor = isGuideline ? "var(--revise)" : color;
  return (
    <button
      type="button"
      onClick={() => onSelectAnchor(card.anchorId ?? card.id)}
      className="relative w-full rounded-[11px] p-3 pl-3.5 text-left transition"
      style={{
        border: `1px solid ${selected ? statusColor : "var(--line)"}`,
        background: selected ? TONE_BG[card.tone] : "var(--surface)",
        opacity: isResolved ? 0.72 : 1,
      }}
    >
      <span
        className="absolute top-3 bottom-3 left-0 w-[3px] rounded-full"
        style={{ background: isResolved ? "var(--pass)" : statusColor }}
      />
      {/* 헤더 행: 코드 · 상태(유일한 컬러 텍스트) · 위반 가능성 */}
      <div className="mb-1 flex items-baseline gap-2">
        <span className="font-mono text-[11px] font-bold text-ink-4">{card.code}</span>
        {isResolved ? (
          <span className="flex items-center gap-1 text-[11px] font-bold text-pass">
            <Icon name="check" size={12} /> 수정안 적용
          </span>
        ) : (
          <span
            className="text-[11px] font-bold whitespace-nowrap"
            style={{ color: statusColor }}
            title={
              isGuideline
                ? `법령 위반이 아닌 심의기준 미흡입니다.${card.coBasis ? ` 병기: ${card.coBasis}` : ""}`
                : undefined
            }
          >
            {isGuideline ? "심의기준 미흡 · 법령 위반 아님" : TONE_WORD_SHORT[card.tone]}
          </span>
        )}
        <span
          className="ml-auto text-[11px] whitespace-nowrap text-ink-3"
          title={card.score != null ? `위반 가능성 ${(card.score * 100).toFixed(0)}%` : undefined}
        >
          {isResolved ? "해소" : (
            <>위반 가능성 <span className={card.grade === "높음" ? "font-bold text-ink" : "font-semibold"}>{card.grade}</span></>
          )}
        </span>
      </div>
      {/* 인용 문구 — 카드의 주인공. 주변이 조용해진 만큼 크기로 위계를 준다 */}
      <div
        className={`text-[14px] leading-[1.5] font-semibold break-keep text-ink ${
          isResolved ? "line-through decoration-ink-4" : ""
        }`}
      >
        “{card.quote}”
      </div>
      {/* 위반 유형 + 요건 요약 */}
      <div className="mt-0.5 flex items-baseline gap-2 text-[12.5px] text-ink-3">
        <span>{card.label}</span>
        {card.criteriaSummary ? (
          <span className="text-[11px] text-ink-4">· {card.criteriaSummary}</span>
        ) : null}
      </div>
      {/* 근거 조문 — 본문과 같은 서체로 조용히, 자르지 않고 (mono는 코드·ID 전용).
          좁은 카드라 법령명은 실무 약칭(금소법 등)으로, 정식 명칭은 판정 상세에서. */}
      {card.basis ? (
        <div className="mt-1.5 line-clamp-2 text-[11.5px] leading-relaxed break-keep text-ink-4" title={card.basis}>
          {abbreviateLawNames(card.basis)}
          {isGuideline && card.coBasis ? ` · 병기 ${abbreviateLawNames(card.coBasis)}` : ""}
        </div>
      ) : null}
      {/* 6대 판매원칙 — 준법감시인의 1차 분류 좌표. 심각도(경보)와 달리
          범주형 색상이라 칩으로 유지한다(설명의무=보라, 부당권유=빨강, 광고규제=파랑). */}
      {principles.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {principles.slice(0, 2).map((principle) => (
            <Tag key={principle} color={principleColor(principle)}>
              {principle}
            </Tag>
          ))}
          {principles.length > 2 && (
            <span className="text-[10.5px] text-ink-4">+{principles.length - 2}</span>
          )}
        </div>
      )}
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
      className="relative w-full rounded-[11px] p-3 pl-3.5 text-left transition"
      style={{
        border: `1px solid ${selected ? color : "var(--line)"}`,
        background: selected ? TONE_BG[card.tone] : "var(--surface)",
      }}
    >
      <span className="absolute top-3 bottom-3 left-0 w-[3px] rounded-full" style={{ background: color }} />
      <div className="mb-1 flex items-baseline gap-2">
        <span className="font-mono text-[11px] font-bold text-ink-4">{card.code}</span>
        <span className="text-[11px] font-bold whitespace-nowrap" style={{ color }}>
          {TONE_WORD_SHORT[card.tone]}
        </span>
        <span
          className="ml-auto text-[11px] whitespace-nowrap text-ink-3"
          title={card.score != null ? `오인 위험 ${(card.score * 100).toFixed(0)}%` : undefined}
        >
          오인 위험 <span className={card.grade === "높음" ? "font-bold text-ink" : "font-semibold"}>{card.grade}</span>
        </span>
      </div>
      <div className="text-[14px] leading-[1.5] font-semibold break-keep text-ink">
        광고 전체를 종합한 소비자 인상
      </div>
      {/* 개별 표현이 모두 통과해도, 전체 인상에서 오인 위험이 생길 수 있음 */}
      {card.rationale ? (
        <div className="mt-0.5 line-clamp-3 text-[12.5px] leading-[1.5] text-ink-3 break-keep">
          {card.rationale}
        </div>
      ) : null}
      <div className="mt-1.5 text-[11.5px] leading-relaxed break-keep text-ink-4" title={card.basis}>
        {abbreviateLawNames(card.basis)}
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

/** 권위 계층 하위 그룹 헤더 — 법령/심의기준/확인필요를 색으로 먼저 구분한다. */
function TierSubHeader({
  color,
  title,
  sub,
  count,
}: {
  color: string;
  title: string;
  sub: string;
  count: number;
}) {
  return (
    <div className="mt-1 flex items-baseline gap-1.5 px-1">
      <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: color }} />
      <span className="text-[11.5px] font-bold text-ink">{title}</span>
      {sub ? <span className="text-[10.5px] text-ink-4">{sub}</span> : null}
      <span className="ml-auto text-[10.5px] font-mono text-ink-4">{count}</span>
    </div>
  );
}

export function RiskList({ result, selectedAnchorId, resolved, onSelectAnchor }: Props) {
  const cards = buildIssueCards(result);
  const resolvedCount = cards.filter((card) => resolved.has(card.id)).length;
  const trackA = cards.filter((card) => card.track === "A");
  const trackB = cards.filter((card) => card.track === "B");

  // 필수 고지 누락은 이미 확정된 사실(누락 여부는 애매하지 않음)이라 tier 버킷에
  // 함께 넣는다. "확인 필요"는 오직 tone==="review"인 개별 anchor(증거 불충분/근거
  // 검색 실패)만 — 필수 고지 누락과 혼동되면 안 된다(둘은 완전히 다른 확실성 층위).
  const isConfirmed = (card: IssueCardModel) => card.kind === "disclosure" || card.tone === "risk";
  const lawCards = trackA.filter((card) => isConfirmed(card) && card.authorityTier !== "guideline");
  const guidelineCards = trackA.filter((card) => isConfirmed(card) && card.authorityTier === "guideline");
  const uncertainCards = trackA.filter((card) => !isConfirmed(card));

  const isSelected = (card: IssueCardModel) =>
    card.anchorId ? card.anchorId === selectedAnchorId : card.id === selectedAnchorId;

  const renderCard = (card: IssueCardModel) => (
    <IssueCard
      key={card.id}
      card={card}
      result={result}
      selected={isSelected(card)}
      isResolved={resolved.has(card.id)}
      onSelectAnchor={onSelectAnchor}
    />
  );

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
            {/* 개별 심사 — 각 표현·고지를 조항별로, 법령/심의기준/확인필요 순으로 구분 */}
            <SectionHeader
              title={REVIEW_LAYER.individual.name}
              sub={REVIEW_LAYER.individual.sub}
              count={trackA.length}
            />
            {trackA.length ? (
              <>
                {lawCards.length ? (
                  <div className="flex flex-col gap-2">
                    <TierSubHeader
                      color="var(--reject)"
                      title={AUTHORITY_GROUP.law.name}
                      sub={AUTHORITY_GROUP.law.sub}
                      count={lawCards.length}
                    />
                    {lawCards.map(renderCard)}
                  </div>
                ) : null}
                {guidelineCards.length ? (
                  <div className="flex flex-col gap-2">
                    <TierSubHeader
                      color="var(--revise)"
                      title={AUTHORITY_GROUP.guideline.name}
                      sub={AUTHORITY_GROUP.guideline.sub}
                      count={guidelineCards.length}
                    />
                    {guidelineCards.map(renderCard)}
                  </div>
                ) : null}
                {uncertainCards.length ? (
                  <details className="mt-1 rounded-[10px] border border-line px-2 py-1.5">
                    <summary className="cursor-pointer list-none text-[11.5px] font-semibold text-ink-4">
                      {AUTHORITY_GROUP.uncertain.name} · {AUTHORITY_GROUP.uncertain.sub} ({uncertainCards.length})
                    </summary>
                    <div className="mt-2 flex flex-col gap-2">{uncertainCards.map(renderCard)}</div>
                  </details>
                ) : null}
              </>
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
