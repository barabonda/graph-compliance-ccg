"use client";

import { useMemo } from "react";
import { VERDICT_LABELS } from "@/lib/labels";
import {
  buildComplianceGates,
  buildDisclosureItems,
  type DisclosureItem,
  type GateStatus,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState } from "../ui";
import { PaneHeader } from "./common";

interface Props {
  result: ReviewOutput | null;
  /** 사전심사 체크리스트에서 '심사자 확인함'으로 표시된 항목들. */
  acknowledged: Set<string>;
  onToggleAck: (id: string) => void;
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

function SummaryChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="rounded-[10px] bg-surface-2 px-3 py-2.5">
      <div className="text-[12px] text-ink-3">{label}</div>
      <div className="text-[22px] font-extrabold" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function SectionTitle({ icon, color, text }: { icon: string; color: string; text: string }) {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-[12px] font-bold" style={{ color }}>
      <Icon name={icon} size={14} color={color} /> {text}
    </div>
  );
}

/** 놓쳤을 수 있는 고지 한 줄. 토글은 '적용/시뮬레이션'이 아니라 '심사자 확인함'. */
function VerifyRow({
  item,
  acknowledged,
  onAck,
}: {
  item: DisclosureItem;
  acknowledged: boolean;
  onAck: () => void;
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-[11px] px-3.5 py-3"
      style={{ border: `1px solid ${acknowledged ? "var(--pass)" : "var(--revise)"}40`, background: "var(--revise-bg)" }}
    >
      <Icon name="alert" size={16} color="var(--revise)" style={{ flexShrink: 0, marginTop: 1 }} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[13.5px] font-bold text-ink">{item.label}</span>
          {item.required && (
            <span className="rounded-full bg-reject-bg px-1.5 py-px text-[10.5px] font-bold text-reject">필수</span>
          )}
        </div>
        <div className="mt-1 text-[12px] leading-relaxed text-ink-3">
          광고에서 이 고지를 자동으로 찾지 못했습니다. 표시 위치·맥락을 직접 확인하세요.
          {item.desc ? ` (${item.desc})` : ""}
        </div>
      </div>
      <button
        type="button"
        onClick={onAck}
        aria-pressed={acknowledged}
        className="inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-[11.5px] font-bold"
        style={
          acknowledged
            ? { borderColor: "var(--pass)", background: "var(--pass-bg)", color: "var(--pass)" }
            : { borderColor: "var(--line-2)", color: "var(--ink-2)" }
        }
      >
        <Icon name="check" size={13} color={acknowledged ? "var(--pass)" : "var(--ink-3)"} />
        {acknowledged ? "확인함" : "심사자 확인"}
      </button>
    </div>
  );
}

export function ExceptionView({ result, acknowledged, onToggleAck }: Props) {
  const items = useMemo(() => (result ? buildDisclosureItems(result) : []), [result]);

  if (!result) {
    return <EmptyState>Review를 실행하면 사전심사 체크리스트가 표시됩니다.</EmptyState>;
  }

  // 적용범위(gate ON) 안에서만 충족/확인필요를 가른다. OFF는 '해당 없음'.
  const applicable = items.filter((item) => item.gateStatus !== "OFF");
  const satisfied = applicable.filter((item) => item.present);
  const toVerify = applicable.filter((item) => !item.present);
  const notApplicable = items.filter((item) => item.gateStatus === "OFF");

  return (
    <div className="grid h-full gap-4" style={{ gridTemplateColumns: "340px minmax(0,1fr)" }}>
      <GateTimeline result={result} />

      <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
        <PaneHeader
          icon="shield"
          title="사전심사 체크리스트"
          sub="충족 · 확인 필요 · 해당 없음 — 결과를 단정하지 않는 보조 점검"
          right={
            <span
              className="rounded-full px-2.5 py-0.5 text-[12px] font-bold"
              style={{ color: "var(--pass)", background: "var(--pass-bg)" }}
            >
              충족 {satisfied.length}/{applicable.length}
            </span>
          }
        />
        <div className="flex-1 overflow-y-auto px-5 py-4.5">
          <div className="mb-5 grid grid-cols-3 gap-3">
            <SummaryChip label="충족" value={satisfied.length} color="var(--pass)" />
            <SummaryChip label="확인 필요" value={toVerify.length} color="var(--revise)" />
            <SummaryChip label="해당 없음" value={notApplicable.length} color="var(--ink-4)" />
          </div>

          <SectionTitle icon="alert" color="var(--revise)" text="놓쳤을 수 있는 것 — 직접 확인 권장" />
          {toVerify.length ? (
            <div className="mb-5 flex flex-col gap-2">
              {toVerify.map((item) => (
                <VerifyRow
                  key={item.id}
                  item={item}
                  acknowledged={acknowledged.has(item.id)}
                  onAck={() => onToggleAck(item.id)}
                />
              ))}
            </div>
          ) : (
            <p className="mb-5 rounded-[10px] bg-surface-2 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-ink-3">
              적용 대상 고지 중 자동 점검으로 빠진 항목이 없습니다. 단, 자동 점검은 완전하지 않으니 표현·맥락은 직접
              확인하세요.
            </p>
          )}

          <SectionTitle icon="check" color="var(--pass)" text="지금 충족된 것 — 근거가 광고에 보임" />
          <div className="mb-5 flex flex-col gap-1.5">
            {satisfied.length ? (
              satisfied.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 rounded-[10px] px-3.5 py-2.5"
                  style={{ background: "var(--pass-bg)" }}
                >
                  <Icon name="check" size={15} color="var(--pass)" stroke={2.4} style={{ flexShrink: 0 }} />
                  <span className="flex-1 text-[13px] font-semibold" style={{ color: "var(--pass)" }}>
                    {item.label}
                  </span>
                  <span className="text-[11.5px] text-ink-3">{item.desc}</span>
                </div>
              ))
            ) : (
              <p className="text-[12.5px] text-ink-3">충족으로 확인된 고지가 아직 없습니다.</p>
            )}
          </div>

          {notApplicable.length > 0 && (
            <>
              <SectionTitle
                icon="x"
                color="var(--ink-4)"
                text={`해당 없음 — 상품군/채널 적용범위 밖 (${notApplicable.length})`}
              />
              <div className="mb-4 flex flex-wrap gap-1.5">
                {notApplicable.map((item) => (
                  <span key={item.id} className="rounded-md bg-surface-2 px-2.5 py-1 text-[11.5px] text-ink-3">
                    {item.label}
                  </span>
                ))}
              </div>
            </>
          )}

          <div className="mt-1 flex items-start gap-2 rounded-[11px] border border-line bg-surface-2 px-3.5 py-3 text-[12px] leading-relaxed text-ink-2">
            <Icon name="alert" size={15} color="var(--ink-4)" style={{ flexShrink: 0, marginTop: 1 }} />
            <span>
              자동 점검은 완전하지 않습니다. ‘충족’도 표시 위계·맥락에 따라 달라질 수 있으니, 이 화면은 통과 여부를
              예측하지 않으며 최종 판단은 심사자 검토를 따릅니다.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
