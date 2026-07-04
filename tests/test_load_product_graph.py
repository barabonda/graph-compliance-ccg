"""번들 상품 메타 CSV 기반 Product Graph 페이로드 빌드 회귀 테스트.

배경: 배포판은 원본 Excel 없이 ``data/demo_product_documents`` 아래 UTF-8 CSV로
상품을 선택한다. ``load_product_graph.build_product_graph_payload``가 CSV 소스를
읽어 10개 상품/30개 문서 페이로드를 만들 수 있어야 한다(그래프 쓰기 없이 검증).
"""

from __future__ import annotations

from pathlib import Path

from load_product_graph import build_product_graph_payload, read_metadata_records

WORKSPACE_ID = "graphcompliance_mvp_jb_20260530"
BUNDLED_ROOT = Path(__file__).resolve().parent.parent / "data" / "demo_product_documents"
BUNDLED_CSV = BUNDLED_ROOT / "jbbank_product_disclosures_metadata_20260528.csv"


def test_read_metadata_records_reads_bundled_csv() -> None:
    records = read_metadata_records(BUNDLED_CSV)
    assert len(records) == 30
    assert {str(row["source_id"]) for row in records}.__len__() == 30  # unique document ids
    assert "씨드모아 통장" in {str(row["product"]) for row in records}


def test_build_product_graph_payload_from_bundled_csv() -> None:
    graph = build_product_graph_payload(
        metadata_path=BUNDLED_CSV,
        disclosure_root=BUNDLED_ROOT,
        workspace_id=WORKSPACE_ID,
    )
    products = {product["name"] for product in graph["products"]}
    assert len(graph["products"]) == 10
    assert len(graph["documents"]) == 30
    assert "씨드모아 통장" in products

    # 카테고리 다양성: 예금/대출 그룹이 모두 포함되어야 한다.
    groups = {group["name"] for group in graph["groups"]}
    assert {"deposit", "loan"}.issubset(groups)

    # 모든 문서 id는 유일해야 한다(공유 약관 source_id 충돌 회귀 방지).
    document_ids = [document["id"] for document in graph["documents"]]
    assert len(document_ids) == len(set(document_ids))

    # 번들 PDF가 실제로 존재해야 한다.
    assert all(document["exists"] for document in graph["documents"])

    # workspace_id 전파 확인.
    assert all(product["workspace_id"] == WORKSPACE_ID for product in graph["products"])
