"""수정안 이미지 생성 `korean` 게이트 회귀 테스트.

배경 결함(_workspace_i18n/01_findings.md #2): `generate_revision_guide_image`/
`refine_revision_guide_image`가 `korean` 게이트 없이 한국어 라벨("고지 영역
추가"/"심사자 보완")과 "Korean copy"/"Korean text" 지시를 무조건 프롬프트에
하드코딩했다 — `extract_ad_from_images`는 이미 `korean` 플래그로 분기하는데
이 두 함수만 빠뜨려, KH(PPCBank) 등 비-KR 워크스페이스의 수정안 이미지에도
한국어가 강제되는 유일한 확인된 "KR→KH 누수" 지점이었다.

여기서는 실제 이미지 생성 API를 호출하지 않고(OPENAI_API_KEY 불필요),
`OpenAI` 클라이언트를 가짜로 바꿔 프롬프트 문자열만 검사한다.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

import ad_image as ad_image_module


class _FakeImagesEdit:
    def __init__(self, capture: dict[str, Any]) -> None:
        self._capture = capture

    def edit(self, **kwargs: Any) -> Any:
        self._capture["prompt"] = kwargs.get("prompt", "")
        self._capture["kwargs"] = kwargs
        data_row = type("Row", (), {"b64_json": base64.b64encode(b"fake-image-bytes").decode("ascii")})()
        return type("Result", (), {"data": [data_row]})()


class _FakeOpenAIClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.images = _FakeImagesEdit(_LAST_CAPTURE)


_LAST_CAPTURE: dict[str, Any] = {}


@pytest.fixture(autouse=True)
def _patch_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    _LAST_CAPTURE.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ad_image_module, "OpenAI", _FakeOpenAIClient)


def test_generate_revision_guide_image_korean_default_hardcodes_korean_labels() -> None:
    ad_image_module.generate_revision_guide_image(
        b"original-bytes",
        "image/png",
        disclosures=["예금자보호 한도 안내"],
        reviewer_items=["세전/세후 확인"],
    )
    prompt = _LAST_CAPTURE["prompt"]
    assert "고지 영역 추가" in prompt
    assert "심사자 보완" in prompt
    assert "(Korean)" in prompt


def test_generate_revision_guide_image_non_korean_gate_drops_korean_hardcoding() -> None:
    ad_image_module.generate_revision_guide_image(
        b"original-bytes",
        "image/png",
        disclosures=["deposit protection notice"],
        reviewer_items=["confirm pre/post-tax basis"],
        korean=False,
    )
    prompt = _LAST_CAPTURE["prompt"]
    assert "고지 영역 추가" not in prompt
    assert "심사자 보완" not in prompt
    assert "(Korean)" not in prompt
    assert "REQUIRED DISCLOSURES ADDED" in prompt
    assert "REVIEWER TO COMPLETE" in prompt


def test_generate_revision_guide_image_non_korean_copy_language_note_is_generic() -> None:
    ad_image_module.generate_revision_guide_image(
        b"original-bytes",
        "image/png",
        revisions=[{"before": "old copy", "after": "new copy"}],
        korean=False,
    )
    prompt = _LAST_CAPTURE["prompt"]
    assert "Korean copy" not in prompt
    assert 'EXACTLY this copy: "new copy"' in prompt


def test_refine_revision_guide_image_korean_default_keeps_korean_instruction() -> None:
    ad_image_module.refine_revision_guide_image(b"guide-bytes", "move the callout up")
    prompt = _LAST_CAPTURE["prompt"]
    assert "Render any Korean text verbatim and legibly." in prompt


def test_refine_revision_guide_image_non_korean_gate_drops_korean_instruction() -> None:
    ad_image_module.refine_revision_guide_image(b"guide-bytes", "move the callout up", korean=False)
    prompt = _LAST_CAPTURE["prompt"]
    assert "Korean" not in prompt
    assert "Render any text verbatim and legibly." in prompt
