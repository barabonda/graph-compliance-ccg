"""Multimodal ad intake and revised-image generation.

두 가지 역할:
1) 이미지 광고 접수 — Claude 비전으로 배너/전단 이미지에서 광고 문안 전체와
   레이아웃(위계) 메모를 추출해 기존 텍스트 심사 파이프라인에 태운다.
   (심사 근거는 항상 추출된 '문안'이며, 추출 결과는 결과 화면에 원본 이미지와
   함께 표시되어 심사자가 대조할 수 있다.)
2) 이미지 수정안 — 심사 후 확정된 교정 문안(corrected copy)을 원본 배너의
   레이아웃·브랜드 톤을 유지한 채 반영한 수정 이미지를 생성한다
   (OpenAI gpt-image-1 edit; env CCG_IMAGE_MODEL로 교체 가능).

정책: 판정 파이프라인 자체는 텍스트 근거로만 동작한다 — 이미지는 입구(추출)와
출구(수정안 렌더링)에서만 쓰여, 그라운딩 규율(조문 인용·근거 추적)이 유지된다.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

try:  # pragma: no cover - optional at import time, required at call time.
    from anthropic import Anthropic
except ImportError:
    Anthropic = None  # type: ignore[assignment]

from openai import OpenAI

LOGGER = logging.getLogger(__name__)

VISION_MODEL_DEFAULT = "claude-sonnet-5"
IMAGE_MODEL_DEFAULT = "gpt-image-2"

# 작은 스키마 — strict 문법 한도 안에서 required/타입이 강제된다.
IMAGE_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "description": "Short campaign/product title visible in the ad (may be empty)."},
        "content_text": {
            "type": "string",
            "description": (
                "ALL advertising copy visible in the image, transcribed verbatim in reading order "
                "(headline first, then body, then fine print), one sentence/line per line. "
                "Keep the original language(s); do not translate, summarize, or omit fine print."
            ),
        },
        "layout_notes": {
            "type": "string",
            "description": (
                "Compliance-relevant layout observations: which claims are headline-sized vs. "
                "footnote-sized, benefit vs. disclosure prominence gap, imagery that implies "
                "safety/guarantee, unreadable fine print, etc."
            ),
        },
    },
    "required": ["title", "content_text", "layout_notes"],
}


def _vision_model() -> str:
    return os.environ.get("CCG_VISION_MODEL", VISION_MODEL_DEFAULT)


def _image_model() -> str:
    return os.environ.get("CCG_IMAGE_MODEL", IMAGE_MODEL_DEFAULT)


def extract_ad_from_image(image_b64: str, media_type: str) -> dict[str, str]:
    """이미지 광고에서 {title, content_text, layout_notes}를 추출한다.

    실패는 그대로 예외로 올린다(no fallback) — 이미지 접수 실패가 텍스트 없이
    빈 심사로 이어지면 안 된다.
    """
    if Anthropic is None:
        raise RuntimeError("anthropic package is required for image ad intake. Install anthropic.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required for image ad intake.")
    model = _vision_model()
    client = Anthropic(
        timeout=float(os.environ.get("CCG_ANTHROPIC_TIMEOUT_SECONDS", "120")),
        max_retries=1,
    )
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "system": (
            "You transcribe financial advertisement images for a compliance pre-review pipeline. "
            "Transcribe EVERY piece of visible ad copy verbatim (including fine print, rates, "
            "conditions, review numbers) in reading order. Never invent text that is not in the image."
        ),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                    },
                    {"type": "text", "text": "Extract the ad copy and layout notes from this advertisement image."},
                ],
            }
        ],
        "tools": [
            {
                "name": "ad_image_extraction",
                "description": "Return the transcribed ad copy and layout notes.",
                "input_schema": IMAGE_EXTRACTION_SCHEMA,
                "strict": True,
            }
        ],
        "tool_choice": {"type": "tool", "name": "ad_image_extraction"},
    }
    if not model.startswith("claude-fable"):
        request["thinking"] = {"type": "disabled"}
    response = client.messages.create(**request)
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "ad_image_extraction":
            data = dict(getattr(block, "input", {}) or {})
            LOGGER.info(
                "ad_image.extracted model=%s text_chars=%d", model, len(str(data.get("content_text") or ""))
            )
            return {
                "title": str(data.get("title") or ""),
                "content_text": str(data.get("content_text") or ""),
                "layout_notes": str(data.get("layout_notes") or ""),
            }
    raise RuntimeError("Vision extraction returned no structured output for the ad image.")


def generate_revised_image(
    original_bytes: bytes,
    media_type: str,
    corrected_text: str,
    *,
    layout_notes: str = "",
    disclosure_text: str = "",
) -> bytes:
    """교정 문안을 반영한 수정 배너 이미지를 생성해 PNG bytes로 반환한다."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for revised ad image generation.")
    prompt = (
        "Recreate this financial advertisement banner with COMPLIANT copy. Keep the same overall "
        "layout, brand colors, logo placement, imagery style and language as the original image, "
        "but REPLACE the advertising text with EXACTLY the following corrected copy (render it "
        "verbatim, no additions, keep its language):\n\n"
        f"{corrected_text.strip()}\n\n"
        "Typography rules: the corrected claims must stay readable; any conditions/disclosure "
        "lines must be clearly legible (not decorative micro-print)."
    )
    if disclosure_text.strip():
        prompt += f"\nAdd a clearly legible disclosure footer area with:\n{disclosure_text.strip()}"
    if layout_notes.strip():
        prompt += f"\nOriginal layout context: {layout_notes.strip()[:500]}"
    ext = "png" if "png" in media_type else "jpeg"
    client = OpenAI(timeout=float(os.environ.get("CCG_IMAGE_TIMEOUT_SECONDS", "180")), max_retries=1)
    result = client.images.edit(
        model=_image_model(),
        image=(f"ad.{ext}", io.BytesIO(original_bytes), media_type),
        prompt=prompt,
    )
    b64 = result.data[0].b64_json
    if not b64:
        raise RuntimeError("Image model returned no image data.")
    LOGGER.info("ad_image.revised model=%s prompt_chars=%d", _image_model(), len(prompt))
    return base64.b64decode(b64)
