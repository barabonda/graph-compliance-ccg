"""Track C(표현·브랜드세이프티) 실판정 스텁 유닛테스트.

Neo4j/LLM 없이 검증: (1) UnSmile 라벨 → 6축 매핑, (2) 후보 게이팅(임베딩+키워드),
(3) additive shape(기존 track_c_summary 키 유지 + judgments 추가), (4) env 게이트 계약.
"""
from __future__ import annotations

import pytest

import load_risk_corpus
from risk_context import (
    CURATED_SEED_AXES,
    RISK_AXES,
    UNSMILE_AXIS_MAPPING,
    track_c_active_summary,
    track_c_extension_summary,
)
from schemas import ReviewInput
from track_c import _gather_candidates, run_track_c, track_c_enabled

KR_WS = "graphcompliance_mvp_jb_20260530"
AXIS_IDS = {axis["id"] for axis in RISK_AXES}


# ---------------------------------------------------------------------------
# (1) 매핑
# ---------------------------------------------------------------------------
def test_unsmile_mapping_targets_are_known_axes() -> None:
    for label, axis_id in UNSMILE_AXIS_MAPPING.items():
        if axis_id is None:
            continue
        assert axis_id in AXIS_IDS, f"{label} 이 알 수 없는 축 {axis_id} 로 매핑됨"


def test_unsmile_mapping_covers_group_labels_and_drops_non_group() -> None:
    # 집단 표적 라벨은 축으로, 비집단(악플/욕설·clean·개인지칭)은 매핑하지 않음.
    assert UNSMILE_AXIS_MAPPING["여성/가족"] == "risk_axis_gender_stereotype"
    assert UNSMILE_AXIS_MAPPING["성소수자"] == "risk_axis_gender_stereotype"
    assert UNSMILE_AXIS_MAPPING["인종/국적"] == "risk_axis_disability_race_migration"
    assert UNSMILE_AXIS_MAPPING["지역"] == "risk_axis_disability_race_migration"
    assert UNSMILE_AXIS_MAPPING["악플/욕설"] is None
    assert UNSMILE_AXIS_MAPPING["clean"] is None
    assert UNSMILE_AXIS_MAPPING["개인지칭"] is None


def test_build_batches_shape_and_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    # 실제 파일 대신 소형 합성 UnSmile 행으로 변환 검증.
    fake_rows = []
    for i in range(300):
        row = {label: "0" for label in UNSMILE_AXIS_MAPPING}
        row["문장"] = f"여성 혐오 예문 {i}"
        row["여성/가족"] = "1"
        row["개인지칭"] = "1" if i % 2 == 0 else "0"
        row["__split"] = "train"
        fake_rows.append(row)
    monkeypatch.setattr(load_risk_corpus, "read_unsmile_rows", lambda: fake_rows)

    axes, patterns, cases, mitigations, stats = load_risk_corpus.build_batches(cap=200, exemplars=15, seed=42)

    assert {a["id"] for a in axes} == AXIS_IDS
    assert len(mitigations) == len(RISK_AXES)
    # cap 준수: 젠더 축 CasePrecedent <= 200.
    gender_cases = [c for c in cases if c["axis_id"] == "risk_axis_gender_stereotype"]
    assert len(gender_cases) == 200
    # 데이터셋 유래 CasePrecedent 는 출처·라이선스 각인.
    assert gender_cases[0]["source_dataset"] == "unsmile_v1.0"
    assert gender_cases[0]["license"] == "CC-BY-NC-ND-4.0"
    assert gender_cases[0]["source_label"] == "여성/가족"
    # curated 시드 축은 dataset 예문이 없어도 example_patterns 로 근거를 확보.
    for axis_id in CURATED_SEED_AXES:
        seed_cases = [c for c in cases if c["axis_id"] == axis_id]
        assert seed_cases, f"{axis_id} 는 curated 시드 CasePrecedent 를 가져야 함"
        assert seed_cases[0]["source_dataset"] == "curated_ccg_seed"
    # 데이터셋 예문 일부가 RiskPattern(임베딩 앵커)으로 승격됨.
    exemplar_patterns = [p for p in patterns if p["pattern_kind"] == "dataset_exemplar"]
    assert exemplar_patterns


# ---------------------------------------------------------------------------
# (2) 후보 게이팅
# ---------------------------------------------------------------------------
def test_gather_candidates_embedding_and_keyword_gate() -> None:
    patterns = [
        {"axis_id": "risk_axis_gender_stereotype", "axis_label": "젠더 고정관념",
         "keywords": ["페미"], "embedding": [1.0, 0.0]},
        {"axis_id": "risk_axis_investment_gamification", "axis_label": "투자/도박화",
         "keywords": ["대박"], "embedding": [0.0, 1.0]},
    ]
    sentences = ["이건 페미 얘기", "완전 무관한 문장"]
    # 첫 문장: 젠더 패턴과 동일 방향(유사도 1.0) + '페미' 키워드 히트.
    # 둘째 문장: 어느 패턴과도 직교(유사도 0) + 키워드 없음 → 후보 아님.
    sentence_embeddings = [[1.0, 0.0], [0.0, 0.0]]
    candidates = _gather_candidates(
        sentences=sentences, sentence_embeddings=sentence_embeddings, patterns=patterns
    )
    assert "risk_axis_gender_stereotype" in candidates
    assert "risk_axis_investment_gamification" not in candidates
    bucket = candidates["risk_axis_gender_stereotype"]
    assert "페미" in bucket["matched_keywords"]
    assert bucket["best_similarity"] >= 0.99
    assert "이건 페미 얘기" in bucket["flagged_sentences"]


# ---------------------------------------------------------------------------
# (3) additive shape + (4) env 게이트
# ---------------------------------------------------------------------------
def test_active_summary_is_additive_over_extension() -> None:
    extension = track_c_extension_summary()
    active = track_c_active_summary(judgments=[{"axis_id": "x"}], candidate_diagnostics={"candidate_axes": []})
    # 기존 키를 모두 유지(프론트 경계면 무회귀).
    for key in extension:
        assert key in active, f"additive 위반: 기존 키 {key} 누락"
    assert active["track"] == "C"
    assert active["status"] == "active"
    assert active["risk_axes"] == extension["risk_axes"]
    # 추가분.
    assert active["judgments"] == [{"axis_id": "x"}]
    assert "candidate_diagnostics" in active


def _review_input() -> ReviewInput:
    return ReviewInput(
        dataset_item_id="t1", title="t", content_text="여성은 살림이나 해라",
        channel="c", source_type="", product_group="auto", selected_product_id="",
        selected_product_name="", workspace_id=KR_WS, language="ko",
    )


def test_gate_off_returns_static_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CCG_ENABLE_TRACK_C", raising=False)
    assert track_c_enabled() is False
    summary = run_track_c(
        review_input=_review_input(), sentences=["여성은 살림이나 해라"],
        retriever=object(), llm=object(), enabled=None,
    )
    assert summary["status"] == "extension_ready"
    assert "judgments" not in summary


class _NotReadyRetriever:
    def track_c_data_ready(self, *, workspace_id: str) -> dict[str, int]:
        return {"axes": 0, "patterns": 0, "cases": 0}


def test_gate_on_without_data_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # 게이트 켜졌는데 코퍼스 없음 → 조용한 스킵이 아니라 명시적 에러(계약).
    with pytest.raises(RuntimeError, match="코퍼스"):
        run_track_c(
            review_input=_review_input(), sentences=["여성은 살림이나 해라"],
            retriever=_NotReadyRetriever(), llm=object(), enabled=True,
        )


class _FakeEmbedder:
    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _FakeRetriever:
    embedder = _FakeEmbedder()

    def track_c_data_ready(self, *, workspace_id: str) -> dict[str, int]:
        return {"axes": 6, "patterns": 10, "cases": 400}

    def track_c_patterns(self, *, workspace_id: str) -> list[dict]:
        return [{"axis_id": "risk_axis_gender_stereotype", "axis_label": "젠더 고정관념",
                 "keywords": ["여성"], "embedding": [1.0, 0.0]}]

    def track_c_precedents(self, *, workspace_id: str, axis_id: str, limit: int = 8) -> list[dict]:
        return [{"id": "cp1", "text": "여성 비하 예문", "source_dataset": "unsmile_v1.0",
                 "license": "CC-BY-NC-ND-4.0", "source_label": "여성/가족", "source_url": "",
                 "targets_individual": False}]

    def track_c_mitigation(self, *, workspace_id: str, axis_id: str) -> str:
        return "성별 고정관념 표현을 기능 중심으로 재작성"


class _FakeLLM:
    def structured(self, **kwargs) -> dict:
        return {"axis_applies": True, "severity": "HIGH", "risk_score": 0.9,
                "why": "선례 cp1 과 유사한 여성 비하", "cited_precedent_ids": ["cp1"],
                "flagged_spans": ["여성은 살림이나 해라"]}


def test_gate_on_with_data_produces_grounded_judgment() -> None:
    summary = run_track_c(
        review_input=_review_input(), sentences=["여성은 살림이나 해라"],
        retriever=_FakeRetriever(), llm=_FakeLLM(), enabled=True,
    )
    assert summary["status"] == "active"
    assert len(summary["judgments"]) == 1
    judgment = summary["judgments"][0]
    assert judgment["axis_id"] == "risk_axis_gender_stereotype"
    # 근거 CasePrecedent 인용 필수.
    assert judgment["cited_precedents"] and judgment["cited_precedents"][0]["id"] == "cp1"
    assert judgment["mitigation"]


class _FakeLLMNoCitation(_FakeLLM):
    def structured(self, **kwargs) -> dict:
        result = super().structured(**kwargs)
        result["cited_precedent_ids"] = ["nonexistent"]
        return result


def test_judgment_dropped_when_no_valid_precedent_cited() -> None:
    # LLM 이 축 적용된다 해도 유효한 선례를 인용 못하면 판정 미생성(근거 없는 판정 금지).
    summary = run_track_c(
        review_input=_review_input(), sentences=["여성은 살림이나 해라"],
        retriever=_FakeRetriever(), llm=_FakeLLMNoCitation(), enabled=True,
    )
    assert summary["status"] == "active"
    assert summary["judgments"] == []
