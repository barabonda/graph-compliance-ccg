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


def track_c_extension_summary() -> dict[str, Any]:
    return {
        "track": "C",
        "status": "extension_ready",
        "routing_use": "brand_safety_risk_and_review_queue",
        "message": "현재 보유 금융광고/법률/상품 데이터 기반 v1에서는 Track A/B를 우선 적용하고, Track C는 별도 사례 데이터 연결 후 활성화합니다.",
        "required_nodes": ["RiskAxis", "RiskPattern", "CasePrecedent", "MitigationAdvice"],
        "risk_axes": RISK_AXES,
    }
