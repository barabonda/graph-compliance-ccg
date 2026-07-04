"""Policy-guided hypernym normalization using retrieved legal evidence."""

from __future__ import annotations

from copy import deepcopy
import logging
import os
from typing import Any

from llm_gateway import LLMGateway
from schemas import Claim, ContextAnchor, PolicyHypernymProposal, Span
from utils import stable_id, to_jsonable


LOGGER = logging.getLogger(__name__)


NORMALIZATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "anchors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "anchor_type": {
                        "type": "string",
                        "enum": ["product_anchor", "claim_anchor", "risk_anchor", "target_consumer_anchor"],
                    },
                    "claim_id": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "text": {"type": "string"},
                    "facts": {"type": "array", "items": {"type": "string"}},
                    "hypernyms": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "hypernym_id": {"type": "string"},
                                "hypernym": {"type": "string"},
                                "support": {"type": "string", "enum": ["STRONG", "WEAK"]},
                                "confidence": {"type": "number"},
                                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                                "why": {"type": "string"},
                            },
                            "required": ["hypernym_id", "hypernym", "support", "confidence", "evidence_ids", "why"],
                        },
                    },
                },
                "required": ["anchor_type", "claim_id", "start", "end", "text", "facts", "hypernyms"],
            },
        }
    },
    "required": ["anchors"],
}


class PolicyGuidedNormalizer:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def normalize(
        self,
        *,
        review_run_id: str,
        claims: list[Claim],
        policy_context: dict[str, Any],
        top_n: int = 5,
        korean: bool = True,
    ) -> list[ContextAnchor]:
        allowed = {
            str(item["hypernym_id"]): str(item["name"])
            for item in policy_context.get("hypernyms", [])
            if item.get("hypernym_id") and item.get("name")
        }
        if not allowed:
            raise RuntimeError("PolicyHypernym vocabulary is empty; run the policy compiler before review.")
        schema = normalization_schema_for_allowed_ids(allowed.keys())
        model = os.environ.get("CCG_POLICY_NORMALIZATION_MODEL") or None
        timeout_seconds = float(os.environ.get("CCG_POLICY_NORMALIZATION_TIMEOUT_SECONDS", "420"))
        allowed_rows = [
            {
                "hypernym_id": item["hypernym_id"],
                "name": item["name"],
                "domain": item.get("domain", ""),
                "description": item.get("description", ""),
            }
            for item in policy_context.get("hypernyms", [])
            if item.get("hypernym_id") in allowed
        ]
        claim_view = normalization_claim_view(claims)
        premises = policy_context.get("premises", [])[:80]
        fragments = policy_context.get("fragments", [])[:40]
        LOGGER.info(
            "policy_normalization.prompt_components review_run_id=%s claims=%d claim_chars=%d "
            "hypernyms=%d hypernym_chars=%d premises=%d premise_chars=%d fragments=%d fragment_chars=%d",
            review_run_id,
            len(claim_view),
            len(str(claim_view)),
            len(allowed_rows),
            len(str(allowed_rows)),
            len(premises),
            len(str(premises)),
            len(fragments),
            len(str(fragments)),
        )
        result = self.llm.structured(
            name="graphcompliance_policy_normalization",
            schema=schema,
            system=(
                "You are doing policy-guided normalization for Korean financial-ad compliance. "
                "Create judgment anchors and map ad context entities/risks only to the provided "
                "PolicyHypernym vocabulary. The hypernym_id field is schema-restricted to approved ids; "
                "choose one of those ids exactly. Do not invent new hypernyms or ids. Mark support STRONG "
                "only when a provided Premise directly supports the mapping; otherwise mark WEAK. Keep only "
                "useful anchors. Do not create standalone target_consumer_anchor items for generic claim "
                "scope qualifiers such as '누구나', '전 고객', '조건 없이', '제한 없이', '무조건', '확정', "
                "or '보장'. Those expressions should remain inside the parent claim/risk anchor because "
                "their compliance meaning depends on the whole claim they modify. Use target_consumer_anchor "
                "only for concrete audience segments such as '고령층 고객', '중위험 투자자', or '소상공인'."
                # 비-KR(영어 우선) 관할: anchor text/span 은 원문 그대로(무번역),
                # facts·why 등 분석 필드는 영어로 — KR 프롬프트는 바이트 동일 유지.
                + (
                    ""
                    if korean
                    else " OUTPUT LANGUAGE OVERRIDE: this workspace reviews ads in a non-Korean "
                    "(English-first) jurisdiction. Anchor text/span values MUST be verbatim copies "
                    "from the original ad (never translate). Write all free-text analysis fields "
                    "(facts, why, explanations) in ENGLISH."
                )
            ),
            user=(
                "[claims]\n"
                f"{claim_view}\n\n"
                "[allowed_policy_hypernyms]\n"
                f"{allowed_rows}\n\n"
                "[policy_premises]\n"
                f"{premises}\n\n"
                "[supporting_policy_fragments]\n"
                f"{fragments}\n\n"
                f"Keep at most {top_n} hypernyms per anchor."
            ),
            timeout_seconds=timeout_seconds,
            model=model,
        )
        anchors: list[ContextAnchor] = []
        valid_claim_ids = {claim.claim_id for claim in claims}
        dropped_items = 0
        for index, item in enumerate(result["anchors"]):
            # Claude 비-strict 폴백(대형 enum 스키마가 strict 문법 한도를 넘는 경우)
            # 에서는 형태·enum이 문법으로 강제되지 않는다. 개별 불량 항목은 전체
            # 심사를 죽이는 대신 감사 로그와 함께 건너뛴다 — 전부 불량이면 실패.
            if not isinstance(item, dict) or item.get("claim_id") not in valid_claim_ids:
                dropped_items += 1
                LOGGER.warning(
                    "normalizer.anchor_dropped review_run_id=%s index=%d reason=invalid_item item=%s",
                    review_run_id,
                    index,
                    str(item)[:200],
                )
                continue
            anchor_id = stable_id("anchor", review_run_id, index, item["claim_id"], item["text"])
            proposals: list[PolicyHypernymProposal] = []
            seen_hypernyms: set[str] = set()
            for h in item["hypernyms"]:
                hypernym_id = str(h["hypernym_id"])
                if hypernym_id not in allowed:
                    dropped_items += 1
                    LOGGER.warning(
                        "normalizer.hypernym_dropped review_run_id=%s anchor_index=%d reason=unknown_hypernym_id id=%s",
                        review_run_id,
                        index,
                        hypernym_id,
                    )
                    continue
                if hypernym_id in seen_hypernyms:
                    continue
                seen_hypernyms.add(hypernym_id)
                confidence = float(h["confidence"])
                normalized_score = min(1.0, confidence + (0.3 if h["support"] == "STRONG" else 0.0))
                proposals.append(
                    PolicyHypernymProposal(
                        proposal_id=stable_id("hypernym", anchor_id, hypernym_id),
                        source_id=anchor_id,
                        hypernym_id=hypernym_id,
                        hypernym=allowed[hypernym_id],
                        support=h["support"],
                        confidence=confidence,
                        normalized_score=normalized_score,
                        evidence_ids=h["evidence_ids"],
                        why=h["why"],
                    )
                )
                if len(proposals) >= top_n:
                    break
            anchors.append(
                ContextAnchor(
                    anchor_id=anchor_id,
                    anchor_type=item["anchor_type"],
                    claim_id=item["claim_id"],
                    span=Span(start=item["start"], end=item["end"], text=item["text"]),
                    facts=item["facts"],
                    hypernyms=proposals,
                )
            )
        if dropped_items and not anchors:
            # 관용은 부분 불량까지 — 전량 불량이면 어휘 거버넌스 실패로 그대로 알린다.
            raise RuntimeError(
                "LLM returned no usable ContextAnchor items "
                f"({dropped_items} dropped: unknown claim_id/PolicyHypernym id or malformed shape)."
            )
        return anchors


def normalization_schema_for_allowed_ids(allowed_ids) -> dict[str, Any]:
    schema = deepcopy(NORMALIZATION_SCHEMA)
    ids = sorted(str(item) for item in allowed_ids)
    hypernym_item = (
        schema["properties"]["anchors"]["items"]["properties"]["hypernyms"]["items"]
    )
    hypernym_item["properties"]["hypernym_id"] = {"type": "string", "enum": ids}
    return schema


def normalization_claim_view(claims: list[Claim]) -> list[dict[str, Any]]:
    """Thin claim representation for policy normalization.

    The full Context Graph keeps entities and relations for audit, but policy
    hypernym normalization only needs the parent claim text, meaning/effect, and
    expression-level qualifiers. Passing the whole graph here made real review
    runs balloon into 100k+ character prompts after long disclosure extraction.
    """
    return [
        {
            "claim_id": claim.claim_id,
            "text": claim.text,
            "span": {
                "start": claim.span.start,
                "end": claim.span.end,
                "text": claim.span.text,
            },
            "meaning": claim.meaning,
            "implicature": claim.implicature,
            "consumer_effect": claim.consumer_effect,
            "risk_hypernym": claim.risk_hypernym,
            "risk_severity": claim.risk_severity,
            "sentence_id": claim.sentence_id,
            "qualifiers": [
                {
                    "text": qualifier.text,
                    "role": qualifier.role,
                    "meaning": qualifier.meaning,
                    "risk_reason": qualifier.risk_reason,
                    "confidence": qualifier.confidence,
                    "prominence_tier": qualifier.prominence_tier,
                }
                for qualifier in claim.qualifiers
            ],
        }
        for claim in claims
    ]
