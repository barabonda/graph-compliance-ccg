"use client";

import type { OverallGraphNode, OverallImpressionGraphModel, OverallNodeKind } from "@/lib/selectors";
import { tr, useLocale, type Locale } from "@/lib/i18n";

// 노드 종류별 의미 색. 향후 prominence(위계)·fact(사실) 노드까지 5종 확장 대비.
const KIND_STYLE: Record<OverallNodeKind, { color: string; bg: string }> = {
  benefit: { color: "var(--reject)", bg: "var(--reject-bg)" },
  mitigate: { color: "var(--revise)", bg: "var(--revise-bg)" },
  reinforce: { color: "var(--pass)", bg: "var(--pass-bg)" },
  prominence: { color: "var(--revise)", bg: "var(--revise-bg)" },
  fact: { color: "var(--reject)", bg: "var(--reject-bg)" },
};

// KH 표시용 — selectors 가 생성하는 노드 제목/엣지 라벨/등급의 EN 표기(데이터 불변, 화면 전용).
const GRAPH_TERM_EN: [string, string][] = [
  ["혜택 주장", "Benefit claim"],
  ["조건 고지", "Condition disclosure"],
  ["위험 고지", "Risk disclosure"],
  ["보호 고지", "Protection disclosure"],
  ["위험 완화", "risk mitigation"],
  ["인상 강화", "impression reinforcement"],
  ["낮음", "Low"],
  ["중간", "Medium"],
  ["높음", "High"],
];

function graphTermDisplay(locale: Locale, text: string): string {
  if (locale !== "en") return text;
  let out = String(text ?? "");
  for (const [ko, en] of GRAPH_TERM_EN) out = out.replaceAll(ko, en);
  return out;
}

function NodeCard({ node }: { node: OverallGraphNode }) {
  const locale = useLocale();
  const style = KIND_STYLE[node.kind];
  return (
    <div className="rounded-[10px] border px-3 py-2" style={{ background: style.bg, borderColor: style.color }}>
      <div className="text-[11px] font-bold" style={{ color: style.color }}>
        {graphTermDisplay(locale, node.title)}
      </div>
      <div className="mt-0.5 text-[12.5px] leading-snug break-keep text-ink">{node.text}</div>
    </div>
  );
}

function Connector({ label, color }: { label: string; color: string }) {
  const locale = useLocale();
  return (
    <div className="flex items-center gap-1.5 pl-3 text-[11px] text-ink-4">
      <span aria-hidden>↓</span>
      <span className="font-semibold" style={{ color }}>
        {graphTermDisplay(locale, label)}
      </span>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

/**
 * 전체 인상 종합 그래프 (세로 흐름). 혜택 주장(빨강)이 중심이고, 그것을
 * 완화(노랑)·강화(초록)하는 문장들이 직선 화살표로 연결된다. 맨 아래 종합 결론.
 */
export function OverallImpressionGraph({ graph }: { graph: OverallImpressionGraphModel }) {
  const locale = useLocale();
  if (!graph.benefit && !graph.edges.length) {
    return (
      <p className="text-[12px] text-ink-4">
        {tr(
          locale,
          "전체 인상 근거 그래프를 구성할 문장 관계가 없습니다.",
          "No sentence relations available to build the overall-impression evidence graph.",
        )}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      {graph.benefit && <NodeCard node={graph.benefit} />}
      {graph.edges.map((edge, index) => (
        <div key={index} className="flex flex-col gap-1">
          <Connector label={edge.label} color={KIND_STYLE[edge.node.kind].color} />
          <NodeCard node={edge.node} />
        </div>
      ))}
      {graph.conclusion && (
        <>
          <div className="pl-3 text-[11px] text-ink-4" aria-hidden>
            ↓
          </div>
          <div
            className="rounded-[10px] border-[1.5px] px-3 py-2.5"
            style={{ borderColor: "var(--revise)", background: "var(--revise-bg)" }}
          >
            <div className="text-[11px] font-bold text-revise">
              {tr(
                locale,
                `전체 인상 종합 · 오인 위험 ${graph.conclusion.grade}`,
                `Overall impression · Misleading risk ${graphTermDisplay(locale, graph.conclusion.grade)}`,
              )}
            </div>
            {graph.conclusion.text && (
              <div className="mt-1 text-[12.5px] leading-relaxed break-keep text-ink-2">{graph.conclusion.text}</div>
            )}
          </div>
        </>
      )}
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-4">
        <LegendDot color="var(--reject)" label={tr(locale, "혜택(위험)", "Benefit (risk)")} />
        <LegendDot color="var(--revise)" label={tr(locale, "완화", "Mitigation")} />
        <LegendDot color="var(--pass)" label={tr(locale, "강화", "Reinforcement")} />
      </div>
    </div>
  );
}
