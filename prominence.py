"""Prominence and disclosure-link artifacts for financial-ad review.

This module does not make final compliance verdicts. It computes evidence
diagnostics that help the Product Fact Graph and Disclosure Gate distinguish
between a disclosure that is present and a disclosure that is prominent enough
to mitigate a benefit claim.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from disclosure_catalog import DISCLOSURE_PROFILES
from schemas import Claim, ReviewInput, SentenceUnit
from utils import stable_id


PROMINENCE_SCORE = {
    "headline": 4,
    "subcopy": 3,
    "body": 2,
    "unknown": 2,
    "footnote": 1,
}

BENEFIT_ROLES = {"benefit_claim", "comparison_claim", "cta"}
DISCLOSURE_ROLES = {"condition_disclosure", "protection_disclosure", "risk_disclosure", "review_procedure"}
LEGACY_CONDITION_CHECK_IDS = {
    "deposit_rate_condition",
    "deposit_term",
    "deposit_tax_basis",
    "depositor_protection_limit",
    "product_document_notice",
    "loan_rate_range",
    "loan_screening",
    "loan_fee",
    "investment_loss_risk",
    "past_performance_warning",
}
PROMINENCE_REQUIRED_CHECK_IDS = {
    check_id
    for check_id, profile in DISCLOSURE_PROFILES.items()
    if profile.prominence_required
} | LEGACY_CONDITION_CHECK_IDS


def build_prominence_artifacts(
    *,
    review_input: ReviewInput,
    sentence_units: list[SentenceUnit],
    claims: list[Claim],
    product_fact_context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    benefit_sentences = [sentence for sentence in sentence_units if sentence.role in BENEFIT_ROLES]
    disclosure_sentences = [sentence for sentence in sentence_units if sentence.role in DISCLOSURE_ROLES]
    disclosure_links = build_disclosure_links(benefit_sentences, disclosure_sentences)
    diagnostics = build_diagnostics(
        review_input=review_input,
        benefit_sentences=benefit_sentences,
        disclosure_links=disclosure_links,
        product_fact_context=product_fact_context,
    )
    updated_product_fact_context = apply_comparison_diagnostics(
        product_fact_context=product_fact_context,
        claims=claims,
        diagnostics=diagnostics,
    )
    analysis = {
        "benefit_sentence_count": len(benefit_sentences),
        "disclosure_sentence_count": len(disclosure_sentences),
        "weak_disclosure_count": sum(1 for item in diagnostics if item.get("diagnostic_code") == "PROMINENCE_INSUFFICIENT"),
        "missing_disclosure_count": sum(1 for item in diagnostics if item.get("diagnostic_code") == "DISCLOSURE_MISSING"),
        "tier_scale": PROMINENCE_SCORE,
    }
    return analysis, disclosure_links, diagnostics, updated_product_fact_context


def build_disclosure_links(
    benefit_sentences: list[SentenceUnit],
    disclosure_sentences: list[SentenceUnit],
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for benefit in benefit_sentences:
        for disclosure in disclosure_sentences:
            if not disclosure_relevant_to_benefit(benefit, disclosure):
                continue
            benefit_score = prominence_score(benefit.prominence_tier)
            disclosure_score = prominence_score(disclosure.prominence_tier)
            gap = benefit_score - disclosure_score
            links.append(
                {
                    "link_id": stable_id("disclosure_link", benefit.sentence_id, disclosure.sentence_id),
                    "relation_type": "MITIGATES_DISCLOSURE_FOR",
                    "benefit_sentence_id": benefit.sentence_id,
                    "benefit_text": benefit.text,
                    "benefit_prominence_tier": benefit.prominence_tier,
                    "disclosure_sentence_id": disclosure.sentence_id,
                    "disclosure_text": disclosure.text,
                    "disclosure_prominence_tier": disclosure.prominence_tier,
                    "prominence_gap": gap,
                    "status": "PROMINENCE_INSUFFICIENT" if gap > 0 else "PROMINENCE_OK",
                }
            )
    return links


def build_diagnostics(
    *,
    review_input: ReviewInput,
    benefit_sentences: list[SentenceUnit],
    disclosure_links: list[dict[str, Any]],
    product_fact_context: dict[str, Any],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    # 혜택 문구 기준으로 묶어, 동등 이상 위계의 관련 고지가 하나라도 있으면
    # 충족으로 본다. 약한 고지 페어가 따로 있다는 이유만으로 발화하면 같은
    # 위계 고지를 이미 갖춘 문안까지 전부 위반으로 집계된다.
    links_by_benefit: dict[str, list[dict[str, Any]]] = {}
    for link in disclosure_links:
        links_by_benefit.setdefault(str(link["benefit_sentence_id"]), []).append(link)
    for benefit_links in links_by_benefit.values():
        best_link = min(benefit_links, key=lambda row: row["prominence_gap"])
        if best_link["prominence_gap"] <= 0:
            continue
        diagnostics.append(
            {
                "diagnostic_id": stable_id("prominence_diagnostic", best_link["link_id"]),
                "diagnostic_code": "PROMINENCE_INSUFFICIENT",
                "severity": "MEDIUM",
                "benefit_sentence_id": best_link["benefit_sentence_id"],
                "disclosure_sentence_id": best_link["disclosure_sentence_id"],
                "prominence_gap": best_link["prominence_gap"],
                "message": "고지는 존재하지만 혜택 문구보다 낮은 위계로 표시되어 완화 근거가 약합니다.",
                "evidence": f"{best_link['benefit_text']} / {best_link['disclosure_text']}",
            }
        )

    missing_checks = [
        row
        for row in product_fact_context.get("disclosure_checks", []) or []
        if row.get("check_id") in PROMINENCE_REQUIRED_CHECK_IDS
        and row.get("gate_status") != "OFF"
        and row.get("status") in {"MISSING", "PRESENT_BUT_NEGATED", "IN_PRODUCT_DOC_ONLY"}
    ]
    if benefit_sentences and missing_checks:
        for check in missing_checks:
            diagnostics.append(
                {
                    "diagnostic_id": stable_id("prominence_diagnostic", review_input.content_text, check.get("check_id", "")),
                    "diagnostic_code": "DISCLOSURE_MISSING",
                    "check_id": str(check.get("check_id") or ""),
                    "severity": "MEDIUM",
                    "benefit_sentence_id": benefit_sentences[0].sentence_id,
                    "disclosure_sentence_id": "",
                    "prominence_gap": None,
                    "message": f"{check.get('label', '필수고지')} 고지가 문안에서 확인되지 않습니다.",
                    "evidence": benefit_sentences[0].text,
                }
            )
    return diagnostics


def apply_comparison_diagnostics(
    *,
    product_fact_context: dict[str, Any],
    claims: list[Claim],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    context = deepcopy(product_fact_context)
    claim_by_id = {claim.claim_id: claim for claim in claims}
    weak_sentence_ids = {str(row.get("benefit_sentence_id")) for row in diagnostics if row.get("diagnostic_code") == "PROMINENCE_INSUFFICIENT"}
    missing_sentence_ids = {str(row.get("benefit_sentence_id")) for row in diagnostics if row.get("diagnostic_code") == "DISCLOSURE_MISSING"}
    claim_facts = {row.get("claim_fact_id"): row for row in context.get("claim_facts", []) or []}
    updated_results: list[dict[str, Any]] = []
    for result in context.get("comparison_results", []) or []:
        row = dict(result)
        claim_fact = claim_facts.get(row.get("claim_fact_id"))
        claim = claim_by_id.get(str(claim_fact.get("claim_id") if claim_fact else ""))
        sentence_id = claim.sentence_id if claim else ""
        if row.get("status") == "SUPPORTED" and sentence_id in weak_sentence_ids:
            row["status"] = "PROMINENCE_INSUFFICIENT"
            row["rationale"] = append_reason(row.get("rationale", ""), "관련 고지가 더 낮은 표시 위계에 있어 현저성이 부족합니다.")
        elif row.get("status") == "SUPPORTED" and sentence_id in missing_sentence_ids:
            row["status"] = "CONDITION_MISSING"
            row["rationale"] = append_reason(row.get("rationale", ""), "상품 사실은 일부 일치하지만 필요한 조건/고지가 문안에 부족합니다.")
        updated_results.append(row)
    context["comparison_results"] = updated_results
    context["prominence_diagnostics"] = diagnostics
    return context


def disclosure_relevant_to_benefit(benefit: SentenceUnit, disclosure: SentenceUnit) -> bool:
    text = f"{benefit.text} {disclosure.text}"
    if any(token in text for token in ["금리", "이자", "수익", "%", "우대", "조건", "기간", "예금자보호", "보호"]):
        return True
    return disclosure.index > benefit.index


def prominence_score(tier: str) -> int:
    return PROMINENCE_SCORE.get(tier or "unknown", PROMINENCE_SCORE["unknown"])


def append_reason(existing: object, extra: str) -> str:
    text = str(existing or "").strip()
    if not text:
        return extra
    if extra in text:
        return text
    return f"{text} {extra}"
