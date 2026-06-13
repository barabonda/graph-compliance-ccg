"""Build cross-law delegation citations between LawArticle nodes.

시행령·감독규정·시행세칙 조문 텍스트는 모법을 "법 제22조", 시행령을 "영 제20조"
같은 축약형으로 인용하지만, 기존 인용 추출은 같은 법령 내부 참조만 엣지로
만들었다. 이 스크립트는 축약·전체명 인용을 파싱해 법령 간(cross-law)
CITES_ARTICLE 엣지를 보강한다. 이 엣지가 있어야 하위 규정을 인용한 CU에서
모법 조문을 자동 병기할 수 있다.

Usage:
    python build_cross_law_citations.py [--dry-run] [--workspace-id ...]
"""

from __future__ import annotations

import argparse
import os
import re
from collections import Counter
from typing import Any

from env_loader import load_local_env


# document_title 값은 DB에 저장된 표기를 그대로 따른다 (띄어쓰기 포함).
LAW = "금융소비자 보호에 관한 법률"
DECREE = "금융소비자 보호에 관한 법률 시행령"
REGULATION = "금융소비자 보호에 관한 감독규정"
REGULATION_DETAIL = "금융소비자보호에 관한 감독규정 시행세칙"
AD_LAW = "표시ㆍ광고의 공정화에 관한 법률"
AD_DECREE = "표시ㆍ광고의 공정화에 관한 법률 시행령"

ARTICLE_NO = r"제(\d+조(?:의\d+)?)"

# 각 하위 법령 문서에서 축약 인용이 가리키는 상위 법령.
# 패턴 앞의 lookbehind는 "방법", "시행령" 같은 합성어 내부 글자 오인을 막는다.
SHORTHAND_TARGETS: dict[str, list[tuple[str, str]]] = {
    DECREE: [
        (rf"(?<![가-힣])법\s*{ARTICLE_NO}", LAW),
    ],
    REGULATION: [
        (rf"(?<![가-힣])법\s*{ARTICLE_NO}", LAW),
        (rf"(?<![가-힣])영\s*{ARTICLE_NO}", DECREE),
        (rf"시행령\s*{ARTICLE_NO}", DECREE),
    ],
    REGULATION_DETAIL: [
        (rf"(?<![가-힣])법\s*{ARTICLE_NO}", LAW),
        (rf"(?<![가-힣])영\s*{ARTICLE_NO}", DECREE),
        (rf"시행령\s*{ARTICLE_NO}", DECREE),
        (rf"감독규정\s*{ARTICLE_NO}", REGULATION),
        (rf"(?<![가-힣])규정\s*{ARTICLE_NO}", REGULATION),
    ],
    AD_DECREE: [
        (rf"(?<![가-힣])법\s*{ARTICLE_NO}", AD_LAW),
    ],
}

# 「법령명」 제N조 형태의 전체명 인용 → document_title 매칭용 키워드.
FULL_NAME_RE = re.compile(rf"「([^」]+)」\s*{ARTICLE_NO}")
FULL_NAME_TARGETS = [
    ("금융소비자 보호에 관한 법률 시행령", DECREE),
    ("금융소비자 보호에 관한 법률", LAW),
    ("금융소비자보호에 관한 감독규정", REGULATION),
    ("금융소비자 보호에 관한 감독규정", REGULATION),
    ("표시ㆍ광고의 공정화에 관한 법률 시행령", AD_DECREE),
    ("표시ㆍ광고의 공정화에 관한 법률", AD_LAW),
]


def extract_cross_law_refs(document_title: str, text: str) -> set[tuple[str, str]]:
    """Return {(target_document_title, target_article_no), ...} cited from text."""
    refs: set[tuple[str, str]] = set()
    for pattern, target_law in SHORTHAND_TARGETS.get(document_title, []):
        for match in re.finditer(pattern, text):
            refs.add((target_law, f"제{match.group(1)}"))
    for match in FULL_NAME_RE.finditer(text):
        quoted, article = match.group(1), f"제{match.group(2)}"
        for needle, target_law in FULL_NAME_TARGETS:
            if needle in quoted:
                if target_law != document_title:
                    refs.add((target_law, article))
                break
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    parser.add_argument("--dry-run", action="store_true", help="Print planned edges without writing.")
    args = parser.parse_args()

    load_local_env()
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    )
    with driver.session() as session:
        articles = [
            dict(row)
            for row in session.run(
                "MATCH (a:LawArticle {workspace_id: $ws}) "
                "RETURN a.id AS id, a.document_title AS document_title, "
                "a.article_no AS article_no, a.text AS text",
                ws=args.workspace_id,
            )
        ]
        by_doc_article: dict[tuple[str, str], str] = {
            (row["document_title"], row["article_no"]): row["id"] for row in articles
        }

        planned: list[dict[str, Any]] = []
        unresolved: Counter[tuple[str, str]] = Counter()
        for row in articles:
            refs = extract_cross_law_refs(row["document_title"] or "", row["text"] or "")
            for target_law, article_no in sorted(refs):
                target_id = by_doc_article.get((target_law, article_no))
                if not target_id:
                    unresolved[(target_law, article_no)] += 1
                    continue
                planned.append(
                    {
                        "source_id": row["id"],
                        "target_id": target_id,
                        "from_law": row["document_title"],
                        "from_no": row["article_no"],
                        "to_law": target_law,
                        "to_no": article_no,
                    }
                )

        pair_counts = Counter((edge["from_law"], edge["to_law"]) for edge in planned)
        print(f"planned cross-law edges: {len(planned)}")
        for (from_law, to_law), count in pair_counts.most_common():
            print(f"  {from_law}  →  {to_law}  x{count}")
        if unresolved:
            print(f"unresolved targets (조문이 코퍼스에 없음): {sum(unresolved.values())}")
            for (law, no), count in unresolved.most_common(8):
                print(f"  {law} {no} x{count}")

        if args.dry_run:
            print("dry-run: no writes")
            return 0

        session.run(
            """
            UNWIND $rows AS row
            MATCH (a:LawArticle {id: row.source_id, workspace_id: $ws})
            MATCH (b:LawArticle {id: row.target_id, workspace_id: $ws})
            MERGE (a)-[r:CITES_ARTICLE {workspace_id: $ws, source: 'cross_law_citation_builder'}]->(b)
            """,
            rows=planned,
            ws=args.workspace_id,
        )
        written = session.run(
            "MATCH (:LawArticle)-[r:CITES_ARTICLE {source: 'cross_law_citation_builder', workspace_id: $ws}]->(:LawArticle) "
            "RETURN count(r) AS n",
            ws=args.workspace_id,
        ).single()["n"]
        print(f"written cross-law CITES_ARTICLE edges: {written}")
    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
