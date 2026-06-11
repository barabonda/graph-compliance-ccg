"use client";

import type { ReviewOutput } from "@/lib/types";
import { buildIssueCards } from "@/lib/selectors";

export type ViewKey = "new" | "review" | "graph" | "product" | "context" | "audit";

const NAV: { key: ViewKey; label: string; sub: string; icon: string }[] = [
  { key: "new", label: "새 심사", sub: "문안 접수 · 실행", icon: "✚" },
  { key: "review", label: "심사 콘솔", sub: "광고 원문 · 위험", icon: "☰" },
  { key: "graph", label: "근거 경로", sub: "설명 그래프", icon: "⤳" },
  { key: "product", label: "상품 사실", sub: "문서 대조", icon: "▤" },
  { key: "context", label: "컨텍스트", sub: "전체 인상 · 문장", icon: "◫" },
  { key: "audit", label: "감사 로그", sub: "추적 · 단계", icon: "≣" },
];

interface Props {
  view: ViewKey;
  setView: (view: ViewKey) => void;
  result: ReviewOutput | null;
  resolvedCount: number;
}

export function Sidebar({ view, setView, result, resolvedCount }: Props) {
  const cards = result ? buildIssueCards(result).filter((card) => card.kind !== "trackB") : [];
  const openCount = Math.max(0, cards.length - resolvedCount);
  const checks = result?.product_fact_context?.disclosure_checks ?? [];
  const met = checks.filter((check) => check.present).length;

  return (
    <aside className="flex w-[228px] shrink-0 flex-col border-r border-line bg-surface px-3.5 py-4">
      <div className="flex items-center gap-2.5 px-2 pb-4">
        <div
          className="grid h-9 w-9 shrink-0 place-items-center rounded-[10px] text-white shadow-[0_4px_12px_rgba(47,109,240,.3)]"
          style={{ background: "linear-gradient(140deg,#2f6df0,#1d3a6e)" }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3 5 6v5c0 4.2 2.8 7.6 7 9 4.2-1.4 7-4.8 7-9V6l-7-3Z" />
            <path d="m9 12 2 2 4-4" />
          </svg>
        </div>
        <div className="min-w-0">
          <div className="text-sm font-extrabold tracking-tight">GraphCompliance</div>
          <div className="font-mono text-[10px] text-ink-4">광고 심의 콘솔 · CCG</div>
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV.map((item) => {
          const active = view === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => setView(item.key)}
              className={`relative flex w-full items-center gap-2.5 rounded-[10px] px-3 py-2.5 text-left transition ${
                active ? "bg-brand-tint" : "hover:bg-surface-2"
              }`}
            >
              {active && <span className="absolute top-2 bottom-2 -left-2.5 w-[3px] rounded-full bg-brand" />}
              <span
                className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg text-[15px] ${
                  active ? "bg-brand text-white" : "bg-surface-3 text-ink-3"
                }`}
              >
                {item.icon}
              </span>
              <span className="min-w-0">
                <span className={`block text-[13px] font-bold ${active ? "text-brand-2" : "text-ink"}`}>{item.label}</span>
                <span className="block text-[10.5px] text-ink-4">{item.sub}</span>
              </span>
            </button>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-2.5">
        <div className="rounded-[11px] border border-line bg-surface-2 px-3 py-3">
          <div className="text-[10.5px] font-bold tracking-wider text-ink-4 uppercase">현재 ReviewRun</div>
          <div className="mt-1.5 truncate font-mono text-[11px] font-bold text-ink-2">
            {result?.review_run_id ?? "—"}
          </div>
          <div className="mt-2.5 flex gap-2">
            <div className="flex-1">
              <div className="text-[10.5px] text-ink-4">미해소 이슈</div>
              <div className={`text-[15px] font-extrabold ${openCount ? "text-reject" : "text-pass"}`}>
                {openCount}
                <span className="text-[11px] font-semibold text-ink-4">/{cards.length}</span>
              </div>
            </div>
            <div className="flex-1">
              <div className="text-[10.5px] text-ink-4">필수 고지</div>
              <div className={`text-[15px] font-extrabold ${checks.length && met < checks.length ? "text-reject" : "text-pass"}`}>
                {met}
                <span className="text-[11px] font-semibold text-ink-4">/{checks.length}</span>
              </div>
            </div>
          </div>
        </div>
        <p className="px-1 text-[10px] leading-relaxed text-ink-4">
          AI 사전심의는 보조 자료이며 최종 심의 책임은 심사자에게 있습니다.
        </p>
      </div>
    </aside>
  );
}
