"use client";

import { CopilotKit } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useState } from "react";
import { AdPane } from "@/components/console/AdPane";
import { ReviewCopilot } from "@/components/copilot/ReviewCopilot";
import { DetailPane } from "@/components/console/DetailPane";
import { ExceptionView } from "@/components/console/ExceptionView";
import { ExecSummary } from "@/components/console/ExecSummary";
import { GraphView } from "@/components/console/GraphView";
import { RiskList } from "@/components/console/RiskList";
import { PipelineProgress } from "@/components/PipelineProgress";
import { ReviewForm } from "@/components/ReviewForm";
import { ContextBar } from "@/components/shell/ContextBar";
import { Sidebar, type ViewKey } from "@/components/shell/Sidebar";
import { Toast } from "@/components/shell/Toast";
import { AuditTab } from "@/components/tabs/AuditTab";
import { DashboardTab } from "@/components/tabs/DashboardTab";
import { HomeTab } from "@/components/tabs/HomeTab";
import { OverallTab } from "@/components/tabs/OverallTab";
import { ProductFactsTab } from "@/components/tabs/ProductFactsTab";
import { SentenceMapTab } from "@/components/tabs/SentenceMapTab";
import { EmptyState, Expandable } from "@/components/ui";
import { useReview } from "@/hooks/useReview";
import { fetchRun } from "@/lib/api";
import { LocaleProvider, localeForResult, tr } from "@/lib/i18n";
import { CHANNELS, DECISIONS, WORKSPACE_ID, type DecisionKey } from "@/lib/labels";
import type { ReviewOutput, ReviewRequest, RunSummary } from "@/lib/types";

interface ReviewMeta {
  title: string;
  channelLabel: string;
}

/**
 * 저장된 ReviewOutput만으로 원문 텍스트를 재구성한다(원문을 별도 보관하지 않는 딥링크용).
 * sentence_units의 span 오프셋에 각 문장 텍스트를 배치해 하이라이트 좌표계를 보존한다.
 */
function reconstructReviewedText(output: ReviewOutput): string {
  const units = output.sentence_units ?? [];
  if (!units.length) return "";
  const maxEnd = units.reduce((max, u) => Math.max(max, u.span?.end ?? 0), 0);
  if (!maxEnd) return units.map((u) => u.span?.text ?? u.text ?? "").join(" ");
  const buf = new Array<string>(maxEnd).fill(" ");
  for (const unit of units) {
    const start = unit.span?.start ?? 0;
    const text = unit.span?.text ?? unit.text ?? "";
    for (let i = 0; i < text.length && start + i < maxEnd; i += 1) buf[start + i] = text[i];
  }
  return buf.join("");
}

export default function Page() {
  const { state, runReview, selectAnchor, loadSample } = useReview();
  const [view, setView] = useState<ViewKey>("home");
  const [meta, setMeta] = useState<ReviewMeta>({ title: "", channelLabel: "" });
  const [resolved, setResolved] = useState<Set<string>>(new Set());
  // 사전심사 체크리스트의 '심사자 확인함' — '수정안 적용(resolved)'과 의미가 다르므로 분리.
  const [acknowledged, setAcknowledged] = useState<Set<string>>(new Set());
  const [decision, setDecision] = useState<DecisionKey | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [draftPreset, setDraftPreset] = useState<Partial<ReviewRequest> | null>(null);
  // 발표용 화면 포커스 — 심사 콘솔에서 한 페인만 전폭으로 확대(정보량 조절).
  const [consoleFocus, setConsoleFocus] = useState<"all" | "ad" | "risk" | "detail">("all");

  // 발표 단축키: 1(원문) 2(위험 카드) 3(판정 상세) 0·ESC(전체). 입력 중에는 무시.
  useEffect(() => {
    if (view !== "review") return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (event.key === "1") setConsoleFocus("ad");
      else if (event.key === "2") setConsoleFocus("risk");
      else if (event.key === "3") setConsoleFocus("detail");
      else if (event.key === "0" || event.key === "Escape") setConsoleFocus("all");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view]);

  const handleSubmit = useCallback(
    async (payload: ReviewRequest, options?: { stayOnNew?: boolean }): Promise<boolean> => {
      setMeta({
        title: payload.title,
        channelLabel: CHANNELS.find((item) => item.value === payload.channel)?.label ?? payload.channel,
      });
      setResolved(new Set());
      setAcknowledged(new Set());
      setDecision(null);
      const ok = await runReview(payload);
      if (ok && !options?.stayOnNew) setView("review");
      return ok;
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
    setAcknowledged(new Set());
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
    setAcknowledged(new Set());
    setDecision(null);
    setView("product");
  }, [loadSample]);

  /** 운영 대시보드에서 과거 실행을 열어 시점 데이터를 콘솔에서 디버깅. */
  const handleOpenRun = useCallback(
    async (run: RunSummary) => {
      const output = await fetchRun(run.id);
      loadSample(output, run.content_text);
      setMeta({
        title: run.title,
        channelLabel: CHANNELS.find((item) => item.value === run.channel)?.label ?? run.channel,
      });
      setResolved(new Set());
      setAcknowledged(new Set());
      setDecision(null);
      setView("review");
    },
    [loadSample],
  );

  /** 평가 로그(run_id만 아는 상태)에서 저장된 실행을 콘솔 상세로 딥링크. */
  const handleOpenRunId = useCallback(
    async (runId: string) => {
      const output = await fetchRun(runId);
      loadSample(output, reconstructReviewedText(output));
      setMeta({
        title: output.ad_image?.extracted_title || output.context_frame?.summary || "평가 실행 상세",
        channelLabel: "",
      });
      setResolved(new Set());
      setAcknowledged(new Set());
      setDecision(null);
      setView("review");
    },
    [loadSample],
  );

  const handleUsePreset = useCallback((preset: Partial<ReviewRequest>) => {
    setDraftPreset({
      dataset_item_id: `preset_${Date.now()}`,
      workspace_id: WORKSPACE_ID,
      ...preset,
    });
    setView("new");
  }, []);

  const handleEditRun = useCallback((run: RunSummary) => {
    setDraftPreset({
      dataset_item_id: `rerun_${run.id}_${Date.now()}`,
      title: run.title,
      content_text: run.content_text,
      channel: run.channel,
      product_group: run.product_group,
      selected_product_name: run.selected_product_name,
      source_type: run.source_type,
      workspace_id: run.workspace_id || WORKSPACE_ID,
      llm_model: run.model,
      actor: run.actor,
    });
    setToast("이전 실행 조건을 새 심사에 불러왔습니다.");
    setView("new");
  }, []);

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

  // 사전심사 체크리스트: 항목을 '심사자 확인함'으로 표시(통과를 단정하지 않음).
  const handleToggleAck = useCallback((id: string) => {
    setAcknowledged((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
        setToast("심사자 확인으로 표시했습니다");
      }
      return next;
    });
  }, []);

  const handleDecide = useCallback((key: DecisionKey | null) => {
    setDecision(key);
    if (key) setToast(`심사자 결정: ${DECISIONS[key].label} 처리되었습니다`);
  }, []);

  const result = state.result;
  // UI 로케일 — KH(비-KR) 심사 결과가 열려 있으면 콘솔 전체가 영어로 표시된다.
  const locale = localeForResult(result);

  return (
    <CopilotKit runtimeUrl="/api/copilotkit" useSingleEndpoint={false}>
    <LocaleProvider locale={locale}>
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
          {view === "home" && (
            <HomeTab
              status={state.status}
              result={result}
              events={state.events}
              onNewReview={() => setView("new")}
              onDashboard={() => setView("dashboard")}
              onOpenRun={handleOpenRun}
              onEditRun={handleEditRun}
              onUsePreset={handleUsePreset}
            />
          )}

          {view === "new" && (
            <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
              <div className="flex min-w-0 flex-col gap-4">
                <div>
                  <h2 className="flex items-center gap-2 text-[20px] font-extrabold tracking-tight text-ink">
                    새 심사
                    <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[12px] font-bold text-brand-2">
                      AI 사전심의
                    </span>
                  </h2>
                  <p className="mt-1 text-[13px] leading-relaxed text-ink-3">
                    금융광고 문안을 법령·심의기준·상품설명서 사실과 대조하고, 규칙 기반 판정과 LLM 해석을 결합해
                    설명가능한 사전 검토를 지원합니다.
                  </p>
                </div>
                <section className="rounded-[14px] border border-line bg-surface p-5 shadow-card">
                  <ReviewForm
                    key={draftPreset?.dataset_item_id ?? "new-review-form"}
                    running={state.status === "running"}
                    onSubmit={handleSubmit}
                    draftPreset={draftPreset}
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
                {/* 약간의 친절한 설명 — 분석 흐름 + 보조 도구 안내 */}
                <div className="rounded-[12px] border border-line bg-surface-2 px-4 py-3 text-[12px] leading-relaxed text-ink-3">
                  접수하면 <b className="font-semibold text-ink-2">문안 구조 분석 → 표현 추출 → 심의기준 매칭 → 판정 → 예외·완화 검토 → 수정안 생성</b>{" "}
                  순으로 분석합니다. AI 사전심의 결과는 보조 자료이며 최종 심의 책임은 심사자에게 있고, 모든 판정은 근거 조항 원문까지 추적할 수 있습니다.
                </div>
              </div>

              <aside className="xl:sticky xl:top-4 xl:self-start">
                <section className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-extrabold text-ink">실시간 진행</h3>
                      <p className="mt-0.5 text-[11px] text-ink-4">심사 중에도 현재 단계를 계속 확인합니다.</p>
                    </div>
                    <span
                      className={`rounded-full px-2 py-1 text-[11px] font-bold ${
                        state.status === "running"
                          ? "bg-review/15 text-review"
                          : result
                            ? "bg-pass/15 text-pass"
                            : "bg-surface-2 text-ink-4"
                      }`}
                    >
                      {state.status === "running" ? "실행 중" : result ? "완료" : "대기"}
                    </span>
                  </div>
                  {state.events.length > 0 ? (
                    <>
                      <PipelineProgress events={state.events} />
                      <div className="max-h-[calc(100vh-280px)] overflow-y-auto pr-1">
                        <AuditTab result={null} events={state.events} />
                      </div>
                    </>
                  ) : (
                    <div className="rounded-[10px] border border-dashed border-line bg-surface-2 px-3 py-4 text-[12px] leading-relaxed text-ink-3">
                      아직 실행된 단계가 없습니다. <b className="font-semibold text-ink-2">심의 분석 시작</b> 또는
                      <b className="font-semibold text-ink-2"> 대기열 실행</b>을 누르면 이곳에 단계별 진행이 표시됩니다.
                    </div>
                  )}
                </section>
              </aside>
            </div>
          )}

          {view === "review" &&
            (result ? (
              <div className="flex h-full min-h-0 flex-col gap-3.5">
                <ExecSummary result={result} resolved={resolved} />
                {/* 발표용 화면 포커스 — 한 페인만 전폭으로. 단축키 1·2·3, ESC 복귀 */}
                <div className="flex items-center justify-end gap-1 text-[11.5px]">
                  <span className="mr-1 font-bold text-ink-4">{tr(locale, "화면", "View")}</span>
                  {(
                    [
                      { key: "all", label: tr(locale, "전체", "All") },
                      { key: "ad", label: tr(locale, "원문 ¹", "Original ¹") },
                      { key: "risk", label: tr(locale, "위험 카드 ²", "Risk cards ²") },
                      { key: "detail", label: tr(locale, "판정 상세 ³", "Details ³") },
                    ] as const
                  ).map((option) => (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => setConsoleFocus(option.key)}
                      className={`rounded-md px-2.5 py-1 font-bold transition ${
                        consoleFocus === option.key
                          ? "bg-ink text-white"
                          : "border border-line bg-surface text-ink-3 hover:border-brand hover:text-brand"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <div
                  className="grid min-h-0 flex-1 overflow-hidden rounded-[14px] border border-line bg-surface shadow-panel"
                  style={{
                    gridTemplateColumns:
                      consoleFocus === "all"
                        ? "minmax(300px,1.12fr) minmax(244px,.8fr) minmax(310px,1.1fr)"
                        : "minmax(0,1fr)",
                    // 암시적 행이 auto로 내용만큼 늘어나면 페인 내부 스크롤이 죽는다 —
                    // 행 트랙을 컨테이너 높이에 고정해 각 페인이 독립 스크롤되게 한다.
                    gridTemplateRows: "minmax(0, 1fr)",
                    // 발표 포커스: 페인 하나만 남으면 실제 글자도 커져야 한다.
                    ...(consoleFocus !== "all" ? { zoom: 1.2 } : {}),
                  }}
                >
                  {(consoleFocus === "all" || consoleFocus === "ad") && (
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
                  )}
                  {(consoleFocus === "all" || consoleFocus === "risk") && (
                    <RiskList
                      result={result}
                      selectedAnchorId={state.selectedAnchorId}
                      resolved={resolved}
                      onSelectAnchor={selectAnchor}
                    />
                  )}
                  {(consoleFocus === "all" || consoleFocus === "detail") && (
                    <DetailPane
                      result={result}
                      selectedAnchorId={state.selectedAnchorId}
                      resolved={resolved}
                      onToggleResolve={handleToggleResolve}
                      onGotoGraph={() => setView("graph")}
                    />
                  )}
                </div>
              </div>
            ) : (
              <EmptyState>{tr(locale, "아직 심사 결과가 없습니다. 새 심사에서 문안을 접수하세요.", "No review results yet. Submit ad copy from New Review.")}</EmptyState>
            ))}

          {view === "graph" && (
            <div className="h-full">
              <GraphView result={result} selectedAnchorId={state.selectedAnchorId} onSelectAnchor={selectAnchor} />
            </div>
          )}

          {view === "exception" && (
            <div className="h-full">
              <ExceptionView result={result} acknowledged={acknowledged} onToggleAck={handleToggleAck} />
            </div>
          )}

          {view === "product" && (
            <div className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
              <ProductFactsTab result={result} />
            </div>
          )}

          {view === "dashboard" && (
            <div className="flex flex-col gap-4">
              <div className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
                <DashboardTab onOpenRun={handleOpenRun} onEditRun={handleEditRun} onOpenRunId={handleOpenRunId} />
              </div>
              {/* 감사 로그(별도 탭 폐지) — 현재 로드된 실행의 단계 추적과 컨텍스트 raw를
                  운영/디버깅 화면 안에서 펼쳐 본다. */}
              {result && (
                <div className="rounded-[14px] border border-line bg-surface p-4 shadow-card">
                  <Expandable
                    header={<span className="text-[13px] font-bold text-ink-2">현재 실행 기술 추적 · 감사 로그</span>}
                  >
                    <div className="flex flex-col gap-4 p-4">
                      <AuditTab result={result} events={state.events} />
                      <Expandable
                        header={<span className="text-[12.5px] font-bold text-ink-3">컨텍스트 raw (ContextFrame/Influence/문장/관계)</span>}
                      >
                        <div className="flex flex-col gap-4 p-4">
                          <OverallTab result={result} />
                          <SentenceMapTab
                            result={result}
                            onSelectAnchor={(anchorId) => {
                              selectAnchor(anchorId);
                              setView("review");
                            }}
                          />
                        </div>
                      </Expandable>
                    </div>
                  </Expandable>
                </div>
              )}
            </div>
          )}
        </div>
      </main>
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
      {/* 심사 코파일럿 — 결과가 로드된 뒤에만 (컨텍스트 없는 자유 법률 상담 방지) */}
      {result && (
        <ReviewCopilot result={result} resolved={resolved} title={meta.title} reviewedText={state.reviewedText} />
      )}
    </div>
    </LocaleProvider>
    </CopilotKit>
  );
}
