"""Track C extension contract for expression and brand-safety risk."""

from __future__ import annotations

from typing import Any


RISK_AXES: list[dict[str, Any]] = [
    {
        "id": "risk_axis_sensitive_history_disaster",
        "label": "역사·민족·참사",
        "example_patterns": ["민감일자 프로모션", "참사 상업화"],
        "mitigation": "민감일자/참사 연상 표현을 프로모션 혜택과 분리하고 중립적 상품 정보로 수정합니다.",
    },
    {
        "id": "risk_axis_hate_symbol_meme",
        "label": "커뮤니티 밈·혐오 상징",
        "example_patterns": ["혐오 상징", "논란 밈 차용"],
        "mitigation": "상징/밈 해석 가능성이 있는 표현은 원본 맥락을 검증하고 대체 이미지를 사용합니다.",
    },
    {
        "id": "risk_axis_gender_stereotype",
        "label": "젠더 고정관념",
        "example_patterns": ["역할 고정관념", "외모/가사 중심 묘사"],
        "mitigation": "소비자 역할을 성별이 아니라 상품 이용 상황과 기능 중심으로 재작성합니다.",
    },
    {
        "id": "risk_axis_disability_race_migration",
        "label": "장애·인종·이주민",
        "example_patterns": ["차별적 일반화", "낙인 표현"],
        "mitigation": "사람 중심 언어를 사용하고 특정 집단에 대한 부정적 귀인을 제거합니다.",
    },
    {
        "id": "risk_axis_crime_suicide_disaster_commercialization",
        "label": "범죄·자살·참사 상업화",
        "example_patterns": ["죽음/범죄 소재 유머화", "피해 상업화"],
        "mitigation": "피해·죽음·범죄 소재를 혜택이나 이벤트 표현과 결합하지 않습니다.",
    },
    {
        "id": "risk_axis_investment_gamification",
        "label": "투자/도박화",
        "example_patterns": ["한방 수익", "룰렛/챌린지", "대박 기회"],
        "mitigation": "게임성·투기성 표현 대신 조건, 위험, 목적 중심 정보로 수정합니다.",
    },
]


# UnSmile(집단별 세분 라벨) → risk_context 6축 매핑.
# 매핑 원칙: 각 라벨을 가장 가까운 기존 축으로 귀속시키되, 축을 새로 만들지 않고
# 기존 축의 "확장"으로 흡수한다(spec: 매핑 불가 라벨은 별도 축이 아니라 기존 축 확장으로).
# - 여성/가족·남성·성소수자 → 젠더/성정체성 고정관념 축
# - 인종/국적·지역·연령·종교 → 집단 낙인(장애·인종·이주민) 축의 확장(지역/연령/종교 낙인 포함)
# - 기타 혐오 → 커뮤니티 밈·혐오 상징 축(포괄 catch-all)
# - 악플/욕설·clean → 집단 표적이 아니므로 축에 매핑하지 않음(CasePrecedent 미시드)
# - 개인지칭 → 축이 아니라 CasePrecedent의 보조 속성(targets_individual)으로만 보존
UNSMILE_AXIS_MAPPING: dict[str, str | None] = {
    "여성/가족": "risk_axis_gender_stereotype",
    "남성": "risk_axis_gender_stereotype",
    "성소수자": "risk_axis_gender_stereotype",
    "인종/국적": "risk_axis_disability_race_migration",
    "지역": "risk_axis_disability_race_migration",
    "연령": "risk_axis_disability_race_migration",
    "종교": "risk_axis_disability_race_migration",
    "기타 혐오": "risk_axis_hate_symbol_meme",
    "악플/욕설": None,
    "clean": None,
    "개인지칭": None,
}

# 축별 키워드 게이트(후보 검색 보조 — 임베딩 유사도와 OR로 결합). 실제 판정은 LLM이 한다;
# 이 목록은 "어떤 축을 LLM에게 물어볼지" 후보를 넓히는 저비용 신호일 뿐이다.
AXIS_KEYWORD_GATE: dict[str, list[str]] = {
    "risk_axis_gender_stereotype": ["여자", "남자", "여성", "남성", "페미", "김치녀", "한남", "성소수자", "게이", "레즈", "주부", "살림", "맘충"],
    "risk_axis_disability_race_migration": ["장애", "외국인", "이주민", "조선족", "흑인", "난민", "노인", "틀딱", "전라도", "경상도", "지역감정", "개독", "무슬림", "짱깨"],
    "risk_axis_hate_symbol_meme": ["혐오", "일베", "극혐", "벌레", "충", "짤", "밈"],
    "risk_axis_sensitive_history_disaster": ["세월호", "참사", "위안부", "학살", "일제", "5·18", "광주민주화", "이태원"],
    "risk_axis_crime_suicide_disaster_commercialization": ["자살", "죽음", "살인", "범죄", "극단적", "피해자"],
    "risk_axis_investment_gamification": ["대박", "한방", "잭팟", "룰렛", "챌린지", "인생역전", "로또", "한탕"],
}

# 시드 데이터셋 라벨이 없는(금융광고 브랜드세이프티 고유) 축 — CasePrecedent은 curated 시드로 채운다.
CURATED_SEED_AXES: set[str] = {
    "risk_axis_sensitive_history_disaster",
    "risk_axis_crime_suicide_disaster_commercialization",
    "risk_axis_investment_gamification",
}


def track_c_extension_summary() -> dict[str, Any]:
    """게이트 OFF(기본) 시의 정적 안내. 기존 계약을 그대로 유지(무회귀)."""
    return {
        "track": "C",
        "status": "extension_ready",
        "routing_use": "brand_safety_risk_and_review_queue",
        "message": "현재 보유 금융광고/법률/상품 데이터 기반 v1에서는 Track A/B를 우선 적용하고, Track C는 별도 사례 데이터 연결 후 활성화합니다.",
        "required_nodes": ["RiskAxis", "RiskPattern", "CasePrecedent", "MitigationAdvice"],
        "risk_axes": RISK_AXES,
    }


def track_c_active_summary(
    *,
    judgments: list[dict[str, Any]],
    candidate_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """게이트 ON + 데이터 적재 시의 실판정 요약.

    **additive 계약**: track_c_extension_summary()의 모든 기존 키(track, status,
    routing_use, message, required_nodes, risk_axes)를 유지하고 `judgments`,
    `candidate_diagnostics` 만 추가한다. status 는 "active" 로 바뀐다. 프론트
    OverallTab 은 track_c_summary 를 Record<string, unknown> 으로만 소비하므로
    키 추가는 안전하다.
    """
    return {
        "track": "C",
        "status": "active",
        "routing_use": "brand_safety_risk_and_review_queue",
        "message": (
            "공개 한국어 혐오표현 데이터셋(UnSmile) 시드로 표현·브랜드세이프티 6축을 실판정합니다. "
            "후보 축에 대해서만 CasePrecedent 근거를 인용해 판정하며, 근거가 없으면 판정을 생성하지 않습니다."
        ),
        "required_nodes": ["RiskAxis", "RiskPattern", "CasePrecedent", "MitigationAdvice"],
        "risk_axes": RISK_AXES,
        "judgments": judgments,
        "candidate_diagnostics": candidate_diagnostics,
    }
