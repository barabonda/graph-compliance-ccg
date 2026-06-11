"""LLM-only structured-output gateway for GraphCompliance CCG.

This module intentionally has no deterministic fallback. If the LLM environment
is not configured, the review run should fail fast instead of silently replacing
policy-guided context engineering with rules.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "gpt-5.4-nano"


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

    def structured(self, *, name: str, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        response = self.client.responses.create(
            model=self.model,
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
        if getattr(response, "status", None) == "incomplete":
            raise RuntimeError(f"OpenAI response incomplete: {getattr(response, 'incomplete_details', None)}")
        for output_item in getattr(response, "output", []) or []:
            for content in getattr(output_item, "content", []) or []:
                if getattr(content, "type", None) == "refusal":
                    raise RuntimeError(f"Model refusal: {getattr(content, 'refusal', '')}")
        return json.loads(response.output_text)
