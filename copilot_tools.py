"""Read-only copilot tools + tool-calling loop for the review-explainer chat.

Five tools, ALL read-only (run-store snapshots + read-only Cypher). No tool can
run a review or mutate data — the chat explains existing results only.

`workspace_id` params allow querying any workspace (KR or KH); note this
sandbox's Neo4j only holds the KH workspace
(graphcompliance_cambodia_ppcbank_20260630) — KR runs would come from the KR
deployment's store.

The chat loop uses the existing LLMGateway's OpenAI client with Chat
Completions function-calling, capped at MAX_TOOL_CALLS per conversation turn.
Tool results are trimmed to the fields the model needs (snapshots are ~200KB).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from llm_gateway import LLMGateway
from run_store import list_runs as store_list_runs
from run_store import load_run as store_load_run

LOGGER = logging.getLogger(__name__)

MAX_TOOL_CALLS = 6
_TEXT = 400  # default truncation for long text fields


def _cut(value: Any, limit: int = _TEXT) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# Neo4j (read-only session helper, workspace 기반 DB 라우팅)
# --------------------------------------------------------------------------- #
def _team_workspaces() -> set[str]:
    raw = os.environ.get("TEAM_NEO4J_WORKSPACES", "")
    return {token.strip() for token in raw.replace(",", " ").split() if token.strip()}


def _creds_for_workspace(workspace_id: str) -> tuple[str, str, str]:
    """워크스페이스별 접속 라우팅.

    KR 코퍼스는 팀원 공용 Aura(TEAM_NEO4J_*)에 있고, KH PoC는 이 샌드박스의
    기본 Aura(NEO4J_*)에 있다. 합의사항에 따라 팀 DB는 이 읽기 전용 조회
    경로에서만 쓴다 — 쓰기가 발생하는 심사 실행은 팀 DB에 연결하지 않는다.
    """
    if workspace_id and workspace_id in _team_workspaces():
        uri = os.environ.get("TEAM_NEO4J_URI", "")
        user = os.environ.get("TEAM_NEO4J_USER", "")
        password = os.environ.get("TEAM_NEO4J_PASSWORD", "")
        if uri and user and password:
            # 팀 Aura는 DB 이름이 다르므로 NEO4J_DATABASE(내 샌드박스용)를 쓰지 않는다.
            return uri, user, password, os.environ.get("TEAM_NEO4J_DATABASE", "")
    return (
        os.environ.get("NEO4J_URI", ""),
        os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", ""),
        os.environ.get("NEO4J_PASSWORD", ""),
        os.environ.get("NEO4J_DATABASE", ""),
    )


def _read_cypher(query: str, *, workspace_id: str = "", **params: Any) -> list[dict[str, Any]]:
    from neo4j import GraphDatabase

    uri, user, password, database = _creds_for_workspace(workspace_id)
    if not uri or not user or not password:
        return []
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) if database else driver.session() as session:
            return [dict(record) for record in session.run(query, **params)]
    finally:
        driver.close()


# --------------------------------------------------------------------------- #
# Tool implementations (read-only)
# --------------------------------------------------------------------------- #
def list_runs(limit: int = 10, workspace_id: str = "") -> list[dict[str, Any]]:
    rows = store_list_runs(limit=max(1, min(int(limit or 10), 50)) * 3)
    out = []
    for row in rows:
        if workspace_id and str(row.get("workspace_id") or "") != workspace_id:
            continue
        out.append(
            {
                "run_id": row.get("id"),
                "ts": row.get("ts"),
                "title": row.get("title"),
                "workspace_id": row.get("workspace_id"),
                "language": row.get("language"),
                "final_verdict": row.get("final_verdict"),
                "issue_count": row.get("issue_count"),
                "cu_ids": row.get("cu_ids"),
                "content_preview": _cut(row.get("content_text"), 120),
            }
        )
        if len(out) >= int(limit or 10):
            break
    return out


def get_run_detail(run_id: str) -> dict[str, Any]:
    output = store_load_run(run_id)
    if not output:
        return {"error": f"run '{run_id}' not found"}
    plan_by_item = {p.get("plan_item_id"): p for p in output.get("cu_plan") or []}
    judgments = []
    for j in output.get("judgments") or []:
        plan = plan_by_item.get(j.get("plan_item_id")) or {}
        judgments.append(
            {
                "cu_id": j.get("cu_id"),
                "verdict": j.get("verdict"),
                "score": j.get("score"),
                "source_article": plan.get("source_article") or "",
                "principle": plan.get("principle") or "",
                "evidence_span": _cut(j.get("evidence_span"), 160),
                "conclusion": _cut(j.get("conclusion")),
            }
        )
    track_b = output.get("overall_impression_judgment") or {}
    pfc = output.get("product_fact_context") or {}
    comparisons = [
        {
            "status": c.get("status"),
            "rationale": _cut(c.get("rationale"), 240),
            "evidence_text": _cut(c.get("evidence_text"), 160),
        }
        for c in pfc.get("comparison_results") or []
    ]
    issues = [
        {
            "risk_code": x.get("risk_code"),
            "principle": x.get("principle"),
            "source_article": x.get("source_article"),
            "severity": x.get("severity"),
            "rationale": _cut(x.get("rationale"), 200),
        }
        for x in (output.get("detected_issues") or [])[:12]
    ]
    translations = output.get("ad_translations") or None
    if translations:
        translations = {
            "en": _cut(translations.get("en"), 300),
            "ko": _cut(translations.get("ko"), 300),
            "note": translations.get("note"),
        }
    return {
        "run_id": run_id,
        "final_verdict": output.get("final_verdict"),
        "rationale": _cut(output.get("rationale"), 300),
        "judgments": judgments,
        "track_b_overall_impression": {
            "verdict": track_b.get("verdict"),
            "misleading_risk_score": track_b.get("misleading_risk_score"),
            "impression": _cut(track_b.get("representative_consumer_impression"), 300),
        },
        "detected_issues": issues,
        "product_fact_comparison": {
            "matched_product": pfc.get("matched_product"),
            "extraction_status": pfc.get("extraction_status"),
            "comparisons": comparisons,
        },
        "ad_translations": translations,
    }


def compare_runs(run_id_a: str, run_id_b: str) -> dict[str, Any]:
    a, b = get_run_detail(run_id_a), get_run_detail(run_id_b)
    if a.get("error") or b.get("error"):
        return {"error": a.get("error") or b.get("error")}

    def verdict_map(detail: dict[str, Any]) -> dict[str, str]:
        worst: dict[str, str] = {}
        rank = {"NON_COMPLIANT": 3, "INSUFFICIENT": 2, "NOT_APPLICABLE": 1, "COMPLIANT": 0}
        for j in detail["judgments"]:
            cu = str(j.get("cu_id"))
            if cu not in worst or rank.get(j.get("verdict"), 0) > rank.get(worst[cu], 0):
                worst[cu] = str(j.get("verdict"))
        return worst

    va, vb = verdict_map(a), verdict_map(b)
    common = sorted(set(va) & set(vb))
    return {
        "run_a": {"run_id": run_id_a, "final_verdict": a["final_verdict"], "track_b": a["track_b_overall_impression"]["verdict"], "product_extraction": a["product_fact_comparison"]["extraction_status"]},
        "run_b": {"run_id": run_id_b, "final_verdict": b["final_verdict"], "track_b": b["track_b_overall_impression"]["verdict"], "product_extraction": b["product_fact_comparison"]["extraction_status"]},
        "cus_only_in_a": sorted(set(va) - set(vb)),
        "cus_only_in_b": sorted(set(vb) - set(va)),
        "common_cu_verdicts": [{"cu_id": cu, "a": va[cu], "b": vb[cu], "changed": va[cu] != vb[cu]} for cu in common],
        "comparison_status_counts_a": _status_counts(a),
        "comparison_status_counts_b": _status_counts(b),
        "issue_count_a": len(a["detected_issues"]),
        "issue_count_b": len(b["detected_issues"]),
    }


def _status_counts(detail: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in detail["product_fact_comparison"]["comparisons"]:
        key = str(c.get("status") or "")
        counts[key] = counts.get(key, 0) + 1
    return counts


def get_product_facts(product_name: str, workspace_id: str) -> list[dict[str, Any]]:
    rows = _read_cypher(
        """
        MATCH (p:Product {name: $name, workspace_id: $ws})
              -[:HAS_PRODUCT_DOCUMENT]->(d:ProductDocument {workspace_id: $ws})
              -[:CONTAINS_FACT]->(f:ProductFact {workspace_id: $ws})
        // DISTINCT: 심사 영속화가 run마다 병렬 엣지를 만들어 경로가 곱해진다.
        RETURN DISTINCT f.fact_type AS fact_type, f.value AS value, f.unit AS unit,
               f.condition AS condition, f.evidence_text AS evidence_text,
               f.confidence AS confidence, d.file_name AS source_document
        ORDER BY fact_type
        """,
        workspace_id=workspace_id,
        name=product_name,
        ws=workspace_id,
    )
    return [
        {
            "fact_type": r["fact_type"],
            "value": r["value"],
            "unit": r["unit"],
            "condition": _cut(r["condition"], 200),
            "evidence_text": _cut(r["evidence_text"], 200),
            "confidence": r["confidence"],
            "source_document": r["source_document"],
        }
        for r in rows
    ] or [{"note": f"no preloaded ProductFacts for '{product_name}' in workspace '{workspace_id}'"}]


def get_cu_detail(cu_id: str, workspace_id: str) -> dict[str, Any]:
    rows = _read_cypher(
        """
        MATCH (cu:ComplianceUnit {id: $cu_id, workspace_id: $ws})
        OPTIONAL MATCH (clause:LegalClause)-[:GROUNDS_CU]->(cu)
        OPTIONAL MATCH (chunk:LegalChunk)-[:EVIDENCES_CU]->(cu)
        // KR 코퍼스는 근거를 (cu)-[:GROUNDED_IN|HAS_SOURCE_CHUNK]->(원문)으로 연결한다.
        OPTIONAL MATCH (cu)-[:GROUNDED_IN|HAS_SOURCE_CHUNK]->(direct)
        RETURN cu.principle AS principle, cu.subject AS subject,
               cu.condition AS condition, cu.constraint AS constraint,
               cu.source_article AS source_article, cu.severity AS severity,
               cu.effective_date AS effective_date,
               collect(DISTINCT {article: clause.article_no, title: clause.document_title, text: clause.text})[0..4] AS clauses,
               collect(DISTINCT {title: chunk.document_title, text: chunk.text})[0..3] AS chunks,
               collect(DISTINCT {article: direct.article_title, title: direct.document_title,
                                 text: coalesce(direct.text, direct.summary, '')})[0..4] AS direct_grounding
        """,
        workspace_id=workspace_id,
        cu_id=cu_id,
        ws=workspace_id,
    )
    if not rows:
        return {"error": f"CU '{cu_id}' not found in workspace '{workspace_id}'"}
    r = rows[0]
    return {
        "cu_id": cu_id,
        "principle": r["principle"],
        "subject": r["subject"],
        "condition": r["condition"],
        "constraint": r["constraint"],
        "source_article": r["source_article"],
        "severity": r["severity"],
        "effective_date": r["effective_date"],
        "grounding_clauses": [
            {"article": c.get("article"), "document": c.get("title"), "text": _cut(c.get("text"), 350)}
            for c in r["clauses"] or [] if c.get("text")
        ],
        "evidence_chunks": [
            {"document": c.get("title"), "text": _cut(c.get("text"), 350)}
            for c in r["chunks"] or [] if c.get("text")
        ],
        "direct_grounding": [
            {"article": c.get("article"), "document": c.get("title"), "text": _cut(c.get("text"), 350)}
            for c in r.get("direct_grounding") or [] if c.get("text")
        ],
    }


TOOL_IMPLS = {
    "list_runs": list_runs,
    "get_run_detail": get_run_detail,
    "compare_runs": compare_runs,
    "get_product_facts": get_product_facts,
    "get_cu_detail": get_cu_detail,
}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "list_runs",
        "description": "최근 심사 실행 목록(run_id, 제목, verdict, workspace). '이전 심사'를 찾을 때 사용.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "최대 개수(기본 10)"},
            "workspace_id": {"type": "string", "description": "선택: workspace 필터"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "get_run_detail",
        "description": "특정 심사 run의 전체 판정: verdict, CU별 판정(id·score·근거조문·사유), Track B, 이슈, 상품 대조, 번역.",
        "parameters": {"type": "object", "properties": {
            "run_id": {"type": "string"}}, "required": ["run_id"]}}},
    {"type": "function", "function": {
        "name": "compare_runs",
        "description": "두 심사 run의 verdict/발화 CU/상품 대조/이슈 수를 구조화 diff로 반환.",
        "parameters": {"type": "object", "properties": {
            "run_id_a": {"type": "string"}, "run_id_b": {"type": "string"}},
            "required": ["run_id_a", "run_id_b"]}}},
    {"type": "function", "function": {
        "name": "get_product_facts",
        "description": "상품의 선적재 ProductFact 목록(fact_type, value, condition, evidence).",
        "parameters": {"type": "object", "properties": {
            "product_name": {"type": "string", "description": "예: 'PPCBank Fixed Deposit'"},
            "workspace_id": {"type": "string"}},
            "required": ["product_name", "workspace_id"]}}},
    {"type": "function", "function": {
        "name": "get_cu_detail",
        "description": "ComplianceUnit 상세(principle/subject/constraint/source_article)와 연결된 근거 조문 원문.",
        "parameters": {"type": "object", "properties": {
            "cu_id": {"type": "string", "description": "예: 'KH-CU-16'"},
            "workspace_id": {"type": "string"}},
            "required": ["cu_id", "workspace_id"]}}},
]

SYSTEM_PROMPT = (
    "너는 JB Compliance 심사 결과를 설명하는 보조자다. 반드시 도구로 조회한 데이터에만 근거해 "
    "답하고, 조회되지 않은 내용은 모른다고 말하라. 판정을 바꾸거나 새 심사를 실행할 수 없다 — "
    "너의 도구는 전부 읽기 전용 조회다. 근거를 말할 때 CU id와 source_article을 인용하라. "
    "최종 판단 권한은 항상 사람 심사자에게 있음을 전제로 답하라. 한국어로 간결히 답하라."
)


def run_copilot_chat(
    messages: list[dict[str, str]],
    *,
    context: dict[str, Any] | None = None,
    llm: LLMGateway | None = None,
) -> dict[str, Any]:
    """Tool-calling chat loop. Returns {reply, tool_calls:[{name, arguments}]}."""
    gateway = llm or LLMGateway()
    system = SYSTEM_PROMPT
    if context:
        system += (
            f"\n[현재 콘솔 컨텍스트] 사용자가 보고 있는 심사 run_id={context.get('run_id') or '(없음)'}, "
            f"workspace_id={context.get('workspace_id') or '(없음)'}. '이번 심사'는 이 run을 가리킨다."
        )
    chat: list[dict[str, Any]] = [{"role": "system", "content": system}]
    chat += [{"role": m.get("role", "user"), "content": str(m.get("content", ""))} for m in messages][-12:]

    called: list[dict[str, Any]] = []
    for _round in range(MAX_TOOL_CALLS + 1):
        force_answer = len(called) >= MAX_TOOL_CALLS
        response = gateway.client.chat.completions.create(
            model=gateway.model,
            messages=chat,
            tools=TOOL_SPECS,
            tool_choice="none" if force_answer else "auto",
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            return {"reply": msg.content or "", "tool_calls": called}
        chat.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]})
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            impl = TOOL_IMPLS.get(name)
            try:
                result = impl(**args) if impl else {"error": f"unknown tool {name}"}
            except TypeError as exc:
                result = {"error": f"bad arguments: {exc}"}
            except Exception as exc:  # noqa: BLE001 — 조회 실패는 답변에 알린다.
                LOGGER.warning("copilot tool %s failed: %s", name, exc)
                result = {"error": f"tool failed: {exc}"}
            called.append({"name": name, "arguments": args})
            chat.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
    return {"reply": "도구 호출 한도에 도달했습니다. 질문을 좁혀 다시 시도해 주세요.", "tool_calls": called}
