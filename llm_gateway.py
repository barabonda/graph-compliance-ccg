"""LLM-only structured-output gateway for GraphCompliance CCG.

This module intentionally has no deterministic fallback. If the LLM environment
is not configured, the review run should fail fast instead of silently replacing
policy-guided context engineering with rules.

Two routes, switchable by env (no hardcoding):
- Cloud (default): OpenAI Responses API with strict json_schema structured output.
- Local: any OpenAI-compatible Chat Completions endpoint (e.g. Ollama on a
  Tailscale host). Set LLM_BASE_URL / LLM_API_KEY / LLM_MODEL to enable. Ollama
  only supports /v1/chat/completions, so this route uses Chat Completions with
  response_format=json_object and injects the JSON Schema into the prompt.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from openai import BadRequestError, OpenAI


DEFAULT_MODEL = "gpt-5.4-nano"
DEFAULT_LOCAL_MODEL = "ax-4.0-light"
LOGGER = logging.getLogger(__name__)

# 로컬(Ollama) 모델 태그. 이 중 하나가 선택되면 OpenAI가 아니라 로컬 엔드포인트로
# 보낸다 — 클라우드 기본 모드에서도 모델 드롭다운으로 로컬 모델을 쓸 수 있게.
LOCAL_MODELS = {"ax-4.0-light", "midm-2.0-base", "exaone4-32b", "qwen3.5:9b", "gemma4"}


def _timeout_seconds() -> float:
    return float(os.environ.get("CCG_OPENAI_TIMEOUT_SECONDS", "120"))


def _max_retries() -> int:
    return int(os.environ.get("CCG_OPENAI_MAX_RETRIES", "1"))


def _local_base_url() -> str:
    return (os.environ.get("LOCAL_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or "").strip()


def _local_api_key() -> str:
    return os.environ.get("LOCAL_LLM_API_KEY") or os.environ.get("LLM_API_KEY") or "ollama"


class LLMGateway:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        requested = (model or "").strip()
        global_local = (os.environ.get("LLM_BASE_URL") or "").strip()
        local_base = _local_base_url()

        def _make_local(target_model: str) -> None:
            if not local_base:
                raise RuntimeError(
                    f"'{target_model}'은 로컬 모델인데 로컬 LLM 엔드포인트가 설정되지 않았습니다 "
                    "(LOCAL_LLM_BASE_URL 또는 LLM_BASE_URL)."
                )
            self.client = OpenAI(
                base_url=local_base,
                api_key=_local_api_key(),
                timeout=_timeout_seconds(),
                max_retries=_max_retries(),
            )
            self.mode = "chat"
            self.model = target_model
            LOGGER.info("llm.gateway mode=chat base_url=%s model=%s", local_base, self.model)

        if client is not None:
            # Injected client (tests / custom): keep the Responses contract as-is.
            self.client = client
            self.mode = "responses"
            self.model = requested or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        elif requested in LOCAL_MODELS:
            # 선택한 모델이 로컬 태그면 provider도 로컬로(클라우드 기본 모드여도).
            _make_local(requested)
        elif global_local:
            # 전역 로컬 토글(LLM_BASE_URL) — 모든 요청을 로컬로.
            _make_local(requested or os.environ.get("LLM_MODEL", DEFAULT_LOCAL_MODEL))
        else:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError(
                    "OPENAI_API_KEY is required for graph-compliance-ccg (or set LLM_BASE_URL "
                    "for a local OpenAI-compatible endpoint); no fallback is available."
                )
            # Without an explicit timeout the SDK waits up to 600s per request
            # (x retries) on a stalled connection, freezing workflow steps that
            # are designed to degrade on failure (e.g. product fact extraction).
            self.client = OpenAI(timeout=_timeout_seconds(), max_retries=_max_retries())
            self.mode = "responses"
            self.model = requested or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    def structured(
        self,
        *,
        name: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        timeout_seconds: float | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        request_started = time.perf_counter()
        effective_model = model or self.model
        LOGGER.info(
            "llm.structured.start name=%s mode=%s model=%s system_chars=%d user_chars=%d",
            name,
            self.mode,
            effective_model,
            len(system),
            len(user),
        )
        client = self.client.with_options(timeout=timeout_seconds) if timeout_seconds else self.client
        if self.mode == "chat":
            output_text = self._chat_structured(client, name, system, user, schema, effective_model)
            status = "completed"
            response_id = None
        else:
            response = client.responses.create(
                model=effective_model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": name,
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
            status = getattr(response, "status", None)
            response_id = getattr(response, "id", None)
            if status == "incomplete":
                raise RuntimeError(f"OpenAI response incomplete: {getattr(response, 'incomplete_details', None)}")
            for output_item in getattr(response, "output", []) or []:
                for content in getattr(output_item, "content", []) or []:
                    if getattr(content, "type", None) == "refusal":
                        raise RuntimeError(f"Model refusal: {getattr(content, 'refusal', '')}")
            output_text = response.output_text
        response_received = time.perf_counter()
        LOGGER.info(
            "llm.structured.response name=%s status=%s response_id=%s api_seconds=%.2f output_chars=%d",
            name,
            status,
            response_id,
            response_received - request_started,
            len(output_text),
        )
        parse_started = time.perf_counter()
        parsed = json.loads(output_text)
        parse_finished = time.perf_counter()
        top_level_counts = {
            key: len(value)
            for key, value in parsed.items()
            if isinstance(value, list)
        }
        LOGGER.info(
            "llm.structured.parsed name=%s parse_seconds=%.2f total_seconds=%.2f top_level_counts=%s",
            name,
            parse_finished - parse_started,
            parse_finished - request_started,
            top_level_counts,
        )
        return parsed

    def _chat_structured(
        self,
        client: Any,
        name: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        effective_model: str,
    ) -> str:
        # Ollama-compatible Chat Completions supports schema-enforced structured
        # output via response_format json_schema (grammar-constrained), which
        # holds required keys far better than json_object. Fall back to
        # json_object if the endpoint rejects json_schema.
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            response = client.chat.completions.create(
                model=effective_model,
                messages=messages,
                temperature=0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": schema, "strict": True},
                },
            )
        except BadRequestError:
            LOGGER.warning("llm.chat json_schema unsupported; falling back to json_object name=%s", name)
            messages[0] = {
                "role": "system",
                "content": (
                    f"{system}\n\n[output_contract]\n반드시 아래 JSON Schema를 만족하는 단일 JSON 객체만 "
                    f"출력하세요. 마크다운/설명 금지.\n{json.dumps(schema, ensure_ascii=False)}"
                ),
            }
            response = client.chat.completions.create(
                model=effective_model,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        content = response.choices[0].message.content or ""
        return _strip_json_fence(content)


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped[: -3]
        # drop a possible leading 'json' language tag line remnant
        stripped = stripped.removeprefix("json").strip()
    return stripped.strip()
