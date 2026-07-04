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
        # OpenAI embeddings 는 빈 문자열을 400 으로 거부한다. 빈 텍스트가 여기까지
        # 온 것은 상류(빈 문안·빈 anchor)의 논리 오류이므로, 알아볼 수 없는 provider
        # 400 대신 어디가 비었는지 짚어주는 명시적 오류로 실패시킨다(no fallback).
        empty_indexes = [i for i, text in enumerate(texts) if not str(text).strip()]
        if empty_indexes:
            raise ValueError(
                f"embed_many received empty text at index {empty_indexes[:5]} of {len(texts)} — "
                "심사 입력(광고 문안/anchor)이 비어 있습니다."
            )
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [list(item.embedding) for item in response.data]
