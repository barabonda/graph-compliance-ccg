"""LLM context-graph extraction for advertising drafts."""

from __future__ import annotations

from typing import Any

from llm_gateway import LLMGateway
from schemas import Claim, ContextEntity, ContextRelation, ContextTriple, ReviewInput, Span
from utils import stable_id


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "text": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "meaning": {"type": "string"},
                    "implicature": {"type": "string"},
                    "consumer_effect": {"type": "string"},
                    "risk_hypernym": {"type": "string"},
                    "risk_severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    "entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "entity_type": {
                                    "type": "string",
                                    "enum": ["product", "feature", "claim_object", "metric", "target_consumer", "channel", "disclosure", "other"],
                                },
                                "start": {"type": "integer"},
                                "end": {"type": "integer"},
                            },
                            "required": ["name", "entity_type", "start", "end"],
                        },
                    },
                    "relations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "source_name": {"type": "string"},
                                "predicate": {"type": "string"},
                                "target_name": {"type": "string"},
                                "evidence": {"type": "string"},
                            },
                            "required": ["source_name", "predicate", "target_name", "evidence"],
                        },
                    },
                },
                "required": [
                    "text",
                    "start",
                    "end",
                    "meaning",
                    "implicature",
                    "consumer_effect",
                    "risk_hypernym",
                    "risk_severity",
                    "entities",
                    "relations",
                ],
            },
        }
    },
    "required": ["claims"],
}


class LLMContextExtractor:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def extract(self, review_input: ReviewInput, *, review_run_id: str) -> list[Claim]:
        result = self.llm.structured(
            name="graphcompliance_context_extraction",
            schema=EXTRACTION_SCHEMA,
            system=(
                "You are a Korean financial-advertising context graph extractor. "
                "Convert the ad draft into policy-alignable graph facts. Do not judge compliance. "
                "Extract atomic claims, exact source spans, entities, factual relations, literal meaning, "
                "likely implicature, consumer effect, and a concise policy-level risk hypernym. "
                "Use the original text only; do not invent facts. Reply JSON only. "
                "Extraction recall is critical: every material benefit, rate, fee, guarantee, safety, "
                "approval, eligibility, past-performance, recommendation, and disclosure statement must be "
                "represented as a separate Claim when it has a distinct compliance meaning. "
                "Do not collapse a risky claim into a later mitigating disclosure. For example, extract "
                "'최고 연 5.0% 금리를 확정 제공' as its own benefit/definitive-rate claim even if a later "
                "sentence says rates may vary by conditions. Also extract the later condition disclosure as "
                "a separate disclosure claim. Mandatory disclosures such as depositor-protection limits are "
                "mitigating disclosure claims unless they imply unlimited principal/return guarantees."
            ),
            user=(
                f"[title]\n{review_input.title}\n\n"
                f"[channel]\n{review_input.channel}\n\n"
                f"[content_text]\n{review_input.content_text}"
            ),
        )
        claims: list[Claim] = []
        for index, item in enumerate(result["claims"]):
            claim_id = stable_id("claim", review_run_id, index, item["text"], item["start"], item["end"])
            entities = [
                ContextEntity(
                    entity_id=stable_id("entity", claim_id, entity["name"], entity["start"], entity["end"]),
                    name=entity["name"],
                    entity_type=entity["entity_type"],
                    span=Span(start=entity["start"], end=entity["end"], text=entity["name"]),
                )
                for entity in item["entities"]
            ]
            by_name = {entity.name: entity.entity_id for entity in entities}
            relations = [
                ContextRelation(
                    source_id=by_name.get(rel["source_name"], stable_id("entity_ref", claim_id, rel["source_name"])),
                    predicate=rel["predicate"],
                    target_id=by_name.get(rel["target_name"], stable_id("entity_ref", claim_id, rel["target_name"])),
                    evidence=rel["evidence"],
                )
                for rel in item["relations"]
            ]
            claims.append(
                Claim(
                    claim_id=claim_id,
                    text=item["text"],
                    span=Span(start=item["start"], end=item["end"], text=item["text"]),
                    meaning=item["meaning"],
                    implicature=item["implicature"],
                    consumer_effect=item["consumer_effect"],
                    risk_hypernym=item["risk_hypernym"],
                    risk_severity=item["risk_severity"],
                    entities=entities,
                    relations=relations,
                )
            )
        return claims


def build_context_triples(*, review_run_id: str, claims: list[Claim]) -> list[ContextTriple]:
    """Materialize extracted claim facts as auditable ER triples."""
    triples: list[ContextTriple] = []
    for claim in claims:
        triples.extend(
            [
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, claim.claim_id, "DENOTES", claim.meaning),
                    claim_id=claim.claim_id,
                    subject=claim.text,
                    predicate="DENOTES",
                    object=claim.meaning,
                    evidence=claim.text,
                    subject_type="Claim",
                    object_type="Meaning",
                ),
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, claim.claim_id, "IMPLIES", claim.implicature),
                    claim_id=claim.claim_id,
                    subject=claim.meaning,
                    predicate="IMPLIES",
                    object=claim.implicature,
                    evidence=claim.text,
                    subject_type="Meaning",
                    object_type="Implicature",
                ),
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, claim.claim_id, "CAN_MISLEAD", claim.consumer_effect),
                    claim_id=claim.claim_id,
                    subject=claim.implicature,
                    predicate="CAN_MISLEAD",
                    object=claim.consumer_effect,
                    evidence=claim.text,
                    subject_type="Implicature",
                    object_type="ConsumerEffect",
                ),
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, claim.claim_id, "RAISES", claim.risk_hypernym),
                    claim_id=claim.claim_id,
                    subject=claim.text,
                    predicate="RAISES",
                    object=claim.risk_hypernym,
                    evidence=claim.text,
                    subject_type="Claim",
                    object_type="RiskNode",
                ),
            ]
        )
        entity_by_id = {entity.entity_id: entity for entity in claim.entities}
        for relation in claim.relations:
            source = entity_by_id.get(relation.source_id)
            target = entity_by_id.get(relation.target_id)
            subject = source.name if source else relation.source_id
            obj = target.name if target else relation.target_id
            triples.append(
                ContextTriple(
                    triple_id=stable_id(
                        "triple",
                        review_run_id,
                        claim.claim_id,
                        subject,
                        relation.predicate,
                        obj,
                        relation.evidence,
                    ),
                    claim_id=claim.claim_id,
                    subject=subject,
                    predicate=relation.predicate,
                    object=obj,
                    evidence=relation.evidence,
                    subject_type=source.entity_type if source else "ContextEntity",
                    object_type=target.entity_type if target else "ContextEntity",
                )
            )
    return triples
