"""LLM-only structured-output gateway for GraphCompliance CCG.

This module intentionally has no deterministic fallback. If the LLM environment
is not configured, the review run should fail fast instead of silently replacing
policy-guided context engineering with rules.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "gpt-5.4-nano"
LOGGER = logging.getLogger(__name__)


class LLMGateway:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        if client is None and not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for graph-compliance-ccg; no fallback is available.")
        # Without an explicit timeout the SDK waits up to 600s per request
        # (x retries) on a stalled connection, freezing workflow steps that
        # are designed to degrade on failure (e.g. product fact extraction).
        self.client = client or OpenAI(
            timeout=float(os.environ.get("CCG_OPENAI_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.environ.get("CCG_OPENAI_MAX_RETRIES", "1")),
        )
        self.model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

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
            "llm.structured.start name=%s model=%s system_chars=%d user_chars=%d",
            name,
            effective_model,
            len(system),
            len(user),
        )
        client = self.client.with_options(timeout=timeout_seconds) if timeout_seconds else self.client
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
        response_received = time.perf_counter()
        output_text = response.output_text
        LOGGER.info(
            "llm.structured.response name=%s status=%s response_id=%s api_seconds=%.2f output_chars=%d",
            name,
            getattr(response, "status", None),
            getattr(response, "id", None),
            response_received - request_started,
            len(output_text),
        )
        if getattr(response, "status", None) == "incomplete":
            raise RuntimeError(f"OpenAI response incomplete: {getattr(response, 'incomplete_details', None)}")
        for output_item in getattr(response, "output", []) or []:
            for content in getattr(output_item, "content", []) or []:
                if getattr(content, "type", None) == "refusal":
                    raise RuntimeError(f"Model refusal: {getattr(content, 'refusal', '')}")
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
