"""`/api/revision-image` workspace_id -> korean 게이트 전파 회귀 테스트.

배경 결함(_workspace_i18n/01_findings.md #2): `server.py`의 이미지 수정안
호출부가 `ad_image.generate_revision_guide_image`/`refine_revision_guide_image`
를 호출할 때 `korean=` 인자를 아예 넘기지 않아, KH(비-KR) 워크스페이스 심사에도
한국어 라벨/문안이 하드코딩된 채 나갔다. `extract_ad_from_images` 호출부
(intake_ad_image)는 이미 `korean=uses_korean_law_context(...)`로 올바르게
게이팅하고 있었으므로, 그 패턴을 이미지 수정안 호출부에도 맞춘다.

이 테스트는 실제 OpenAI/Neo4j 호출 없이 `server.generate_revision_guide_image`/
`server.refine_revision_guide_image`/`server.workspace_id_for_run`을 가짜로
바꿔, 계산된 `korean` 값이 두 호출부 모두에 정확히 전달되는지만 검증한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import server as server_module

KH_WORKSPACE = "graphcompliance_cambodia_ppcbank_20260630"
KR_WORKSPACE = "graphcompliance_mvp_jb_20260530"


@pytest.fixture(autouse=True)
def _isolate_non_kr_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCG_NON_KR_LAW_WORKSPACES", KH_WORKSPACE)


@pytest.fixture()
def _ad_image_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(server_module, "AD_IMAGE_DIR", tmp_path)
    return tmp_path


def _write_original(ad_image_dir: Path, run_id: str) -> None:
    (ad_image_dir / f"{run_id}_original.png").write_bytes(b"fake-original-bytes")


def test_revision_image_uses_explicit_payload_workspace_id(
    monkeypatch: pytest.MonkeyPatch, _ad_image_dir: Path
) -> None:
    run_id = "run_kh_explicit"
    _write_original(_ad_image_dir, run_id)
    monkeypatch.setattr(server_module, "load_run", lambda run_id: {})

    def _fail_if_called(_run_id: str) -> str:
        raise AssertionError("workspace_id_for_run should not be called when payload provides workspace_id")

    monkeypatch.setattr(server_module, "workspace_id_for_run", _fail_if_called)

    captured: dict[str, Any] = {}

    def fake_generate(*args: Any, **kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"fake-guide-bytes"

    monkeypatch.setattr(server_module, "generate_revision_guide_image", fake_generate)

    result = server_module.revision_image(
        {"review_run_id": run_id, "corrected_text": "corrected copy", "workspace_id": KH_WORKSPACE}
    )

    assert captured["korean"] is False
    assert result["review_run_id"] == run_id


def test_revision_image_falls_back_to_run_lookup_for_workspace_id(
    monkeypatch: pytest.MonkeyPatch, _ad_image_dir: Path
) -> None:
    run_id = "run_kh_fallback"
    _write_original(_ad_image_dir, run_id)
    monkeypatch.setattr(server_module, "load_run", lambda run_id: {})
    monkeypatch.setattr(server_module, "workspace_id_for_run", lambda run_id: KH_WORKSPACE)

    captured: dict[str, Any] = {}

    def fake_generate(*args: Any, **kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"fake-guide-bytes"

    monkeypatch.setattr(server_module, "generate_revision_guide_image", fake_generate)

    server_module.revision_image({"review_run_id": run_id, "corrected_text": "corrected copy"})

    assert captured["korean"] is False


def test_revision_image_kr_workspace_keeps_korean_gate_true(
    monkeypatch: pytest.MonkeyPatch, _ad_image_dir: Path
) -> None:
    run_id = "run_kr_default"
    _write_original(_ad_image_dir, run_id)
    monkeypatch.setattr(server_module, "load_run", lambda run_id: {})
    monkeypatch.setattr(server_module, "workspace_id_for_run", lambda run_id: KR_WORKSPACE)

    captured: dict[str, Any] = {}

    def fake_generate(*args: Any, **kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"fake-guide-bytes"

    monkeypatch.setattr(server_module, "generate_revision_guide_image", fake_generate)

    server_module.revision_image({"review_run_id": run_id, "corrected_text": "corrected copy"})

    assert captured["korean"] is True


def test_revision_image_refine_path_also_gets_korean_gate(
    monkeypatch: pytest.MonkeyPatch, _ad_image_dir: Path
) -> None:
    run_id = "run_kh_refine"
    _write_original(_ad_image_dir, run_id)
    (_ad_image_dir / f"{run_id}_revised.png").write_bytes(b"fake-previous-guide-bytes")
    monkeypatch.setattr(server_module, "workspace_id_for_run", lambda run_id: KH_WORKSPACE)

    captured: dict[str, Any] = {}

    def fake_refine(*args: Any, **kwargs: Any) -> bytes:
        captured.update(kwargs)
        return b"fake-refined-bytes"

    monkeypatch.setattr(server_module, "refine_revision_guide_image", fake_refine)

    server_module.revision_image({"review_run_id": run_id, "feedback": "move callout up"})

    assert captured["korean"] is False


def test_products_search_threads_workspace_id_query_param(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search_products(q: str, product_group: str = "auto", limit: int = 12, workspace_id: str = "") -> list[dict[str, Any]]:
        captured["workspace_id"] = workspace_id
        return []

    monkeypatch.setattr(server_module, "search_products", fake_search_products)

    server_module.products_search(q="Fixed Deposit", workspace_id=KH_WORKSPACE)

    assert captured["workspace_id"] == KH_WORKSPACE
