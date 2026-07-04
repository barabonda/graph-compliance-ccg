"use client";

import type { ReviewOutput } from "@/lib/types";
import { tr, useLocale } from "@/lib/i18n";
import { buildIssueCards, disclosureIsSatisfied } from "@/lib/selectors";
import { Icon } from "../Icon";

export type ViewKey = "home" | "new" | "review" | "graph" | "exception" | "product" | "audit" | "dashboard";

const NAV: { key: ViewKey; label: string; labelEn: string; sub: string; subEn: string; icon: string }[] = [
  { key: "home", label: "홈", labelEn: "Home", sub: "상태 · 최근 심사", subEn: "Status · recent reviews", icon: "dashboard" },
  { key: "new", label: "새 심사", labelEn: "New review", sub: "문안 접수 · 실행", subEn: "Submit copy · run", icon: "plus" },
  // 수정안은 심사 콘솔의 '수정안' diff 모드로 통합 (별도 탭 폐지)
  { key: "review", label: "심사 콘솔", labelEn: "Review console", sub: "원문 · 위험 · 수정안", subEn: "Original · risks · revisions", icon: "review" },
  { key: "graph", label: "근거 경로", labelEn: "Evidence path", sub: "설명 그래프", subEn: "Explanation graph", icon: "graph" },
  { key: "exception", label: "사전심사 체크리스트", labelEn: "Pre-review checklist", sub: "충족·확인 필요 점검", subEn: "Satisfied · needs confirmation", icon: "shield" },
  { key: "product", label: "상품 사실", labelEn: "Product facts", sub: "문서 대조", subEn: "Document comparison", icon: "layers" },
  { key: "dashboard", label: "운영 대시보드", labelEn: "Operations dashboard", sub: "실행 기록 · 감사 추적", subEn: "Run history · audit trail", icon: "dashboard" },
];

interface Props {
  view: ViewKey;
  setView: (view: ViewKey) => void;
  result: ReviewOutput | null;
  resolvedCount: number;
}

export function Sidebar({ view, setView, result, resolvedCount }: Props) {
  const locale = useLocale();
  const cards = result ? buildIssueCards(result, locale).filter((card) => card.kind !== "trackB") : [];
  const openCount = Math.max(0, cards.length - resolvedCount);
  const checks = result?.product_fact_context?.disclosure_checks ?? [];
  const met = checks.filter(disclosureIsSatisfied).length;

  return (
    <aside className="flex w-[228px] shrink-0 flex-col border-r border-line bg-surface px-3.5 py-4">
      <button
        type="button"
        onClick={() => setView("home")}
        className="flex items-center gap-2.5 rounded-[12px] px-2 pb-4 text-left hover:bg-surface-2"
      >
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
          <div className="text-sm font-extrabold tracking-tight">JB Compliance</div>
          <div className="font-mono text-[11px] text-ink-4">JunBub · CONTENT SAFEGUARD</div>
        </div>
      </button>

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
                className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${
                  active ? "bg-brand" : "bg-surface-3"
                }`}
              >
                <Icon name={item.icon} size={18} color={active ? "#fff" : "var(--ink-3)"} />
              </span>
              <span className="min-w-0">
                <span className={`block text-[13px] font-bold ${active ? "text-brand-2" : "text-ink"}`}>{tr(locale, item.label, item.labelEn)}</span>
                <span className="block text-[11px] text-ink-4">{tr(locale, item.sub, item.subEn)}</span>
              </span>
            </button>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-2.5">
        <div className="rounded-[11px] border border-line bg-surface-2 px-3 py-3">
          <div className="text-[11px] font-bold tracking-wider text-ink-4 uppercase">{tr(locale, "현재 ReviewRun", "Current ReviewRun")}</div>
          <div className="mt-1.5 truncate font-mono text-[11px] font-bold text-ink-2">
            {result?.review_run_id ?? "—"}
          </div>
          <div className="mt-2.5 flex gap-2">
            <div className="flex-1">
              <div className="text-[11px] text-ink-4">{tr(locale, "미해소 이슈", "Open issues")}</div>
              <div className={`text-[15px] font-extrabold ${openCount ? "text-reject" : "text-pass"}`}>
                {openCount}
                <span className="text-[11px] font-semibold text-ink-4">/{cards.length}</span>
              </div>
            </div>
            <div className="flex-1">
              <div className="text-[11px] text-ink-4">{tr(locale, "필수 고지", "Required disclosures")}</div>
              <div className={`text-[15px] font-extrabold ${checks.length && met < checks.length ? "text-reject" : "text-pass"}`}>
                {met}
                <span className="text-[11px] font-semibold text-ink-4">/{checks.length}</span>
              </div>
            </div>
          </div>
        </div>
        <p className="px-1 text-[11px] leading-relaxed text-ink-4">
          {tr(
            locale,
            "AI 사전심의는 보조 자료이며 최종 심의 책임은 심사자에게 있습니다.",
            "AI pre-review is a supporting aid; the final review decision rests with the reviewer.",
          )}
        </p>
      </div>
    </aside>
  );
}
