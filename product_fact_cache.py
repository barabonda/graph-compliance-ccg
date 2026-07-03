"""Preloaded ProductFact cache for deployable review runs.

Runtime ProductFact extraction reads local product PDFs. That is useful in a
developer machine, but brittle in a deployed service where those PDFs may not be
mounted. This module provides a small JSONL cache contract so selected demo
products can ship with already-extracted facts.
"""

from __future__ import annotations

import json
import os
import unicodedata
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_PRODUCT_FACT_CACHE_PATH = Path(__file__).resolve().parent / "data" / "preloaded_product_facts.jsonl"
SOURCE = "graphcompliance_ccg_preloaded_product_fact"


def product_fact_cache_path() -> Path:
    return Path(os.environ.get("CCG_PRODUCT_FACT_CACHE_PATH", str(DEFAULT_PRODUCT_FACT_CACHE_PATH)))


def normalize_product_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", unicodedata.normalize("NFC", value or ""))
    return "".join(normalized.lower().split())


@lru_cache(maxsize=8)
def load_product_fact_cache(path_text: str | None = None) -> tuple[dict[str, Any], ...]:
    path = Path(path_text) if path_text else product_fact_cache_path()
    if not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return tuple(rows)


def find_preloaded_product_facts(product_name: str, *, workspace_id: str = "") -> dict[str, Any] | None:
    product_key = normalize_product_key(product_name)
    if not product_key:
        return None
    for row in load_product_fact_cache(str(product_fact_cache_path())):
        cached_workspace = str(row.get("workspace_id") or "")
        if workspace_id and cached_workspace and cached_workspace != workspace_id:
            continue
        aliases = [
            str(row.get("product_name") or ""),
            *(str(alias) for alias in row.get("aliases", []) or []),
        ]
        if product_key in {normalize_product_key(alias) for alias in aliases if alias}:
            return dict(row)
    return None


def append_product_fact_bundle(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "source": SOURCE,
        "generated_at": datetime.now(UTC).isoformat(),
        **bundle,
    }
    existing = [
        item
        for item in load_product_fact_cache(str(path))
        if normalize_product_key(str(item.get("product_name") or ""))
        != normalize_product_key(str(bundle.get("product_name") or ""))
    ]
    with path.open("w", encoding="utf-8") as handle:
        for item in existing:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    load_product_fact_cache.cache_clear()
