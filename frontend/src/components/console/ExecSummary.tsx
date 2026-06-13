"use client";

import { riskGrade, VERDICT_LABELS, verdictBadgeTone } from "@/lib/labels";
import { buildIssueCards, disclosureIsSatisfied } from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { Badge, Tag } from "../ui";

function StatMini({
  label,
  value,
  sub,
  danger,
}: {
  label: string;
  value: string | number;
  sub?: string;
  danger: boolean;
}) {
  return (
    <div className="text-center">
      <div className="text-[10.5px] font-semibold whitespace-nowrap text-ink-4">{label}</div>
      <div className="mt-1">
        <span className={`text-[22px] font-extrabold ${danger ? "text-reject" : "text-pass"}`}>{value}</span>
        {sub && <span className="text-[11px] font-semibold text-ink-4">{sub}</span>}
      </div>
    </div>
  );
}

export function ExecSummary({ result, resolved }: { result: ReviewOutput; resolved: Set<string> }) {
  const cards = buildIssueCards(result).filter((card) => card.kind !== "trackB");
  const open = cards.filter((card) => !resolved.has(card.id)).length;
  const highOpen = cards.filter((card) => card.tone === "risk" && !resolved.has(card.id)).length;
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const met = checks.filter(disclosureIsSatisfied).length;
  const misleading = Number(result.overall_impression_judgment?.misleading_risk_score ?? 0);
  const grade = riskGrade(misleading);
  const gradeColor =
    grade.tone === "reject" ? "var(--reject)" : grade.tone === "review" ? "var(--revise)" : "var(--pass)";
  const gradeBg =
    grade.tone === "reject" ? "var(--reject-bg)" : grade.tone === "review" ? "var(--revise-bg)" : "var(--pass-bg)";
  const [aiLabel] = VERDICT_LABELS[result.final_verdict] ?? [result.final_verdict];

  return (
    <div className="flex shrink-0 items-stretch gap-4.5 rounded-[14px] border border-line bg-surface px-4.5 py-3.5 shadow-card">
      {/* 좌: AI 판정 */}
      <div className="flex flex-col justify-center gap-2 border-r border-line pr-4.5">
        <div className="text-[10.5px] font-bold tracking-wider text-ink-4 uppercase">AI 판정 · 권고</div>
        <Badge tone={verdictBadgeTone(result.final_verdict)}>{aiLabel}</Badge>
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-ink-3">오인 위험</span>
          <span
            title={`misleading_risk_score ${misleading.toFixed(2)}`}
            className="rounded-full px-2 py-0.5 text-[11px] font-bold"
            style={{ color: gradeColor, background: gradeBg }}
          >
            {grade.label}
          </span>
        </div>
      </div>

      {/* 중: 요약 사유 */}
      <div className="flex min-w-0 flex-1 flex-col justify-center">
        <div className="mb-1.5 flex items-center gap-1.5">
          <Icon name="spark" size={14} color="var(--brand)" />
          <span className="text-[11px] font-bold tracking-wider text-ink-4">요약 사유 · EXECUTIVE SUMMARY</span>
        </div>
        <p className="m-0 line-clamp-3 text-[13.5px] leading-relaxed text-ink-2" style={{ textWrap: "pretty" }}>
          {result.rationale}
        </p>
        {result.routing?.review_phrase_required_before_publication && (
          <div className="mt-1.5">
            <Tag tone="review">게시 전 심의필 표시 필요</Tag>
          </div>
        )}
      </div>

      {/* 우: 지표 */}
      <div className="flex items-center gap-4.5 border-l border-line pl-4.5">
        <StatMini label="미해소 이슈" value={open} sub={` / ${cards.length}`} danger={open > 0} />
        <StatMini label="위반 의심" value={highOpen} danger={highOpen > 0} />
        <StatMini
          label="필수 고지"
          value={`${met}/${checks.length}`}
          danger={checks.length > 0 && met < checks.length}
        />
      </div>
    </div>
  );
}
