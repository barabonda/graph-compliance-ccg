"""Policy-guided hypernym normalization using retrieved legal evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from llm_gateway import LLMGateway
from schemas import Claim, ContextAnchor, PolicyHypernymProposal, Span
from utils import stable_id, to_jsonable


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
    ) -> list[ContextAnchor]:
        allowed = {
            str(item["hypernym_id"]): str(item["name"])
            for item in policy_context.get("hypernyms", [])
            if item.get("hypernym_id") and item.get("name")
        }
        if not allowed:
            raise RuntimeError("PolicyHypernym vocabulary is empty; run the policy compiler before review.")
        schema = normalization_schema_for_allowed_ids(allowed.keys())
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
        result = self.llm.structured(
            name="graphcompliance_policy_normalization",
            schema=schema,
            system=(
                "You are doing policy-guided normalization for Korean financial-ad compliance. "
                "Create judgment anchors and map ad context entities/risks only to the provided "
                "PolicyHypernym vocabulary. The hypernym_id field is schema-restricted to approved ids; "
                "choose one of those ids exactly. Do not invent new hypernyms or ids. Mark support STRONG "
                "only when a provided Premise directly supports the mapping; otherwise mark WEAK. Keep only "
                "useful anchors."
            ),
            user=(
                "[claims]\n"
                f"{to_jsonable(claims)}\n\n"
                "[allowed_policy_hypernyms]\n"
                f"{allowed_rows}\n\n"
                "[policy_premises]\n"
                f"{policy_context.get('premises', [])[:80]}\n\n"
                "[supporting_policy_fragments]\n"
                f"{policy_context.get('fragments', [])[:40]}\n\n"
                f"Keep at most {top_n} hypernyms per anchor."
            ),
        )
        anchors: list[ContextAnchor] = []
        valid_claim_ids = {claim.claim_id for claim in claims}
        for index, item in enumerate(result["anchors"]):
            if item["claim_id"] not in valid_claim_ids:
                raise RuntimeError(f"LLM returned unknown claim_id for ContextAnchor: {item['claim_id']}")
            anchor_id = stable_id("anchor", review_run_id, index, item["claim_id"], item["text"])
            proposals: list[PolicyHypernymProposal] = []
            seen_hypernyms: set[str] = set()
            for h in item["hypernyms"]:
                hypernym_id = str(h["hypernym_id"])
                if hypernym_id not in allowed:
                    raise RuntimeError(f"LLM returned unknown PolicyHypernym id: {hypernym_id}")
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
        return anchors


def normalization_schema_for_allowed_ids(allowed_ids) -> dict[str, Any]:
    schema = deepcopy(NORMALIZATION_SCHEMA)
    ids = sorted(str(item) for item in allowed_ids)
    hypernym_item = (
        schema["properties"]["anchors"]["items"]["properties"]["hypernyms"]["items"]
    )
    hypernym_item["properties"]["hypernym_id"] = {"type": "string", "enum": ids}
    return schema
