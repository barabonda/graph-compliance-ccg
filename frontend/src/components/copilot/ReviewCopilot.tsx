"use client";

import "@copilotkit/react-core/v2/styles.css";
import { CopilotSidebar, useAgentContext, useRenderTool } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useRef, useState } from "react";
import { buildCopilotReviewContext } from "@/lib/copilotContext";
import type { ReviewOutput } from "@/lib/types";

const WIDTH_KEY = "jb_copilot_sidebar_width";
const WIDTH_VAR = "--jb-copilot-width";
const WIDTH_MIN = 320;
const WIDTH_MAX = 760;
const WIDTH_DEFAULT = 420;

/** 그래프 조회 도구 → 준법 도메인 라벨. 채팅에 "규정 검색 중…" 상태 칩으로 렌더된다. */
const TOOL_LABELS: Record<string, string> = {
  search_regulations: "규정 검색",
  get_regulation_article: "조문 원문 조회",
  search_compliance_units: "심의 기준 검색",
  get_product_facts: "상품 사실 조회",
  list_regulation_documents: "규정 문서 목록 조회",
  graph_query: "정책 그래프 질의",
};

function toolArgsSummary(args: Record<string, unknown> | undefined): string {
  if (!args) return "";
  return ["keyword", "document_keyword", "article_no", "clause_no", "product_name", "question", "tier"]
    .map((key) => args[key])
    .filter((value) => typeof value === "string" && value)
    .join(" · ");
}

/** Claude식 진행 서사 — 도구 호출을 숨기지 않고 무엇을 조회 중인지 보여준다. */
function GraphToolChip({
  name,
  args,
  status,
}: {
  name: string;
  args?: Record<string, unknown>;
  status: string;
}) {
  const running = status !== "complete";
  const summary = toolArgsSummary(args);
  return (
    <div
      className="my-1 flex items-center gap-2 rounded-[9px] border border-line bg-surface-2 px-2.5 py-1.5 text-[12px]"
      style={{ opacity: running ? 0.85 : 1 }}
    >
      <span aria-hidden>{running ? "⏳" : "✓"}</span>
      <span className="font-semibold text-ink-2">{TOOL_LABELS[name] ?? name}</span>
      {summary ? <span className="truncate text-ink-4">{summary}</span> : null}
      <span className="ml-auto whitespace-nowrap text-ink-4">{running ? "조회 중…" : "완료"}</span>
    </div>
  );
}

/**
 * 심사 코파일럿 — 심의 결과가 열려 있을 때만 마운트한다.
 * 팝업 대신 도킹형 사이드챗: 심의 질의는 짧은 문답이 아니라 근거 조문·요건별
 * 판단을 오가는 긴 대화라, 콘솔 옆에 붙어 함께 보이는 형태가 맞다.
 * 컨텍스트는 준법 도메인 언어로 요약된 판정·근거로 한정(grounding).
 */
export function ReviewCopilot({
  result,
  resolved,
  title,
  reviewedText,
}: {
  result: ReviewOutput;
  resolved: Set<string>;
  title?: string;
  reviewedText?: string;
}) {
  useAgentContext({
    description: "현재 열려 있는 광고 심의 결과 (AI 사전심의 요약 · 원문 · 요건별 판단 포함)",
    // AG-UI Context.value 는 문자열 — JSON 직렬화해 전달한다.
    value: JSON.stringify(buildCopilotReviewContext(result, resolved, title, reviewedText), null, 1),
  });
  // 모든 도구 호출을 진행 칩으로 렌더 — 서술(무엇을 왜) + 칩(무엇을 조회 중) 조합으로
  // Claude식 진행 서사를 만든다.
  useRenderTool(
    {
      name: "*",
      render: (props) => (
        <GraphToolChip name={props.name} args={props.args as Record<string, unknown>} status={String(props.status)} />
      ),
    },
    [],
  );

  // ---- 가로폭 드래그 조정 ----------------------------------------------
  // width prop 은 CopilotSidebar 내부 useMemo deps 에 들어가 변경 시 chatView 가
  // 리마운트(접힘/재열림 깜빡임)된다. 대신 CSS 변수(--jb-copilot-width)로 폭을
  // 제어한다: 드래그 중 React 렌더 0회, width prop 미지정 시 활성화되는 내부
  // ResizeObserver 가 body 마진을 따라온다. 핸들 위치도 같은 변수로 계산.
  const [dragging, setDragging] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const widthRef = useRef(WIDTH_DEFAULT);

  useEffect(() => {
    const saved = Number(window.localStorage.getItem(WIDTH_KEY));
    const initial = saved >= WIDTH_MIN && saved <= WIDTH_MAX ? saved : WIDTH_DEFAULT;
    widthRef.current = initial;
    document.documentElement.style.setProperty(WIDTH_VAR, `${initial}px`);
  }, []);

  // 열림 상태는 토글 버튼의 aria-label("Close chat"=열림)로 감지 — 좌표(rect)는
  // 열림 애니메이션 중 신뢰할 수 없지만 aria-label 은 의미론적이라 안정적이다.
  useEffect(() => {
    const check = () => setSidebarOpen(Boolean(document.querySelector('button[aria-label="Close chat"]')));
    check();
    const observer = new MutationObserver(check);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-label"] });
    return () => observer.disconnect();
  }, []);

  const startDrag = useCallback((event: React.PointerEvent) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = widthRef.current;
    let latest = startWidth;
    setDragging(true);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    // 내부 레이아웃 이펙트가 body 마진에 260ms 트랜지션을 걸어 드래그를 뒤쫓는다 —
    // 드래그 중에는 끄고 마진도 직접 갱신해 손에 붙게 한다.
    const prevTransition = document.body.style.transition;
    document.body.style.transition = "none";
    const onMove = (move: PointerEvent) => {
      latest = Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, startWidth + (startX - move.clientX)));
      document.documentElement.style.setProperty(WIDTH_VAR, `${latest}px`);
      document.body.style.marginInlineEnd = `${latest}px`;
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      document.body.style.transition = prevTransition;
      widthRef.current = latest;
      setDragging(false);
      window.localStorage.setItem(WIDTH_KEY, String(latest));
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }, []);

  return (
    <>
      <CopilotSidebar
        defaultOpen={false}
        labels={{
          modalHeaderTitle: "JB Compliance Chat",
          chatInputPlaceholder: "판정·근거·조문에 대해 물어보세요",
          welcomeMessageText: "심의 결과의 판정 근거를 무엇이든 물어보세요.",
        }}
      />
      {sidebarOpen && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="채팅 폭 조정"
          onPointerDown={startDrag}
          className="fixed top-0 bottom-0 z-[10000] w-[7px] cursor-col-resize max-md:hidden"
          style={{ right: `calc(var(${WIDTH_VAR}, ${WIDTH_DEFAULT}px) - 3px)` }}
        >
          <div
            className="mx-auto h-full w-[2.5px] rounded-full transition-colors"
            style={{ background: dragging ? "var(--brand)" : "transparent" }}
          />
        </div>
      )}
    </>
  );
}
