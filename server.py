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
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from neo4j.exceptions import AuthError, ServiceUnavailable
from openai import APIConnectionError, APIStatusError, AuthenticationError, BadRequestError, RateLimitError

from env_loader import load_local_env
from llm_gateway import LLMGateway
from run_store import list_runs, load_run, record_run
from workflow import GraphComplianceCCGWorkflow, review_input_from_payload
from utils import to_jsonable


load_local_env(Path.cwd() / ".env")
logging.basicConfig(
    level=getattr(logging, os.environ.get("CCG_LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
app = FastAPI(title="GraphCompliance CCG", version="0.1.0")
CONSOLE_DIR = Path(__file__).resolve().parent / "console"


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
            model=str(payload.get("llm_model") or ""),
            content_text=str(payload.get("content_text") or ""),
            actor=str(payload.get("actor") or ""),
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
                    if jsonable.get("event") == "result" and isinstance(jsonable.get("result"), dict):
                        record_run(
                            jsonable["result"],
                            title=str(payload.get("title") or ""),
                            channel=str(payload.get("channel") or ""),
                            product_group=str(payload.get("product_group") or ""),
                            model=str(payload.get("llm_model") or ""),
                            content_text=str(payload.get("content_text") or ""),
                            actor=str(payload.get("actor") or ""),
                        )
                    event_queue.put(jsonable)
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


@app.get("/api/product-doc/{document_id}")
def product_doc(document_id: str) -> FileResponse:
    """Serve a JB product disclosure PDF by its document id (source_id).

    The reviewer needs to verify the original document. We resolve the path
    from the disclosure metadata (never from a client-supplied path) and
    confirm the resolved file stays inside the disclosure root and is a PDF,
    so this cannot be used for path traversal. The browser PDF viewer opens
    inline; the caller appends `#page=N` to jump to the cited page.
    """
    from pathlib import Path as _Path

    from product_facts import load_disclosure_metadata, resolve_document_path

    row = next(
        (item for item in load_disclosure_metadata() if str(item.get("source_id") or "") == document_id),
        None,
    )
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "document_not_found", "message": "Unknown document id."})

    path = resolve_document_path(str(row.get("relative_path") or "")).resolve()
    root = _Path(os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT", "")).resolve() if os.environ.get(
        "JB_PRODUCT_DISCLOSURE_ROOT"
    ) else path.parents[2] if len(path.parents) >= 3 else path.parent
    if path.suffix.lower() != ".pdf" or not path.exists():
        raise HTTPException(status_code=404, detail={"error": "document_missing", "message": "PDF not available."})
    if os.environ.get("JB_PRODUCT_DISCLOSURE_ROOT") and root not in path.parents:
        raise HTTPException(status_code=403, detail={"error": "document_outside_root", "message": "Path not allowed."})

    # Korean filenames can't go in a latin-1 HTTP header; RFC 5987 encode them
    # and keep the disposition inline so the browser PDF viewer opens it.
    from urllib.parse import quote

    disposition = f"inline; filename*=UTF-8''{quote(str(row.get('file_name') or path.name))}"
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": disposition})


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
