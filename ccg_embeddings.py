"""OpenAI embedding gateway for policy-guided CU retrieval.

There is intentionally no local or deterministic fallback. If embeddings are
required and the OpenAI environment is missing, retrieval fails fast.
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


DEFAULT_EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


class EmbeddingGateway:
    def __init__(self, *, model: str = DEFAULT_EMBEDDING_MODEL, client: Any | None = None) -> None:
        if client is None and not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for graph-compliance-ccg embeddings; no fallback is available.")
        self.client = client or OpenAI()
        self.model = model

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [list(item.embedding) for item in response.data]
