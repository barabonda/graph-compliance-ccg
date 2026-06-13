"use client";

import { useCallback, useState } from "react";
import { AdPane } from "@/components/console/AdPane";
import { DetailPane } from "@/components/console/DetailPane";
import { ExceptionView } from "@/components/console/ExceptionView";
import { ExecSummary } from "@/components/console/ExecSummary";
import { GraphView } from "@/components/console/GraphView";
import { RiskList } from "@/components/console/RiskList";
import { ReviewForm } from "@/components/ReviewForm";
import { ContextBar } from "@/components/shell/ContextBar";
import { Sidebar, type ViewKey } from "@/components/shell/Sidebar";
import { Toast } from "@/components/shell/Toast";
import { AuditTab } from "@/components/tabs/AuditTab";
import { OverallTab } from "@/components/tabs/OverallTab";
import { ProductFactsTab } from "@/components/tabs/ProductFactsTab";
import { SentenceMapTab } from "@/components/tabs/SentenceMapTab";
import { EmptyState } from "@/components/ui";
import { useReview } from "@/hooks/useReview";
import { CHANNELS, DECISIONS, type DecisionKey } from "@/lib/labels";
import type { ReviewOutput, ReviewRequest } from "@/lib/types";

interface ReviewMeta {
  title: string;
  channelLabel: string;
}

export default function Page() {
  const { state, runReview, selectAnchor, loadSample } = useReview();
  const [view, setView] = useState<ViewKey>("new");
  const [meta, setMeta] = useState<ReviewMeta>({ title: "", channelLabel: "" });
  const [resolved, setResolved] = useState<Set<string>>(new Set());
  const [decision, setDecision] = useState<DecisionKey | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const handleSubmit = useCallback(
    async (payload: ReviewRequest) => {
      setMeta({
        title: payload.title,
        channelLabel: CHANNELS.find((item) => item.value === payload.channel)?.label ?? payload.channel,
      });
      setResolved(new Set());
      setDecision(null);
      const ok = await runReview(payload);
      if (ok) setView("review");
    },
    [runReview],
  );

  const handleLoadSample = useCallback(async () => {
    const [{ default: sample }, { SAMPLE_REVIEW_TEXT }] = await Promise.all([
      import("@/fixtures/sample-review.json"),
      import("@/fixtures/sample-meta"),
    ]);
    loadSample(sample as unknown as ReviewOutput, SAMPLE_REVIEW_TEXT);
    setMeta({ title: "JB 특판예금 출시 안내", channelLabel: "은행 이벤트 페이지" });
    setResolved(new Set());
    setDecision(null);
    setView("review");
  }, [loadSample]);

  /** 상품문서 대조가 채워진 샘플 — 상품 사실 화면 데모용. */
  const handleLoadProductSample = useCallback(async () => {
    const { default: sample } = await import("@/fixtures/sample-productfacts.json");
    const text =
      "JB시니어우대예금 특판 안내. 최고 연 5.0% 금리를 확정 제공하며 안정적으로 목돈을 관리할 수 있습니다. 기본금리와 우대금리는 가입기간, 우대조건 충족 여부에 따라 달라질 수 있습니다. 이 예금은 예금자보호법에 따라 원금과 이자를 합하여 1인당 최고 1억원까지 보호됩니다.";
    loadSample(sample as unknown as ReviewOutput, text);
    setMeta({ title: "JB시니어우대예금 특판 안내", channelLabel: "웹페이지" });
    setResolved(new Set());
    setDecision(null);
    setView("product");
  }, [loadSample]);

  const handleToggleResolve = useCallback((id: string) => {
    setResolved((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        setToast("수정안을 적용했습니다 · 이슈 해소");
      }
      return next;
    });
  }, []);

  const handleDecide = useCallback((key: DecisionKey | null) => {
    setDecision(key);
    if (key) setToast(`심사자 결정: ${DECISIONS[key].label} 처리되었습니다`);
  }, []);

  const result = state.result;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar view={view} setView={setView} result={result} resolvedCount={resolved.size} />
      <main className="flex min-w-0 flex-1 flex-col">
        <ContextBar
          status={state.status}
          result={result}
          reviewTitle={meta.title}
          events={state.events}
          decision={decision}
          onDecide={handleDecide}
        />
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {view === "new" && (
            <div className="mx-auto flex max-w-4xl flex-col gap-4">
              <section className="rounded-[14px] border border-line bg-surface p-5 shadow-card">
                <h2 className="mb-1 text-base font-extrabold">새 심사</h2>
                <p className="mb-4 text-xs text-ink-3">
                  광고 문안을 접수하면 정책 그래프 대조 → 표현 심사 → 전체 인상 → 상품 사실 대조 순으로 분석합니다.
                </p>
                <ReviewForm
                  running={state.status === "running"}
                  onSubmit={handleSubmit}
                  onLoadSample={handleLoadSample}
                  onLoadProductSample={handleLoadProductSample}
                />
                {state.error && (
                  <div className="mt-3 rounded-md border border-reject/40 bg-reject/5 px-3 py-2 text-sm text-reject">
                    <strong>{state.error.code}</strong>: {state.error.message}
                    {state.error.cause && <div className="mt-1 text-xs opacity-80">원인: {state.error.cause}</div>}
                  </div>
                )}
              </section>
              {(state.status === "running" || (state.events.length > 0 && !result)) && (
                <section className="rounded-[14px] border border-line bg-surface p-5 shadow-card">
                  <h3 className="mb-3 text-sm font-bold">분석 파이프라인</h3>
                  <AuditTab result={null} events={state.events} />
                </section>
              )}
            </div>
          )}

          {view === "review" &&
            (result ? (
              <div className="flex h-full min-h-0 flex-col gap-3.5">
                <ExecSummary result={result} resolved={resolved} />
                <div
                  className="grid min-h-0 flex-1 overflow-hidden rounded-[14px] border border-line bg-surface shadow-panel"
                  style={{
                    gridTemplateColumns: "minmax(300px,1.12fr) minmax(244px,.8fr) minmax(310px,1.1fr)",
                    // 암시적 행이 auto로 내용만큼 늘어나면 페인 내부 스크롤이 죽는다 —
                    // 행 트랙을 컨테이너 높이에 고정해 각 페인이 독립 스크롤되게 한다.
                    gridTemplateRows: "minmax(0, 1fr)",
                  }}
                >
                  <AdPane
                    result={result}
                    reviewedText={state.reviewedText}
                    reviewTitle={meta.title}
                    channelLabel={meta.channelLabel}
                    selectedAnchorId={state.selectedAnchorId}
                    resolved={resolved}
                    onSelectAnchor={selectAnchor}
                    onToggleResolve={handleToggleResolve}
                  />
                  <RiskList
                    result={result}
                    selectedAnchorId={state.selectedAnchorId}
                    resolved={resolved}
                    onSelectAnchor={selectAnchor}
                  />
                  <DetailPane
                    result={result}
                    selectedAnchorId={state.selectedAnchorId}
                    resolved={resolved}
                    onToggleResolve={handleToggleResolve}
                    onGotoGraph={() => setView("graph")}
                  />
                </div>
              </div>
            ) : (
              <EmptyState>아직 심사 결과가 없습니다. 새 심사에서 문안을 접수하세요.</EmptyState>
            ))}

          {view === "graph" && (
            <div className="h-full">
              <GraphView result={result} selectedAnchorId={state.selectedAnchorId} onSelectAnchor={selectAnchor} />
            </div>
          )}

          {view === "exception" && (
            <div className="h-full">
              <ExceptionView result={result} resolved={resolved} />
            </div>
          )}

          {view === "product" && (
            <div className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
              <ProductFactsTab result={result} />
            </div>
          )}

          {view === "context" && (
            <div className="flex flex-col gap-4">
              <div className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
                <OverallTab result={result} />
              </div>
              <div className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
                <SentenceMapTab
                  result={result}
                  onSelectAnchor={(anchorId) => {
                    selectAnchor(anchorId);
                    setView("review");
                  }}
                />
              </div>
            </div>
          )}

          {view === "audit" && (
            <div className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
              <AuditTab result={result} events={state.events} />
            </div>
          )}
        </div>
      </main>
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
    </div>
  );
}
