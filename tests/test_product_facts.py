"""상품 단일 확정(resolve_single_product) 회귀 테스트.

배경 결함: 사용자가 명시적으로 선택한 상품(selected_product)이 퍼지 패밀리 매칭과
함께 2개로 세어져 NEEDS_PRODUCT_SELECTION으로 빠지면서, 문서가 실제로 있는데도
ProductFact가 0개로 추출되지 않았다.
"""

from __future__ import annotations

from product_facts import PRODUCT_MATCH_PRIORITY, resolve_single_product


def _m(basis, product):
    return {"match_basis": basis, "product": product}


def test_selected_product_wins_over_fuzzy_family():
    # 실측 케이스: 선택 상품 + 퍼지 패밀리 → 선택 상품으로 확정.
    matched = [
        _m("selected_product", "(26년 JUMP UP) 특판 예금"),
        _m("exact_product_family", "(봄맞이) 특판 예금"),
    ]
    resolved = resolve_single_product(matched)
    assert resolved is not None and resolved["product"] == "(26년 JUMP UP) 특판 예금"


def test_exact_name_used_when_no_selection():
    matched = [_m("exact_product_name", "JB 주거래 플러스 예금"), _m("fuzzy", "기타")]
    assert resolve_single_product(matched)["product"] == "JB 주거래 플러스 예금"


def test_family_used_as_last_resort():
    assert resolve_single_product([_m("exact_product_family", "(봄맞이) 특판 예금")])["product"] == "(봄맞이) 특판 예금"


def test_priority_order_selected_over_exact_name():
    matched = [_m("exact_product_name", "다른상품"), _m("selected_product", "선택상품")]
    assert resolve_single_product(matched)["product"] == "선택상품"


def test_genuine_ambiguity_returns_none():
    # 같은 등급에서 다수 → 진짜 모호 → None(NEEDS_PRODUCT_SELECTION).
    matched = [_m("exact_product_name", "A"), _m("exact_product_name", "B")]
    assert resolve_single_product(matched) is None


def test_no_match_returns_none():
    assert resolve_single_product([]) is None
    assert resolve_single_product([_m("fuzzy", "x"), _m("token_overlap", "y")]) is None


def test_selected_product_not_found_stays_unresolved():
    """다국어 조사(_workspace_i18n/01_findings.md #1)에서 확인 대상으로 지목된
    PRODUCT_MATCH_PRIORITY 티어 누락 지점의 회귀 테스트.

    ``selected_product_not_found``는 의도적으로 확정 티어에서 제외된다 —
    포함시키면 "타이핑했지만 어디에도 없는 상품"이 마치 확정된 것처럼 통과해
    실제로는 없는 상품에 대한 사실 대조를 건너뛴 채 조용히 진행되어 버린다.
    workspace_id가 검색 체인 끝까지 전파되면(jb_data_context.py) 정확히
    타이핑한 상품명은 이 티어가 아니라 "selected_product"/"exact_product_name"
    티어로 정상 확정되므로, 이 배타는 KH 확정 실패의 원인이 아니다.
    """
    assert "selected_product_not_found" not in PRODUCT_MATCH_PRIORITY
    matched = [_m("selected_product_not_found", "존재하지 않는 상품")]
    assert resolve_single_product(matched) is None
