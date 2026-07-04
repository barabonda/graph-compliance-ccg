"""Shared helpers for stable ids and JSON-friendly dataclasses."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, is_dataclass
from typing import Any


def uses_korean_law_context(workspace_id: str) -> bool:
    """Whether to inject hardcoded Korean-law examples/delegation into judgments.

    Defaults to True for EVERY workspace, so KR (and every existing workspace)
    keeps its exact current behavior — no regression. Workspaces listed in the
    env var ``CCG_NON_KR_LAW_WORKSPACES`` (comma/space separated) return False,
    so their judgment rationale cites only each CU's own ``source_article``
    instead of hardcoded Korean statutes. This is a per-workspace branch, not a
    copy of the shared judging code.
    """
    raw = os.environ.get("CCG_NON_KR_LAW_WORKSPACES", "")
    non_kr = {token.strip() for token in raw.replace(",", " ").split() if token.strip()}
    return workspace_id not in non_kr


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    digest = hashlib.sha256("||".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:length]}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value

