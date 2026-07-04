"""Reference-only ad translation for non-KR workspaces (display only).

Korean reviewers also review overseas (e.g. Khmer/English) ad copy, so the
console shows English/Korean reference translations under the original text.

Hard rules:
- Display only. The translation is NEVER fed into the judging pipeline
  (extraction/normalization/retrieval/judgment/revision all read the original).
- Non-KR workspaces only (reuses env ``CCG_NON_KR_LAW_WORKSPACES`` via
  ``utils.uses_korean_law_context``). KR responses keep ``ad_translations=None``.
- Best-effort: any LLM failure leaves the values ``None`` and the review
  proceeds untouched.
- Same original text is not re-translated (process-local cache keyed by the
  original's content hash).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from llm_gateway import LLMGateway
from utils import content_hash, uses_korean_law_context

LOGGER = logging.getLogger(__name__)

TRANSLATION_NOTE = "참고용 번역 — 심사 근거는 원문 기준"

TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "en": {"type": "string", "description": "Faithful English translation of the full ad text."},
        "ko": {"type": "string", "description": "광고 전문의 충실한 한국어 번역."},
        "sentences": {
            "type": "array",
            "description": "Per-sentence aligned translations, SAME order and count as the input sentence list.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "en": {"type": "string"},
                    "ko": {"type": "string"},
                },
                "required": ["en", "ko"],
            },
        },
    },
    "required": ["en", "ko", "sentences"],
}

_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()


def translate_ad_for_display(
    llm: LLMGateway,
    content_text: str,
    workspace_id: str,
    sentence_texts: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return {en, ko, sentences, note} for non-KR workspaces, or None for KR.

    ``sentences`` is a per-sentence aligned list [{original, en, ko}] following the
    review pipeline's own sentence segmentation (sentence_units), so the console
    can interleave EN/KO right under each original sentence. Display only.
    """
    if uses_korean_law_context(workspace_id):
        return None
    text = (content_text or "").strip()
    sentences = [s.strip() for s in (sentence_texts or []) if s and s.strip()]
    if not text:
        return {"en": None, "ko": None, "sentences": None, "note": TRANSLATION_NOTE}

    key = content_hash(text + "\x00" + "\x00".join(sentences))
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return dict(cached)

    translations: dict[str, Any] = {"en": None, "ko": None, "sentences": None, "note": TRANSLATION_NOTE}
    try:
        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
        result = llm.structured(
            name="graphcompliance_ad_reference_translation",
            schema=TRANSLATION_SCHEMA,
            system=(
                "You translate advertisement copy for compliance reviewers. Translate the given ad text "
                "faithfully into BOTH English (en) and Korean (ko). Preserve meaning, numbers, rates, "
                "conditions and disclaimers exactly; do not soften, embellish or omit anything. If the "
                "original already is in one of the target languages, return it unchanged for that language. "
                "Also translate EACH numbered sentence in [sentences] individually — return the 'sentences' "
                "array in the SAME order with the SAME count. Reference display only — never add commentary."
            ),
            user=f"[ad_text]\n{text}\n\n[sentences]\n{numbered if sentences else '(none)'}",
        )
        en = str(result.get("en") or "").strip()
        ko = str(result.get("ko") or "").strip()
        translations["en"] = en or None
        translations["ko"] = ko or None
        rows = result.get("sentences") or []
        if sentences and len(rows) == len(sentences):
            translations["sentences"] = [
                {
                    "original": sentences[i],
                    "en": str(rows[i].get("en") or "").strip() or None,
                    "ko": str(rows[i].get("ko") or "").strip() or None,
                }
                for i in range(len(sentences))
            ]
        elif rows:
            LOGGER.warning(
                "ad_translation sentence count mismatch (%d in, %d out) — falling back to whole-text only",
                len(sentences), len(rows),
            )
        with _cache_lock:
            _cache[key] = dict(translations)
    except Exception as exc:  # noqa: BLE001 — 번역 실패가 심사를 막으면 안 된다.
        LOGGER.warning("ad_translation failed (review continues, values stay null) err=%s", exc)
    return translations
