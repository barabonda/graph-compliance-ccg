"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";

/** 심사 결과 설명 챗 사이드패널 (경량 자체 구현).
 *
 * CopilotKit 폴백 구현이다: CopilotKit v1.62의 사이드바는 자체 Node
 * CopilotRuntime(GraphQL 프로토콜 + 런타임 내 LLM tool-loop)을 요구해,
 * 백엔드 파이썬 /api/copilot의 "읽기 전용 도구 tool-calling 루프"를 단일
 * 두뇌로 쓰는 본 설계와 충돌한다. 동일 UX를 fetch /api/copilot으로 구현.
 * 도구는 전부 읽기 전용 — 심사 실행·데이터 변경 불가.
 */

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  tools?: string[];
}

interface Props {
  /** 현재 콘솔에 열려 있는 심사 run — 챗의 "이번 심사" 컨텍스트 */
  runId: string;
  workspaceId: string;
}

const SUGGESTIONS = [
  "이번 심사는 왜 이런 판정이 났는지 종합적으로 설명해줘",
  "product fact와 law 중 어느 부분이 문제였어?",
  "PPCBank Fixed Deposit의 상품 사실 보여줘",
];

export function CopilotPanel({ runId, workspaceId }: Props) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, busy]);

  const send = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || busy) return;
      const history = [...messages, { role: "user" as const, content: question }];
      setMessages(history);
      setInput("");
      setBusy(true);
      try {
        const res = await fetch("/api/copilot", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: history.map(({ role, content }) => ({ role, content })),
            context: { run_id: runId, workspace_id: workspaceId },
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as { reply?: string; tool_calls?: { name: string }[] };
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.reply || "(빈 응답)",
            tools: (data.tool_calls ?? []).map((t) => t.name),
          },
        ]);
      } catch (error) {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `조회에 실패했습니다: ${String(error)}. 백엔드(:8770) 상태를 확인해 주세요.` },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy, messages, runId, workspaceId],
  );

  return (
    <>
      {/* 토글 버튼 */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="fixed right-5 bottom-5 z-40 flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2.5 text-[12.5px] font-bold text-ink shadow-panel hover:bg-surface-2"
        aria-label="심사 결과 설명 보조 열기"
      >
        <Icon name="eye" size={15} color="var(--ink-2)" />
        결과 설명 보조
      </button>

      {open && (
        <aside className="fixed top-0 right-0 z-50 flex h-full w-[380px] flex-col border-l border-line bg-surface shadow-panel">
          {/* 헤더 — 읽기 전용 명시 */}
          <div className="flex items-start justify-between border-b border-line px-4 py-3">
            <div>
              <div className="text-[13.5px] font-extrabold text-ink">심사 결과 설명 보조</div>
              <div className="mt-0.5 text-[11px] leading-relaxed text-ink-3">
                읽기 전용 · 최종 판단은 심사자 — 저장된 심사 결과를 조회해 설명만 합니다
              </div>
              {runId ? (
                <div className="mt-1 font-mono text-[10px] text-ink-4">이번 심사: {runId.slice(0, 28)}…</div>
              ) : (
                <div className="mt-1 text-[10px] text-ink-4">열려 있는 심사 없음 — 최근 심사를 조회해 질문할 수 있습니다</div>
              )}
            </div>
            <button type="button" onClick={() => setOpen(false)} className="p-1 text-ink-3 hover:text-ink" aria-label="닫기">
              ✕
            </button>
          </div>

          {/* 메시지 */}
          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {messages.length === 0 && (
              <div className="space-y-2">
                <div className="text-[12px] text-ink-3">예시 질문:</div>
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void send(s)}
                    className="block w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-left text-[12px] text-ink-2 hover:bg-surface"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : ""}>
                <div
                  className={
                    m.role === "user"
                      ? "inline-block max-w-[92%] rounded-xl bg-[#2f6df0] px-3 py-2 text-left text-[12.5px] leading-relaxed text-white"
                      : "inline-block max-w-[95%] rounded-xl border border-line bg-surface-2 px-3 py-2 text-[12.5px] leading-relaxed whitespace-pre-wrap text-ink"
                  }
                >
                  {m.content}
                </div>
                {m.tools && m.tools.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {m.tools.map((t, j) => (
                      <span key={j} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[9.5px] text-ink-4">
                        🔍 {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {busy && <div className="text-[12px] text-ink-3">조회 중… (읽기 전용 도구 호출)</div>}
          </div>

          {/* 입력 */}
          <form
            className="flex gap-2 border-t border-line px-3 py-3"
            onSubmit={(e) => {
              e.preventDefault();
              void send(input);
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="심사 결과에 대해 질문…"
              className="flex-1 rounded-lg border border-line bg-surface-2 px-3 py-2 text-[12.5px] text-ink outline-none focus:border-[#2f6df0]"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              className="rounded-lg bg-[#2f6df0] px-3.5 py-2 text-[12.5px] font-bold text-white disabled:opacity-40"
            >
              전송
            </button>
          </form>
        </aside>
      )}
    </>
  );
}
