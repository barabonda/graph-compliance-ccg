"use client";

import { principleColor, verdictBadgeTone, VERDICT_LABELS, abbreviateLawNames } from "@/lib/labels";
import {
  buildEvidencePath,
  buildIssueCards,
  delegationByPrinciple,
  judgmentsForAnchor,
  planItemsForAnchor,
  type EvidenceNodeKind,
} from "@/lib/selectors";
import type { FinalVerdict, LLMJudgment, ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState, Tag } from "../ui";
import { DelegationChain, PrincipleTags } from "./DelegationChain";
import { PaneHeader } from "./common";
import { TONE_BG, TONE_COLOR, TONE_WORD_SHORT } from "./RiskList";

interface Props {
  result: ReviewOutput | null;
  selectedAnchorId: string;
  onSelectAnchor: (anchorId: string) => void;
}

/** 해설 문장 칩 색 — 경로 해설에서 재사용. */
const NODE_META: Record<EvidenceNodeKind, { color: string }> = {
  claim: { color: "var(--reject)" },
  risk: { color: "#e0701a" },
  policy: { color: "#a07200" },
  cu: { color: "var(--brand)" },
  premise: { color: "#7c5cde" },
  clause: { color: "var(--pass)" },
};

/** 개별 판정 verdict → 심사 실무 언어·색. */
const JUDGMENT_LABEL: Record<string, { word: string; color: string }> = {
  NON_COMPLIANT: { word: "위반 의심", color: "var(--reject)" },
  INSUFFICIENT: { word: "검토 필요", color: "var(--revise)" },
  COMPLIANT: { word: "적합", color: "var(--pass)" },
  NOT_APPLICABLE: { word: "해당 없음", color: "var(--ink-4)" },
};

const FINAL_TONE_BG: Record<string, string> = {
  pass: "linear-gradient(150deg,#0a7550,#0a5f42)",
  review: "linear-gradient(150deg,#2760d8,#1d4bb0)",
  revise: "linear-gradient(150deg,#a86a00,#8a5700)",
  reject: "linear-gradient(150deg,#c2372c,#9e2c23)",
};

/** 레이어 사이 세로 커넥터 — 흐름의 의미(grounding·위임·판정)를 라벨로 명시. */
function Connector({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center py-1" aria-hidden>
      <span className="h-3.5 w-0.5 bg-line-2" />
      <span className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-[11px] font-bold text-ink-3">
        {label}
      </span>
      <span className="h-3.5 w-0.5 bg-line-2" />
      <Icon name="arrowR" size={13} color="var(--ink-4)" style={{ transform: "rotate(90deg)", marginTop: -2 }} />
    </div>
  );
}

/** 레이어 컨테이너 — 좌측 세로 라벨 + 내용. 계층이 위→아래로 읽히게 한다. */
function Layer({ no, title, sub, children }: { no: string; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[13px] border border-line bg-surface-2 px-4 py-3.5">
      <div className="mb-2.5 flex items-baseline gap-2">
        <span className="font-mono text-[11px] font-bold text-ink-4">{no}</span>
        <span className="text-[12px] font-extrabold tracking-wide text-ink-2 uppercase">{title}</span>
        {sub && <span className="text-[11px] text-ink-4">{sub}</span>}
      </div>
      {children}
    </section>
  );
}

export function GraphView({ result, selectedAnchorId, onSelectAnchor }: Props) {
  if (!result) {
    return <EmptyState>Review를 실행하면 근거 경로 그래프가 표시됩니다.</EmptyState>;
  }
  const anchorCards = buildIssueCards(result).filter((card) => card.kind === "anchor" && card.anchorId);
  const activeId =
    anchorCards.find((card) => card.anchorId === selectedAnchorId)?.anchorId ?? anchorCards[0]?.anchorId ?? "";
  const path = activeId ? buildEvidencePath(result, activeId) : null;

  if (!path) {
    return <EmptyState>경로를 추적할 Claim anchor가 없습니다.</EmptyState>;
  }

  const activeCard = anchorCards.find((card) => card.anchorId === activeId);
  const anchor = result.context_anchors?.find((item) => item.anchor_id === activeId);
  const hypernyms = (anchor?.hypernyms ?? []).slice(0, 4);
  const plans = planItemsForAnchor(result, activeId);
  const judgments = judgmentsForAnchor(result, activeId);
  const judgmentByPlan = new Map<string, LLMJudgment>(judgments.map((j) => [j.plan_item_id, j]));
  const delegationGroups = delegationByPrinciple(result, activeId).filter((g) => g.steps.length > 0);
  const finalVerdict = (result.final_verdict ?? "needs_review") as FinalVerdict;
  const finalTone = verdictBadgeTone(finalVerdict);
  const verdictCounts = judgments.reduce<Record<string, number>>((acc, j) => {
    acc[j.verdict] = (acc[j.verdict] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="grid h-full gap-4" style={{ gridTemplateColumns: "248px minmax(0,1fr)" }}>
      {/* 좌: claim 선택 */}
      <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
        <div className="border-b border-line px-4 py-3.5">
          <div className="text-[11px] font-bold tracking-wider text-ink-4 uppercase">설명 경로 선택</div>
          <div className="mt-1 text-[12.5px] text-ink-3">Claim을 선택해 근거 경로를 추적합니다.</div>
        </div>
        <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2.5">
          {anchorCards.map((card) => {
            const selected = card.anchorId === activeId;
            const color = TONE_COLOR[card.tone];
            return (
              <button
                key={card.id}
                type="button"
                onClick={() => card.anchorId && onSelectAnchor(card.anchorId)}
                className="rounded-[9px] px-2.5 py-2.5 text-left"
                style={{
                  border: selected ? `1.5px solid ${color}` : "1px solid var(--line)",
                  background: selected ? TONE_BG[card.tone] : "var(--surface)",
                }}
              >
                <div className="mb-1 flex items-center gap-1.5">
                  <span className="font-mono text-[11px] font-bold text-ink-4">{card.code}</span>
                  <span className="ml-auto h-1.5 w-1.5 rounded-full" style={{ background: color }} />
                </div>
                <div className="text-[12.5px] leading-snug font-semibold break-keep text-ink">“{card.quote}”</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 우: 계층형 근거 경로 — Context Graph → 심의 기준 → 법령 위임 사슬 → 판정.
          변호사의 추론 순서 그대로 위에서 아래로 읽힌다(평탄한 가로 체인 폐기). */}
      <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
        <PaneHeader
          icon="graph"
          title="근거 경로"
          sub={`${activeCard?.code ?? ""} · 광고 표현 → 법령 위임 사슬 → 판정`}
          right={
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-bold"
              style={{ color: TONE_COLOR[path.tone], background: TONE_BG[path.tone] }}
            >
              {TONE_WORD_SHORT[path.tone]}
            </span>
          }
        />
        <div className="flex-1 overflow-y-auto px-5 py-5">
          {/* ① Context Graph — 광고 표현과 그 의미(위험 유형·정책어 정규화) */}
          <Layer no="①" title="Context Graph" sub="광고 표현 · 위험 분류 · 정책어 정규화">
            <div className="rounded-[11px] border bg-surface p-3" style={{ borderColor: "color-mix(in srgb, var(--reject) 35%, var(--line))" }}>
              <div className="text-[14px] leading-snug font-bold break-keep text-ink">“{path.quote}”</div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="rounded-md px-2 py-0.5 text-[11px] font-bold" style={{ color: "#b45309", background: "#fdf3e3" }}>
                  위험 유형 · {path.riskLabel}
                </span>
                {hypernyms.map((h) => (
                  <span
                    key={h.proposal_id}
                    className="rounded-md bg-surface-3 px-2 py-0.5 text-[11px] font-semibold text-ink-2"
                    title={`정책어 정규화 (confidence ${(h.confidence * 100).toFixed(0)}%)`}
                  >
                    {h.hypernym}
                    {h.support === "STRONG" ? " ●" : ""}
                  </span>
                ))}
              </div>
            </div>
          </Layer>

          <Connector label={`grounding — 심의 기준 ${plans.length}건 매칭`} />

          {/* ② 심의 기준(CU) — 한 표현이 여러 기준에 걸리는 fan-out을 그대로 보여준다 */}
          <Layer no="②" title="심의 기준 · Compliance Unit" sub={`${plans.length}건 · 각 기준별 개별 판정`}>
            <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
              {plans.map((item) => {
                const judgment = judgmentByPlan.get(item.plan_item_id);
                const meta = judgment ? JUDGMENT_LABEL[judgment.verdict] : null;
                return (
                  <div
                    key={item.plan_item_id}
                    className="flex flex-col gap-1.5 rounded-[11px] border bg-surface p-3"
                    style={{ borderColor: meta ? `color-mix(in srgb, ${meta.color} 40%, var(--line))` : "var(--line)" }}
                  >
                    <div className="flex items-center gap-1.5">
                      {item.principle && <Tag color={principleColor(item.principle)}>{item.principle}</Tag>}
                      {meta && (
                        <span className="ml-auto text-[11px] font-bold whitespace-nowrap" style={{ color: meta.color }}>
                          {meta.word}
                          {judgment && judgment.verdict !== "NOT_APPLICABLE" ? ` ${(judgment.score * 100).toFixed(0)}%` : ""}
                        </span>
                      )}
                    </div>
                    <div className="line-clamp-2 text-[12.5px] leading-snug font-semibold break-keep text-ink">
                      {item.risk_title || item.constraint || item.subject}
                    </div>
                    <div className="mt-auto line-clamp-2 text-[11px] leading-relaxed text-ink-3" title={item.source_article}>
                      {abbreviateLawNames(item.source_article)}
                    </div>
                  </div>
                );
              })}
            </div>
          </Layer>

          <Connector label="근거 조문 — 법령 위임 사슬 (법률 → 시행령 → 감독규정 → 심의기준)" />

          {/* ③ 법령 위임 사슬 — 조문이 어느 권위 계층에서 왔는지 세로 위계로 */}
          <Layer no="③" title="법령 위임 사슬" sub="원칙별 · 권위 계층 순서">
            {delegationGroups.length > 0 ? (
              <div className="grid gap-2.5" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
                {delegationGroups.map((group) => (
                  <div key={group.principle} className="rounded-[11px] border border-line bg-surface px-4 py-3.5">
                    <div className="mb-2">
                      <PrincipleTags principles={[group.principle]} />
                    </div>
                    <DelegationChain steps={group.steps} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[12.5px] text-ink-4">이 표현에 연결된 위임 사슬이 없습니다 — 대표 조문은 위 심의 기준 카드를 참고하세요.</div>
            )}
          </Layer>

          <Connector label="조문 적용 → 판정" />

          {/* ④ 판정 — 개별 판정이 최종 결과로 수렴 */}
          <Layer no="④" title="판정" sub="개별 판정 → 광고 전체 최종 결과">
            <div className="flex flex-wrap items-stretch gap-3">
              <div className="min-w-[200px] flex-1 rounded-[11px] border border-line bg-surface p-3">
                <div className="mb-1.5 text-[11px] font-bold text-ink-4">이 표현의 개별 판정</div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(verdictCounts).map(([verdict, count]) => {
                    const meta = JUDGMENT_LABEL[verdict];
                    if (!meta) return null;
                    return (
                      <span
                        key={verdict}
                        className="rounded-md px-2 py-1 text-[12px] font-bold"
                        style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 10%, white)` }}
                      >
                        {meta.word} {count}건
                      </span>
                    );
                  })}
                  {judgments.length === 0 && <span className="text-[12px] text-ink-4">판정 없음 — 심사자 확인 필요</span>}
                </div>
                {path.disclosure && (
                  <div className="mt-2 border-t border-line pt-2 text-[11.5px] leading-relaxed text-ink-3">
                    <b className="text-ink-2">필요 고지/예외</b> · {path.disclosure}
                  </div>
                )}
              </div>
              <div
                className="flex min-w-[190px] flex-col justify-center gap-1 rounded-[11px] px-4 py-3 text-white"
                style={{ background: FINAL_TONE_BG[finalTone] }}
              >
                <div className="text-[11px] font-bold tracking-wider uppercase opacity-85">최종 결과 · 광고 전체</div>
                <div className="text-[18px] font-extrabold">{VERDICT_LABELS[finalVerdict]?.[0] ?? finalVerdict}</div>
                <div className="text-[11px] opacity-85">이 표현을 포함한 전체 판정의 종합 — 최종 승인은 심사자</div>
              </div>
            </div>
          </Layer>

          {/* 자연어 해설 */}
          <div className="mt-5">
            <div className="mb-2.5 text-[11px] font-bold tracking-wider text-ink-4 uppercase">경로 해설</div>
            <div className="rounded-[12px] border border-line bg-surface-2 px-4.5 py-4">
              <p className="m-0 text-[13.5px] leading-[1.75] text-ink-2">
                광고 표현 <b className="text-ink">“{path.quote}”</b> 은(는){" "}
                <b style={{ color: NODE_META.risk.color }}>{path.riskLabel}</b> 위험으로 분류되어,{" "}
                {hypernyms.length > 0 ? (
                  <>
                    정책어 <b style={{ color: NODE_META.policy.color }}>{hypernyms[0].hypernym}</b>
                    {hypernyms.length > 1 ? ` 외 ${hypernyms.length - 1}건` : ""}을 통해{" "}
                  </>
                ) : null}
                {path.cuName ? (
                  <>
                    심의 기준 <b style={{ color: NODE_META.cu.color }}>{path.cuName}</b>
                    {plans.length > 1 ? ` 외 ${plans.length - 1}건` : ""}에 연결되었습니다.{" "}
                  </>
                ) : (
                  <>관련 심의 기준이 아직 연결되지 않아 검토가 필요합니다. </>
                )}
                {path.articles.length > 0 ? (
                  <>
                    법적 근거는 <b style={{ color: NODE_META.clause.color }}>{abbreviateLawNames(path.articles.join(", "))}</b> 이며,
                    위임 사슬을 따라 적용되어{" "}
                  </>
                ) : null}
                최종적으로 <b style={{ color: TONE_COLOR[path.tone] }}>{TONE_WORD_SHORT[path.tone]}</b> 판정에 기여했습니다.{" "}
                <span className="text-ink-4">— AI 권고이며 최종 판단은 심사자 검토를 따릅니다.</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
