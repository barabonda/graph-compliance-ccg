"""LLM-only structured-output gateway for GraphCompliance CCG.

This module intentionally has no deterministic fallback. If the LLM environment
is not configured, the review run should fail fast instead of silently replacing
policy-guided context engineering with rules.

Three routes, switchable by env/model (no hardcoding):
- Cloud (default): OpenAI Responses API with strict json_schema structured output.
- Anthropic: Claude Messages API with forced tool-use structured output.
- Local: any OpenAI-compatible Chat Completions endpoint (e.g. Ollama on a
  Tailscale host). Set LLM_BASE_URL / LLM_API_KEY / LLM_MODEL to enable. Ollama
  only supports /v1/chat/completions, so this route uses Chat Completions with
  response_format=json_object and injects the JSON Schema into the prompt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from openai import BadRequestError as OpenAIBadRequestError
from openai import OpenAI

try:  # Optional runtime provider. Keep OpenAI/local installs working without it.
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - exercised by runtime error path.
    Anthropic = None  # type: ignore[assignment]


DEFAULT_MODEL = "gpt-5.4-nano"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_LOCAL_MODEL = "ax-4.0-light"
LOGGER = logging.getLogger(__name__)

# 로컬(Ollama) 모델 태그. 이 중 하나가 선택되면 OpenAI가 아니라 로컬 엔드포인트로
# 보낸다 — 클라우드 기본 모드에서도 모델 드롭다운으로 로컬 모델을 쓸 수 있게.
LOCAL_MODELS = {"ax-4.0-light", "midm-2.0-base", "exaone4-32b", "qwen3.5:9b", "gemma4"}
ANTHROPIC_MODELS = {
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
}
ANTHROPIC_MODEL_ALIASES = {
    "fable-5": "claude-fable-5",
    "opus-4.8": "claude-opus-4-8",
    "opus-4.6": "claude-opus-4-6",
    "sonnet-5": "claude-sonnet-5",
    "haiku-4.5": "claude-haiku-4-5-20251001",
}


def _timeout_seconds() -> float:
    return float(os.environ.get("CCG_OPENAI_TIMEOUT_SECONDS", "120"))


def _max_retries() -> int:
    return int(os.environ.get("CCG_OPENAI_MAX_RETRIES", "1"))


def _anthropic_timeout_seconds() -> float:
    return float(os.environ.get("CCG_ANTHROPIC_TIMEOUT_SECONDS", os.environ.get("CCG_OPENAI_TIMEOUT_SECONDS", "120")))


def _anthropic_max_retries() -> int:
    return int(os.environ.get("CCG_ANTHROPIC_MAX_RETRIES", os.environ.get("CCG_OPENAI_MAX_RETRIES", "1")))


def _anthropic_max_output_tokens() -> int:
    return int(os.environ.get("CCG_ANTHROPIC_MAX_OUTPUT_TOKENS", "20000"))


def _local_base_url() -> str:
    return (os.environ.get("LOCAL_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or "").strip()


def _local_api_key() -> str:
    return os.environ.get("LOCAL_LLM_API_KEY") or os.environ.get("LLM_API_KEY") or "ollama"


def _canonical_model_name(model: str) -> str:
    return ANTHROPIC_MODEL_ALIASES.get(model.strip(), model.strip())


def _is_anthropic_model(model: str) -> bool:
    canonical = _canonical_model_name(model)
    return canonical.startswith("claude-") or canonical in ANTHROPIC_MODELS


class LLMGateway:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        requested = _canonical_model_name(model or "")
        global_local = (os.environ.get("LLM_BASE_URL") or "").strip()
        local_base = _local_base_url()
        provider = (os.environ.get("LLM_PROVIDER") or "").strip().lower()

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

        def _make_anthropic(target_model: str) -> None:
            if Anthropic is None:
                raise RuntimeError(
                    "anthropic package is required for Claude review models. "
                    "Install anthropic or choose an OpenAI/local model."
                )
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is required for Claude review models; no fallback is available."
                )
            self.client = Anthropic(timeout=_anthropic_timeout_seconds(), max_retries=_anthropic_max_retries())
            self.mode = "anthropic"
            self.model = target_model
            LOGGER.info("llm.gateway mode=anthropic model=%s", self.model)

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
        elif provider == "anthropic" or _is_anthropic_model(requested):
            _make_anthropic(requested or os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL))
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
        elif self.mode == "anthropic":
            response_id, status, output_text = self._anthropic_structured(client, name, system, user, schema, effective_model)
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
        except OpenAIBadRequestError:
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

    def _anthropic_structured(
        self,
        client: Any,
        name: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        effective_model: str,
    ) -> tuple[str | None, str, str]:
        """Return JSON text from Claude forced tool-use.

        Anthropic Messages does not use OpenAI's `response_format`, so we expose
        the same JSON Schema as a single forced tool input. Claude must populate
        the tool input; if a model unexpectedly returns text, we still parse it
        as strict JSON instead of silently falling back to another model.
        """

        tool_name = _anthropic_tool_name(name)
        response = client.messages.create(
            model=effective_model,
            max_tokens=_anthropic_max_output_tokens(),
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[
                {
                    "name": tool_name,
                    "description": "Return the requested structured JSON object for the compliance workflow.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == tool_name:
                return (
                    getattr(response, "id", None),
                    str(getattr(response, "stop_reason", "tool_use") or "tool_use"),
                    json.dumps(getattr(block, "input", {}), ensure_ascii=False),
                )
        text_parts = [
            getattr(block, "text", "")
            for block in getattr(response, "content", []) or []
            if getattr(block, "type", None) == "text"
        ]
        if not text_parts:
            raise RuntimeError(f"Claude response did not contain tool_use output for {tool_name}.")
        return (
            getattr(response, "id", None),
            str(getattr(response, "stop_reason", "text") or "text"),
            _strip_json_fence("".join(text_parts)),
        )


def _anthropic_tool_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")
    return (cleaned or "structured_output")[:64]


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped[: -3]
        # drop a possible leading 'json' language tag line remnant
        stripped = stripped.removeprefix("json").strip()
    return stripped.strip()
