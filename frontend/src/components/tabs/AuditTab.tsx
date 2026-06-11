"use client";

import type { ReviewOutput, StreamEvent } from "@/lib/types";
import { Badge, EmptyState, Tag, type BadgeTone } from "../ui";

interface Props {
  result: ReviewOutput | null;
  events: StreamEvent[];
}

interface AuditStep {
  name: string;
  ok: boolean;
  summary: string;
}

function badgeFor(event: StreamEvent): { tone: BadgeTone; text: string } {
  if (event.event === "error") return { tone: "reject", text: "error" };
  if (event.event === "step_started") return { tone: "review", text: "running" };
  if (event.event === "step_completed") return { tone: "pass", text: "done" };
  if (event.event === "result") return { tone: "pass", text: "result" };
  return { tone: "review", text: "check" };
}

function buildAuditSteps(result: ReviewOutput): AuditStep[] {
  const chains = result.policy_evidence_chains ?? {};
  const chainCount = (rows?: { status?: string }[]) => (rows ?? []).filter((row) => row.status === "FOUND").length;
  return [
    {
      name: "Context extraction",
      ok: (result.context_anchors ?? []).length > 0,
      summary: `${result.context_anchors?.length ?? 0} anchors generated`,
    },
    {
      name: "Policy normalization",
      ok: (result.context_anchors ?? []).every((anchor) => anchor.hypernyms?.length),
      summary: "Approved PolicyHypernym vocabulary selected",
    },
    {
      name: "CU retrieval",
      ok: (result.cu_plan ?? []).length > 0,
      summary: `${result.cu_plan?.length ?? 0} CUPlan items · ${(result.system_review_items ?? []).length} diagnostics`,
    },
    {
      name: "Policy evidence chains",
      ok: chainCount(chains.legal_basis_chains) > 0,
      summary: `${chainCount(chains.legal_basis_chains)} legal · ${chainCount(chains.disclosure_chains)} disclosure · ${chainCount(
        chains.exception_chains,
      )} exception`,
    },
    {
      name: "LLM judgment",
      ok: (result.judgments ?? []).length > 0,
      summary: `${result.judgments?.length ?? 0} judgments`,
    },
    { name: "Exception override", ok: true, summary: `${result.exception_reviews?.length ?? 0} exception reviews` },
    {
      name: "Track B overall impression",
      ok: Boolean(result.overall_impression_judgment?.verdict),
      summary: `${result.overall_impression_judgment?.verdict ?? "pending"} · ${Number(
        result.overall_impression_judgment?.misleading_risk_score ?? 0,
      ).toFixed(2)}`,
    },
    {
      name: "Product fact graph",
      ok: Boolean(result.product_fact_context?.extraction_status),
      summary: `${result.product_fact_context?.extraction_status ?? "pending"} · ${
        (result.product_fact_context?.comparison_results ?? []).length
      } comparisons`,
    },
    {
      name: "Routing",
      ok: result.final_verdict !== "pass_candidate" || (result.cu_plan ?? []).length > 0,
      summary: result.final_verdict ?? "pending",
    },
  ];
}

export function AuditTab({ result, events }: Props) {
  if (events.length) {
    return (
      <div className="space-y-2">
        {events.map((event, index) => {
          const badge = badgeFor(event);
          return (
            <article
              key={index}
              className={`rounded-lg border bg-surface p-3 ${
                event.event === "error" ? "border-reject/50" : event.event === "result" ? "border-pass/50" : "border-line"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <strong className="text-[13px]">{event.step ?? event.event}</strong>
                <Badge tone={badge.tone}>{badge.text}</Badge>
              </div>
              {event.summary && <p className="mt-1 text-xs text-ink-3">{event.summary}</p>}
              {event.counts && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {Object.entries(event.counts).map(([key, value]) => (
                    <Tag key={key}>
                      {key} {value}
                    </Tag>
                  ))}
                </div>
              )}
              {event.detail != null && (
                <details open className="mt-2 text-xs text-ink-3">
                  <summary className="cursor-pointer font-semibold">error detail</summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-surface-2 p-2 font-mono text-[11px] whitespace-pre-wrap">
                    {JSON.stringify(event.detail, null, 2)}
                  </pre>
                </details>
              )}
              {event.sample != null && (
                <details className="mt-2 text-xs text-ink-3">
                  <summary className="cursor-pointer font-semibold">sample</summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-surface-2 p-2 font-mono text-[11px] whitespace-pre-wrap">
                    {JSON.stringify(event.sample, null, 2)}
                  </pre>
                </details>
              )}
              {event.received_at && <div className="mt-1.5 text-right text-[11px] text-ink-3">{event.received_at}</div>}
            </article>
          );
        })}
      </div>
    );
  }

  if (result) {
    return (
      <div className="space-y-2">
        {buildAuditSteps(result).map((step) => (
          <article key={step.name} className="rounded-lg border border-line bg-surface p-3">
            <div className="flex items-center justify-between gap-2">
              <strong className="text-[13px]">{step.name}</strong>
              <Badge tone={step.ok ? "pass" : "review"}>{step.ok ? "success" : "check"}</Badge>
            </div>
            <p className="mt-1 text-xs text-ink-3">{step.summary}</p>
          </article>
        ))}
      </div>
    );
  }

  return <EmptyState>Review를 실행하면 단계별 trace가 여기에 실시간으로 표시됩니다.</EmptyState>;
}
