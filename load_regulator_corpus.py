"""규제당국 하위규범 코퍼스 적재 — 공정위 심사지침·고시 6종 + 금융위 가이드라인(OCR).

권위 계층(tier) 구분:
- 심사지침 4종(공정위 내부 심사기준) → authority_tier='guideline'
- 고시 2종(표시광고법 위임 법규보충적 행정규칙 — 대외 구속력) → authority_tier='law'
- 금융광고규제 가이드라인(금융위·금감원 행정지도) → authority_tier='guideline'

출처 신뢰도:
- md 6종은 법령 오픈데이터 변환본 → ocr_verified=true
- 금융위 가이드라인은 VLM OCR 산출(검수 전) → ocr_verified=false
  (판정 사유에 "(원문 확인 필요)"가 따라가야 하는 대상)

Usage: python load_regulator_corpus.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

from env_loader import load_local_env
from utils import stable_id

DATASET_DIR = Path("/Users/barabonda/Downloads/JB금융그룹해커톤_데이터셋/금융법률 데이터셋/all")
OCR_JSON = Path("/Users/barabonda/Desktop/project/paper_agent/out/guideline_ocr/guideline_full.json")
WS_DEFAULT = "graphcompliance_mvp_jb_20260530"

AD_LAW = "표시ㆍ광고의 공정화에 관한 법률"
AD_DECREE = "표시ㆍ광고의 공정화에 관한 법률 시행령"
LAW = "금융소비자 보호에 관한 법률"
DECREE = "금융소비자 보호에 관한 법률 시행령"
REGULATION = "금융소비자 보호에 관한 감독규정"

MD_SOURCES = [
    ("financial_product_labeling_advertising_review_guideline_금융상품_등의_표시·광고에_관한_심사지침.md",
     "금융상품 등의 표시·광고에 관한 심사지침", "guideline", "심사지침"),
    ("comparative_labeling_advertising_review_guideline_비교표시·광고에_관한_심사지침.md",
     "비교표시·광고에 관한 심사지침", "guideline", "심사지침"),
    ("deceptive_labeling_advertising_review_guideline_기만적인_표시·광고_심사지침.md",
     "기만적인 표시·광고 심사지침", "guideline", "심사지침"),
    ("endorsement_review_guideline_추천·보증_등에_관한_표시·광고_심사지침.md",
     "추천·보증 등에 관한 표시·광고 심사지침", "guideline", "심사지침"),
    ("unfair_labeling_advertising_review_guideline_부당한_표시·광고행위의_유형_및_기준_지정고시.md",
     "부당한 표시·광고행위의 유형 및 기준 지정고시", "law", "고시"),
    ("important_labeling_advertising_notice_중요한_표시·광고사항_고시.md",
     "중요한 표시·광고사항 고시", "law", "고시"),
]

HEAD_RE = re.compile(r"^### (?P<no>[^(\n]+)\((?P<title>[^)]*)\)\s*(?P<rest>.*)$")
ROMAN_RE = re.compile(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+$")
ARTICLE_NO_RE = re.compile(r"제(\d+조(?:의\d+)?)")

# 이 문서들의 축약 인용 → 대상 법령 (공정위 계열은 '법'=표시광고법)
CITE_PATTERNS = [
    (re.compile(r"금소법\s*시행령\s*제(\d+조(?:의\d+)?)"), DECREE),
    (re.compile(r"금소법\s*제(\d+조(?:의\d+)?)"), LAW),
    (re.compile(r"「금융소비자\s*보호에\s*관한\s*법률」[^제]{0,10}제(\d+조(?:의\d+)?)"), LAW),
    (re.compile(r"「표시[·ㆍ]광고의\s*공정화에\s*관한\s*법률\s*시행령」\s*제(\d+조(?:의\d+)?)"), AD_DECREE),
    (re.compile(r"「표시[·ㆍ]광고의\s*공정화에\s*관한\s*법률」[^제]{0,10}제(\d+조(?:의\d+)?)"), AD_LAW),
    (re.compile(r"(?<![가-힣])시행령\s*제(\d+조(?:의\d+)?)"), AD_DECREE),
    (re.compile(r"(?<![가-힣])법\s*제(\d+조(?:의\d+)?)"), AD_LAW),
]


def parse_md(path: Path, document_title: str) -> list[dict]:
    articles: list[dict] = []
    current: dict | None = None
    roman = ""
    seen: Counter = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = HEAD_RE.match(line)
        if m:
            if current:
                articles.append(current)
            no = m.group("no").strip()
            if ROMAN_RE.match(no):
                roman = no
                article_no = no
            else:
                article_no = f"{roman}-{no}" if roman else no
            seen[article_no] += 1
            if seen[article_no] > 1:
                article_no = f"{article_no}#{seen[article_no]}"
            current = {
                "document_title": document_title,
                "article_no": article_no,
                "article_title": m.group("title").strip()[:120],
                "text": (m.group("rest") or "").strip(),
            }
            continue
        if line.startswith("# ") or line.strip() == "## Articles":
            continue
        if current is not None:
            current["text"] = (current["text"] + "\n" + line.rstrip()).strip()
    if current:
        articles.append(current)
    return articles


def parse_ocr_json(path: Path, document_title: str) -> list[dict]:
    """VLM OCR kg_payload → 섹션 단위 chunk. 검수 전이므로 ocr_verified=false 대상."""
    data = json.loads(path.read_text(encoding="utf-8"))
    sections = sorted(data.get("sections", []), key=lambda s: (s.get("page", 0), s.get("order", 0)))
    texts = data.get("texts", [])
    by_section: dict[str, list] = {}
    for t in sorted(texts, key=lambda x: (x.get("page", 0), x.get("order", 0))):
        by_section.setdefault(str(t.get("section_id") or ""), []).append(t.get("content") or "")
    articles = []
    for i, s in enumerate(sections):
        title = (s.get("clean_title") or s.get("title") or "").strip() or f"섹션{i+1}"
        body = "\n".join(x for x in by_section.get(str(s.get("id") or ""), []) if x).strip()
        if not body:
            continue
        articles.append({
            "document_title": document_title,
            "article_no": f"p{s.get('page', 0)}-{i+1}",
            "article_title": title[:120],
            "text": body,
        })
    return articles


def extract_citations(articles: list[dict]) -> list[dict]:
    edges = []
    for a in articles:
        refs = set()
        for pattern, target in CITE_PATTERNS:
            for m in pattern.finditer(a["text"]):
                refs.add((target, f"제{m.group(1)}"))
        for target, no in sorted(refs):
            edges.append({"from_doc": a["document_title"], "from_no": a["article_no"], "to_doc": target, "to_no": no})
    return edges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace-id", default=WS_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    batches: list[tuple[list[dict], str, str, bool, str]] = []
    for fname, title, tier, doc_class in MD_SOURCES:
        arts = parse_md(DATASET_DIR / fname, title)
        batches.append((arts, tier, doc_class, True, "law_open_data_md"))
        print(f"  [{tier:9}/{doc_class}] {title[:34]:36} {len(arts)}개 조항")
    if OCR_JSON.exists():
        arts = parse_ocr_json(OCR_JSON, "금융광고규제 가이드라인")
        batches.append((arts, "guideline", "행정지도", False, "unlimited_ocr_gundam_unverified"))
        print(f"  [guideline/행정지도] 금융광고규제 가이드라인(OCR)              {len(arts)}개 섹션 (ocr_verified=FALSE)")

    all_articles = [a for arts, *_ in batches for a in arts]
    all_edges = []
    for arts, *_ in batches:
        all_edges.extend(extract_citations(arts))
    edge_summary = Counter((e["to_doc"][:14]) for e in all_edges)
    print(f"\n인용 엣지 {len(all_edges)}개: {dict(edge_summary)}")

    if args.dry_run:
        print("dry-run: 쓰기 없음")
        return 0

    load_local_env()
    from neo4j import GraphDatabase
    ws = args.workspace_id
    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    with driver.session() as s:
        for arts, tier, doc_class, verified, source in batches:
            rows = [{
                "id": stable_id("law_article_regulator", ws, a["document_title"], a["article_no"]),
                **a, "heading": f"{a['article_no']}({a['article_title']})",
            } for a in arts]
            s.run("""
                UNWIND $rows AS row
                MERGE (a:LawArticle {id: row.id, workspace_id: $ws})
                SET a.document_title = row.document_title, a.article_no = row.article_no,
                    a.article_title = row.article_title, a.heading = row.heading, a.text = row.text,
                    a.authority_tier = $tier, a.doc_class = $doc_class,
                    a.ocr_verified = $verified, a.source = $source, a.corpus_id = 'regulator_subordinate_20260702'
                """, rows=rows, ws=ws, tier=tier, doc_class=doc_class, verified=verified, source=source)
        edge_rows = [{
            "from_id": stable_id("law_article_regulator", ws, e["from_doc"], e["from_no"]),
            "to_doc": e["to_doc"], "to_no": e["to_no"],
        } for e in all_edges]
        n = s.run("""
            UNWIND $rows AS row
            MATCH (a:LawArticle {id: row.from_id, workspace_id: $ws})
            MATCH (b:LawArticle {workspace_id: $ws})
            WHERE b.document_title = row.to_doc AND b.article_no = row.to_no
            MERGE (a)-[r:CITES_ARTICLE {workspace_id: $ws, source: 'regulator_corpus_loader'}]->(b)
            RETURN count(r) AS n
            """, rows=edge_rows, ws=ws).single()["n"]
        total = s.run("MATCH (a:LawArticle {workspace_id:$ws, corpus_id:'regulator_subordinate_20260702'}) RETURN count(a) AS n", ws=ws).single()["n"]
        print(f"\n적재 완료: 조항 {total}개, 인용 엣지 {n}개")
    driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
