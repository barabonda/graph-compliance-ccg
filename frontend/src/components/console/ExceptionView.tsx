"use client";

import { useMemo, useState } from "react";
import { VERDICT_LABELS, verdictBadgeTone } from "@/lib/labels";
import {
  buildComplianceGates,
  buildDisclosureItems,
  buildIssueCards,
  type GateStatus,
} from "@/lib/selectors";
import type { FinalVerdict, ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { Badge, EmptyState } from "../ui";
import { PaneHeader } from "./common";

interface Props {
  result: ReviewOutput | null;
  resolved: Set<string>;
}

const GATE_META: Record<GateStatus, { color: string; bg: string; icon: string }> = {
  ok: { color: "var(--pass)", bg: "var(--pass-bg)", icon: "check" },
  warn: { color: "var(--revise)", bg: "var(--revise-bg)", icon: "alert" },
  fail: { color: "var(--reject)", bg: "var(--reject-bg)", icon: "x" },
};

function GateTimeline({ result }: { result: ReviewOutput }) {
  const gates = buildComplianceGates(result);
  const cuPlan = result.cu_plan?.length ?? 0;
  const [aiLabel] = VERDICT_LABELS[result.final_verdict] ?? [result.final_verdict];

  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
      <PaneHeader icon="clock" title="Compliance Gate" sub="파이프라인 단계별 추적" />
      <div className="flex-1 overflow-y-auto px-4.5 pt-4.5 pb-3">
        {gates.map((gate, i) => {
          const meta = GATE_META[gate.status];
          const last = i === gates.length - 1;
          return (
            <div key={gate.step} className="flex gap-3">
              <div className="flex shrink-0 flex-col items-center">
                <div
                  className="grid h-[30px] w-[30px] place-items-center rounded-full"
                  style={{ background: meta.bg, border: `1.5px solid ${meta.color}` }}
                >
                  <Icon name={meta.icon} size={15} color={meta.color} stroke={2.4} />
                </div>
                {!last && (
                  <div
                    className="my-1 w-0.5 flex-1 rounded"
                    style={{ minHeight: 26, background: gate.status === "fail" ? "var(--reject)" : "var(--line-2)" }}
                  />
                )}
              </div>
              <div className={`min-w-0 flex-1 ${last ? "pb-2" : "pb-4"}`}>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] font-bold text-ink-4">STEP {gate.step}</span>
                  <span className="text-[13.5px] font-bold text-ink">{gate.name}</span>
                </div>
                <div className="mt-0.5 text-[12.5px] leading-relaxed text-ink-2">{gate.detail}</div>
                <span
                  className="mt-1.5 inline-block rounded-md px-2 py-0.5 font-mono text-[11px] font-bold"
                  style={{ color: meta.color, background: meta.bg }}
                >
                  {gate.meta}
                </span>
              </div>
            </div>
          );
        })}
        <div className="mt-1 flex items-start gap-2.5 rounded-[10px] border border-[#f3c9c4] bg-reject-bg px-3 py-2.5">
          <Icon name="alert" size={16} color="var(--reject)" style={{ flexShrink: 0, marginTop: 1 }} />
          <div className="text-[12.5px] leading-relaxed text-[#9a2f27]">
            <b>CU 후보 {cuPlan}건 (검색 성공)</b>이므로 ‘검색 실패’가 아니라 실제 검토 대상입니다. 표현 심사와 예외·고지
            충족 결과로 <b>{aiLabel}</b>이(가) 산정되었습니다.
          </div>
        </div>
      </div>
    </div>
  );
}

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative h-[23px] w-10 shrink-0 rounded-full transition-colors"
      style={{ background: on ? "var(--pass)" : "var(--line-2)" }}
      aria-pressed={on}
    >
      <span
        className="absolute top-[2.5px] h-[18px] w-[18px] rounded-full bg-white transition-[left] duration-200"
        style={{ left: on ? 19.5 : 2.5, boxShadow: "0 1px 3px rgba(0,0,0,.25)" }}
      />
    </button>
  );
}

function RoutingCell({
  label,
  verdict,
  sub,
  highlight,
}: {
  label: string;
  verdict: FinalVerdict;
  sub: string;
  highlight?: boolean;
}) {
  const [vLabel] = VERDICT_LABELS[verdict] ?? [verdict];
  const tone = verdictBadgeTone(verdict);
  const color =
    tone === "reject" ? "var(--reject)" : tone === "revise" ? "var(--revise)" : tone === "pass" ? "var(--pass)" : "var(--review)";
  return (
    <div
      className="rounded-[12px] px-4 py-3.5"
      style={
        highlight
          ? { border: `1.5px solid ${color}55`, background: tone === "reject" ? "var(--reject-bg)" : tone === "revise" ? "var(--revise-bg)" : "var(--review-bg)" }
          : { border: "1px solid var(--line)", background: "var(--surface-2)" }
      }
    >
      <div className="flex items-center gap-1.5">
        {highlight && <Icon name="spark" size={13} color={color} />}
        <span className="text-[11px] font-bold tracking-wider uppercase" style={{ color: highlight ? color : "var(--ink-4)" }}>
          {label}
        </span>
      </div>
      <div className="mt-2">
        <Badge tone={tone}>{vLabel}</Badge>
      </div>
      <div className="mt-2 text-[12px] text-ink-2">{sub}</div>
    </div>
  );
}

export function ExceptionView({ result, resolved }: Props) {
  const baseItems = useMemo(() => (result ? buildDisclosureItems(result) : []), [result]);
  const [present, setPresent] = useState<Record<string, boolean>>({});

  if (!result) {
    return <EmptyState>Review를 실행하면 예외·고지 검토가 표시됩니다.</EmptyState>;
  }

  const items = baseItems.map((item) => ({ ...item, present: present[item.id] ?? item.present }));
  const required = items.filter((item) => item.required);
  const metRequired = required.filter((item) => item.present).length;
  const allMet = required.length > 0 && metRequired === required.length;

  const cards = buildIssueCards(result).filter((card) => card.kind === "anchor");
  const highOpen = cards.filter((card) => card.tone === "risk" && !resolved.has(card.id)).length;

  // 조정 시 예상 라우팅 (AI 권고형). 필수 고지 미충족 → 반려 권고,
  // 고위험 미해소 → 수정 권고, 그 외 → 검토 필요.
  const predicted: FinalVerdict =
    metRequired < required.length ? "reject" : highOpen > 0 ? "revise" : "needs_review";

  const toggle = (id: string) =>
    setPresent((prev) => {
      const current = items.find((item) => item.id === id)?.present ?? false;
      return { ...prev, [id]: !current };
    });

  return (
    <div className="grid h-full gap-4" style={{ gridTemplateColumns: "340px minmax(0,1fr)" }}>
      <GateTimeline result={result} />

      <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
        <PaneHeader
          icon="shield"
          title="예외 · 고지 충족 검토"
          sub="고지를 추가하면 라우팅이 어떻게 완화되는지 시뮬레이션"
          right={
            <span
              className="rounded-full px-2.5 py-0.5 text-[12px] font-bold"
              style={{
                color: allMet ? "var(--pass)" : "var(--reject)",
                background: allMet ? "var(--pass-bg)" : "var(--reject-bg)",
              }}
            >
              필수 {metRequired}/{required.length}
            </span>
          }
        />
        <div className="flex-1 overflow-y-auto px-5 py-4.5">
          {/* 시뮬레이션 결과 */}
          <div className="mb-5 grid grid-cols-2 gap-3">
            <RoutingCell
              label="현재 판정 (권고)"
              verdict={result.final_verdict}
              sub={`필수 고지 ${baseItems.filter((i) => i.required && i.present).length}/${required.length} · 고위험 위반 미해소`}
            />
            <RoutingCell
              label="조정 시 예상"
              verdict={predicted}
              sub={`필수 고지 ${metRequired}/${required.length} · 고위험 미해소 ${highOpen}건`}
              highlight
            />
          </div>

          <div className="mb-2.5 flex items-center justify-between">
            <span className="text-[11px] font-bold tracking-wider text-ink-4 uppercase">고지 / 예외 항목</span>
            <span className="text-[11.5px] text-ink-3">토글로 고지 추가를 시뮬레이션</span>
          </div>

          <div className="flex flex-col gap-2">
            {items.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-3.5 rounded-[11px] px-3.5 py-3 transition-colors"
                style={{
                  border: `1px solid ${item.present ? "#bfe6d4" : "var(--line)"}`,
                  background: item.present ? "var(--pass-bg)" : "var(--surface)",
                }}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13.5px] font-bold text-ink">{item.label}</span>
                    {item.required ? (
                      <span className="rounded-full bg-reject-bg px-1.5 py-px text-[10.5px] font-bold text-reject">필수</span>
                    ) : (
                      <span className="rounded-full bg-surface-3 px-1.5 py-px text-[10.5px] font-bold text-ink-3">권장</span>
                    )}
                  </div>
                  <div className="mt-1 text-[12px] leading-relaxed text-ink-3">{item.desc}</div>
                  {item.status !== "PRESENT" && item.status !== "MISSING" ? (
                    <div className="mt-1 text-[11.5px] leading-relaxed text-ink-3">
                      {item.statusLabel}
                      {item.gateReason ? ` · ${item.gateReason}` : ""}
                    </div>
                  ) : null}
                </div>
                <span
                  className="w-24 text-right text-[11.5px] font-bold"
                  style={{ color: item.present ? "var(--pass)" : "var(--ink-4)" }}
                >
                  {item.present ? "충족" : item.statusLabel}
                </span>
                <Toggle on={item.present} onClick={() => toggle(item.id)} />
              </div>
            ))}
          </div>

          <div className="mt-4 rounded-[11px] border border-line bg-surface-2 px-3.5 py-3 text-[12.5px] leading-relaxed text-ink-2">
            금융상품 광고는 위험 표현이 있다고 해서 곧바로 위반이 확정되지 않습니다. 필수 고지가 인접 위치에 명료히
            병기되고 준법감시인 심의를 거치면 완화될 수 있으나,{" "}
            <b className="text-ink">원금보장 오인·확정수익 단정과 같은 고위험 표현은 고지만으로 완화되지 않으며 표현 자체의 수정이 필요</b>
            합니다. — 본 시뮬레이션은 AI 보조 추정이며 최종 판단은 심사자 검토를 따릅니다.
          </div>
        </div>
      </div>
    </div>
  );
}
