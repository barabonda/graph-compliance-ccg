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
                "Compliance-relevant layout observations, CONCISE (3-4 short sentences max): "
                "which claims are headline-sized vs. footnote-sized, benefit vs. disclosure "
                "prominence gap, imagery implying safety/guarantee, unreadable fine print."
            ),
        },
    },
    "required": ["title", "content_text", "layout_notes"],
}


def _vision_model() -> str:
    return os.environ.get("CCG_VISION_MODEL", VISION_MODEL_DEFAULT)


def _image_model() -> str:
    return os.environ.get("CCG_IMAGE_MODEL", IMAGE_MODEL_DEFAULT)


def extract_ad_from_image(image_b64: str, media_type: str, *, korean: bool = True) -> dict[str, str]:
    """이미지 광고에서 {title, content_text, layout_notes}를 추출한다.

    content_text 는 원문 그대로(언어 불문 verbatim), layout_notes 는 심사자
    언어를 따른다 — KR 워크스페이스는 한국어, 비-KR(영어 우선)은 영어.
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
            "conditions, review numbers) in reading order. Never invent text that is not in the image. "
            + (
                "Write layout_notes and title in KOREAN (한국어) — the reviewer is a Korean "
                "compliance officer. Keep layout_notes to 3-4 short sentences."
                if korean
                else "Write layout_notes in ENGLISH, 3-4 short sentences."
            )
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


def generate_revision_guide_image(
    original_bytes: bytes,
    media_type: str,
    *,
    revisions: list[dict[str, str]] | None = None,
    disclosures: list[str] | None = None,
    reviewer_items: list[str] | None = None,
    corrected_text: str = "",
) -> bytes:
    """'수정 가이드' 마크업 이미지를 생성한다 — 완성 광고 재현이 아니라,
    원본 배너 위에 디자인 검수 스타일의 콜아웃(①②③)으로 '어느 자리에 어떤
    문구가 들어가야 하는지'를 표시한 어노테이션 이미지.

    완성본 재현은 원문 요소(헤드라인 등)를 유실하거나 수치를 왜곡할 위험이
    커서, 심사 실무에 맞는 '표시 위치 지시서'로 설계를 바꿨다.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for revision guide image generation.")

    callouts: list[str] = []
    marker = 1
    for row in (revisions or [])[:4]:
        before = (row.get("before") or "").strip()
        after = (row.get("after") or "").strip()
        if not before or not after:
            continue
        callouts.append(
            f"({marker}) Point a red callout at the exact spot where the original text \"{before[:80]}\" "
            f"appears, cross that text out with a red strikethrough overlay, and show a green replacement "
            f"box next to it containing EXACTLY this Korean copy: \"{after[:120]}\""
        )
        marker += 1
    if disclosures:
        lines = "\n".join(f"- {d}" for d in disclosures[:6])
        callouts.append(
            f"({marker}) Draw a green dashed rectangle over the bottom footer area labeled "
            f"\"고지 영역 추가\" and list inside it, in small but clearly legible Korean text:\n{lines}"
        )
        marker += 1
    if reviewer_items:
        items = ", ".join(reviewer_items[:4])
        callouts.append(
            f"({marker}) Add an orange callout in a corner labeled \"심사자 보완\" noting these "
            f"product-specific items must be filled in by the reviewer: {items}"
        )
        marker += 1
    if not callouts and corrected_text.strip():
        callouts.append(
            "(1) Add a green annotation box beside the main copy containing EXACTLY this corrected "
            f"Korean copy: \"{corrected_text.strip()[:400]}\""
        )

    prompt = (
        "You are producing a COMPLIANCE REVISION GUIDE (design-review markup), NOT a finished ad. "
        "Keep the original banner fully visible and unmodified as the base layer — do NOT redraw, "
        "remove or replace any original text or imagery. On top of it, add clean annotation graphics "
        "in the style of a professional design review: numbered circular markers with thin leader "
        "lines, red strikethrough overlays on problematic text, green suggestion boxes with the "
        "replacement copy, and dashed zone rectangles. Render every annotation text VERBATIM as "
        "given (Korean), in a clear legible sans-serif. Annotations:\n"
        + "\n".join(callouts)
        + "\nCanvas: if needed, extend margins around the original banner to fit the annotation "
        "boxes without covering original content."
    )
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
    LOGGER.info("ad_image.revision_guide model=%s callouts=%d prompt_chars=%d", _image_model(), len(callouts), len(prompt))
    return base64.b64decode(b64)


def refine_revision_guide_image(guide_bytes: bytes, feedback: str) -> bytes:
    """생성된 수정 가이드에 심사자의 개선 지시를 반영해 재편집한다.

    전체 재생성이 아니라 직전 가이드 이미지를 베이스로 한 edit — 지시하지 않은
    부분(원본 배너·기존 콜아웃)은 유지된다.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for revision guide refinement.")
    prompt = (
        "This image is a compliance revision GUIDE (design-review markup over an ad banner). "
        "Apply ONLY the following reviewer instruction, keeping everything else — the original "
        "banner, existing callouts, numbering and text — unchanged. Render any Korean text "
        "verbatim and legibly.\n"
        f"Reviewer instruction: {feedback.strip()[:600]}"
    )
    client = OpenAI(timeout=float(os.environ.get("CCG_IMAGE_TIMEOUT_SECONDS", "180")), max_retries=1)
    result = client.images.edit(
        model=_image_model(),
        image=("guide.png", io.BytesIO(guide_bytes), "image/png"),
        prompt=prompt,
    )
    b64 = result.data[0].b64_json
    if not b64:
        raise RuntimeError("Image model returned no image data.")
    LOGGER.info("ad_image.revision_guide_refined model=%s feedback_chars=%d", _image_model(), len(feedback))
    return base64.b64decode(b64)
