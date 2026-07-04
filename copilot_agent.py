"""심사 코파일럿 — LangGraph 에이전트 (AG-UI/CopilotKit 연동).

준법감시인이 심의 결과 화면에서 자연어로 되묻는 보조 에이전트.

Grounding 규율(프로젝트 표준과 동일):
- 1차 근거: 프론트가 useAgentContext 로 공유한 심의 결과(판정·원칙별 현황·카드·근거 조문).
- 2차 근거: 화면에 없으면 거버넌스 레이어(copilot_graph_tools)를 통해 Neo4j 의
  정책 그래프·상품 그래프·가이드라인 코퍼스를 읽기 전용으로 조회해 인용.
- 둘 다에서 못 찾으면 없다고 답한다. 자유 법률 해석·자문 생성 금지.
- 프론트 도구(copilotkit.actions)는 모델에 바인딩만 하고 실행은 AG-UI 어댑터가
  클라이언트로 넘긴다(Phase 2 UI 조작용).
"""
from __future__ import annotations

import os

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command
from typing_extensions import Annotated, Literal, NotRequired, TypedDict

from copilot_graph_tools import GRAPH_TOOLS, chat_model

# "ag-ui" 키(하이픈)는 class 문법으로 못 쓰므로 functional TypedDict.
# 이 키가 스키마에 있어야 어댑터가 넣어주는 공유 컨텍스트가 노드까지 전달된다.
CopilotAgentState = TypedDict(
    "CopilotAgentState",
    {
        "messages": Annotated[list, add_messages],
        "copilotkit": NotRequired[dict],
        "ag-ui": NotRequired[dict],
    },
)

SYSTEM_PROMPT = """당신은 JB금융그룹 금융광고 사전심의 시스템의 '심사 코파일럿'입니다.
준법감시인이 AI 사전심의 결과를 이해하고 검토하도록 돕습니다.

반드시 지킬 규칙:
1. 답변의 1차 근거는 아래 [심의 결과 컨텍스트]입니다. 화면에 없는 규정 원문·심의 기준·
   상품 사실이 필요하면 그래프 조회 도구(search_regulations, get_regulation_article,
   search_compliance_units, get_product_facts, list_regulation_documents, graph_query)로
   찾아서 답하십시오. 도구 결과를 쓸 때는 출처(문서명·조문)를 함께 인용하십시오.
2. 컨텍스트와 도구 결과 어디에도 없는 내용은 "확인되지 않는 정보"라고 밝히고 추측하지
   마십시오. 새로운 법률 해석이나 법률 자문을 생성하지 마십시오.
3. 주장에는 근거 조문(법령 또는 은행 광고심의 기준 등)을 함께 인용하십시오.
4. '법령 위반 근거'와 '심의기준 미흡'을 구분하십시오. 심의기준 미흡은 법령 위반이
   아니라 자율규제(은행연합회 심의기준, 금소법 제22조 위임) 보완 권고입니다.
5. 원문 검수가 안 된 자료(원문검수됨=false, OCR 산출물)를 인용할 때는 문장 끝에
   "(원문 확인 필요)" 를 붙이십시오.
6. 준법감시 실무 용어를 쓰십시오. 내부 개발 용어(anchor, CU, verdict 등)는 금지.
7. 컨텍스트·도구 결과의 JSON 키 이름(권위_계층, 요건별_판단, 그라운딩_조문 등)을
   그대로 노출하지 말고 자연스러운 한국어 문장으로 풀어 말하십시오.
8. 간결하게 답하십시오. 목록이 필요하면 짧은 불릿으로.
9. AI 사전심의는 보조 자료이며 최종 심의 책임은 심사자에게 있습니다.
10. 도구를 호출하기 전에 무엇을 왜 조회하는지 한 문장으로 먼저 말한 뒤 호출하십시오
    (예: "은행 광고심의 기준 제16조 원문을 그래프에서 확인하겠습니다."). 도구 결과를
    받으면 찾은 내용의 요지부터 이어서 설명하십시오. 심사자가 진행 과정을 따라올 수
    있어야 합니다.
"""


def _context_text(state: dict) -> str:
    items = (state.get("ag-ui") or {}).get("context") or []
    parts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            desc = item.get("description") or "컨텍스트"
            value = item.get("value") or ""
        else:  # pydantic Context 객체 폴백
            desc = getattr(item, "description", None) or "컨텍스트"
            value = getattr(item, "value", "") or ""
        parts.append(f"### {desc}\n{value}")
    return "\n\n".join(parts)


async def chat_node(
    state: CopilotAgentState, config: RunnableConfig
) -> Command[Literal["tool_node", "__end__"]]:
    # 모델은 copilot_graph_tools.chat_model() — 기본 Claude Sonnet 5,
    # CCG_COPILOT_MODEL env 로 교체 가능 (claude-*→Anthropic, 그 외→OpenAI).
    model = chat_model()
    fe_tools = (state.get("copilotkit") or {}).get("actions", [])
    bound = model.bind_tools([*fe_tools, *GRAPH_TOOLS])

    context_text = _context_text(state)
    system = SystemMessage(
        content=SYSTEM_PROMPT
        + "\n\n[심의 결과 컨텍스트]\n"
        + (
            context_text
            or "(공유된 심의 결과 없음 — 규정·상품 질의는 그래프 도구로 답하되, "
            "특정 광고 판정 질문이면 심사 결과 화면을 연 상태에서 질문해 달라고 안내하십시오.)"
        )
    )
    response = await bound.ainvoke([system, *state["messages"]], config)

    # 백엔드 그래프 도구 호출이면 tool_node 로. 프론트 도구 호출이면 run 을 끝내고
    # AG-UI 어댑터가 클라이언트에서 실행 후 continue 모드로 되돌아온다.
    fe_names = {t.get("name") for t in fe_tools if isinstance(t, dict)}
    calls = getattr(response, "tool_calls", None) or []
    if calls and any(call.get("name") not in fe_names for call in calls):
        return Command(goto="tool_node", update={"messages": [response]})
    return Command(goto="__end__", update={"messages": [response]})


workflow = StateGraph(CopilotAgentState)
workflow.add_node("chat_node", chat_node)
workflow.add_node("tool_node", ToolNode(tools=GRAPH_TOOLS))
workflow.add_edge("tool_node", "chat_node")
workflow.set_entry_point("chat_node")
graph = workflow.compile(checkpointer=MemorySaver())
