"use client";

import { VERDICT_LABELS, verdictBadgeTone } from "@/lib/labels";
import { buildIssueCards, issueHeadline, keepNoticeCount } from "@/lib/selectors";
import type { ReviewOutput, StreamEvent } from "@/lib/types";
import { Badge, MetricCell } from "./ui";

interface Props {
  status: "idle" | "running" | "done" | "error";
  result: ReviewOutput | null;
  reviewedText: string;
  events: StreamEvent[];
}

export function VerdictHeader({ status, result, events }: Props) {
  if (status === "running") {
    const last = events.at(-1);
    return (
      <section className="flex flex-wrap items-center gap-4 rounded-lg border border-line bg-panel p-4 shadow-panel">
        <div className="min-w-56 flex-1">
          <Badge tone="review">실행 중</Badge>
          <p className="mt-2 text-sm text-muted">LLM/Neo4j 단계별 이벤트를 수신하고 있습니다.</p>
        </div>
        <MetricCell label="Events" value={events.length} />
        <MetricCell label="Step" value={<span className="text-sm">{last?.step ?? "-"}</span>} />
        <MetricCell label="Status" value={<span className="text-sm">{last?.event ?? "start"}</span>} />
        <MetricCell label="Run" value={<span className="text-sm">{last?.review_run_id ? "생성됨" : "-"}</span>} />
      </section>
    );
  }

  if (!result) {
    return (
      <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
        <span className="text-sm font-bold text-muted">심사 대기</span>
        <p className="mt-1 text-sm text-muted">광고 문안을 입력하고 Review를 실행하세요.</p>
      </section>
    );
  }

  const [label, desc] = VERDICT_LABELS[result.final_verdict] ?? [result.final_verdict, ""];
  const cards = buildIssueCards(result);
  const headline = issueHeadline(cards);
  const issueCount = cards.filter((card) => card.kind !== "trackB").length;
  const keepCount = keepNoticeCount(result);
  const misleadingScore = Number(result.overall_impression_judgment?.misleading_risk_score ?? 0);
  const hasRetrievalFailure = (result.context_anchors?.length ?? 0) > 0 && (result.cu_plan?.length ?? 0) === 0;

  return (
    <section className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-line bg-panel px-4 py-3 shadow-panel">
      <Badge tone={verdictBadgeTone(result.final_verdict)}>{label}</Badge>
      <span className="min-w-48 flex-1 text-sm font-semibold text-foreground" title={desc}>
        {headline || desc}
        {hasRetrievalFailure && <span className="ml-2 font-medium text-warn">정책 매칭 실패 · 검토 필요</span>}
      </span>
      <span className="text-sm text-muted">
        이슈 <b className="text-foreground">{issueCount}</b> · 유지 고지 <b className="text-foreground">{keepCount}</b> ·
        오인 <b className="text-foreground">{misleadingScore.toFixed(2)}</b>
      </span>
    </section>
  );
}
