"""FastAPI server for the GraphCompliance CCG reviewer."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from neo4j.exceptions import AuthError, ServiceUnavailable
from openai import APIConnectionError, APIStatusError, AuthenticationError, BadRequestError, RateLimitError

from env_loader import load_local_env
from jb_data_context import search_products
from llm_gateway import LLMGateway
from run_store import list_runs, load_run, record_run
from workflow import GraphComplianceCCGWorkflow, review_input_from_payload
from utils import to_jsonable


load_local_env(Path(__file__).resolve().parent / ".env")
logging.basicConfig(
    level=getattr(logging, os.environ.get("CCG_LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = FastAPI(title="GraphCompliance CCG", version="0.1.0")
CONSOLE_DIR = Path(__file__).resolve().parent / "console"

# 심사 코파일럿(AG-UI/LangGraph) — 의존성 문제로 실패해도 심의 API 는 살아있어야 한다.
# ag_ui_langgraph.add_langgraph_fastapi_endpoint 대신 직접 라우트를 정의하는 이유:
# 스트림 응답에 Connection: close 를 붙여야 한다. keep-alive 소켓을 CopilotKit 런타임
# (undici)이 재사용하려다 'terminated' 에러를 RUN_ERROR 로 흘리는 노이즈가 있다
# (CopilotKit/CopilotKit#2402 계열). 런마다 새 연결이면 발생하지 않는다.
try:
    from ag_ui.core.types import RunAgentInput
    from ag_ui.encoder import EventEncoder
    from copilotkit import LangGraphAGUIAgent
    from fastapi import Request
    from fastapi.responses import StreamingResponse

    from copilot_agent import graph as copilot_graph

    _copilot_agent = LangGraphAGUIAgent(
        name="compliance_copilot",
        description="심의 결과를 근거 조문과 함께 설명하는 심사 코파일럿",
        graph=copilot_graph,
    )

    @app.post("/copilot-agent")
    async def copilot_agent_endpoint(input_data: RunAgentInput, request: Request):
        encoder = EventEncoder(accept=request.headers.get("accept"))
        request_agent = _copilot_agent.clone()  # 요청별 상태 격리 (endpoint.py 와 동일)

        async def event_generator():
            async for event in request_agent.run(input_data):
                yield encoder.encode(event)

        return StreamingResponse(
            event_generator(),
            media_type=encoder.get_content_type(),
            headers={"Connection": "close"},
        )

    @app.get("/copilot-agent/health")
    def copilot_agent_health() -> dict[str, str]:
        return {"status": "ok", "agent": "compliance_copilot"}
except Exception:  # noqa: BLE001
    logging.getLogger(__name__).exception("copilot agent mount failed — 심의 API는 계속 동작")


def workflow_for(payload: dict[str, Any]) -> GraphComplianceCCGWorkflow:
    """선택한 모델(payload.llm_model)이 있으면 그 모델로 게이트웨이를 구성한다.

    클라우드↔로컬 전환은 .env(LLM_BASE_URL)가 정하고, 이 값은 활성 경로 안에서
    모델만 오버라이드한다(빈 값이면 .env 기본 모델 사용).
    """
    model = str(payload.get("llm_model") or "").strip()
    if model:
        return GraphComplianceCCGWorkflow(llm=LLMGateway(model=model))
    return GraphComplianceCCGWorkflow()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/products/search")
def products_search(q: str = "", product_group: str = "auto", limit: int = 12) -> dict[str, Any]:
    """Search product metadata so reviewers select a real Product row."""

    return {"products": search_products(q, product_group=product_group, limit=limit)}


@app.post("/api/review")
def review(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        workflow = workflow_for(payload)
        output = workflow.review(review_input_from_payload(payload))
        jsonable = to_jsonable(output)
        record_run(
            jsonable,
            title=str(payload.get("title") or ""),
            channel=str(payload.get("channel") or ""),
            product_group=str(payload.get("product_group") or ""),
            selected_product_name=str(payload.get("selected_product_name") or ""),
            selected_product_id=str(payload.get("selected_product_id") or ""),
            source_type=str(payload.get("source_type") or ""),
            model=str(payload.get("llm_model") or ""),
            content_text=str(payload.get("content_text") or ""),
            actor=str(payload.get("actor") or ""),
            workspace_id=str(payload.get("workspace_id") or ""),
            language=str(payload.get("language") or "ko"),
        )
        return jsonable
    except ServiceUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "neo4j_unavailable",
                "message": "Neo4j is unavailable or DNS/network resolution failed.",
                "cause": str(exc),
            },
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "neo4j_auth_failed",
                "message": "Neo4j authentication failed. Check NEO4J_USER and NEO4J_PASSWORD.",
            },
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=openai_error_detail("openai_auth_failed", exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=openai_error_detail("openai_rate_limited", exc)) from exc
    except BadRequestError as exc:
        detail = openai_error_detail("openai_bad_request", exc)
        if "model" in str(exc).lower():
            detail["message"] = "OpenAI rejected the request. Check OPENAI_MODEL and structured-output support."
        raise HTTPException(status_code=400, detail=detail) from exc
    except APIConnectionError as exc:
        raise HTTPException(status_code=503, detail=openai_error_detail("openai_connection_failed", exc)) from exc
    except APIStatusError as exc:
        raise HTTPException(status_code=exc.status_code, detail=openai_error_detail("openai_api_error", exc)) from exc
    except RuntimeError as exc:
        detail = runtime_error_detail(exc)
        raise HTTPException(status_code=detail.pop("status_code"), detail=detail) from exc


@app.post("/api/review/stream")
def review_stream(payload: dict[str, Any]) -> StreamingResponse:
    def event_lines():
        event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        heartbeat_seconds = float(os.environ.get("CCG_REVIEW_STREAM_HEARTBEAT_SECONDS", "15"))

        def worker() -> None:
            try:
                workflow = workflow_for(payload)
                review_input = review_input_from_payload(payload)
                for event in workflow.review_events(review_input):
                    jsonable = to_jsonable(event)
                    # 결과를 먼저 클라이언트로 보낸다 — 스냅샷 저장(파일+Neo4j)의 지연이나
                    # 실패가 result 전달을 막거나 유실시키지 않도록. record_run은 예외를
                    # 던지지 않지만, 순서 자체로도 결과 전달을 보장한다.
                    event_queue.put(jsonable)
                    if jsonable.get("event") == "result" and isinstance(jsonable.get("result"), dict):
                        record_run(
                            jsonable["result"],
                            title=str(payload.get("title") or ""),
                            channel=str(payload.get("channel") or ""),
                            product_group=str(payload.get("product_group") or ""),
                            selected_product_name=str(payload.get("selected_product_name") or ""),
                            selected_product_id=str(payload.get("selected_product_id") or ""),
                            source_type=str(payload.get("source_type") or ""),
                            model=str(payload.get("llm_model") or ""),
                            content_text=str(payload.get("content_text") or ""),
                            actor=str(payload.get("actor") or ""),
                            workspace_id=str(payload.get("workspace_id") or ""),
                            language=str(payload.get("language") or "ko"),
                        )
            except Exception as exc:  # noqa: BLE001 - converted into a structured stream error below.
                event_queue.put(stream_error_payload(exc))
            finally:
                event_queue.put(None)

        thread = threading.Thread(target=worker, name="graphcompliance-review-stream", daemon=True)
        thread.start()
        last_payload_at = time.monotonic()
        while True:
            try:
                event = event_queue.get(timeout=heartbeat_seconds)
            except queue.Empty:
                yield json.dumps(
                    {
                        "event": "heartbeat",
                        "step": "Review still running",
                        "summary": "긴 분석 단계가 계속 처리 중입니다. 연결 유지를 위해 heartbeat를 보냅니다.",
                        "counts": {"seconds_since_last_event": round(time.monotonic() - last_payload_at, 1)},
                    },
                    ensure_ascii=False,
                ) + "\n"
                continue
            if event is None:
                break
            last_payload_at = time.monotonic()
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(event_lines(), media_type="application/x-ndjson")


def _product_document_node(document_id: str) -> dict[str, Any] | None:
    """Look up a ProductDocument by id in the sandbox Neo4j (holds KH products).

    Web-sourced products (PPCBank KH) live only in the graph, not in the KR
    disclosure CSV, so the reviewer's "상품페이지 보기" needs this fallback.
    Read-only; returns the node's properties or None."""
    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not (uri and user and password):
        return None
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        database = os.environ.get("NEO4J_DATABASE")
        try:
            with (driver.session(database=database) if database else driver.session()) as session:
                rec = session.run(
                    "MATCH (d:ProductDocument {id: $id}) RETURN d ORDER BY d.updated_at DESC LIMIT 1",
                    id=document_id,
                ).single()
                return dict(rec["d"]) if rec else None
        finally:
            driver.close()
    except Exception:  # noqa: BLE001 — a lookup failure just means no fallback.
        return None


def _local_product_doc_path(relative_path: str):
    """Resolve a KH product document's local snapshot under the crawl dir, safely.

    Never uses a client-supplied path — ``relative_path`` comes from the graph
    node. Confirms the resolved file stays inside an allowed root."""
    from pathlib import Path as _Path

    if not relative_path:
        return None
    import unicodedata

    rel = relative_path.replace("\\", "/")
    roots = [(_Path(__file__).resolve().parent / "data" / "cambodia" / "products").resolve()]
    jb = os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT")
    if jb:
        roots.append(_Path(jb).resolve())
    names = [rel, unicodedata.normalize("NFC", rel), unicodedata.normalize("NFD", rel), _Path(rel).name]
    for root in roots:
        for name in names:
            candidate = (root / name).resolve()
            if candidate.exists() and (candidate == root or root in candidate.parents):
                return candidate
    return None


@app.get("/api/product-doc/{document_id}")
def product_doc(document_id: str):
    """Serve/redirect to a product's source document by its document id.

    KR products: a disclosure PDF resolved from the metadata CSV (never from a
    client path) and confirmed to stay inside the disclosure root — served
    inline; the caller appends ``#page=N`` to jump to the cited page. KH
    (PPCBank) products are web-sourced and live only in the graph, so we fall
    back to the ProductDocument node: redirect to its ``source_url`` (the live
    product page), or serve the local crawl snapshot if there is no URL.
    """
    from pathlib import Path as _Path
    from urllib.parse import quote

    from product_facts import load_disclosure_metadata, resolve_document_path

    # 1) KR disclosure CSV (PDF) — unchanged behaviour.
    row = next(
        (item for item in load_disclosure_metadata() if str(item.get("source_id") or "") == document_id),
        None,
    )
    if row is not None:
        path = resolve_document_path(str(row.get("relative_path") or "")).resolve()
        root = _Path(os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT", "")).resolve() if os.environ.get(
            "JB_PRODUCT_DISCLOSURE_ROOT"
        ) else path.parents[2] if len(path.parents) >= 3 else path.parent
        if path.suffix.lower() != ".pdf" or not path.exists():
            raise HTTPException(status_code=404, detail={"error": "document_missing", "message": "PDF not available."})
        if os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT") and root not in path.parents:
            raise HTTPException(status_code=403, detail={"error": "document_outside_root", "message": "Path not allowed."})
        disposition = f"inline; filename*=UTF-8''{quote(str(row.get('file_name') or path.name))}"
        return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": disposition})

    # 2) Graph-backed product document (KH / web-sourced products).
    doc = _product_document_node(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail={"error": "document_not_found", "message": "Unknown document id."})

    source_url = str(doc.get("source_url") or "").strip()
    if source_url.startswith(("http://", "https://")):
        # The "product page" for a web-sourced product is the live page itself.
        return RedirectResponse(source_url, status_code=307)

    local = _local_product_doc_path(str(doc.get("relative_path") or doc.get("file_name") or ""))
    if local is not None:
        ext = local.suffix.lower()
        media = {".pdf": "application/pdf", ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8"}.get(
            ext, "text/plain; charset=utf-8"
        )
        disposition = f"inline; filename*=UTF-8''{quote(str(doc.get('file_name') or local.name))}"
        return FileResponse(local, media_type=media, headers={"Content-Disposition": disposition})

    raise HTTPException(
        status_code=404,
        detail={"error": "document_missing", "message": "No source URL or local snapshot for this product document."},
    )


@app.get("/api/runs")
def runs(limit: int = 100) -> dict[str, Any]:
    """운영 대시보드용 최근 실행 요약 목록(최신순)."""
    return {"runs": list_runs(limit=limit)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    """저장된 실행의 시점 데이터(전체 ReviewOutput) — 디버깅용."""
    output = load_run(run_id)
    if output is None:
        raise HTTPException(status_code=404, detail={"error": "run_not_found", "message": "Unknown review run id."})
    return output


@app.post("/api/copilot")
def copilot(payload: dict[str, Any]) -> dict[str, Any]:
    """심사 결과 설명 챗 (읽기 전용 도구만 호출 — 심사 실행/데이터 변경 불가).

    payload: {messages: [{role, content}], context?: {run_id, workspace_id}}
    반환: {reply, tool_calls: [{name, arguments}]}
    """
    from copilot_tools import run_copilot_chat

    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": "messages is required."})
    context = payload.get("context") if isinstance(payload.get("context"), dict) else None
    try:
        return run_copilot_chat(messages, context=context)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=openai_error_detail("openai_auth_failed", exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=openai_error_detail("openai_rate_limited", exc)) from exc
    except APIConnectionError as exc:
        raise HTTPException(status_code=503, detail=openai_error_detail("openai_connection_failed", exc)) from exc
    except RuntimeError as exc:
        detail = runtime_error_detail(exc)
        raise HTTPException(status_code=detail.pop("status_code"), detail=detail) from exc


@app.get("/")
def console() -> FileResponse:
    return FileResponse(CONSOLE_DIR / "index.html")


app.mount("/console", StaticFiles(directory=CONSOLE_DIR), name="console")


def openai_error_detail(code: str, exc: Exception) -> dict[str, Any]:
    return {
        "error": code,
        "message": friendly_openai_message(code, exc),
        "cause": str(exc),
    }


def friendly_openai_message(code: str, exc: Exception) -> str:
    text = str(exc)
    if "insufficient_quota" in text:
        return "OpenAI quota or billing is insufficient for this API key."
    if code == "openai_rate_limited":
        return "OpenAI rate limit or quota blocked the LLM call."
    if code == "openai_auth_failed":
        return "OpenAI authentication failed. Check OPENAI_API_KEY."
    if code == "openai_connection_failed":
        return "OpenAI network connection failed."
    return "OpenAI API request failed."


def stream_error_event(code: str, detail: dict[str, Any]) -> str:
    return json.dumps(stream_error_dict(code, detail), ensure_ascii=False) + "\n"


def stream_error_dict(code: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": "error",
        "step": "Error",
        "summary": detail.get("message") or code,
        "error": code,
        "detail": detail,
    }


def stream_error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ServiceUnavailable):
        return stream_error_dict("neo4j_unavailable", {
            "error": "neo4j_unavailable",
            "message": "Neo4j is unavailable or DNS/network resolution failed.",
            "cause": str(exc),
        })
    if isinstance(exc, AuthError):
        return stream_error_dict("neo4j_auth_failed", {
            "error": "neo4j_auth_failed",
            "message": "Neo4j authentication failed. Check NEO4J_USER and NEO4J_PASSWORD.",
            "cause": str(exc),
        })
    if isinstance(exc, AuthenticationError):
        return stream_error_dict("openai_auth_failed", openai_error_detail("openai_auth_failed", exc))
    if isinstance(exc, RateLimitError):
        return stream_error_dict("openai_rate_limited", openai_error_detail("openai_rate_limited", exc))
    if isinstance(exc, BadRequestError):
        detail = openai_error_detail("openai_bad_request", exc)
        if "model" in str(exc).lower():
            detail["message"] = "OpenAI rejected the request. Check OPENAI_MODEL and structured-output support."
        return stream_error_dict("openai_bad_request", detail)
    if isinstance(exc, APIConnectionError):
        return stream_error_dict("openai_connection_failed", openai_error_detail("openai_connection_failed", exc))
    if isinstance(exc, APIStatusError):
        detail = openai_error_detail("openai_api_error", exc)
        detail["status_code"] = exc.status_code
        return stream_error_dict("openai_api_error", detail)
    if isinstance(exc, RuntimeError):
        detail = runtime_error_detail(exc)
        return stream_error_dict(str(detail.get("error") or "review_runtime_error"), detail)
    return stream_error_dict("review_runtime_error", {
        "error": "review_runtime_error",
        "message": "Review workflow failed.",
        "cause": str(exc),
    })


def runtime_error_detail(exc: RuntimeError) -> dict[str, Any]:
    message = str(exc)
    if "unknown PolicyHypernym id" in message:
        return {
            "status_code": 422,
            "error": "policy_normalization_failed",
            "message": (
                "LLM returned a PolicyHypernym id that is not in the approved Neo4j vocabulary. "
                "Re-run vocabulary governance or inspect the policy_context_for_claims result."
            ),
            "cause": message,
        }
    if "PolicyHypernym vocabulary is empty" in message:
        return {
            "status_code": 503,
            "error": "policy_vocabulary_missing",
            "message": "PolicyHypernym vocabulary is empty. Run the policy compiler before review.",
            "cause": message,
        }
    if "Policy alignment graph is missing" in message or "Policy alignment graph is not ready" in message:
        return {
            "status_code": 503,
            "error": "policy_alignment_missing",
            "message": (
                "Policy alignment graph is missing or incomplete. Run policy_compiler.py and "
                "vocabulary_governance.py for this workspace before review."
            ),
            "cause": message,
        }
    if "No embedded Premise nodes found" in message:
        return {
            "status_code": 503,
            "error": "policy_premise_embeddings_missing",
            "message": "Embedded Premise nodes are missing. Run policy_compiler.py before review.",
            "cause": message,
        }
    if "OPENAI_API_KEY is required" in message:
        return {
            "status_code": 503,
            "error": "openai_key_missing",
            "message": "OPENAI_API_KEY is required for LLM-only review.",
            "cause": message,
        }
    return {
        "status_code": 500,
        "error": "review_runtime_error",
        "message": "Review workflow failed before a verdict could be produced.",
        "cause": message,
    }
