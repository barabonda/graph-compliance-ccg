"use client";

import { trackBBadgeTone } from "@/lib/labels";
import type { ReviewOutput } from "@/lib/types";
import { Badge, Card, EmptyState, KeyValueText, Tag } from "../ui";

function riskTone(level?: string) {
  return trackBBadgeTone(level, level === "HIGH" ? 1 : level === "MEDIUM" ? 0.55 : 0.2);
}

export function OverallTab({ result }: { result: ReviewOutput | null }) {
  if (!result) {
    return <EmptyState>Review를 실행하면 전체 광고 인상과 문장 영향이 여기에 표시됩니다.</EmptyState>;
  }
  const frame = result.context_frame ?? {};
  const influences = result.context_influences ?? [];
  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <Card
          title="ContextFrame"
          actions={<Badge tone={riskTone(frame.overall_risk_level)}>{frame.overall_risk_level || "UNKNOWN"}</Badge>}
        >
          <KeyValueText
            items={[
              ["요약", frame.summary || "-"],
              ["핵심 메시지", frame.primary_message || "-"],
              ["대표 소비자 인상", frame.representative_consumer_impression || "-"],
            ]}
          />
        </Card>
        <Card title="광고 목적 / 톤 / 위험 축">
          <div className="mb-2 flex flex-wrap gap-1.5">
            <Tag>목적 {frame.product_purpose || "-"}</Tag>
            <Tag>톤 {frame.tone || "-"}</Tag>
          </div>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {(frame.risk_axes ?? []).length ? (
              (frame.risk_axes ?? []).map((axis) => <Tag key={axis}>{axis}</Tag>)
            ) : (
              <Tag>위험 축 없음</Tag>
            )}
          </div>
          <p className="text-xs leading-relaxed text-muted">
            이 레이어는 광고 전체를 먼저 읽고, 문장별 판단이 전체 인상에 어떻게 기여하는지 judge evidence window에
            전달합니다.
          </p>
        </Card>
      </div>
      <Card title="ContextInfluence">
        {influences.length ? (
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {influences.map((item) => (
              <article key={item.influence_id} className="rounded-md border border-line bg-panel-soft p-3">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <strong className="text-[13px]">{item.influence_type || "influence"}</strong>
                  <Tag>
                    {item.risk_delta || "NEUTRAL"} · {Number(item.confidence ?? 0).toFixed(2)}
                  </Tag>
                </div>
                <p className="text-xs leading-relaxed text-muted">{item.effect || "-"}</p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState>문장/표현이 전체 인상에 미치는 영향이 추출되지 않았습니다.</EmptyState>
        )}
      </Card>
    </div>
  );
}
