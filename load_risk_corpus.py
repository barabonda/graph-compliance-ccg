"""Track C(표현·브랜드세이프티) 리스크 코퍼스 적재.

공개 한국어 혐오표현 데이터셋 **UnSmile**(Smilegate AI, CC-BY-NC-ND 4.0) 시드를
risk_context.py 의 6개 리스크 축으로 매핑해 그래프에 적재한다.

적재 노드/관계:
    (RiskAxis)-[:HAS_PATTERN]->(RiskPattern)      # 임베딩 매칭 앵커(후보 검색용)
    (RiskAxis)-[:HAS_PRECEDENT]->(CasePrecedent)  # 판정 근거로 인용될 예문(출처·라이선스 각인)
    (RiskAxis)-[:HAS_MITIGATION]->(MitigationAdvice)

**적재 대상 DB**: 로컬 기본 DB(NEO4J_URI/NEO4J_DATABASE). Track C 코퍼스는 CCG 소유
데이터이므로 심사 산출물과 같은 로컬 DB에 저장한다. 팀 공용 Aura(KR 법령 코퍼스)에는
쓰지 않는다("팀 DB에 새 노드/엣지 생성 금지" 합의 준수). Track C 검색도 이 로컬 DB를
직접 읽는다(retriever._session_for 의 팀-Aura 라우팅을 우회).

라이선스: UnSmile 데이터셋은 CC-BY-NC-ND 4.0(상업 이용 제약). 본 적재는 MVP 연구/심사
시드 용도이며, 각 CasePrecedent 는 source_dataset/license/source_label/source_url 을
보존한다. 자세한 확인 기록은 _workspace_trackc/dataset_license.md 참조.

Usage:
    python load_risk_corpus.py [--workspace-id WS] [--cap 200] [--exemplars 15]
                               [--seed 42] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import random
from pathlib import Path
from typing import Any

from env_loader import load_local_env
from risk_context import (
    AXIS_KEYWORD_GATE,
    CURATED_SEED_AXES,
    RISK_AXES,
    UNSMILE_AXIS_MAPPING,
)
from utils import normalize_space, stable_id

LOGGER = logging.getLogger(__name__)

WS_DEFAULT = "graphcompliance_mvp_jb_20260530"
UNSMILE_DIR = Path(__file__).resolve().parent / "data" / "risk_corpus" / "unsmile"
UNSMILE_FILES = [
    ("unsmile_train_v1.0.tsv", "train"),
    ("unsmile_valid_v1.0.tsv", "valid"),
]
UNSMILE_SOURCE_URL = "https://github.com/smilegate-ai/korean_unsmile_dataset"
UNSMILE_LICENSE = "CC-BY-NC-ND-4.0"
UNSMILE_SOURCE = "unsmile_v1.0"

DEFAULT_CASE_CAP = 200
DEFAULT_EXEMPLARS = 15
INDIVIDUAL_COL = "개인지칭"

CORPUS_ID = "risk_corpus_unsmile_20260704"


def read_unsmile_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for fname, split in UNSMILE_FILES:
        path = UNSMILE_DIR / fname
        if not path.exists():
            raise FileNotFoundError(
                f"UnSmile 파일이 없습니다: {path}. data/risk_corpus/unsmile/ 아래에 "
                "unsmile_train_v1.0.tsv / unsmile_valid_v1.0.tsv 를 내려받으세요."
            )
        with path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for raw in reader:
                raw["__split"] = split
                rows.append(raw)
    return rows


def axis_precedents(
    rows: list[dict[str, str]],
    *,
    cap: int,
    rng: random.Random,
) -> dict[str, list[dict[str, Any]]]:
    """UnSmile 행 → 축별 CasePrecedent 후보(중복 제거 + 축당 cap 샘플링)."""
    by_axis_texts: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, set[str]] = {}
    for row in rows:
        text = normalize_space(row.get("문장", ""))
        if not text:
            continue
        targets_individual = row.get(INDIVIDUAL_COL, "0").strip() == "1"
        for label, axis_id in UNSMILE_AXIS_MAPPING.items():
            if axis_id is None:
                continue
            if row.get(label, "0").strip() != "1":
                continue
            bucket = by_axis_texts.setdefault(axis_id, [])
            seen_axis = seen.setdefault(axis_id, set())
            if text in seen_axis:
                continue
            seen_axis.add(text)
            bucket.append(
                {
                    "text": text,
                    "source_dataset": UNSMILE_SOURCE,
                    "license": UNSMILE_LICENSE,
                    "source_label": label,
                    "source_url": UNSMILE_SOURCE_URL,
                    "targets_individual": targets_individual,
                    "split": row["__split"],
                }
            )
    # 대표성 샘플링: 축당 cap 이내로 결정론적 셔플 후 절단(전량 적재 금지).
    for axis_id, bucket in by_axis_texts.items():
        rng.shuffle(bucket)
        by_axis_texts[axis_id] = bucket[:cap]
    return by_axis_texts


def build_batches(
    *,
    cap: int,
    exemplars: int,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """축/패턴/사례/완화 노드 페이로드를 만든다(임베딩·DB 쓰기 없이 순수 변환)."""
    rng = random.Random(seed)
    rows = read_unsmile_rows()
    precedents_by_axis = axis_precedents(rows, cap=cap, rng=rng)

    axis_nodes: list[dict[str, Any]] = []
    pattern_nodes: list[dict[str, Any]] = []
    case_nodes: list[dict[str, Any]] = []
    mitigation_nodes: list[dict[str, Any]] = []
    stats: dict[str, int] = {}

    for axis in RISK_AXES:
        axis_id = axis["id"]
        keywords = AXIS_KEYWORD_GATE.get(axis_id, [])
        axis_nodes.append(
            {
                "id": axis_id,
                "label": axis["label"],
                "keywords": keywords,
                "example_patterns": axis["example_patterns"],
            }
        )
        mitigation_nodes.append(
            {
                "id": stable_id("mitigation", axis_id),
                "axis_id": axis_id,
                "text": axis["mitigation"],
            }
        )
        # 1) 큐레이션 패턴(대표 표현) — 임베딩 앵커.
        for phrase in axis["example_patterns"]:
            pattern_nodes.append(
                {
                    "id": stable_id("risk_pattern", axis_id, "curated", phrase),
                    "axis_id": axis_id,
                    "text": phrase,
                    "pattern_kind": "curated",
                }
            )
        precedents = precedents_by_axis.get(axis_id, [])
        if axis_id in CURATED_SEED_AXES:
            # 시드 데이터셋에 해당 라벨이 없는(금융광고 브랜드세이프티 고유) 축은
            # example_patterns 를 CasePrecedent(curated 시드)로 채워 판정 근거를 확보한다.
            for phrase in axis["example_patterns"]:
                case_nodes.append(
                    {
                        "id": stable_id("case_precedent", axis_id, "curated", phrase),
                        "axis_id": axis_id,
                        "text": phrase,
                        "source_dataset": "curated_ccg_seed",
                        "license": "internal",
                        "source_label": axis["label"],
                        "source_url": "",
                        "targets_individual": False,
                        "split": "curated",
                    }
                )
        else:
            # 2) 데이터셋 대표 예문 일부를 RiskPattern(임베딩 앵커)으로 승격 —
            #    짧은 큐레이션 문구보다 실제 문장이 광고 문장과의 유사도 신호가 강하다.
            for case in precedents[:exemplars]:
                pattern_nodes.append(
                    {
                        "id": stable_id("risk_pattern", axis_id, "dataset", case["text"]),
                        "axis_id": axis_id,
                        "text": case["text"],
                        "pattern_kind": "dataset_exemplar",
                    }
                )
            # 3) 전체 CasePrecedent(판정 근거로 인용).
            for case in precedents:
                case_nodes.append(
                    {
                        "id": stable_id("case_precedent", axis_id, case["source_label"], case["text"]),
                        "axis_id": axis_id,
                        **case,
                    }
                )
        stats[axis["label"]] = len(precedents) if axis_id not in CURATED_SEED_AXES else len(axis["example_patterns"])

    return axis_nodes, pattern_nodes, case_nodes, mitigation_nodes, stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Track C 리스크 코퍼스 적재(UnSmile 시드)")
    parser.add_argument("--workspace-id", default=WS_DEFAULT)
    parser.add_argument("--cap", type=int, default=DEFAULT_CASE_CAP, help="축당 CasePrecedent 상한")
    parser.add_argument("--exemplars", type=int, default=DEFAULT_EXEMPLARS, help="축당 데이터셋 승격 RiskPattern 수")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="임베딩·DB 쓰기 없이 통계만 출력")
    args = parser.parse_args()

    axis_nodes, pattern_nodes, case_nodes, mitigation_nodes, stats = build_batches(
        cap=args.cap, exemplars=args.exemplars, seed=args.seed
    )

    LOGGER.info("=== Track C 코퍼스 변환 결과 ===")
    LOGGER.info("RiskAxis=%d RiskPattern=%d CasePrecedent=%d MitigationAdvice=%d",
                len(axis_nodes), len(pattern_nodes), len(case_nodes), len(mitigation_nodes))
    for label, count in stats.items():
        LOGGER.info("  [%s] CasePrecedent %d개", label, count)

    if args.dry_run:
        LOGGER.info("dry-run: 임베딩/쓰기 없음")
        return 0

    load_local_env()
    from ccg_embeddings import EmbeddingGateway
    from neo4j import GraphDatabase

    uri = os.environ.get("NEO4J_URI", "")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not uri or not user or not password:
        raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, NEO4J_PASSWORD 가 필요합니다(fallback 없음).")

    embedder = EmbeddingGateway()
    LOGGER.info("RiskPattern %d개 임베딩 중...", len(pattern_nodes))
    embeddings = embedder.embed_many([node["text"] for node in pattern_nodes])
    for node, vector in zip(pattern_nodes, embeddings):
        node["embedding"] = vector

    ws = args.workspace_id
    database = os.environ.get("NEO4J_DATABASE") or None
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        session = driver.session(database=database) if database else driver.session()
        with session:
            session.run(
                """
                UNWIND $rows AS row
                MERGE (a:RiskAxis {id: row.id, workspace_id: $ws})
                SET a.label = row.label, a.keywords = row.keywords,
                    a.example_patterns = row.example_patterns, a.corpus_id = $corpus
                """,
                rows=axis_nodes, ws=ws, corpus=CORPUS_ID,
            )
            session.run(
                """
                UNWIND $rows AS row
                MERGE (p:RiskPattern {id: row.id, workspace_id: $ws})
                SET p.text = row.text, p.pattern_kind = row.pattern_kind,
                    p.embedding = row.embedding, p.corpus_id = $corpus
                WITH p, row
                MATCH (a:RiskAxis {id: row.axis_id, workspace_id: $ws})
                MERGE (a)-[:HAS_PATTERN]->(p)
                """,
                rows=pattern_nodes, ws=ws, corpus=CORPUS_ID,
            )
            session.run(
                """
                UNWIND $rows AS row
                MERGE (c:CasePrecedent {id: row.id, workspace_id: $ws})
                SET c.text = row.text, c.source_dataset = row.source_dataset,
                    c.license = row.license, c.source_label = row.source_label,
                    c.source_url = row.source_url, c.targets_individual = row.targets_individual,
                    c.split = row.split, c.corpus_id = $corpus
                WITH c, row
                MATCH (a:RiskAxis {id: row.axis_id, workspace_id: $ws})
                MERGE (a)-[:HAS_PRECEDENT]->(c)
                """,
                rows=case_nodes, ws=ws, corpus=CORPUS_ID,
            )
            session.run(
                """
                UNWIND $rows AS row
                MERGE (m:MitigationAdvice {id: row.id, workspace_id: $ws})
                SET m.text = row.text, m.corpus_id = $corpus
                WITH m, row
                MATCH (a:RiskAxis {id: row.axis_id, workspace_id: $ws})
                MERGE (a)-[:HAS_MITIGATION]->(m)
                """,
                rows=mitigation_nodes, ws=ws, corpus=CORPUS_ID,
            )
            counts = session.run(
                """
                MATCH (a:RiskAxis {workspace_id: $ws, corpus_id: $corpus})
                OPTIONAL MATCH (a)-[:HAS_PATTERN]->(p:RiskPattern)
                OPTIONAL MATCH (a)-[:HAS_PRECEDENT]->(c:CasePrecedent)
                OPTIONAL MATCH (a)-[:HAS_MITIGATION]->(m:MitigationAdvice)
                RETURN count(DISTINCT a) AS axes, count(DISTINCT p) AS patterns,
                       count(DISTINCT c) AS cases, count(DISTINCT m) AS mitigations
                """,
                ws=ws, corpus=CORPUS_ID,
            ).single()
        LOGGER.info(
            "적재 완료(로컬 DB): RiskAxis=%d RiskPattern=%d CasePrecedent=%d MitigationAdvice=%d",
            counts["axes"], counts["patterns"], counts["cases"], counts["mitigations"],
        )
    finally:
        driver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
