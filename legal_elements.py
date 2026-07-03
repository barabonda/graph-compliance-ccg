"""Legal-element feature modeling for Korean financial-ad CU retrieval.

This module does not make compliance verdicts. It converts the already
LLM-extracted Context Graph signals into a typed evidence layer so CU retrieval
can require positive legal elements before sending candidates to the LLM judge.
"""

from __future__ import annotations

from dataclasses import replace

from schemas import AnchorFeatureSet, Claim, ContextAnchor, CULegalElementProfile
from utils import stable_id


CANONICAL_POSITIVE_FEATURES = [
    "universal_scope_expression",
    "unconditional_expression",
    "certainty_expression",
    "guarantee_expression",
    "benefit_claim_expression",
    "risk_downplay_expression",
    "comparison_target",
    "comparative_superiority_claim",
    "coercion_or_tie_in_context",
    "collateral_or_guarantee_demand",
    "sales_process_context",
    "past_performance_claim",
    "product_fact_assertion",
]

CANONICAL_ACTION_TYPES = [
    "guarantee_or_return_misleading",
    "condition_or_scope_missing",
    "comparison_ad",
    "unfair_superior_position_sales",
    "required_disclosure_missing",
    "past_performance_or_future_return",
    "product_fact_mismatch",
    "suitability_or_target_solicitation",
    "review_procedure",
    "sanction_only",
]

FEATURE_BY_QUALIFIER_ROLE = {
    "target_scope": "universal_scope_expression",
    "condition_scope": "unconditional_expression",
    "certainty": "certainty_expression",
    "guarantee": "guarantee_expression",
    "benefit_scope": "benefit_claim_expression",
    "risk_downplay": "risk_downplay_expression",
}

# 한정어(qualifier)의 극성. 한정어가 '존재'한다고 위험 표현이 되는 게 아니다 —
# "우대조건 충족 시"는 조건을 '고지'한 것이지 '무조건 표현'이 아니다(의미 반전 방지).
# 아래 단정 토큰을 qualifier 가 직접 말할 때만 해당 role 의 위험 feature 가 즉시 성립.
ASSERTIVE_QUALIFIER_TOKENS: dict[str, tuple[str, ...]] = {
    "condition_scope": ("조건 없이", "무조건", "조건 불문", "제한 없이", "심사 없이", "묻지도"),
    "target_scope": ("누구나", "누구에게나", "모든", "전원", "어떤 분이라도"),
    # "반드시"는 제외 — "반드시 확인/유의"(보호 문구) vs "반드시 수익"(오인)로 문맥
    # 의존적이라 단독 토큰으로는 오탐. 확정·확실·보장·단정만 확정적 오인 신호로 본다.
    "certainty": ("확정", "확실", "보장", "단정"),
    "guarantee": ("보장", "보전", "확정"),
}

ACTION_TYPES_BY_FEATURE = {
    "guarantee_expression": ["guarantee_or_return_misleading"],
    "certainty_expression": ["guarantee_or_return_misleading", "condition_or_scope_missing"],
    "unconditional_expression": ["condition_or_scope_missing", "guarantee_or_return_misleading"],
    "universal_scope_expression": ["condition_or_scope_missing"],
    "benefit_claim_expression": ["required_disclosure_missing"],
    "risk_downplay_expression": ["required_disclosure_missing", "guarantee_or_return_misleading"],
    "comparison_target": ["comparison_ad"],
    "comparative_superiority_claim": ["comparison_ad"],
    "coercion_or_tie_in_context": ["unfair_superior_position_sales"],
    "collateral_or_guarantee_demand": ["unfair_superior_position_sales"],
    "past_performance_claim": ["past_performance_or_future_return"],
    "product_fact_assertion": ["product_fact_mismatch", "required_disclosure_missing"],
}

ACTION_TYPE_PRIORITY = {
    "guarantee_or_return_misleading": 1,
    "condition_or_scope_missing": 2,
    "required_disclosure_missing": 3,
    "past_performance_or_future_return": 4,
    "comparison_ad": 5,
    "product_fact_mismatch": 6,
    "suitability_or_target_solicitation": 7,
    "unfair_superior_position_sales": 8,
}

ACTION_TYPE_BY_PROFILE_TEXT = [
    ("comparison_ad", ["비교", "우월", "최고", "1위", "타사", "다른 금융", "비교광고"]),
    ("unfair_superior_position_sales", ["우월적 지위", "꺾기", "강요", "담보", "보증", "편익 요구", "연대보증"]),
    ("past_performance_or_future_return", ["과거", "수익률", "운용실적", "조기상환", "미래 수익"]),
    ("guarantee_or_return_misleading", ["보장", "확정", "손실보전", "이익보장", "수익 보장"]),
    ("condition_or_scope_missing", ["조건", "제한", "누구나", "무조건", "가입대상", "우대"]),
    ("required_disclosure_missing", ["설명", "고지", "표시", "필수", "수수료", "금리", "예금자보호"]),
    ("review_procedure", ["심의필", "준법감시인", "사전승인", "심의"]),
    ("sanction_only", ["과태료", "제재", "벌점", "시정요구", "사용중단"]),
]

REQUIRED_FEATURES_BY_ACTION_TYPE = {
    "comparison_ad": ["comparison_target", "comparative_superiority_claim"],
    "unfair_superior_position_sales": [
        "coercion_or_tie_in_context",
        "collateral_or_guarantee_demand",
        "sales_process_context",
    ],
    "guarantee_or_return_misleading": ["guarantee_expression", "certainty_expression"],
    "condition_or_scope_missing": ["unconditional_expression", "universal_scope_expression"],
    "past_performance_or_future_return": ["past_performance_claim"],
    "product_fact_mismatch": ["product_fact_assertion"],
}

ALLOWED_FEATURES_BY_ACTION_TYPE = {
    "guarantee_or_return_misleading": [
        "guarantee_expression",
        "certainty_expression",
        "risk_downplay_expression",
        "benefit_claim_expression",
        "unconditional_expression",
    ],
    "condition_or_scope_missing": [
        "unconditional_expression",
        "universal_scope_expression",
        "certainty_expression",
        "benefit_claim_expression",
        "product_fact_assertion",
    ],
    "required_disclosure_missing": [
        "benefit_claim_expression",
        "product_fact_assertion",
        "guarantee_expression",
        "certainty_expression",
        "unconditional_expression",
        "universal_scope_expression",
        "risk_downplay_expression",
        "past_performance_claim",
    ],
    "comparison_ad": ["comparison_target", "comparative_superiority_claim"],
    "unfair_superior_position_sales": [
        "coercion_or_tie_in_context",
        "collateral_or_guarantee_demand",
        "sales_process_context",
    ],
    "past_performance_or_future_return": ["past_performance_claim", "benefit_claim_expression", "certainty_expression"],
    "product_fact_mismatch": ["product_fact_assertion", "benefit_claim_expression"],
    "suitability_or_target_solicitation": ["universal_scope_expression", "sales_process_context"],
    "review_procedure": [],
    "sanction_only": [],
}

FEATURE_ALIAS_RULES = [
    ("comparison_target", ["비교 대상", "비교대상", "비교 기준", "비교기준", "타사", "타 은행", "다른 금융"]),
    ("comparative_superiority_claim", ["우월", "우수", "유리", "높은", "최고", "1위", "객관적 근거 없이 비교"]),
    ("coercion_or_tie_in_context", ["강요", "끼워", "꺾기", "의사에 반하여", "원하지 않는", "부당한 요구"]),
    ("collateral_or_guarantee_demand", ["담보", "보증 요구", "연대보증", "부당 보증"]),
    ("sales_process_context", ["판매 과정", "영업 과정", "계약 체결 과정", "우월적 지위"]),
    ("past_performance_claim", ["과거", "운용실적", "수익률", "조기상환", "성과"]),
    ("guarantee_expression", ["보장", "이익보장", "손실보전", "손실 보전", "수익 보장", "확정 보장"]),
    # "반드시" alone is often a protective disclosure ("반드시 확인/유의").
    # Treat it as certainty only when it asserts payout, benefit, or return.
    ("certainty_expression", ["확정", "단정", "확실", "반드시 지급", "반드시 받", "반드시 수익", "무조건 지급", "오인"]),
    ("unconditional_expression", ["조건 없이", "무조건", "제한 없이", "제한조건", "우대조건", "조건", "제한"]),
    ("universal_scope_expression", ["누구나", "모든", "전체", "가입대상", "대상 범위", "소비자군"]),
    ("risk_downplay_expression", ["안정", "안전", "위험 없음", "손실 없음", "리스크 낮"]),
    ("benefit_claim_expression", ["혜택", "금리", "수익", "수수료", "한도", "우대", "이자율"]),
    # 절차·보호 문서어("약관","상품설명서 확인")는 사실 '단정'이 아니라 확인 권유라
    # 제외 — 실제 상품 사실(금리·수수료·한도·수익률 등)만 product_fact_assertion 신호.
    ("product_fact_assertion", ["상품유형", "상품 유형", "금리", "이자율", "수익률", "수수료", "한도", "가입기간", "예금자보호"]),
]


def attach_anchor_feature_sets(
    *,
    review_run_id: str,
    anchors: list[ContextAnchor],
    claims: list[Claim],
    relations: list | None = None,
) -> tuple[list[ContextAnchor], list[AnchorFeatureSet]]:
    claim_by_id = {claim.claim_id: claim for claim in claims}
    enriched: list[ContextAnchor] = []
    feature_sets: list[AnchorFeatureSet] = []
    for anchor in anchors:
        feature_set = build_anchor_feature_set(
            review_run_id=review_run_id,
            anchor=anchor,
            claim=claim_by_id.get(anchor.claim_id),
            relations=relations,
        )
        feature_sets.append(feature_set)
        enriched.append(replace(anchor, feature_set=feature_set))
    return enriched, feature_sets


def claim_has_relation_hedge(claim: Claim | None, relations: list | None) -> bool:
    """이 claim 의 문장에 QUALIFIES/MITIGATES 관계로 연결된 문장이 있는가.

    헤지 인식은 표면 토큰이 아니라 이미 추출된 그래프 관계를 우선 신뢰한다 —
    어휘가 바뀌어도 관계 타입은 안정적이고, 이중 유지보수(토큰 사전)를 피한다.
    """
    if not claim or not getattr(claim, "sentence_id", "") or not relations:
        return False
    sid = claim.sentence_id
    for rel in relations:
        rel_type = str(getattr(rel, "relation_type", "") or (rel.get("relation_type") if isinstance(rel, dict) else ""))
        if rel_type not in ("QUALIFIES", "MITIGATES"):
            continue
        src = getattr(rel, "source_sentence_id", None) or (rel.get("source_sentence_id") if isinstance(rel, dict) else None)
        tgt = getattr(rel, "target_sentence_id", None) or (rel.get("target_sentence_id") if isinstance(rel, dict) else None)
        if sid in (src, tgt):
            return True
    return False


def build_anchor_feature_set(
    *, review_run_id: str, anchor: ContextAnchor, claim: Claim | None, relations: list | None = None
) -> AnchorFeatureSet:
    """토큰 매칭은 '위험 확신 성립'의 1차 스크리닝일 뿐이다.

    - 명시 단정어(ASSERTIVE) 매칭 → 위험 확정(feature 발화).
    - 비매칭 → '안전 확정'이 아니라 '판단 불충분': feature 미발화로 rule_satisfied 가
      낮아지고 judge 가 INSUFFICIENT→needs_review 로 처리한다(과탐/미탐 균형 원칙).
    - 헤지 인식은 그래프 관계(QUALIFIES/MITIGATES)를 우선 신뢰 — 관계가 있으면
      토큰 없이도 헤지 존재로 evidence 에 기록하고, 단정어와 공존하면 충돌로
      표시해 judge 가 최종 판단하게 한다.
    """
    positive_features: list[str] = []
    evidence: list[str] = []
    haystack = normalized_text(" ".join([anchor.span.text, *anchor.facts, *(h.hypernym for h in anchor.hypernyms)]))
    relation_hedge = claim_has_relation_hedge(claim, relations)
    if relation_hedge:
        evidence.append("관계 기반 헤지: 이 claim 문장에 QUALIFIES/MITIGATES 연결 문장 존재")
    if claim:
        for qualifier in claim.qualifiers:
            if normalized_text(qualifier.text) not in haystack and not (
                anchor.span.start <= qualifier.span.start and qualifier.span.end <= anchor.span.end
            ):
                continue
            feature = FEATURE_BY_QUALIFIER_ROLE.get(qualifier.role)
            if not feature:
                continue
            assertive = ASSERTIVE_QUALIFIER_TOKENS.get(qualifier.role)
            qualifier_text = normalized_text(qualifier.text)
            if assertive is None:
                # benefit_scope·risk_downplay 등 극성 무해 role — 기존 동작 유지.
                positive_features.append(feature)
                evidence.append(f"ClaimQualifier role={qualifier.role} text='{qualifier.text}'")
            elif any(token in qualifier_text for token in assertive):
                positive_features.append(feature)
                if relation_hedge:
                    evidence.append(
                        f"ClaimQualifier role={qualifier.role} 명시 단정 표현 text='{qualifier.text}' — 단, 관계 기반 헤지와 충돌: judge 최종 판단"
                    )
                else:
                    evidence.append(f"ClaimQualifier role={qualifier.role} 명시 단정 표현 text='{qualifier.text}'")
            else:
                evidence.append(f"완화 한정어(문맥 의존, 결정론 미발화 → judge 판단): role={qualifier.role} text='{qualifier.text}'")
        risk_text = normalized_text(" ".join([claim.risk_hypernym, claim.meaning, claim.implicature, claim.consumer_effect]))
        if any(token in risk_text for token in ["과거", "수익률", "운용실적", "조기상환"]):
            positive_features.append("past_performance_claim")
            evidence.append("Claim risk/meaning indicates past-performance reliance.")
        if any(token in risk_text for token in ["비교", "타사", "우월", "1위"]):
            positive_features.extend(["comparison_target", "comparative_superiority_claim"])
            evidence.append("Claim risk/meaning indicates comparative advertising.")
        if any(token in risk_text for token in ["강요", "끼워", "담보", "보증 요구", "연대보증"]):
            positive_features.append("coercion_or_tie_in_context")
            evidence.append("Claim risk/meaning indicates coercion or tie-in sales context.")
    if any(token in haystack for token in ["비교", "타사", "우월", "1위"]):
        positive_features.extend(["comparison_target", "comparative_superiority_claim"])
        evidence.append("Anchor text/facts include comparative advertising signal.")
    if any(token in haystack for token in ["강요", "끼워", "담보 요구", "연대보증"]):
        positive_features.append("coercion_or_tie_in_context")
        evidence.append("Anchor text/facts include unfair superior-position sales signal.")
    if any(token in haystack for token in ["금리", "%", "퍼센트", "수익", "수수료", "한도"]):
        positive_features.append("product_fact_assertion")
        evidence.append("Anchor text/facts include a fact-like product assertion.")

    action_types = sorted(
        {
            action_type
            for feature in positive_features
            for action_type in ACTION_TYPES_BY_FEATURE.get(feature, [])
        },
        key=lambda item: ACTION_TYPE_PRIORITY.get(item, 100),
    )
    missing_context: list[str] = []
    if "comparison_ad" not in action_types:
        missing_context.append("no_comparison_target")
    if "unfair_superior_position_sales" not in action_types:
        missing_context.append("no_superior_position_or_coercion_context")
    if anchor.anchor_type in {"product_anchor", "target_consumer_anchor"}:
        missing_context.append("scope_anchor_not_actionable_by_default")
    return AnchorFeatureSet(
        feature_set_id=stable_id("anchor_feature_set", review_run_id, anchor.anchor_id),
        anchor_id=anchor.anchor_id,
        action_types=dedupe(action_types),
        positive_features=dedupe(positive_features),
        missing_context=dedupe(missing_context),
        evidence=dedupe(evidence),
    )


def build_legal_element_profile_from_compiler_row(
    *,
    workspace_id: str,
    cu_id: str,
    action_type: str,
    required_positive_features: list[str],
    applicability_scope: list[str],
    risk_title: str,
    exception_eligible: bool,
    rationale: str,
) -> dict[str, object]:
    normalized_action_type = action_type or "required_disclosure_missing"
    normalized_features = canonicalize_required_features(required_positive_features, action_type=normalized_action_type)
    return {
        "id": stable_id("cu_legal_element_profile", workspace_id, cu_id, normalized_action_type, risk_title),
        "cu_id": cu_id,
        "action_type": normalized_action_type,
        "required_positive_features": normalized_features,
        "applicability_scope": dedupe(applicability_scope),
        "risk_title": risk_title,
        "exception_eligible": bool(exception_eligible),
        "rationale": rationale,
    }


def infer_legal_profile_from_text(*, workspace_id: str, cu_id: str, text: str) -> dict[str, object]:
    action_type = "required_disclosure_missing"
    for candidate_action_type, tokens in ACTION_TYPE_BY_PROFILE_TEXT:
        if any(token in text for token in tokens):
            action_type = candidate_action_type
            break
    required = REQUIRED_FEATURES_BY_ACTION_TYPE.get(action_type, [])
    exception_eligible = any(token in text for token in ["예외", "고지", "설명", "조건", "예금자보호", "상품설명"])
    risk_title = risk_title_for(action_type, text)
    return build_legal_element_profile_from_compiler_row(
        workspace_id=workspace_id,
        cu_id=cu_id,
        action_type=action_type,
        required_positive_features=required,
        applicability_scope=[],
        risk_title=risk_title,
        exception_eligible=exception_eligible,
        rationale="Derived from compiler CU profile text as an offline legal-element scaffold.",
    )


def candidate_satisfies_legal_elements(
    *,
    feature_set: AnchorFeatureSet | None,
    profile: CULegalElementProfile | None,
) -> tuple[bool, list[str], list[str]]:
    if not profile:
        return False, [], ["missing_cu_legal_element_profile"]
    if profile.action_type in {"review_procedure", "sanction_only"}:
        return False, [], ["non_actionable_legal_element_profile"]
    features = set(feature_set.positive_features if feature_set else [])
    action_types = set(feature_set.action_types if feature_set else [])
    if profile.action_type not in action_types and profile.required_positive_features:
        return False, [], [f"action_type_not_supported:{profile.action_type}"]
    required = set(canonicalize_required_features(profile.required_positive_features, action_type=profile.action_type))
    matched = sorted(required & features)
    if required and not matched:
        return False, [], sorted(required)
    if profile.action_type == "comparison_ad" and not features.intersection({"comparison_target", "comparative_superiority_claim"}):
        return False, matched, ["comparison_target", "comparative_superiority_claim"]
    if profile.action_type == "unfair_superior_position_sales" and not features.intersection(
        {"coercion_or_tie_in_context", "collateral_or_guarantee_demand", "sales_process_context"}
    ):
        return False, matched, ["coercion_or_tie_in_context", "collateral_or_guarantee_demand", "sales_process_context"]
    return True, matched, []


def profile_from_row(row: dict[str, object]) -> CULegalElementProfile | None:
    profile_id = str(row.get("legal_profile_id") or "")
    if not profile_id:
        return None
    return CULegalElementProfile(
        profile_id=profile_id,
        cu_id=str(row.get("cu_id") or ""),
        action_type=str(row.get("action_type") or ""),
        required_positive_features=canonicalize_required_features(
            [str(item) for item in row.get("required_positive_features") or []],
            action_type=str(row.get("action_type") or ""),
        ),
        applicability_scope=[str(item) for item in row.get("applicability_scope") or []],
        risk_title=str(row.get("risk_title") or ""),
        exception_eligible=bool(row.get("exception_eligible")),
        rationale=str(row.get("legal_profile_rationale") or ""),
    )


def canonicalize_required_features(items: list[str], *, action_type: str = "") -> list[str]:
    canonical: list[str] = []
    for item in items or []:
        canonical.extend(canonicalize_required_feature(item))
    canonical = dedupe(canonical)
    allowed = ALLOWED_FEATURES_BY_ACTION_TYPE.get(action_type)
    if allowed is None:
        return canonical
    allowed_set = set(allowed)
    return [feature for feature in canonical if feature in allowed_set]


def canonicalize_required_feature(item: str) -> list[str]:
    """요건 문구 하나 → 대표 canonical feature 하나.

    요건명은 하나의 행위요건을 지칭하므로 첫(우선순위 최상의) 매칭만 취한다 —
    "수익을 반드시 지급받을 수 있다고 오인"이 certainty 와 benefit 둘 다에
    걸릴 때 부수 어휘(수익)로 요건이 불어나는 것을 막는다.
    """
    text = " ".join(str(item or "").split())
    if not text:
        return []
    if text in CANONICAL_POSITIVE_FEATURES:
        return [text]
    normalized = normalized_text(text)
    for feature, aliases in FEATURE_ALIAS_RULES:
        if any(normalized_text(alias) in normalized for alias in aliases):
            return [feature]
    return []


def unknown_canonical_features(items: list[str]) -> list[str]:
    return sorted({str(item) for item in items or [] if str(item) not in CANONICAL_POSITIVE_FEATURES})


def risk_title_for(action_type: str, text: str) -> str:
    if action_type == "guarantee_or_return_misleading":
        return "확정·보장 표현으로 수익 보장 오인 가능"
    if action_type == "condition_or_scope_missing":
        return "대상·조건 제한 누락으로 무조건 혜택 오인 가능"
    if action_type == "comparison_ad":
        return "비교·우월 표현에 대한 객관 근거 필요"
    if action_type == "unfair_superior_position_sales":
        return "우월적 지위 이용 또는 끼워팔기 정황 검토"
    if action_type == "past_performance_or_future_return":
        return "과거 성과를 미래 수익으로 오인시킬 가능성"
    if action_type == "review_procedure":
        return "광고 심의·심의필 절차 확인 필요"
    if action_type == "sanction_only":
        return "제재 근거 정보"
    short = " ".join(text.split())[:42]
    return f"필수 고지·설명 근거 확인 필요: {short}" if short else "필수 고지·설명 근거 확인 필요"


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def normalized_text(value: str) -> str:
    return "".join(str(value or "").split())
