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
    """단일 이미지 편의 래퍼 — extract_ad_from_images 참조."""
    return extract_ad_from_images([{"base64": image_b64, "media_type": media_type}], korean=korean)


def extract_ad_from_images(images: list[dict[str, str]], *, korean: bool = True) -> dict[str, str]:
    """이미지 광고(1~N장, 카드뉴스·다장 배너)에서 {title, content_text, layout_notes}를 추출.

    content_text 는 원문 그대로(언어 불문 verbatim, 페이지 순서대로),
    layout_notes 는 심사자 언어를 따른다 — KR 한국어, 비-KR(영어 우선) 영어.
    실패는 그대로 예외로 올린다(no fallback) — 이미지 접수 실패가 텍스트 없이
    빈 심사로 이어지면 안 된다.
    """
    if Anthropic is None:
        raise RuntimeError("anthropic package is required for image ad intake. Install anthropic.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required for image ad intake.")
    if not images:
        raise RuntimeError("No ad images provided for extraction.")
    model = _vision_model()
    client = Anthropic(
        timeout=float(os.environ.get("CCG_ANTHROPIC_TIMEOUT_SECONDS", "120")),
        max_retries=1,
    )
    multi = len(images) > 1
    content: list[dict[str, Any]] = []
    for index, image in enumerate(images, start=1):
        if multi:
            content.append({"type": "text", "text": f"[Page {index} of {len(images)}]"})
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": str(image.get("media_type") or "image/png"),
                    "data": str(image.get("base64") or ""),
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": (
                "Extract the ad copy and layout notes from this multi-page advertisement. "
                "Transcribe pages in order; the pages form ONE ad."
                if multi
                else "Extract the ad copy and layout notes from this advertisement image."
            ),
        }
    )
    request: dict[str, Any] = {
        "model": model,
        "max_tokens": 8192 if multi else 4096,
        "system": (
            "You transcribe financial advertisement images for a compliance pre-review pipeline. "
            "Transcribe EVERY piece of visible ad copy verbatim (including fine print, rates, "
            "conditions, review numbers) in reading order. Never invent text that is not in the image. "
            + (
                "If multiple pages are given they form one ad — transcribe them in page order as one "
                "continuous copy (do not repeat page markers in content_text). "
                if multi
                else ""
            )
            + (
                "Write layout_notes and title in KOREAN (한국어) — the reviewer is a Korean "
                "compliance officer. Keep layout_notes to 3-4 short sentences"
                + (" covering all pages (mention page numbers when relevant)." if multi else ".")
                if korean
                else "Write layout_notes in ENGLISH, 3-4 short sentences"
                + (" covering all pages." if multi else ".")
            )
        ),
        "messages": [{"role": "user", "content": content}],
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
                "ad_image.extracted model=%s pages=%d text_chars=%d",
                model,
                len(images),
                len(str(data.get("content_text") or "")),
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
    korean: bool = True,
) -> bytes:
    """'수정 가이드' 마크업 이미지를 생성한다 — 완성 광고 재현이 아니라,
    원본 배너 위에 디자인 검수 스타일의 콜아웃(①②③)으로 '어느 자리에 어떤
    문구가 들어가야 하는지'를 표시한 어노테이션 이미지.

    완성본 재현은 원문 요소(헤드라인 등)를 유실하거나 수치를 왜곡할 위험이
    커서, 심사 실무에 맞는 '표시 위치 지시서'로 설계를 바꿨다.

    ``korean``: KR 워크스페이스는 콜아웃 라벨(고지 영역 추가/심사자 보완)과
    교정 문구 렌더링 지시를 한국어로 고정한다(기존 동작 유지). 비-KR(KH 등)은
    라벨을 영어로 쓰고 "Korean" 언어 지정 없이 "as given"으로만 지시해, 원문이
    영어/크메르어여도 한국어가 강제되지 않는다. ``extract_ad_from_images``의
    ``korean`` 게이팅 패턴을 따른다.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for revision guide image generation.")

    disclosure_zone_label = "고지 영역 추가" if korean else "REQUIRED DISCLOSURES ADDED"
    reviewer_zone_label = "심사자 보완" if korean else "REVIEWER TO COMPLETE"
    copy_language_note = "Korean copy" if korean else "copy"
    disclosure_text_note = "Korean text" if korean else "text"

    callouts: list[str] = []
    marker = 1
    # 넘겨받은 revisions 는 이미 '이 이미지에 실제로 있는 문구'만 필터링된
    # 것이다(server.revision_image). 콜아웃 폭주 방지를 위한 안전 상한만 둔다.
    max_revision_callouts = int(os.environ.get("CCG_IMAGE_MAX_REVISION_CALLOUTS", "8"))
    for row in (revisions or [])[:max_revision_callouts]:
        before = (row.get("before") or "").strip()
        after = (row.get("after") or "").strip()
        if not before or not after:
            continue
        callouts.append(
            f"({marker}) Point a red callout at the exact spot where the original text \"{before[:80]}\" "
            f"appears, cross that text out with a red strikethrough overlay, and show a green replacement "
            f"box next to it containing EXACTLY this {copy_language_note}: \"{after[:120]}\""
        )
        marker += 1
    if disclosures:
        lines = "\n".join(f"- {d}" for d in disclosures[:6])
        callouts.append(
            f"({marker}) Draw a green dashed rectangle over the bottom footer area labeled "
            f"\"{disclosure_zone_label}\" and list inside it, in small but clearly legible {disclosure_text_note}:\n{lines}"
        )
        marker += 1
    if reviewer_items:
        items = ", ".join(reviewer_items[:4])
        callouts.append(
            f"({marker}) Add an orange callout in a corner labeled \"{reviewer_zone_label}\" noting these "
            f"product-specific items must be filled in by the reviewer: {items}"
        )
        marker += 1
    if not callouts and corrected_text.strip():
        callouts.append(
            f"(1) Add a green annotation box beside the main copy containing EXACTLY this corrected "
            f"{copy_language_note}: \"{corrected_text.strip()[:400]}\""
        )

    render_instruction = (
        "given (Korean), in a clear legible sans-serif."
        if korean
        else "given, in the ad's original language, in a clear legible sans-serif."
    )
    prompt = (
        "You are producing a COMPLIANCE REVISION GUIDE (design-review markup), NOT a finished ad. "
        "Keep the original banner fully visible and unmodified as the base layer — do NOT redraw, "
        "remove or replace any original text or imagery. On top of it, add clean annotation graphics "
        "in the style of a professional design review: numbered circular markers with thin leader "
        "lines, red strikethrough overlays on problematic text, green suggestion boxes with the "
        f"replacement copy, and dashed zone rectangles. Render every annotation text VERBATIM as "
        f"{render_instruction} Annotations:\n"
        + "\n".join(callouts)
        + "\nCanvas: if needed, extend margins around the original banner to fit the annotation "
        "boxes without covering original content."
    )
    ext = "png" if "png" in media_type else "jpeg"
    # medium 품질이면 한 번 생성이 ~1분이라, 일시적 연결/5xx 오류엔 재시도가
    # 맞다(예전엔 high 라 재시도=타임아웃 doubling 이 502의 원인이었지만, medium
    # 에선 3회 시도해도 여유롭게 프론트 컷 안). 타임아웃은 넉넉히.
    client = OpenAI(
        timeout=float(os.environ.get("CCG_IMAGE_TIMEOUT_SECONDS", "300")),
        max_retries=int(os.environ.get("CCG_IMAGE_MAX_RETRIES", "2")),
    )
    result = client.images.edit(
        model=_image_model(),
        image=(f"ad.{ext}", io.BytesIO(original_bytes), media_type),
        prompt=prompt,
        # 검수용 마크업은 medium 이면 충분하고, 기본(auto/high)보다 생성이 훨씬
        # 빨라 타임아웃을 피한다. low/medium/high/auto 로 env 조정.
        quality=os.environ.get("CCG_IMAGE_QUALITY", "medium"),
    )
    b64 = result.data[0].b64_json
    if not b64:
        raise RuntimeError("Image model returned no image data.")
    LOGGER.info("ad_image.revision_guide model=%s callouts=%d prompt_chars=%d", _image_model(), len(callouts), len(prompt))
    return base64.b64decode(b64)


def refine_revision_guide_image(guide_bytes: bytes, feedback: str, *, korean: bool = True) -> bytes:
    """생성된 수정 가이드에 심사자의 개선 지시를 반영해 재편집한다.

    전체 재생성이 아니라 직전 가이드 이미지를 베이스로 한 edit — 지시하지 않은
    부분(원본 배너·기존 콜아웃)은 유지된다.

    ``korean``: KR 워크스페이스는 "Render any Korean text..."를 유지한다(기존
    동작). 비-KR(KH 등)은 언어를 특정하지 않고 일반 텍스트 렌더링 지시로 바꿔,
    원문이 한국어가 아닌 경우에도 한국어가 강제되지 않게 한다.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for revision guide refinement.")
    render_note = "Render any Korean text verbatim and legibly." if korean else "Render any text verbatim and legibly."
    prompt = (
        "This image is a compliance revision GUIDE (design-review markup over an ad banner). "
        "Apply ONLY the following reviewer instruction, keeping everything else — the original "
        f"banner, existing callouts, numbering and text — unchanged. {render_note}\n"
        f"Reviewer instruction: {feedback.strip()[:600]}"
    )
    # medium 품질이면 한 번 생성이 ~1분이라, 일시적 연결/5xx 오류엔 재시도가
    # 맞다(예전엔 high 라 재시도=타임아웃 doubling 이 502의 원인이었지만, medium
    # 에선 3회 시도해도 여유롭게 프론트 컷 안). 타임아웃은 넉넉히.
    client = OpenAI(
        timeout=float(os.environ.get("CCG_IMAGE_TIMEOUT_SECONDS", "300")),
        max_retries=int(os.environ.get("CCG_IMAGE_MAX_RETRIES", "2")),
    )
    result = client.images.edit(
        model=_image_model(),
        image=("guide.png", io.BytesIO(guide_bytes), "image/png"),
        prompt=prompt,
        quality=os.environ.get("CCG_IMAGE_QUALITY", "medium"),
    )
    b64 = result.data[0].b64_json
    if not b64:
        raise RuntimeError("Image model returned no image data.")
    LOGGER.info("ad_image.revision_guide_refined model=%s feedback_chars=%d", _image_model(), len(feedback))
    return base64.b64decode(b64)
