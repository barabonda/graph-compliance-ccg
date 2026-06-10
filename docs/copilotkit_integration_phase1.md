# CopilotKit 통합 가이드 — Phase 1 (해커톤 안전 경로)

GraphCompliance CCG의 **기존 FastAPI 파이프라인과 콘솔은 그대로 두고**, 그 위에 CopilotKit의 챗 사이드바 · Generative UI · Human-in-the-loop(HITL)를 얹는 최소 침습 통합 설계서입니다.

> 핵심 전략: Phase 1에서는 파이프라인을 LangGraph/AG-UI로 재작성하지 않습니다. 기존 `/api/review`(및 `/api/review/stream`)를 **CopilotKit 액션(툴)으로 노출**하고, `ReviewOutput`을 **Generative UI로 렌더**합니다. 수정안 승인만 HITL로 처리합니다. (정식 AG-UI 연동은 Phase 2, 본 문서 §6의 스켈레톤이 그 다리입니다.)

---

## 0. 사전 확인 — 우리가 이미 가진 것

| 자산 | 위치 | Phase 1에서의 역할 |
|---|---|---|
| `POST /api/review` | `server.py:30` | 동기 1회 심사 → `ReviewOutput`(JSON) 반환. **CopilotKit 액션이 호출할 엔드포인트.** |
| `POST /api/review/stream` | `server.py:71` | NDJSON 단계 이벤트 스트림. 진행상황 Generative UI용. |
| `workflow.review_events()` | `workflow.py:52` | `start / step_started / step_completed / result` 이벤트. §6에서 AG-UI로 매핑. |
| `ReviewOutput` | `schemas.py:191` | anchors·cu_plan·judgments·effective_judgments·overall_impression_judgment·revision_suggestions·routing 등. **Generative UI 렌더 입력.** |
| v3 콘솔 컴포넌트 | `console/review_console_v3.html` | anchor 카드·라우팅 ladder·Track B·수정안 diff 디자인 → **React 컴포넌트로 포팅해 재사용.** |

---

## 1. 목표 아키텍처 (Phase 1)

```
[Browser]
  React app (Next.js)
   ├─ <CopilotKit runtimeUrl="/api/copilotkit">
   ├─ <CopilotSidebar>                  ← 준법관리자와 대화
   ├─ useCopilotReadable(현재 광고 초안) ← "이 문구 왜 위반?" 답변 컨텍스트
   ├─ useCopilotAction("reviewAdDraft", render) ← 심사 호출 + ReviewOutput 렌더
   └─ useCopilotAction("approveRewrite", renderAndWaitForResponse) ← HITL 승인
        │
        ▼  (runtimeUrl)
[Copilot Runtime  (Node / Next route /api/copilotkit)]
   CopilotRuntime + LLM service adapter
        │  server action / fetch
        ▼
[기존 FastAPI]  POST /api/review  (변경 없음)
        │
        ▼
 workflow → retriever(Neo4j) + LLM judge → ReviewOutput
```

요점: **CopilotKit은 프론트 + Node 런타임**, GraphCompliance 파이프라인은 **Python FastAPI 그대로**. 둘은 HTTP 한 줄로 연결됩니다.

---

## 2. 매핑 — 우리 개념 → CopilotKit 프리미티브

| GraphCompliance | CopilotKit primitive | 비고 |
|---|---|---|
| 광고 초안 입력 | `useCopilotReadable` | 에이전트가 항상 현재 초안을 컨텍스트로 인지 |
| `POST /api/review` 호출 | `useCopilotAction` (handler) | "이 광고 심사해줘" → 액션 실행 |
| `ReviewOutput` 시각화 | `useCopilotAction({ render })` = **Generative UI** | v3 카드들을 render로 반환 |
| 단계 이벤트(`review_events`) | render 내 진행상태 / (Phase 2) AG-UI events | `/api/review/stream` 소비 |
| 수정안 승인/수정/반려 | `renderAndWaitForResponse` = **HITL** | 사람이 버튼으로 응답 |
| Regulatory Watcher | 별도 `useCopilotAction("checkRegulatoryDrift")` | 에이전트가 호출 가능한 툴 |
| 감사 추적(Audit) | `useCopilotReadable` + 백엔드 저장 | 근거 path·모델 버전 기록 |

---

## 3. 스캐폴드

```bash
# CopilotKit이 Next.js 앱 + /api/copilotkit 런타임을 스캐폴드
npx copilotkit@latest create
cd <app>
npm run dev
```

`.env`:
```
OPENAI_API_KEY=...                       # Copilot Runtime용 LLM
GRAPHCOMPLIANCE_API=http://localhost:8770 # 기존 FastAPI (server.py)
```

> v2 API는 `@copilotkit/react-core/v2`로 재구성되었습니다. 아래 임포트 경로/시그니처는 골격이며, 실제 버전은 docs(§8 링크)로 확인하세요.

---

## 4. 단계별 구현

### 4.1 Provider + Sidebar

```tsx
// app/layout.tsx (또는 main)
import { CopilotKit } from "@copilotkit/react-core";
import { CopilotSidebar } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko"><body>
      <CopilotKit runtimeUrl="/api/copilotkit">
        <CopilotSidebar
          labels={{ title: "준법자문가 AI", initial: "심사할 광고 문안을 붙여넣거나 ‘심사’라고 말해보세요." }}
        >
          {children}
        </CopilotSidebar>
      </CopilotKit>
    </body></html>
  );
}
```

### 4.2 현재 초안을 에이전트 컨텍스트로 노출 (Shared/Readable)

```tsx
import { useCopilotReadable } from "@copilotkit/react-core";

function DraftProvider({ draft }: { draft: AdDraft }) {
  useCopilotReadable({
    description: "현재 심사 대상 광고 초안 (제목·본문·상품군·채널)",
    value: draft,
  });
  return null;
}
```
→ 이제 챗에서 "‘조건 없이’가 왜 문제야?" 같은 질문에 에이전트가 초안 문맥으로 답합니다.

### 4.3 심사 액션 + ReviewOutput Generative UI

```tsx
import { useCopilotAction } from "@copilotkit/react-core";
import { ReviewResult } from "@/components/ReviewResult"; // v3 카드 포팅

useCopilotAction({
  name: "reviewAdDraft",
  description: "광고 초안을 GraphCompliance 파이프라인으로 준법 심사한다.",
  parameters: [
    { name: "content_text", type: "string", required: true },
    { name: "title", type: "string" },
    { name: "product_group", type: "string", description: "auto|deposit|loan|investment|insurance" },
    { name: "channel", type: "string" },
  ],
  handler: async ({ content_text, title, product_group = "auto", channel = "bank_event_page_text" }) => {
    const res = await fetch("/api/graphcompliance/review", {  // §5의 얇은 프록시
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content_text, title, product_group, channel,
        workspace_id: "graphcompliance_mvp_jb_20260530" }),
    });
    return await res.json(); // ReviewOutput
  },
  // Generative UI: 에이전트가 결과를 우리 컴포넌트로 렌더
  render: ({ status, result }) =>
    status === "complete"
      ? <ReviewResult data={result} />
      : <ReviewProgress status={status} />,  // 4.4
});
```

`ReviewResult`는 v3 콘솔(`review_console_v3.html`)의 카드 로직을 React로 옮기면 됩니다 — 라우팅 ladder, anchor 카드(HIGH/MED/LOW/NONE), raw→effective 전이칩, Track B 경로, 수정안 diff. 디자인 자산이 그대로 살아납니다.

### 4.4 진행 상태 — 스트리밍 매핑 (선택)

`/api/review/stream`(NDJSON)을 소비해 단계 진행을 보여줍니다.

```tsx
async function* streamReview(body: ReviewInput) {
  const res = await fetch("/api/graphcompliance/review-stream", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const reader = res.body!.getReader(); const dec = new TextDecoder(); let buf = "";
  while (true) {
    const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split("\n"); buf = lines.pop() ?? "";
    for (const ln of lines) if (ln.trim()) yield JSON.parse(ln); // {event, step, summary, ...}
  }
}
// event === "result" 이면 event.result === ReviewOutput
```

`ReviewProgress`는 `step_started/step_completed`의 `step`·`summary`를 단계 체크리스트로 렌더(예: "CU candidate retrieval · 36 candidates").

### 4.5 HITL — 수정안 승인/수정/반려

```tsx
useCopilotAction({
  name: "approveRewrite",
  description: "AI 수정 문안을 준법관리자가 승인/수정/반려한다.",
  parameters: [{ name: "before", type: "string" }, { name: "after", type: "string" }],
  renderAndWaitForResponse: ({ args, respond, status }) => (
    <RewriteApproval
      before={args.before} after={args.after} disabled={status !== "executing"}
      onApprove={(finalText) => respond?.({ decision: "approved", finalText })}
      onReject={(reason)   => respond?.({ decision: "rejected", reason })}
    />
  ),
});
```
→ 에이전트가 수정안을 제안하면 사람이 버튼으로 승인/편집/반려하고, 그 결정이 대화 흐름으로 돌아갑니다. **"AI가 대체"가 아니라 "관리자가 승인"** 포지셔닝이 그대로 구현됩니다.

### 4.6 Regulatory Watcher를 툴로

```tsx
useCopilotAction({
  name: "checkRegulatoryDrift",
  description: "광고/템플릿의 고지 문구가 최신 규정과 일치하는지(stale 여부) 점검한다.",
  parameters: [{ name: "text", type: "string", required: true }],
  handler: async ({ text }) => {
    const r = await fetch("/api/graphcompliance/reg-watch", {
      method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ text }) });
    return await r.json(); // [{rule:"예금자보호 한도", old:"5천만원", new:"1억원", effective_from:"2025-09-01", source}]
  },
  render: ({ result }) => <RegulatoryDriftCard findings={result} />,
});
```
백엔드는 Policy Graph 노드의 `effective_from / version`을 검사해 stale 고지를 탐지(예: "5천만원" → "1억원", 2025-09-01 시행).

---

## 5. 백엔드 — 변경 최소화

기존 `server.py`는 **그대로 둡니다.** Copilot Runtime(Next) 쪽에 얇은 프록시 라우트만 추가해 CORS·계약을 캡슐화합니다.

```ts
// app/api/graphcompliance/review/route.ts
export async function POST(req: Request) {
  const body = await req.json();
  const r = await fetch(`${process.env.GRAPHCOMPLIANCE_API}/api/review`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}
```
(스트림 라우트는 `r.body`를 그대로 파이프.)

`/api/copilotkit` 런타임 라우트(스캐폴드가 생성)는 LLM 어댑터만 설정하면 됩니다. 위 `useCopilotAction`들은 프론트 액션이라 런타임 수정이 거의 없습니다.

---

## 6. (Phase 2 다리) `review_events` → AG-UI 이벤트 매핑 스켈레톤

정식 CopilotKit 연동(Shared State·Threads·CoAgent)을 원하면, 파이프라인을 AG-UI 호환으로 노출해야 합니다. 우리의 `review_events`는 이미 단계 스트림이라 매핑이 단순합니다.

```python
# ag_ui_adapter.py  (FastAPI에 추가; 기존 workflow 재사용)
# review_events(start/step_started/step_completed/result) → AG-UI 이벤트 스트림
def to_ag_ui(event: dict) -> dict:
    e = event["event"]
    if e == "start":
        return {"type": "RUN_STARTED", "runId": event["review_run_id"]}
    if e == "step_started":
        return {"type": "STEP_STARTED", "stepName": event["step"]}
    if e == "step_completed":
        # 단계 요약/카운트를 상태 패치로
        return {"type": "STATE_DELTA", "delta": {"step": event["step"],
                "summary": event.get("summary"), "counts": event.get("counts", {})}}
    if e == "result":
        return {"type": "STATE_SNAPSHOT", "snapshot": to_jsonable(event["result"])}  # ReviewOutput
    return {"type": "CUSTOM", "payload": event}
```
- `STATE_SNAPSHOT`(=ReviewOutput) ↔ CopilotKit **Shared State** → 프론트가 `useCoAgentStateRender`로 자동 렌더.
- 멀티 에이전트(Regulatory Watcher·Claim·Product Fact·Compliance Gate·LLM Judge·Rewrite·Audit)는 LangGraph 노드로 두면, 노드 전이가 그대로 `STEP_STARTED`로 흐릅니다.
- 이때 `workflow.py`의 12단계가 이미 노드 경계와 거의 일치하므로 재구성 비용이 낮습니다.

---

## 7. 해커톤 체크리스트 & 데모 스크립트

**구현 체크리스트 (Phase 1)**
- [ ] `npx copilotkit create` → Next 앱 + `/api/copilotkit`
- [ ] `CopilotKit` provider + `CopilotSidebar`
- [ ] 프록시 라우트 2개(`/review`, `/review-stream`) → 기존 8770 포트
- [ ] `reviewAdDraft` 액션 + `ReviewResult`(v3 카드 포팅) Generative UI
- [ ] `approveRewrite` HITL
- [ ] `checkRegulatoryDrift` 툴 + 카드
- [ ] `useCopilotReadable`로 현재 초안 노출

**데모 흐름 (3분)**
1. 관리자가 챗에 광고 문안 붙여넣기 → "심사해줘".
2. `reviewAdDraft` 실행 → 진행 단계 스트리밍 → `ReviewResult` 렌더(반려, anchor HIGH 카드, raw→예외↓→effective 전이, Track B 1.00, 라우팅 ladder).
3. 챗 질문: "‘조건 없이’가 왜 위반이야?" → readable 컨텍스트로 근거 답변.
4. 에이전트가 수정안 제안 → **HITL 승인 카드** → 관리자가 한 단어 수정 후 승인.
5. `checkRegulatoryDrift`가 "예금자보호 5천만원 → 1억원(2025-09-01)" stale 자동 탐지 → 수정안 반영.
6. (선택) 감사 추적: 근거 조항·graph path·모델 버전·승인자 저장.

이 흐름이 해커톤 주제의 "규제 문서 검색·참조 / 리스크 분류 / 규칙+LLM 결합 / 관리자 검토·승인"을 한 번에 보여줍니다.

---

## 8. 검증 포인트 & 출처

- **버전 주의**: CopilotKit v2는 `@copilotkit/react-core/v2` 등으로 재구성됨. 위 임포트·시그니처는 골격이니 실제 버전 docs로 확정하세요(특히 `renderAndWaitForResponse`, generative UI render의 `status` 값, 런타임 어댑터 설정).
- **Generative UI**는 에이전트가 React 컴포넌트를 렌더하는 기능이라, v3의 vanilla 카드는 React 컴포넌트로 옮겨야 합니다(디자인/로직은 그대로 이식 가능).
- **라이브 런타임 필요**: CopilotKit은 Copilot Runtime 서버가 떠 있어야 실제 동작합니다(정적 HTML 아티팩트로는 목업까지만).

참고 문서:
- CopilotKit 개요 — https://docs.copilotkit.ai/
- Quickstart — https://docs.copilotkit.ai/built-in-agent/quickstart
- Generative UI / Tool Rendering — https://docs.copilotkit.ai/built-in-agent/generative-ui/tool-rendering
- Frontend Tools — https://docs.copilotkit.ai/built-in-agent/frontend-tools
- Shared State — https://docs.copilotkit.ai/built-in-agent/shared-state
- AG-UI 프로토콜 — https://docs.copilotkit.ai/built-in-agent/ag-ui
- LangGraph (FastAPI) — https://docs.copilotkit.ai/langgraph-fastapi
- Copilot Runtime — https://docs.copilotkit.ai/built-in-agent/copilot-runtime
