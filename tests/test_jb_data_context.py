"""상품 검색/매칭 workspace_id 전파 회귀 테스트 (_workspace_i18n/01_findings.md #1).

배경 결함: KH(PPCBank) 상품 그래프(Product 23·ProductFact 255)가 실재하는데도
`search_products`/`match_products_from_neo4j`/`load_product_rows_from_neo4j`가
전부 KR workspace로 하드코딩돼 있어(프로세스 전역 `WORKSPACE_ID` env, 그리고
`@lru_cache(maxsize=1)`로 워크스페이스 분기 불가) KH 리뷰에서 KH 상품 데이터에
절대 도달할 수 없었다. 또한 로컬 JB(KR) CSV 폴백이 워크스페이스와 무관하게
항상 병합돼, KH 검색 결과에 KR 상품명이 섞이는 교차 오염 위험이 있었다.

이 테스트는 (1) workspace_id가 검색 함수 시그니처를 타고 끝까지 전파되는지,
(2) 비-KR 워크스페이스에서 로컬 KR CSV가 병합되지 않는지(오염 0), (3) Neo4j
조회 캐시가 workspace_id별로 분리되는지를 검증한다. 실제 Neo4j 네트워크 호출은
하지 않는다(가짜 driver로 대체).
"""

from __future__ import annotations

from typing import Any

import pytest

import jb_data_context as jb_data_context_module
from jb_data_context import (
    all_product_rows,
    match_products,
    search_products,
    selected_product_match,
)
from schemas import ReviewInput

KR_WORKSPACE = "graphcompliance_mvp_jb_20260530"
KH_WORKSPACE = "graphcompliance_cambodia_ppcbank_20260630"

_KR_LOCAL_ROW = {
    "JB주거래우대예금": {
        "product": "JB주거래우대예금",
        "product_group": "deposit",
        "major": "예금상품공시",
        "subcategory": "",
        "category": "",
        "document_count": 2,
        "document_labels": ["상품설명서"],
        "source_ids": ["kr_doc_1"],
        "documents": [],
    }
}

_KH_GRAPH_ROW = {
    "PPCBank Fixed Deposit": {
        "product": "PPCBank Fixed Deposit",
        "product_group": "deposit",
        "major": "PPCBank",
        "subcategory": "deposit",
        "category": "personal_banking",
        "document_count": 1,
        "document_labels": ["Product Terms"],
        "source_ids": ["kh_doc_1"],
        "documents": [],
        "source": jb_data_context_module.PRODUCT_GRAPH_SOURCE,
    }
}


@pytest.fixture(autouse=True)
def _isolate_non_kr_workspaces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CCG_NON_KR_LAW_WORKSPACES", KH_WORKSPACE)


@pytest.fixture()
def _fake_local_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jb_data_context_module, "load_product_rows", lambda: dict(_KR_LOCAL_ROW))


def test_all_product_rows_kh_workspace_excludes_kr_local_csv(monkeypatch: pytest.MonkeyPatch, _fake_local_rows: None) -> None:
    monkeypatch.setattr(
        jb_data_context_module, "load_product_rows_from_neo4j", lambda workspace_id="": dict(_KH_GRAPH_ROW)
    )
    rows = all_product_rows(KH_WORKSPACE)
    assert "PPCBank Fixed Deposit" in rows
    assert "JB주거래우대예금" not in rows  # KR 오염 0


def test_all_product_rows_kr_workspace_still_merges_local_csv(monkeypatch: pytest.MonkeyPatch, _fake_local_rows: None) -> None:
    monkeypatch.setattr(jb_data_context_module, "load_product_rows_from_neo4j", lambda workspace_id="": {})
    rows = all_product_rows(KR_WORKSPACE)
    assert "JB주거래우대예금" in rows  # 기존 KR 동작 무회귀


def test_search_products_threads_workspace_id_to_neo4j_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_workspace_ids: list[str] = []

    def fake_loader(workspace_id: str = "") -> dict[str, dict[str, Any]]:
        seen_workspace_ids.append(workspace_id)
        return dict(_KH_GRAPH_ROW) if workspace_id == KH_WORKSPACE else {}

    monkeypatch.setattr(jb_data_context_module, "load_product_rows_from_neo4j", fake_loader)
    monkeypatch.setattr(jb_data_context_module, "load_product_rows", lambda: {})

    results = search_products("PPCBank Fixed Deposit", workspace_id=KH_WORKSPACE)

    assert seen_workspace_ids == [KH_WORKSPACE]
    assert results and results[0]["product"] == "PPCBank Fixed Deposit"


def test_search_products_kh_workspace_never_returns_kr_products(
    monkeypatch: pytest.MonkeyPatch, _fake_local_rows: None
) -> None:
    monkeypatch.setattr(
        jb_data_context_module, "load_product_rows_from_neo4j", lambda workspace_id="": dict(_KH_GRAPH_ROW)
    )
    # 광범위 그룹 검색(빈 query)이어도 KR 로컬 상품이 섞이면 안 된다.
    results = search_products("", product_group="deposit", workspace_id=KH_WORKSPACE)
    assert results
    assert all(row["product"] != "JB주거래우대예금" for row in results)


def test_match_products_non_kr_workspace_skips_local_csv_fallback(
    monkeypatch: pytest.MonkeyPatch, _fake_local_rows: None
) -> None:
    monkeypatch.setattr(
        jb_data_context_module,
        "match_products_from_neo4j",
        lambda text, claims, product_group, workspace_id="": [],
    )
    matches = match_products("아무 광고 문안", [], "deposit", KH_WORKSPACE)
    assert matches == []  # KR CSV 폴백으로 새지 않음


def test_match_products_kr_workspace_still_uses_local_csv_fallback(
    monkeypatch: pytest.MonkeyPatch, _fake_local_rows: None
) -> None:
    monkeypatch.setattr(
        jb_data_context_module,
        "match_products_from_neo4j",
        lambda text, claims, product_group, workspace_id="": [],
    )
    matches = match_products("JB주거래우대예금 특판 안내", [], "deposit", KR_WORKSPACE)
    assert matches and matches[0]["product"] == "JB주거래우대예금"


def test_selected_product_match_non_kr_workspace_excludes_kr_local_candidates(
    monkeypatch: pytest.MonkeyPatch, _fake_local_rows: None
) -> None:
    monkeypatch.setattr(jb_data_context_module, "load_product_rows_from_neo4j", lambda workspace_id="": {})
    review_input = ReviewInput(
        content_text="PPCBank Fixed Deposit ad copy",
        workspace_id=KH_WORKSPACE,
        selected_product_name="Some Untracked KH Product",
    )
    result = selected_product_match(review_input, current_matches=[], product_group="deposit")
    assert result is not None
    assert result["match_basis"] == "selected_product_not_found"
    assert result["product"] == "Some Untracked KH Product"


def test_load_product_rows_from_neo4j_cache_is_scoped_per_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """`@lru_cache(maxsize=1)`이 워크스페이스 하나로 고정되던 결함의 핵심 회귀:
    서로 다른 workspace_id 호출이 서로의 결과를 덮어쓰지 않아야 한다."""
    import neo4j

    jb_data_context_module.load_product_rows_from_neo4j.cache_clear()
    monkeypatch.setenv("NEO4J_URI", "bolt://fake-host:7687")
    monkeypatch.setenv("NEO4J_USER", "fake-user")
    monkeypatch.setenv("NEO4J_PASSWORD", "fake-password")
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)

    rows_by_workspace = {
        KR_WORKSPACE: [
            {
                "product": "KR상품A",
                "product_group": "deposit",
                "major": "",
                "subcategory": "",
                "category": "",
                "document_count": 1,
                "document_labels": [],
                "source_ids": [],
                "documents": [],
            }
        ],
        KH_WORKSPACE: [
            {
                "product": "PPCBank Fixed Deposit",
                "product_group": "deposit",
                "major": "",
                "subcategory": "",
                "category": "",
                "document_count": 1,
                "document_labels": [],
                "source_ids": [],
                "documents": [],
            }
        ],
    }
    run_calls: list[str] = []

    class _FakeSession:
        def __init__(self, rows_by_workspace: dict[str, list[dict[str, Any]]]) -> None:
            self._rows_by_workspace = rows_by_workspace

        def __enter__(self) -> "_FakeSession":
            return self

        def __exit__(self, *exc_info: object) -> bool:
            return False

        def run(self, _query: str, **kwargs: Any) -> list[dict[str, Any]]:
            workspace_id = kwargs.get("workspace_id", "")
            run_calls.append(workspace_id)
            return list(self._rows_by_workspace.get(workspace_id, []))

    class _FakeDriver:
        def __init__(self, rows_by_workspace: dict[str, list[dict[str, Any]]]) -> None:
            self._rows_by_workspace = rows_by_workspace

        def session(self, *args: object, **kwargs: object) -> _FakeSession:
            return _FakeSession(self._rows_by_workspace)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        neo4j.GraphDatabase, "driver", lambda uri, auth=None: _FakeDriver(rows_by_workspace)
    )

    try:
        kr_rows = jb_data_context_module.load_product_rows_from_neo4j(KR_WORKSPACE)
        kh_rows = jb_data_context_module.load_product_rows_from_neo4j(KH_WORKSPACE)

        assert "KR상품A" in kr_rows
        assert "PPCBank Fixed Deposit" not in kr_rows
        assert "PPCBank Fixed Deposit" in kh_rows
        assert "KR상품A" not in kh_rows
        assert run_calls == [KR_WORKSPACE, KH_WORKSPACE]
    finally:
        jb_data_context_module.load_product_rows_from_neo4j.cache_clear()
