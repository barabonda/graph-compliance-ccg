import {
  CopilotRuntime,
  createCopilotHonoHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";
import { handle } from "hono/vercel";

// 심사 코파일럿 — FastAPI 백엔드(server.py)에 ag-ui-langgraph 로 마운트된
// LangGraph 에이전트(/copilot-agent)를 AG-UI 프로토콜로 연결한다.
const API_BASE = process.env.CCG_API_BASE ?? "http://localhost:8770";

const runtime = new CopilotRuntime({
  agents: {
    // 프로바이더/훅의 기본 agent id 가 "default" 라 이 키를 쓴다.
    default: new LangGraphHttpAgent({
      url: `${API_BASE}/copilot-agent`,
    }),
  },
  runner: new InMemoryAgentRunner(),
});

const app = createCopilotHonoHandler({
  runtime,
  basePath: "/api/copilotkit",
});

export const GET = handle(app);
export const POST = handle(app);
export const PATCH = handle(app);
export const DELETE = handle(app);
