"""Display-only reference translation for non-KR (e.g. Cambodia) reviews.

판정 파이프라인 밖의 표시 전용 레이어 — 원문·판정에는 절대 개입하지 않는다.
KH 심사 콘솔은 원문(영어)과 함께 3개 언어(EN·KM·KO)를 병기한다: 현지 소비자
언어(크메르어), 판정 언어(영어), 그리고 한국 심사자·발표 청중용 한국어.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from llm_gateway import LLMGateway
from utils import content_hash, uses_korean_law_context

LOGGER = logging.getLogger(__name__)

# 이 모듈은 비-KR(영어 우선) 워크스페이스에서만 동작한다(KR은 None 반환) —
# 노출 문구도 그 관할의 언어(영어)로 쓴다.
TRANSLATION_NOTE = "Reference translation — judgments are based on the original text"

_SENTENCE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "en": {"type": "string"},
        "km": {"type": "string"},
        "ko": {"type": "string"},
    },
    "required": ["en", "km", "ko"],
}

TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "en": {"type": "string", "description": "Faithful English translation of the full ad text."},
        "km": {"type": "string", "description": "Faithful Khmer (Cambodian) translation of the full ad text."},
        "ko": {"type": "string", "description": "Faithful Korean translation of the full ad text."},
        "sentences": {
            "type": "array",
            "description": "Per-sentence aligned translations, SAME order and count as the input sentence list.",
            "items": _SENTENCE_ITEM,
        },
        "revisions": {
            "type": "array",
            "description": "Aligned translations for the [revisions] list (corrected ad copy lines), SAME order and count.",
            "items": _SENTENCE_ITEM,
        },
    },
    "required": ["en", "km", "ko", "sentences", "revisions"],
}

_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()


def _aligned_rows(rows: list[Any], originals: list[str], *, what: str) -> list[dict[str, Any]] | None:
    """LLM 정렬 배열 → [{original, en, km, ko}]. 개수 불일치는 표시 생략(경고)."""
    if not originals:
        return None
    if len(rows) != len(originals):
        if rows:
            LOGGER.warning(
                "ad_translation %s count mismatch (%d in, %d out) — omitting per-line display",
                what, len(originals), len(rows),
            )
        return None
    return [
        {
            "original": originals[i],
            "en": str(rows[i].get("en") or "").strip() or None,
            "km": str(rows[i].get("km") or "").strip() or None,
            "ko": str(rows[i].get("ko") or "").strip() or None,
        }
        for i in range(len(originals))
    ]


def translate_ad_for_display(
    llm: LLMGateway,
    content_text: str,
    workspace_id: str,
    sentence_texts: list[str] | None = None,
    revision_texts: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return {en, km, ko, sentences, revisions, note} for non-KR workspaces, or None for KR.

    ``sentences``/``revisions`` are aligned lists [{original, en, km, ko}] following
    the pipeline's own segmentation, so the console can interleave the three
    reference languages right under each original/corrected line. Display only.
    """
    if uses_korean_law_context(workspace_id):
        return None
    text = (content_text or "").strip()
    sentences = [s.strip() for s in (sentence_texts or []) if s and s.strip()]
    # 수정문(교정안) 줄 — diff의 + 줄에 3개 언어를 병기하기 위한 번역 대상.
    revisions = []
    seen_rev: set[str] = set()
    for item in revision_texts or []:
        line = str(item or "").strip()
        if not line or line in seen_rev:
            continue
        seen_rev.add(line)
        revisions.append(line)
    revisions = revisions[:40]
    empty: dict[str, Any] = {"en": None, "km": None, "ko": None, "sentences": None, "revisions": None, "note": TRANSLATION_NOTE}
    if not text:
        return dict(empty)

    key = content_hash(text + "\x00" + "\x00".join(sentences) + "\x01" + "\x00".join(revisions))
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None:
        return dict(cached)

    translations = dict(empty)
    try:
        numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
        numbered_revisions = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(revisions))
        result = llm.structured(
            name="graphcompliance_ad_reference_translation",
            schema=TRANSLATION_SCHEMA,
            system=(
                "You translate advertisement copy for compliance reviewers. Translate the given ad text "
                "faithfully into English (en), Khmer (km, Cambodian), AND Korean (ko). Preserve meaning, "
                "numbers, rates, conditions and disclaimers exactly; do not soften, embellish or omit "
                "anything. If the original already is in one of the target languages, return it unchanged "
                "for that language. Also translate EACH numbered line in [sentences] and [revisions] "
                "individually — return each array in the SAME order with the SAME count (empty array if "
                "the input list is '(none)'). Reference display only — never add commentary."
            ),
            user=(
                f"[ad_text]\n{text}\n\n"
                f"[sentences]\n{numbered if sentences else '(none)'}\n\n"
                f"[revisions]\n{numbered_revisions if revisions else '(none)'}"
            ),
        )
        translations["en"] = str(result.get("en") or "").strip() or None
        translations["km"] = str(result.get("km") or "").strip() or None
        translations["ko"] = str(result.get("ko") or "").strip() or None
        translations["sentences"] = _aligned_rows(result.get("sentences") or [], sentences, what="sentence")
        translations["revisions"] = _aligned_rows(result.get("revisions") or [], revisions, what="revision")
        with _cache_lock:
            _cache[key] = dict(translations)
    except Exception as exc:  # noqa: BLE001 — 번역 실패가 심사를 막으면 안 된다.
        LOGGER.warning("ad_translation failed (review continues, values stay null) err=%s", exc)
    return translations
