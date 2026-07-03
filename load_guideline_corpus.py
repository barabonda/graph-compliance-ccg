"""은행 광고심의 기준(은행연합회 자율규제) → 가이드라인 tier LawArticle 적재.

소스는 OCR이 아니라 사람이 검증한 변환본(은행_광고심의_기준_및_세칙_검증수정본.md)
이므로 ocr_verified=true 로 적재한다. (OCR 산출물을 적재할 땐 ocr_verified=false 로
두고, 판정 사유에 "(원문 확인 필요)"가 따라가게 한다 — 검수 전 breadcrumb 왜곡 방지.)

적재 후 조문 텍스트의 인용(금소법 제22조, 금소법 시행령 제18조, 세칙→기준 제N조)을
파싱해 법령↔가이드라인 CITES_ARTICLE 엣지를 생성한다. 이 엣지가 "법 OK / 위임된
심의기준 미흡" breadcrumb 의 그래프 경로가 된다.

Usage: python load_guideline_corpus.py [--dry-run] [--md PATH]
"""
from __future__ import annotations

import argparse
import os
import re
from collections import Counter

from env_loader import load_local_env
from utils import stable_id

DEFAULT_MD = (
    "/Users/barabonda/Downloads/JB금융그룹해커톤_데이터셋/금융광고 심의 데이터셋/"
    "은행_광고심의_기준_및_세칙_검증수정본.md"
)
STANDARD = "은행 광고심의 기준"
STANDARD_DETAIL = "은행 광고심의 기준 세칙"
CORPUS_ID = "bank_ad_review_standard_20230126"
LAW = "금융소비자 보호에 관한 법률"
DECREE = "금융소비자 보호에 관한 법률 시행령"
AD_LAW = "표시ㆍ광고의 공정화에 관한 법률"

ARTICLE_HEAD_RE = re.compile(r"^### 제(\d+)조(?:의(\d+))?\(([^)]+)\)\s*(.*)$")
DOC_HEAD_RE = re.compile(r"^# (.+)$")

# 조문 텍스트의 축약 인용 → 대상 법령 (순서 중요: 구체 패턴 먼저)
CITATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"금소법\s*시행령\s*제(\d+조(?:의\d+)?)"), DECREE),
    (re.compile(r"금소법\s*제(\d+조(?:의\d+)?)"), LAW),
    (re.compile(r"「금융소비자\s*보호에\s*관한\s*법률\s*시행령」\s*제(\d+조(?:의\d+)?)"), DECREE),
    (re.compile(r"「금융소비자\s*보호에\s*관한\s*법률」.*?제(\d+조(?:의\d+)?)"), LAW),
    (re.compile(r"「표시[·ㆍ]광고의\s*공정화에\s*관한\s*법률」\s*제(\d+조(?:의\d+)?)"), AD_LAW),
]
# 세칙 → 기준 위임 인용
DETAIL_TO_STANDARD_RE = re.compile(r"기준\s*제(\d+조(?:의\d+)?)")


def parse_markdown(md_path: str) -> list[dict]:
    """검증수정본 md → 조문 레코드. 부칙(조번호가 다시 1로 리셋)은 제외한다."""
    articles: list[dict] = []
    current_doc = None
    current: dict | None = None
    in_addendum = False
    last_no = 0
    for line in open(md_path, encoding="utf-8"):
        doc_match = DOC_HEAD_RE.match(line)
        if doc_match:
            title = doc_match.group(1).strip()
            if title in (STANDARD, STANDARD_DETAIL):
                if current:
                    articles.append(current)
                    current = None
                current_doc = title
                in_addendum = False
                last_no = 0
            continue
        head = ARTICLE_HEAD_RE.match(line)
        if head and current_doc:
            no = int(head.group(1))
            if no < last_no:  # 조번호 리셋 = 부칙 시작
                in_addendum = True
            last_no = max(last_no, no)
            if current:
                articles.append(current)
                current = None
            if in_addendum:
                continue
            article_no = f"제{no}조" + (f"의{head.group(2)}" if head.group(2) else "")
            current = {
                "document_title": current_doc,
                "article_no": article_no,
                "article_title": head.group(3).strip(),
                "text": (head.group(4) or "").strip(),
            }
            continue
        if current is not None and not in_addendum:
            current["text"] = (current["text"] + "\n" + line.rstrip()).strip()
    if current:
        articles.append(current)
    # 문서별 중복 조문 방지 (목차 등에서 온 노이즈 차단)
    seen: set[tuple[str, str]] = set()
    unique = []
    for a in articles:
        key = (a["document_title"], a["article_no"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)
    return unique


def extract_citations(articles: list[dict]) -> list[dict]:
    edges: list[dict] = []
    for a in articles:
        text = a["text"]
        refs: set[tuple[str, str]] = set()
        for pattern, target_doc in CITATION_PATTERNS:
            for m in pattern.finditer(text):
                refs.add((target_doc, f"제{m.group(1)}"))
        if a["document_title"] == STANDARD_DETAIL:
            for m in DETAIL_TO_STANDARD_RE.finditer(text):
                refs.add((STANDARD, f"제{m.group(1)}"))
        for target_doc, target_no in sorted(refs):
            edges.append(
                {
                    "from_doc": a["document_title"],
                    "from_no": a["article_no"],
                    "to_doc": target_doc,
                    "to_no": target_no,
                }
            )
    return edges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=DEFAULT_MD)
    ap.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    articles = parse_markdown(args.md)
    by_doc = Counter(a["document_title"] for a in articles)
    print(f"파싱: {dict(by_doc)}")
    # 구조 검수: 기준 21개조, 세칙 13개조 연속성
    for doc, expected in ((STANDARD, 21), (STANDARD_DETAIL, 13)):
        nos = sorted(int(re.match(r"제(\d+)조", a["article_no"]).group(1)) for a in articles if a["document_title"] == doc)
        missing = [n for n in range(1, expected + 1) if n not in nos]
        status = "OK" if not missing and len(nos) == expected else f"결번 {missing}"
        print(f"  {doc}: {len(nos)}/{expected}개조 {status}")
    print("\n제16~18조 전수 검수(핵심 요건 문구 눈검증용):")
    for a in articles:
        if a["document_title"] == STANDARD and a["article_no"] in ("제16조", "제17조", "제18조"):
            print(f"  [{a['article_no']}({a['article_title']})] {a['text'][:80]}...")

    edges = extract_citations(articles)
    edge_kinds = Counter((e["from_doc"][-2:], e["to_doc"][:12]) for e in edges)
    print(f"\n인용 엣지 {len(edges)}개:")
    for (f, t), n in edge_kinds.most_common():
        print(f"  ...{f} → {t}...: {n}")

    if args.dry_run:
        print("\ndry-run: 쓰기 없음")
        return 0

    load_local_env()
    from neo4j import GraphDatabase

    ws = args.workspace_id
    rows = [
        {
            "id": stable_id("law_article_guideline", ws, a["document_title"], a["article_no"]),
            **a,
            "heading": f"{a['article_no']}({a['article_title']})",
        }
        for a in articles
    ]
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        s.run(
            """
            UNWIND $rows AS row
            MERGE (a:LawArticle {id: row.id, workspace_id: $ws})
            SET a.document_title = row.document_title,
                a.article_no = row.article_no,
                a.article_title = row.article_title,
                a.heading = row.heading,
                a.text = row.text,
                a.authority_tier = 'guideline',
                a.ocr_verified = true,
                a.source = 'bank_ad_review_standard_verified_md',
                a.corpus_id = $corpus
            """,
            rows=rows, ws=ws, corpus=CORPUS_ID,
        )
        edge_rows = [
            {
                "from_id": stable_id("law_article_guideline", ws, e["from_doc"], e["from_no"]),
                "to_doc": e["to_doc"], "to_no": e["to_no"],
            }
            for e in edges
        ]
        result = s.run(
            """
            UNWIND $rows AS row
            MATCH (a:LawArticle {id: row.from_id, workspace_id: $ws})
            MATCH (b:LawArticle {workspace_id: $ws})
            WHERE b.document_title = row.to_doc AND b.article_no = row.to_no
            MERGE (a)-[r:CITES_ARTICLE {workspace_id: $ws, source: 'guideline_corpus_loader'}]->(b)
            RETURN count(r) AS n
            """,
            rows=edge_rows, ws=ws,
        ).single()
        n_articles = s.run(
            "MATCH (a:LawArticle {workspace_id:$ws, authority_tier:'guideline'}) RETURN count(a) AS n", ws=ws
        ).single()["n"]
        print(f"\n적재 완료: 가이드라인 조문 {n_articles}개, 인용 엣지 {result['n']}개")
    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
