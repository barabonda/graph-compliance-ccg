"use client";

import { principleColor, riskGrade, VERDICT_LABELS, verdictBadgeTone } from "@/lib/labels";
import { principleDisplay, riskGradeLabelEn, tr, useLocale, verdictLabel } from "@/lib/i18n";
import { buildIssueCards, disclosureIsSatisfied, principleBreakdown } from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { Badge, Tag } from "../ui";

function StatMini({
  label,
  value,
  sub,
  danger,
  minor,
  toneColor,
}: {
  label: string;
  value: string | number;
  sub?: string;
  danger: boolean;
  /** 보조 지표 — 주요 3지표보다 한 단계 작게. */
  minor?: boolean;
  /** danger 2색(적/녹) 대신 특정 색을 직접 지정 (예: 심의기준 미흡 앰버). */
  toneColor?: string;
}) {
  return (
    <div className="text-center">
      <div className="text-[11px] font-semibold whitespace-nowrap text-ink-4">{label}</div>
      <div className="mt-1">
        <span
          className={`font-extrabold ${minor ? "text-[16px]" : "text-[22px]"} ${
            toneColor ? "" : danger ? "text-reject" : "text-pass"
          }`}
          style={toneColor ? { color: toneColor } : undefined}
        >
          {value}
        </span>
        {sub && <span className="text-[11px] font-semibold text-ink-4">{sub}</span>}
      </div>
    </div>
  );
}

export function ExecSummary({ result, resolved }: { result: ReviewOutput; resolved: Set<string> }) {
  const locale = useLocale();
  const cards = buildIssueCards(result, locale).filter((card) => card.kind !== "trackB");
  const open = cards.filter((card) => !resolved.has(card.id)).length;
  // 권위 계층 분리 — "법령 위반 근거"와 "심의기준 미흡(법 위반 아님)"은 다른 말이다.
  // 이 둘을 주 지표로 승격하고(둘을 합치면 사실상 "위반 의심"이 되므로 별도 지표는
  // 뺐다 — 같은 숫자를 두 번 세는 인상을 준다), 미해소·필수고지는 보조 지표로.
  const lawOpen = cards.filter((card) => card.authorityTier === "law" && !resolved.has(card.id)).length;
  const guidelineOpen = cards.filter((card) => card.authorityTier === "guideline" && !resolved.has(card.id)).length;
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const met = checks.filter(disclosureIsSatisfied).length;
  const misleading = Number(result.overall_impression_judgment?.misleading_risk_score ?? 0);
  const grade = riskGrade(misleading);
  const gradeColor =
    grade.tone === "reject" ? "var(--reject)" : grade.tone === "review" ? "var(--revise)" : "var(--pass)";
  const gradeBg =
    grade.tone === "reject" ? "var(--reject-bg)" : grade.tone === "review" ? "var(--revise-bg)" : "var(--pass-bg)";
  const [aiLabel] = VERDICT_LABELS[result.final_verdict]
    ? verdictLabel(locale, result.final_verdict, VERDICT_LABELS)
    : [result.final_verdict];
  const gradeLabel = locale === "en" ? riskGradeLabelEn(misleading) : grade.label;

  return (
    <div className="flex shrink-0 items-stretch gap-4.5 rounded-[14px] border border-line bg-surface px-4.5 py-3.5 shadow-card">
      {/* 좌: AI 판정 */}
      <div className="flex flex-col justify-center gap-2 border-r border-line pr-4.5">
        <div className="text-[11px] font-bold tracking-wider text-ink-4 uppercase">{tr(locale, "AI 판정 · 권고", "AI verdict · Advisory")}</div>
        <Badge tone={verdictBadgeTone(result.final_verdict)}>{aiLabel}</Badge>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-ink-3">{tr(locale, "오인 위험", "Misleading risk")}</span>
          <span
            title={`misleading_risk_score ${misleading.toFixed(2)}`}
            className="rounded-full px-2 py-0.5 text-[11px] font-bold"
            style={{ color: gradeColor, background: gradeBg }}
          >
            {gradeLabel}
          </span>
        </div>
      </div>

      {/* 중: 요약 사유 */}
      <div className="flex min-w-0 flex-1 flex-col justify-center">
        <div className="mb-1.5 flex items-center gap-1.5">
          <Icon name="spark" size={14} color="var(--brand)" />
          <span className="text-[11px] font-bold tracking-wider text-ink-4">{tr(locale, "요약 사유 · EXECUTIVE SUMMARY", "EXECUTIVE SUMMARY")}</span>
        </div>
        <p className="m-0 line-clamp-3 text-[13.5px] leading-relaxed text-ink-2" style={{ textWrap: "pretty" }}>
          {result.rationale}
        </p>
        {/* 6대 판매원칙별 현황 — 심의 의견서의 원칙별 목차와 1:1. 0건도 "점검됨"의 정보. */}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
          <span className="text-[11px] font-bold tracking-wider text-ink-4">{tr(locale, "판매원칙", "Sales principles")}</span>
          {principleBreakdown(result, resolved).map(({ label, count }) => (
            <span key={label} className="flex items-center gap-1 whitespace-nowrap">
              <span
                className="h-[6px] w-[6px] rounded-full"
                style={{ background: count ? (principleColor(label) ?? "var(--ink-3)") : "var(--line-2)" }}
              />
              <span className={count ? "font-semibold text-ink-2" : "text-ink-4"}>{principleDisplay(locale, label)}</span>
              <span className={count ? "font-bold text-ink" : "text-ink-4"}>{count}</span>
            </span>
          ))}
        </div>
        {result.routing?.review_phrase_required_before_publication && (
          <div className="mt-1.5">
            <Tag tone="review">{tr(locale, "게시 전 심의필 표시 필요", "Pre-publication review mark required")}</Tag>
          </div>
        )}
      </div>

      {/* 우: 지표 — 법령/심의기준 2개를 주 지표로, 미해소·필수고지는 보조로 */}
      <div className="flex items-center gap-4.5 border-l border-line pl-4.5">
        <StatMini label={tr(locale, "법령 근거", "Legal basis")} value={lawOpen} danger={lawOpen > 0} />
        <StatMini label={tr(locale, "심의기준 미흡", "Guideline shortfalls")} value={guidelineOpen} danger={false} toneColor="var(--revise)" />
        <StatMini label={tr(locale, "미해소 이슈", "Open issues")} value={open} sub={` / ${cards.length}`} danger={open > 0} minor />
        <StatMini
          label={tr(locale, "필수 고지", "Required disclosures")}
          value={`${met}/${checks.length}`}
          danger={checks.length > 0 && met < checks.length}
          minor
        />
      </div>
    </div>
  );
}
