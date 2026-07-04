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
    from anthropic import BadRequestError as AnthropicBadRequestError
except ImportError:  # pragma: no cover - exercised by runtime error path.
    Anthropic = None  # type: ignore[assignment]
    AnthropicBadRequestError = None  # type: ignore[assignment, misc]


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


def _anthropic_client() -> Any:
    if Anthropic is None:
        raise RuntimeError(
            "anthropic package is required for Claude review models. Install anthropic or choose an OpenAI/local model."
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required for Claude review models; no fallback is available.")
    return Anthropic(timeout=_anthropic_timeout_seconds(), max_retries=_anthropic_max_retries())


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
            self.client = _anthropic_client()
            self.mode = "anthropic"
            self.model = target_model
            LOGGER.info("llm.gateway mode=anthropic model=%s", self.model)

        self._client_injected = client is not None
        self._override_clients: dict[str, Any] = {}

        if client is not None:
            # Injected client (tests / custom): keep the Responses contract as-is.
            self.client = client
            self.mode = "responses"
            self.model = requested or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        elif requested in LOCAL_MODELS:
            # 선택한 모델이 로컬 태그면 provider도 로컬로(클라우드 기본 모드여도).
            _make_local(requested)
        elif provider == "anthropic" or _is_anthropic_model(requested):
            _make_anthropic(requested or os.environ.get("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL))
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

    def _mode_for_model(self, effective_model: str) -> str:
        """per-call 모델 오버라이드의 provider를 대칭적으로 재해석한다.

        claude-*는 anthropic으로, 로컬 태그는 로컬(chat)로. provider를 특정하지
        않는 모델(OpenAI 계열)이 anthropic 게이트웨이에 오버라이드로 들어오면
        OpenAI 경로로 돌려보낸다(전역 로컬 토글이 있으면 로컬로). 주입된
        클라이언트(테스트/커스텀)는 절대 우회하지 않는다.
        """
        if self._client_injected:
            return self.mode
        if _is_anthropic_model(effective_model):
            return "anthropic"
        if effective_model in LOCAL_MODELS:
            return "chat"
        if self.mode == "anthropic":
            return "chat" if _local_base_url() else "responses"
        return self.mode

    def _client_for(self, mode: str) -> Any:
        if mode == self.mode:
            return self.client
        cached = self._override_clients.get(mode)
        if cached is not None:
            return cached
        if mode == "anthropic":
            cached = _anthropic_client()
        elif mode == "chat":
            local_base = _local_base_url()
            if not local_base:
                raise RuntimeError(
                    "로컬 모델 오버라이드인데 로컬 LLM 엔드포인트가 설정되지 않았습니다 "
                    "(LOCAL_LLM_BASE_URL 또는 LLM_BASE_URL)."
                )
            cached = OpenAI(
                base_url=local_base,
                api_key=_local_api_key(),
                timeout=_timeout_seconds(),
                max_retries=_max_retries(),
            )
        else:
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError(
                    "OPENAI_API_KEY is required to route this model override to OpenAI; "
                    "no fallback is available."
                )
            cached = OpenAI(timeout=_timeout_seconds(), max_retries=_max_retries())
        self._override_clients[mode] = cached
        return cached

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
        effective_model = _canonical_model_name(model or self.model)
        effective_mode = self._mode_for_model(effective_model)
        LOGGER.info(
            "llm.structured.start name=%s mode=%s model=%s system_chars=%d user_chars=%d",
            name,
            effective_mode,
            effective_model,
            len(system),
            len(user),
        )
        client = self._client_for(effective_mode)
        client = client.with_options(timeout=timeout_seconds) if timeout_seconds else client
        if effective_mode == "chat":
            output_text = self._chat_structured(client, name, system, user, schema, effective_model)
            status = "completed"
            response_id = None
        elif effective_mode == "anthropic":
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
        if isinstance(parsed, dict):
            # 비-strict tool-use 에서 Claude 가 배열/객체 필드를 JSON "문자열"로
            # 이중 인코딩해 반환하는 경우가 있다 — 스키마가 array/object 라고
            # 선언한 최상위 필드만 되풀어 준다(정상 문자열 필드는 건드리지 않음).
            for key, spec in ((schema or {}).get("properties") or {}).items():
                value = parsed.get(key)
                if isinstance(value, str) and spec.get("type") in ("array", "object"):
                    try:
                        parsed[key] = json.loads(value)
                        LOGGER.warning("llm.structured.coerced_stringified_json name=%s key=%s", name, key)
                    except json.JSONDecodeError:
                        pass
                # 배열 자리에 {"<key>": [...]} 처럼 한 겹 더 감싼 dict 가 오는 경우:
                # 내부의 유일한 리스트로 풀어 준다.
                value = parsed.get(key)
                if isinstance(value, dict) and spec.get("type") == "array":
                    inner_lists = [item for item in value.values() if isinstance(item, list)]
                    if len(inner_lists) == 1:
                        parsed[key] = inner_lists[0]
                        LOGGER.warning("llm.structured.unwrapped_nested_array name=%s key=%s", name, key)
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
        request: dict[str, Any] = {
            "model": effective_model,
            "max_tokens": _anthropic_max_output_tokens(),
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [
                {
                    "name": tool_name,
                    "description": "Return the requested structured JSON object for the compliance workflow.",
                    # strict: 스키마를 문법 수준으로 강제 — enum(승인 어휘)·required·타입
                    # 이탈을 원천 차단한다. OpenAI Responses 의 strict json_schema 와 등가.
                    "input_schema": _anthropic_strict_schema(schema),
                    "strict": True,
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
        }
        # Claude 4.6+ 계열(Sonnet 5·Opus 4.7/4.8·Fable 5)은 temperature 등 샘플링
        # 파라미터를 400으로 거부한다 — 보내지 않는다. 또한 Sonnet 5는 thinking이
        # 기본 on인데 강제 tool_choice와 함께 쓸 수 없어 명시적으로 끈다.
        # (Fable 5는 thinking을 끌 수 없어 disabled 자체가 400 — thinking을 생략한다.
        #  Fable에서 강제 tool_choice가 거부되면 structured output 경로 재설계 필요.)
        if not effective_model.startswith("claude-fable"):
            request["thinking"] = {"type": "disabled"}
        try:
            response = _anthropic_stream_final(client, request)
        except AnthropicBadRequestError as exc:
            # 스키마가 크거나 복잡하면(예: 추출 단계) strict 문법 컴파일이 거부된다
            # ("grammar is too large" / "Schema is too complex for compilation" 등).
            # 그 호출만 비-strict 로 재시도 — enum 강제가 필요한 normalizer 류의
            # 작은 스키마는 strict 혜택을 그대로 유지한다.
            message = str(exc).lower()
            if not any(marker in message for marker in ("grammar is too large", "too complex", "strict tools")):
                raise
            LOGGER.warning(
                "llm.anthropic strict grammar too large; retrying non-strict name=%s model=%s",
                name,
                effective_model,
            )
            request["tools"][0].pop("strict", None)
            request["tools"][0]["input_schema"] = schema
            # 비-strict에서는 required/enum이 문법으로 강제되지 않으므로 스키마를
            # 프롬프트에도 명시해 형태 이탈(키 누락·문자열 항목·미승인 id)을 줄인다.
            request["system"] = (
                system
                + "\n\nThe tool input MUST be a JSON object that conforms exactly to this JSON Schema "
                + "(all required keys present, only allowed enum values):\n"
                + json.dumps(schema, ensure_ascii=False)
            )
            response = _anthropic_stream_final(client, request)
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            # 잘린 tool input은 파싱은 되지만 필수 키/판정 항목이 유실된 채로
            # 저장되므로, 조용히 통과시키지 않고 실패시킨다.
            raise RuntimeError(
                f"Claude response truncated at max_tokens for {tool_name}; "
                "increase CCG_ANTHROPIC_MAX_OUTPUT_TOKENS or shorten the input."
            )
        if stop_reason == "refusal":
            raise RuntimeError(f"Model refusal: Claude declined the {tool_name} request (stop_reason=refusal).")
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


def _anthropic_stream_final(client: Any, request: dict[str, Any]) -> Any:
    """스트리밍 호출로 최종 메시지를 얻는다.

    cu_judgment 처럼 입력이 수십만 자인 요청을 non-streaming 으로 보내면
    Anthropic 이 장시간 연결을 드랍한다(~10분 한계, 'Request timed out or
    interrupted'). 스트리밍은 토큰이 계속 흐르는 동안 연결이 유지되므로
    대형 판정 요청도 안정적으로 완료된다. 반환 Message 는 create() 와 동일.
    """
    with client.messages.stream(**request) as stream:
        return stream.get_final_message()


# Claude strict tool-use 가 지원하지 않는 JSON Schema 제약 키워드.
# (수치/길이 제약은 미지원 — 값 범위 가드는 소비자 코드가 담당, 예: normalize_judgment_score)
_ANTHROPIC_UNSUPPORTED_SCHEMA_KEYS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "minItems",
    "maxItems",
    "uniqueItems",
    "pattern",
}


def _anthropic_strict_schema(schema: Any) -> Any:
    """strict tool-use 용 스키마 사본 — 미지원 제약 키워드만 제거.

    additionalProperties:false·전체 required 는 이미 OpenAI strict 경로용으로
    충족돼 있으므로 손대지 않는다. enum(예: 승인된 hypernym_id 목록)은 유지되어
    문법 수준에서 강제된다 — 비-strict 에서 Claude 가 enum 밖 id 를 반환해
    policy_normalization_failed 가 났던 원인 봉쇄.
    """
    if isinstance(schema, dict):
        return {
            key: _anthropic_strict_schema(value)
            for key, value in schema.items()
            if key not in _ANTHROPIC_UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(schema, list):
        return [_anthropic_strict_schema(value) for value in schema]
    return schema


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
