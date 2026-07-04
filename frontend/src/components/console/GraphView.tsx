"use client";

import {
  buildEvidencePath,
  buildIssueCards,
  delegationByPrinciple,
  type EvidenceNodeKind,
} from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState } from "../ui";
import { DelegationChain, PrincipleTags } from "./DelegationChain";
import { PaneHeader } from "./common";
import { TONE_BG, TONE_COLOR, TONE_WORD_SHORT } from "./RiskList";

interface Props {
  result: ReviewOutput | null;
  selectedAnchorId: string;
  onSelectAnchor: (anchorId: string) => void;
}

const NODE_META: Record<EvidenceNodeKind, { type: string; color: string; icon: string }> = {
  claim: { type: "광고 표현", color: "#d6453a", icon: "flag" },
  risk: { type: "위험 유형", color: "#e0701a", icon: "alert" },
  policy: { type: "정책어 (Hypernym)", color: "#c08a00", icon: "layers" },
  cu: { type: "Compliance Unit", color: "#2f6df0", icon: "clause" },
  premise: { type: "전제 (Premise)", color: "#7c5cde", icon: "target" },
  clause: { type: "근거 조문", color: "#0f9d6b", icon: "clause" },
};

const NODE_W = 168;
const NODE_H = 124;
const GAP = 40;
const TERM_W = 184;
const PAD_X = 12;
const PAD_Y = 16;

function GraphNode({
  x,
  y,
  kind,
  label,
  sub,
  connected,
}: {
  x: number;
  y: number;
  kind: EvidenceNodeKind;
  label: string;
  sub?: string;
  connected: boolean;
}) {
  const meta = NODE_META[kind];
  return (
    <foreignObject x={x} y={y} width={NODE_W} height={NODE_H}>
      <div
        className="flex h-full flex-col overflow-hidden rounded-[13px] bg-surface shadow-card"
        style={{ border: `1px solid ${meta.color}33`, opacity: connected ? 1 : 0.55 }}
      >
        <div style={{ height: 4, background: meta.color }} />
        <div className="flex flex-1 flex-col gap-2 px-3 pt-2.5 pb-3">
          <div className="flex items-center gap-1.5">
            <span
              className="grid h-[22px] w-[22px] shrink-0 place-items-center rounded-md"
              style={{ background: `${meta.color}1a` }}
            >
              <Icon name={meta.icon} size={14} color={meta.color} />
            </span>
            <span
              className="font-mono text-[11px] leading-tight font-bold tracking-wide uppercase"
              style={{ color: meta.color }}
            >
              {meta.type}
            </span>
          </div>
          <div className="line-clamp-3 text-[12.5px] leading-snug font-semibold break-keep text-ink">{label}</div>
          {sub && <div className="mt-auto font-mono text-[11px] text-ink-4">{sub}</div>}
        </div>
      </div>
    </foreignObject>
  );
}

function TerminalNode({ x, y, label }: { x: number; y: number; label: string }) {
  return (
    <foreignObject x={x} y={y} width={TERM_W} height={NODE_H}>
      <div
        className="flex h-full flex-col gap-2 rounded-[13px] px-3.5 py-3 text-white"
        style={{ background: "linear-gradient(160deg,#0f9d6b,#0c805a)", boxShadow: "0 8px 20px rgba(15,157,107,.28)" }}
      >
        <div className="flex items-center gap-1.5">
          <Icon name="flag" size={14} color="#fff" />
          <span className="font-mono text-[11px] font-bold tracking-wide uppercase">필요 고지 / 예외</span>
        </div>
        <div className="line-clamp-3 text-[12.5px] leading-snug font-bold break-keep">{label}</div>
        <div className="mt-auto text-[11px] opacity-85">고지 충족 시 위반 완화 가능</div>
      </div>
    </foreignObject>
  );
}

/** 노드 i의 오른쪽 가장자리 → 노드 i+1 왼쪽 가장자리 사이 베지어 화살표. */
function Edge({ x1, x2, yMid, dim }: { x1: number; x2: number; yMid: number; dim: boolean }) {
  const c = (x1 + x2) / 2;
  return (
    <g opacity={dim ? 0.4 : 1}>
      <path
        d={`M ${x1} ${yMid} C ${c} ${yMid}, ${c} ${yMid}, ${x2 - 8} ${yMid}`}
        fill="none"
        stroke="var(--line-2)"
        strokeWidth={2}
        strokeDasharray="2 3"
      />
      <path
        d={`M ${x2 - 12} ${yMid - 5} l 6 5 l -6 5`}
        fill="none"
        stroke="var(--brand)"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </g>
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

  const total = path.nodes.length + 1; // + terminal
  const widths = path.nodes.map(() => NODE_W).concat(TERM_W);
  const svgW = PAD_X * 2 + widths.reduce((sum, w) => sum + w, 0) + GAP * (total - 1);
  const svgH = PAD_Y * 2 + NODE_H;
  const yMid = PAD_Y + NODE_H / 2;
  const activeCard = anchorCards.find((card) => card.anchorId === activeId);
  const delegationGroups = delegationByPrinciple(result, activeId).filter((g) => g.steps.length > 0);

  // 각 노드의 x 시작 좌표.
  const xs: number[] = [];
  let cursor = PAD_X;
  for (let i = 0; i < total; i += 1) {
    xs.push(cursor);
    cursor += widths[i] + GAP;
  }

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

      {/* 우: 그래프 + 해설 */}
      <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
        <PaneHeader
          icon="graph"
          title="근거 경로 그래프"
          sub={`${activeCard?.code ?? ""} · ${path.riskLabel}`}
          right={
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-bold"
              style={{ color: TONE_COLOR[path.tone], background: TONE_BG[path.tone] }}
            >
              {TONE_WORD_SHORT[path.tone]}
            </span>
          }
        />
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {/* 가로 노드 체인 (SVG) */}
          <div className="overflow-x-auto pb-2">
            <svg width={svgW} height={svgH} style={{ display: "block" }}>
              {path.nodes.map((_, i) => {
                const x1 = xs[i] + widths[i];
                const x2 = xs[i + 1];
                return <Edge key={`e_${i}`} x1={x1} x2={x2} yMid={yMid} dim={!path.nodes[i + 1]?.connected && i + 1 < path.nodes.length} />;
              })}
              {path.nodes.map((node, i) => (
                <GraphNode
                  key={node.kind}
                  x={xs[i]}
                  y={PAD_Y}
                  kind={node.kind}
                  label={node.label}
                  sub={node.sub}
                  connected={node.connected}
                />
              ))}
              <TerminalNode x={xs[total - 1]} y={PAD_Y} label={path.disclosure} />
            </svg>
          </div>

          {/* 범례 */}
          <div className="mt-6 flex flex-wrap gap-x-3.5 gap-y-2 border-t border-line pt-4">
            {(Object.keys(NODE_META) as EvidenceNodeKind[]).map((kind) => (
              <div key={kind} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: NODE_META[kind].color }} />
                <span className="text-[11.5px] font-semibold text-ink-3">{NODE_META[kind].type}</span>
              </div>
            ))}
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "#0f9d6b" }} />
              <span className="text-[11.5px] font-semibold text-ink-3">필요 고지 / 예외</span>
            </div>
          </div>

          {/* 법령 위임 사슬 — 판매원칙별 위임 위계 전개 */}
          {delegationGroups.length > 0 && (
            <div className="mt-6">
              <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-ink-4 uppercase">
                법령 위임 사슬 <span className="font-normal normal-case text-ink-4">· 법률 → 시행령 → 감독규정 → 심의기준</span>
              </div>
              <div className="space-y-2.5">
                {delegationGroups.map((group) => (
                  <div key={group.principle} className="rounded-[12px] border border-line bg-surface-2 px-4.5 py-4">
                    <div className="mb-2">
                      <PrincipleTags principles={[group.principle]} />
                    </div>
                    <DelegationChain steps={group.steps} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 자연어 해설 */}
          <div className="mt-6">
            <div className="mb-2.5 text-[11px] font-bold tracking-wider text-ink-4 uppercase">경로 해설</div>
            <div className="rounded-[12px] border border-line bg-surface-2 px-4.5 py-4">
              <div className="mb-3.5 flex flex-wrap items-center gap-1.5">
                {path.nodes.map((node, i) => (
                  <span key={node.kind} className="flex items-center gap-1.5">
                    <span
                      className="rounded-[7px] px-2 py-0.5 text-[12px] font-semibold"
                      style={{ color: NODE_META[node.kind].color, background: `${NODE_META[node.kind].color}12` }}
                    >
                      {node.label.length > 18 ? `${node.label.slice(0, 18)}…` : node.label}
                    </span>
                    {i < path.nodes.length - 1 && <Icon name="arrowR" size={13} color="var(--ink-4)" />}
                  </span>
                ))}
              </div>
              <p className="m-0 text-[13.5px] leading-[1.75] text-ink-2">
                광고 표현 <b className="text-ink">“{path.quote}”</b> 은(는){" "}
                <b style={{ color: "#e0701a" }}>{path.riskLabel}</b> 위험으로 분류되어,{" "}
                {path.nodes[2]?.connected ? (
                  <>
                    <b style={{ color: "#c08a00" }}>{path.nodes[2].label}</b> 정책어를 통해{" "}
                  </>
                ) : null}
                {path.cuName ? (
                  <>
                    <b style={{ color: "#2f6df0" }}>{path.cuName}</b> 심의 기준에 연결되었습니다.{" "}
                  </>
                ) : (
                  <>관련 ComplianceUnit이 아직 연결되지 않아 검토가 필요합니다. </>
                )}
                {path.premise ? (
                  <>
                    해당 기준의 전제는 <b style={{ color: "#7c5cde" }}>“{path.premise}”</b> 이며,{" "}
                  </>
                ) : null}
                {path.articles.length > 0 ? (
                  <>
                    그 법적 근거는 <b style={{ color: "#0f9d6b" }}>{path.articles.join(", ")}</b> 입니다.
                  </>
                ) : (
                  <>법적 근거 조문은 추가 확인이 필요합니다.</>
                )}{" "}
                <span className="text-ink-4">— AI 권고이며 최종 판단은 심사자 검토를 따릅니다.</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
