"use client";

import { useCallback, useEffect, useState } from "react";
import { DetailPanel } from "@/components/DetailPanel";
import { HighlightedText } from "@/components/HighlightedText";
import { IssuePanel } from "@/components/IssuePanel";
import { ReviewForm } from "@/components/ReviewForm";
import { RiskStrip } from "@/components/RiskStrip";
import { AuditTab } from "@/components/tabs/AuditTab";
import { EvidencePathTab } from "@/components/tabs/EvidencePathTab";
import { OverallTab } from "@/components/tabs/OverallTab";
import { ProductFactsTab } from "@/components/tabs/ProductFactsTab";
import { SentenceMapTab } from "@/components/tabs/SentenceMapTab";
import { VerdictHeader } from "@/components/VerdictHeader";
import { useReview } from "@/hooks/useReview";
import { checkHealth } from "@/lib/api";
import type { ReviewOutput, ReviewRequest } from "@/lib/types";

const TABS = [
  { key: "overall", label: "전체 맥락", sub: "Overall" },
  { key: "sentences", label: "문장 지도", sub: "Sentence Map" },
  { key: "detail", label: "이슈 상세", sub: "Anchor Detail" },
  { key: "graph", label: "근거 경로", sub: "Evidence Path" },
  { key: "productFacts", label: "상품 사실", sub: "Product Facts" },
  { key: "audit", label: "감사 추적", sub: "Audit / Trace" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function Page() {
  const { state, runReview, selectAnchor, togglePrinciple, loadSample } = useReview();
  const [activeTab, setActiveTab] = useState<TabKey>("overall");
  const [backendUp, setBackendUp] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ping = async () => {
      const ok = await checkHealth();
      if (!cancelled) setBackendUp(ok);
    };
    ping();
    const timer = setInterval(ping, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const handleSubmit = useCallback(
    async (payload: ReviewRequest) => {
      setActiveTab("audit");
      const ok = await runReview(payload);
      if (ok) setActiveTab("overall");
    },
    [runReview],
  );

  const handleLoadSample = useCallback(async () => {
    const [{ default: sample }, { SAMPLE_REVIEW_TEXT }] = await Promise.all([
      import("@/fixtures/sample-review.json"),
      import("@/fixtures/sample-meta"),
    ]);
    loadSample(sample as unknown as ReviewOutput, SAMPLE_REVIEW_TEXT);
    setActiveTab("overall");
  }, [loadSample]);

  const copyRunId = async () => {
    if (state.result?.review_run_id) {
      await navigator.clipboard.writeText(state.result.review_run_id);
    }
  };

  /** 원문 하이라이트/칩 클릭 → anchor 선택 + 우측 상세 카드로 포커스 이동. */
  const selectFromText = useCallback(
    (anchorId: string) => {
      selectAnchor(anchorId);
      document.getElementById("issue-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    [selectAnchor],
  );

  return (
    <main className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-3.5 p-4 md:p-5">
      <header className="flex flex-wrap items-end justify-between gap-4 rounded-lg border border-line bg-panel p-5 shadow-panel">
        <div>
          <p className="text-xs font-extrabold tracking-widest text-accent uppercase">GraphCompliance CCG</p>
          <h1 className="mt-1 text-xl font-extrabold">금융광고 준법심사 콘솔</h1>
          <p className="mt-1 text-sm text-muted">
            광고 문안의 Claim, PolicyHypernym, CU 판단, 근거, 예외 검토를 한 화면에서 추적합니다.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs font-semibold text-muted">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              backendUp == null ? "bg-line-strong" : backendUp ? "bg-ok" : "bg-danger"
            }`}
          />
          {backendUp == null ? "백엔드 확인 중" : backendUp ? "Neo4j live · Graph-gated LLM" : "백엔드 연결 안 됨 (8770)"}
        </div>
      </header>

      <section className="rounded-lg border border-line bg-panel p-4 shadow-panel">
        <ReviewForm running={state.status === "running"} onSubmit={handleSubmit} onLoadSample={handleLoadSample} />
        {state.error && (
          <div className="mt-3 rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
            <strong>{state.error.code}</strong>: {state.error.message}
            {state.error.cause && <div className="mt-1 text-xs opacity-80">원인: {state.error.cause}</div>}
          </div>
        )}
      </section>

      <VerdictHeader status={state.status} result={state.result} reviewedText={state.reviewedText} events={state.events} />

      <RiskStrip result={state.result} selectedPrinciple={state.selectedPrinciple} onToggle={togglePrinciple} />

      <section className="grid gap-3.5 xl:grid-cols-[3fr_2fr]">
        <article className="rounded-lg border border-line bg-panel p-4 shadow-panel">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-base font-bold">광고 원문 하이라이트</h2>
            <span className="font-mono text-[11px] text-muted">{state.result?.review_run_id ?? ""}</span>
          </div>
          <HighlightedText
            result={state.result}
            reviewedText={state.reviewedText}
            selectedAnchorId={state.selectedAnchorId}
            selectedPrinciple={state.selectedPrinciple}
            onSelectAnchor={selectFromText}
          />
        </article>
        <aside id="issue-detail" className="rounded-lg border border-line bg-panel p-4 shadow-panel">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-base font-bold">이슈</h2>
            <button
              type="button"
              onClick={copyRunId}
              disabled={!state.result?.review_run_id}
              className="rounded-md border border-line px-2.5 py-1 text-xs font-semibold text-muted hover:border-accent hover:text-accent disabled:opacity-40"
            >
              Run ID 복사
            </button>
          </div>
          <div className="max-h-[42rem] overflow-y-auto pr-1">
            <IssuePanel result={state.result} selectedAnchorId={state.selectedAnchorId} onSelectAnchor={selectAnchor} />
          </div>
        </aside>
      </section>

      <section className="rounded-lg border border-line bg-panel shadow-panel">
        <div role="tablist" className="flex flex-wrap gap-1 border-b border-line px-3 pt-3">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              role="tab"
              aria-selected={activeTab === tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`rounded-t-md border-b-2 px-3.5 py-2 text-sm font-bold transition ${
                activeTab === tab.key
                  ? "border-accent text-accent"
                  : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              {tab.label} <span className="ml-1 text-[11px] font-semibold opacity-70">{tab.sub}</span>
            </button>
          ))}
        </div>
        <div className="p-4">
          {activeTab === "overall" && <OverallTab result={state.result} />}
          {activeTab === "sentences" && <SentenceMapTab result={state.result} onSelectAnchor={selectAnchor} />}
          {activeTab === "detail" && <DetailPanel result={state.result} selectedAnchorId={state.selectedAnchorId} />}
          {activeTab === "graph" && <EvidencePathTab result={state.result} selectedAnchorId={state.selectedAnchorId} />}
          {activeTab === "productFacts" && <ProductFactsTab result={state.result} />}
          {activeTab === "audit" && <AuditTab result={state.result} events={state.events} />}
        </div>
      </section>

      <footer className="pb-2 text-center text-[11px] text-muted">
        1차 준법심사 지원 도구입니다. 법률 자문이 아니며, 최종 판단은 준법감시 담당자의 검토를 따릅니다.
      </footer>
    </main>
  );
}
