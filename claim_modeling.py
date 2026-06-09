"""Claim-level modeling helpers for expression qualifiers."""

from __future__ import annotations

from dataclasses import replace

from schemas import Claim, ClaimQualifier, ContextAnchor


FOLDABLE_QUALIFIER_ROLES = {
    "target_scope",
    "condition_scope",
    "certainty",
    "guarantee",
    "benefit_scope",
    "risk_downplay",
}

QUALIFIER_FOLD_ANCHOR_TYPES = {"target_consumer_anchor"}
QUALIFIER_PARENT_ANCHOR_TYPES = {"claim_anchor", "risk_anchor"}


def fold_qualifier_anchors_into_parent_claims(anchors: list[ContextAnchor], claims: list[Claim]) -> list[ContextAnchor]:
    """Fold generic scope/certainty/guarantee subspans into their parent claim.

    Concrete consumer segments can remain target-consumer anchors, but generic
    ad-scope expressions such as "누구나" should be judged as part of the claim
    they modify. The LLM extraction stage identifies those expressions as
    ClaimQualifier records; this helper uses that explicit model signal rather
    than hardcoded verdict rules.
    """

    qualifiers_by_claim = {claim.claim_id: claim.qualifiers for claim in claims}
    folded: list[ContextAnchor] = []
    for anchor in anchors:
        qualifiers = qualifiers_by_claim.get(anchor.claim_id, [])
        if should_fold_anchor(anchor, qualifiers):
            continue
        if anchor.anchor_type in QUALIFIER_PARENT_ANCHOR_TYPES:
            facts = dedupe([*anchor.facts, *qualifier_facts_for_anchor(anchor, qualifiers)])
            folded.append(replace(anchor, facts=facts))
        else:
            folded.append(anchor)
    return folded


def should_fold_anchor(anchor: ContextAnchor, qualifiers: list[ClaimQualifier]) -> bool:
    if anchor.anchor_type not in QUALIFIER_FOLD_ANCHOR_TYPES:
        return False
    anchor_text = normalize_text(anchor.span.text)
    return any(
        qualifier.role in FOLDABLE_QUALIFIER_ROLES and normalize_text(qualifier.text) == anchor_text
        for qualifier in qualifiers
    )


def qualifier_facts_for_anchor(anchor: ContextAnchor, qualifiers: list[ClaimQualifier]) -> list[str]:
    facts: list[str] = []
    for qualifier in qualifiers:
        if qualifier.role not in FOLDABLE_QUALIFIER_ROLES:
            continue
        if not qualifier_belongs_to_anchor(anchor, qualifier):
            continue
        facts.append(
            (
                f"ClaimQualifier role={qualifier.role} text='{qualifier.text}' "
                f"meaning='{qualifier.meaning}' risk_reason='{qualifier.risk_reason}'"
            )
        )
    return facts


def qualifier_belongs_to_anchor(anchor: ContextAnchor, qualifier: ClaimQualifier) -> bool:
    if normalize_text(qualifier.text) in normalize_text(anchor.span.text):
        return True
    return anchor.span.start <= qualifier.span.start and qualifier.span.end <= anchor.span.end


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_text(value: str) -> str:
    return "".join(str(value or "").split())
