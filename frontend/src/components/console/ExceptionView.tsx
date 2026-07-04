"use client";

import { useMemo } from "react";
import { abbreviateLawNames } from "@/lib/labels";
import { buildDisclosureItems, type DisclosureItem } from "@/lib/selectors";
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

/** 권위 계층 배지 — 이 프로젝트의 핵심 구분(법령 위반 근거 vs 심의기준 미흡). */
function TierBadge({ tier, note }: { tier: string; note?: string }) {
  if (tier === "law") {
    return (
      <span
        className="rounded-full bg-reject-bg px-1.5 py-px text-[11px] font-bold whitespace-nowrap text-reject"
        title="법령이 표시를 요구하는 항목 — 누락 시 법령 위반 근거가 됩니다."
      >
        법령 근거
      </span>
    );
  }
  if (tier === "guideline") {
    return (
      <span
        className="rounded-full bg-revise-bg px-1.5 py-px text-[11px] font-bold whitespace-nowrap text-revise"
        title={note || "법령 위반이 아닌 심의기준(자율규제) 미흡입니다."}
      >
        심의기준
      </span>
    );
  }
  return null;
}

function SummaryChip({ label, value, sub, color }: { label: string; value: number; sub?: string; color: string }) {
  return (
    <div className="rounded-[10px] bg-surface-2 px-3 py-2.5">
      <div className="text-[12px] text-ink-3">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-[22px] font-extrabold" style={{ color }}>
          {value}
        </span>
        {sub && <span className="text-[11px] font-semibold text-ink-4">{sub}</span>}
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

/** 놓쳤을 수 있는 고지 한 줄. 토글은 '적용/시뮬레이션'이 아니라 '심사자 확인함'.
 * 색 예산: 전면 워시 대신 흰 카드 + 좌측 세로 바(법령=빨강·심의기준=앰버)만 —
 * 본문은 흰 배경 위 진한 잉크라 작은 글자도 또렷하다. */
function VerifyRow({
  item,
  acknowledged,
  onAck,
}: {
  item: DisclosureItem;
  acknowledged: boolean;
  onAck: () => void;
}) {
  const barColor = acknowledged ? "var(--pass)" : item.authorityTier === "law" ? "var(--reject)" : "var(--revise)";
  return (
    <div
      className="relative flex items-start gap-3 rounded-[11px] border border-line bg-surface py-3 pr-3.5 pl-4.5"
      style={{ opacity: acknowledged ? 0.72 : 1 }}
    >
      <span className="absolute top-3 bottom-3 left-0 w-[3px] rounded-full" style={{ background: barColor }} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`text-[14px] font-bold text-ink ${acknowledged ? "line-through decoration-ink-4" : ""}`}>
            {item.label}
          </span>
          {item.required && (
            <span className="rounded-full bg-reject-bg px-1.5 py-px text-[11px] font-bold text-reject">필수</span>
          )}
          <TierBadge tier={item.authorityTier} note={item.tierNote} />
        </div>
        <div className="mt-1 text-[12.5px] leading-relaxed break-keep text-ink-2">
          광고에서 이 고지를 자동으로 찾지 못했습니다. 표시 위치·맥락을 직접 확인하세요.
          {item.desc ? ` (${item.desc})` : ""}
        </div>
        {item.basis && (
          <div className="mt-1.5 text-[12px] leading-relaxed break-keep text-ink-3" title={item.basis}>
            <b className="text-ink-2">근거</b> · {abbreviateLawNames(item.basis)}
            {item.coBasis ? ` · 병기 ${abbreviateLawNames(item.coBasis)}` : ""}
          </div>
        )}
      </div>
      <button
        type="button"
        onClick={onAck}
        aria-pressed={acknowledged}
        className="inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1.5 text-[12px] font-bold"
        style={
          acknowledged
            ? { borderColor: "var(--pass)", background: "var(--pass-bg)", color: "var(--pass)" }
            : { borderColor: "var(--line-2)", color: "var(--ink-2)", background: "var(--surface)" }
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
  // 확인 필요: 법령 근거·필수·심각도 순으로 — 심사자가 위에서부터 처리하면 되는 순서.
  const toVerify = applicable
    .filter((item) => !item.present)
    .sort(
      (a, b) =>
        (b.authorityTier === "law" ? 1 : 0) - (a.authorityTier === "law" ? 1 : 0) ||
        (b.required ? 1 : 0) - (a.required ? 1 : 0) ||
        b.severity - a.severity,
    );
  const notApplicable = items.filter((item) => item.gateStatus === "OFF");
  const ackCount = toVerify.filter((item) => acknowledged.has(item.id)).length;
  const lawPending = toVerify.filter((item) => item.authorityTier === "law" && !acknowledged.has(item.id)).length;
  // 진행률: 충족 + 심사자 확인 완료 / 적용 대상 전체.
  const progress = applicable.length ? Math.round(((satisfied.length + ackCount) / applicable.length) * 100) : 100;
  const allDone = toVerify.length === ackCount;

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
      <PaneHeader
        icon="shield"
        title="사전심사 체크리스트"
        sub="충족 · 확인 필요 · 해당 없음 — 결과를 단정하지 않는 보조 점검"
        right={
          <div className="flex items-center gap-2">
            <span
              className="rounded-full px-2.5 py-0.5 text-[12px] font-bold"
              style={
                allDone
                  ? { color: "var(--pass)", background: "var(--pass-bg)" }
                  : { color: "var(--revise)", background: "var(--revise-bg)" }
              }
            >
              심사자 확인 {ackCount}/{toVerify.length}
            </span>
            <span
              className="rounded-full px-2.5 py-0.5 text-[12px] font-bold"
              style={{ color: "var(--pass)", background: "var(--pass-bg)" }}
            >
              충족 {satisfied.length}/{applicable.length}
            </span>
          </div>
        }
      />
      <div className="flex-1 overflow-y-auto px-5 py-4.5">
        {/* 점검 진행률 — 충족 + 심사자 확인을 합친 처리율 */}
        <div className="mb-4">
          <div className="mb-1 flex items-baseline justify-between text-[11.5px] text-ink-3">
            <span className="font-bold">
              점검 진행률 {progress}%
              {lawPending > 0 && (
                <span className="ml-2 font-semibold text-reject">법령 근거 미확인 {lawPending}건 우선 확인</span>
              )}
            </span>
            <span className="text-ink-4">충족 {satisfied.length} + 확인 {ackCount} / 적용 {applicable.length}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface-3">
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${progress}%`, background: allDone ? "var(--pass)" : "var(--brand)" }}
            />
          </div>
        </div>

        <div className="mb-5 grid grid-cols-4 gap-3">
          <SummaryChip label="충족" value={satisfied.length} color="var(--pass)" />
          <SummaryChip
            label="확인 필요 · 법령 근거"
            value={toVerify.filter((i) => i.authorityTier === "law").length}
            sub="누락 시 법령 위반"
            color="var(--reject)"
          />
          <SummaryChip
            label="확인 필요 · 심의기준"
            value={toVerify.filter((i) => i.authorityTier !== "law").length}
            sub="자율규제 보완"
            color="var(--revise)"
          />
          <SummaryChip label="해당 없음" value={notApplicable.length} color="var(--ink-4)" />
        </div>

        <SectionTitle icon="alert" color="var(--revise)" text="놓쳤을 수 있는 것 — 직접 확인 권장 (법령 근거 우선 정렬)" />
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
                className="relative flex items-center gap-3 rounded-[10px] border border-line bg-surface py-2.5 pr-3.5 pl-4.5"
              >
                <span className="absolute top-2.5 bottom-2.5 left-0 w-[3px] rounded-full bg-pass" />
                <Icon name="check" size={15} color="var(--pass)" stroke={2.4} style={{ flexShrink: 0 }} />
                <span className="min-w-0 flex-1 text-[13.5px] font-bold text-ink">{item.label}</span>
                <TierBadge tier={item.authorityTier} note={item.tierNote} />
                <span className="max-w-[45%] truncate text-[12px] text-ink-3" title={item.basis || item.desc}>
                  {item.basis ? abbreviateLawNames(item.basis) : item.desc}
                </span>
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
                <span
                  key={item.id}
                  className="rounded-md bg-surface-2 px-2.5 py-1 text-[11.5px] text-ink-3"
                  title={item.gateReason || undefined}
                >
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
  );
}
