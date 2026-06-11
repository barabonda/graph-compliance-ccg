"""LLM context-graph extraction for advertising drafts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_gateway import LLMGateway
from schemas import (
    Claim,
    ClaimQualifier,
    ContextEntity,
    ContextFrame,
    ContextInfluence,
    ContextRelation,
    ContextTriple,
    InterSentenceRelation,
    ReviewInput,
    SentenceUnit,
    Span,
)
from utils import stable_id


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "context_frame": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "primary_message": {"type": "string"},
                "product_purpose": {"type": "string"},
                "tone": {"type": "string"},
                "representative_consumer_impression": {"type": "string"},
                "risk_axes": {"type": "array", "items": {"type": "string"}},
                "overall_risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            },
            "required": [
                "summary",
                "primary_message",
                "product_purpose",
                "tone",
                "representative_consumer_impression",
                "risk_axes",
                "overall_risk_level",
            ],
        },
        "sentence_units": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "text": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "role": {
                        "type": "string",
                        "enum": [
                            "launch_notice",
                            "benefit_claim",
                            "condition_disclosure",
                            "risk_disclosure",
                            "protection_disclosure",
                            "cta",
                            "comparison_claim",
                            "review_procedure",
                            "other",
                        ],
                    },
                    "local_meaning": {"type": "string"},
                    "context_effect": {"type": "string"},
                    "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    "prominence_tier": {"type": "string", "enum": ["headline", "subcopy", "body", "footnote", "unknown"]},
                },
                "required": [
                    "index",
                    "text",
                    "start",
                    "end",
                    "role",
                    "local_meaning",
                    "context_effect",
                    "risk_level",
                    "prominence_tier",
                ],
            },
        },
        "inter_sentence_relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_index": {"type": "integer"},
                    "target_index": {"type": "integer"},
                    "relation_type": {
                        "type": "string",
                        "enum": ["REINFORCES", "QUALIFIES", "CONTRADICTS", "MITIGATES", "AMPLIFIES_RISK", "SEQUENCES", "OTHER"],
                    },
                    "explanation": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["source_index", "target_index", "relation_type", "explanation", "evidence"],
            },
        },
        "context_influences": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_type": {"type": "string", "enum": ["sentence", "claim", "qualifier", "frame"]},
                    "source_index": {"type": "integer"},
                    "source_text": {"type": "string"},
                    "target_type": {"type": "string", "enum": ["context_frame", "sentence", "claim", "consumer_effect"]},
                    "target_index": {"type": "integer"},
                    "influence_type": {"type": "string"},
                    "effect": {"type": "string"},
                    "risk_delta": {"type": "string", "enum": ["LOWERS_RISK", "RAISES_RISK", "NEUTRAL", "CLARIFIES", "AMBIGUOUS"]},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "source_type",
                    "source_index",
                    "source_text",
                    "target_type",
                    "target_index",
                    "influence_type",
                    "effect",
                    "risk_delta",
                    "confidence",
                ],
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sentence_index": {"type": "integer"},
                    "text": {"type": "string"},
                    "start": {"type": "integer"},
                    "end": {"type": "integer"},
                    "meaning": {"type": "string"},
                    "implicature": {"type": "string"},
                    "consumer_effect": {"type": "string"},
                    "risk_hypernym": {"type": "string"},
                    "risk_severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                    "qualifiers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "text": {"type": "string"},
                                "role": {
                                    "type": "string",
                                    "enum": [
                                        "target_scope",
                                        "condition_scope",
                                        "certainty",
                                        "guarantee",
                                        "benefit_scope",
                                        "risk_downplay",
                                        "urgency",
                                        "comparison",
                                        "disclosure_qualifier",
                                        "other",
                                    ],
                                },
                                "start": {"type": "integer"},
                                "end": {"type": "integer"},
                                "meaning": {"type": "string"},
                                "risk_reason": {"type": "string"},
                                "confidence": {"type": "number"},
                                "prominence_tier": {"type": "string", "enum": ["headline", "subcopy", "body", "footnote", "unknown"]},
                            },
                            "required": ["text", "role", "start", "end", "meaning", "risk_reason", "confidence", "prominence_tier"],
                        },
                    },
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
                    "sentence_index",
                    "text",
                    "start",
                    "end",
                    "meaning",
                    "implicature",
                    "consumer_effect",
                    "risk_hypernym",
                    "risk_severity",
                    "qualifiers",
                    "entities",
                    "relations",
                ],
            },
        }
    },
    "required": ["context_frame", "sentence_units", "inter_sentence_relations", "context_influences", "claims"],
}


@dataclass(frozen=True)
class HierarchicalContextExtraction:
    context_frame: ContextFrame
    sentence_units: list[SentenceUnit]
    inter_sentence_relations: list[InterSentenceRelation]
    context_influences: list[ContextInfluence]
    claims: list[Claim]


class LLMContextExtractor:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    def extract(self, review_input: ReviewInput, *, review_run_id: str) -> list[Claim]:
        return self.extract_hierarchical(review_input, review_run_id=review_run_id).claims

    def extract_hierarchical(self, review_input: ReviewInput, *, review_run_id: str) -> HierarchicalContextExtraction:
        result = self.llm.structured(
            name="graphcompliance_context_extraction",
            schema=EXTRACTION_SCHEMA,
            system=(
                "You are a Korean financial-advertising context graph extractor. "
                "Convert the ad draft into a hierarchical, policy-alignable context graph. Do not judge compliance. "
                "Use an RLM-style recursive decomposition pattern: first summarize the whole ad as a ContextFrame, "
                "then split the original text into ordered SentenceUnit objects, then describe inter-sentence "
                "relations and context influences, and only then extract atomic Claim details inside each sentence. "
                "Extract exact source spans, entities, factual relations, literal meaning, likely implicature, "
                "consumer effect, and a concise policy-level risk hypernym. "
                "Use the original text only; do not invent facts. Reply JSON only. "
                "Extraction recall is critical: every material benefit, rate, fee, guarantee, safety, "
                "approval, eligibility, past-performance, recommendation, and disclosure statement must be "
                "represented as a separate Claim when it has a distinct compliance meaning. "
                "Within each Claim, extract risky or materially limiting expression-level qualifiers as "
                "ClaimQualifier items. Examples: '누구나' -> target_scope, '전 고객' -> target_scope, "
                "'조건 없이' or '제한 없이' -> condition_scope, '확정' or '반드시' -> certainty, "
                "'보장' or '원금보장' -> guarantee, '안정적 고수익' -> risk_downplay/benefit_scope. "
                "Do not create a standalone target_consumer anchor later for generic scope words like "
                "'누구나'; those words belong inside the parent Claim as qualifiers. Concrete consumer "
                "segments such as '고령층 고객', '중위험 투자자', or '소상공인' may remain target_consumer "
                "entities because they define an actual audience segment. "
                "SentenceUnit role must distinguish neutral launch notices from benefit claims and disclosures. "
                "Classify each SentenceUnit and ClaimQualifier prominence_tier as headline, subcopy, body, "
                "footnote, or unknown. Use headline for leading/large/emphasized benefit copy, subcopy for "
                "supporting copy near the headline, body for ordinary sentences, and footnote for small-print, "
                "asterisked, parenthetical, bottom, or disclaimer-like text. "
                "For example, 'JB 특판예금 출시.' is usually launch_notice and should not become a risky "
                "standalone claim unless the sentence itself contains a material benefit or misleading claim. "
                "InterSentenceRelation should capture how sentences interact: a later '조건 없이 안정적인 고수익' "
                "sentence can REINFORCE or AMPLIFY_RISK of an earlier '확정 보장 수익' sentence; a condition "
                "or depositor-protection disclosure can QUALIFY or MITIGATE a benefit claim. "
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
        frame_row = result["context_frame"]
        context_frame = ContextFrame(
            frame_id=stable_id("context_frame", review_run_id),
            summary=frame_row["summary"],
            primary_message=frame_row["primary_message"],
            product_purpose=frame_row["product_purpose"],
            tone=frame_row["tone"],
            representative_consumer_impression=frame_row["representative_consumer_impression"],
            risk_axes=frame_row["risk_axes"],
            overall_risk_level=frame_row["overall_risk_level"],
        )
        sentence_units: list[SentenceUnit] = []
        sentence_id_by_index: dict[int, str] = {}
        for item in result["sentence_units"]:
            sentence_id = stable_id("sentence", review_run_id, item["index"], item["text"], item["start"], item["end"])
            sentence_id_by_index[int(item["index"])] = sentence_id
            sentence_units.append(
                SentenceUnit(
                    sentence_id=sentence_id,
                    index=int(item["index"]),
                    text=item["text"],
                    span=Span(start=item["start"], end=item["end"], text=item["text"]),
                    role=item["role"],
                    local_meaning=item["local_meaning"],
                    context_effect=item["context_effect"],
                    risk_level=item["risk_level"],
                    prominence_tier=item.get("prominence_tier") or "unknown",
                )
            )
        relations_by_index = {
            (int(row["source_index"]), int(row["target_index"]), row["relation_type"], row["evidence"]): row
            for row in result["inter_sentence_relations"]
        }
        inter_sentence_relations = [
            InterSentenceRelation(
                relation_id=stable_id("inter_sentence_relation", review_run_id, source_index, target_index, row["relation_type"], row["evidence"]),
                source_sentence_id=sentence_id_by_index.get(source_index, ""),
                target_sentence_id=sentence_id_by_index.get(target_index, ""),
                relation_type=row["relation_type"],
                explanation=row["explanation"],
                evidence=row["evidence"],
            )
            for (source_index, target_index, _relation_type, _evidence), row in relations_by_index.items()
        ]
        claims: list[Claim] = []
        claim_id_by_index: dict[int, str] = {}
        for index, item in enumerate(result["claims"]):
            claim_id = stable_id("claim", review_run_id, index, item["text"], item["start"], item["end"])
            claim_id_by_index[index] = claim_id
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
            qualifiers = [
                ClaimQualifier(
                    qualifier_id=stable_id("qualifier", claim_id, qualifier["text"], qualifier["role"], qualifier["start"], qualifier["end"]),
                    text=qualifier["text"],
                    role=qualifier["role"],
                    span=Span(start=qualifier["start"], end=qualifier["end"], text=qualifier["text"]),
                    meaning=qualifier["meaning"],
                    risk_reason=qualifier["risk_reason"],
                    confidence=float(qualifier["confidence"]),
                    prominence_tier=qualifier.get("prominence_tier") or "unknown",
                )
                for qualifier in item["qualifiers"]
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
                    sentence_id=sentence_id_by_index.get(int(item["sentence_index"]), ""),
                    entities=entities,
                    relations=relations,
                    qualifiers=qualifiers,
                )
            )
        context_influences = []
        for index, row in enumerate(result["context_influences"]):
            source_id = hierarchical_source_id(row, sentence_id_by_index, claim_id_by_index, context_frame.frame_id)
            target_id = hierarchical_target_id(row, sentence_id_by_index, claim_id_by_index, context_frame.frame_id)
            context_influences.append(
                ContextInfluence(
                    influence_id=stable_id("context_influence", review_run_id, index, source_id, target_id, row["effect"]),
                    source_id=source_id,
                    source_type=row["source_type"],
                    target_id=target_id,
                    target_type=row["target_type"],
                    influence_type=row["influence_type"],
                    effect=row["effect"],
                    risk_delta=row["risk_delta"],
                    confidence=float(row["confidence"]),
                )
            )
        return HierarchicalContextExtraction(
            context_frame=context_frame,
            sentence_units=sentence_units,
            inter_sentence_relations=inter_sentence_relations,
            context_influences=context_influences,
            claims=claims,
        )


def hierarchical_source_id(row: dict[str, Any], sentence_id_by_index: dict[int, str], claim_id_by_index: dict[int, str], frame_id: str) -> str:
    if row["source_type"] == "sentence":
        return sentence_id_by_index.get(int(row["source_index"]), "")
    if row["source_type"] == "claim":
        return claim_id_by_index.get(int(row["source_index"]), "")
    if row["source_type"] == "frame":
        return frame_id
    return stable_id("qualifier_ref", row["source_text"], row["source_index"])


def hierarchical_target_id(row: dict[str, Any], sentence_id_by_index: dict[int, str], claim_id_by_index: dict[int, str], frame_id: str) -> str:
    if row["target_type"] == "sentence":
        return sentence_id_by_index.get(int(row["target_index"]), "")
    if row["target_type"] == "claim":
        return claim_id_by_index.get(int(row["target_index"]), "")
    if row["target_type"] in {"context_frame", "consumer_effect"}:
        return frame_id if row["target_type"] == "context_frame" else stable_id("consumer_effect_ref", row["target_index"])
    return ""


def build_context_triples(
    *,
    review_run_id: str,
    claims: list[Claim],
    context_frame: ContextFrame | None = None,
    sentence_units: list[SentenceUnit] | None = None,
    inter_sentence_relations: list[InterSentenceRelation] | None = None,
    context_influences: list[ContextInfluence] | None = None,
) -> list[ContextTriple]:
    """Materialize extracted claim facts as auditable ER triples."""
    triples: list[ContextTriple] = []
    if context_frame:
        triples.extend(
            [
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, context_frame.frame_id, "HAS_PRIMARY_MESSAGE"),
                    claim_id="",
                    subject="AdDraft",
                    predicate="HAS_PRIMARY_MESSAGE",
                    object=context_frame.primary_message,
                    evidence=context_frame.summary,
                    subject_type="AdDraft",
                    object_type="ContextFrame",
                ),
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, context_frame.frame_id, "CREATES_CONSUMER_IMPRESSION"),
                    claim_id="",
                    subject=context_frame.primary_message,
                    predicate="CREATES_CONSUMER_IMPRESSION",
                    object=context_frame.representative_consumer_impression,
                    evidence=context_frame.summary,
                    subject_type="ContextFrame",
                    object_type="ConsumerEffect",
                ),
            ]
        )
    for sentence in sentence_units or []:
        triples.extend(
            [
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, sentence.sentence_id, "HAS_SENTENCE_ROLE", sentence.role),
                    claim_id="",
                    subject=sentence.text,
                    predicate="HAS_SENTENCE_ROLE",
                    object=sentence.role,
                    evidence=sentence.text,
                    subject_type="SentenceUnit",
                    object_type="SentenceRole",
                ),
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, sentence.sentence_id, "AFFECTS_CONTEXT", sentence.context_effect),
                    claim_id="",
                    subject=sentence.text,
                    predicate="AFFECTS_CONTEXT",
                    object=sentence.context_effect,
                    evidence=sentence.text,
                    subject_type="SentenceUnit",
                    object_type="ContextInfluence",
                ),
            ]
        )
    sentence_text_by_id = {sentence.sentence_id: sentence.text for sentence in sentence_units or []}
    for relation in inter_sentence_relations or []:
        triples.append(
            ContextTriple(
                triple_id=stable_id("triple", review_run_id, relation.relation_id, relation.relation_type),
                claim_id="",
                subject=sentence_text_by_id.get(relation.source_sentence_id, relation.source_sentence_id),
                predicate=relation.relation_type,
                object=sentence_text_by_id.get(relation.target_sentence_id, relation.target_sentence_id),
                evidence=relation.evidence,
                subject_type="SentenceUnit",
                object_type="SentenceUnit",
            )
        )
    for influence in context_influences or []:
        triples.append(
            ContextTriple(
                triple_id=stable_id("triple", review_run_id, influence.influence_id, influence.influence_type),
                claim_id="",
                subject=influence.source_id,
                predicate=influence.influence_type,
                object=influence.effect,
                evidence=influence.effect,
                subject_type=influence.source_type,
                object_type=influence.target_type,
            )
        )
    for claim in claims:
        if claim.sentence_id:
            triples.append(
                ContextTriple(
                    triple_id=stable_id("triple", review_run_id, claim.sentence_id, "CONTAINS_CLAIM", claim.claim_id),
                    claim_id=claim.claim_id,
                    subject=sentence_text_by_id.get(claim.sentence_id, claim.sentence_id),
                    predicate="CONTAINS_CLAIM",
                    object=claim.text,
                    evidence=claim.text,
                    subject_type="SentenceUnit",
                    object_type="Claim",
                )
            )
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
        for qualifier in claim.qualifiers:
            triples.extend(
                [
                    ContextTriple(
                        triple_id=stable_id("triple", review_run_id, claim.claim_id, "HAS_QUALIFIER", qualifier.qualifier_id),
                        claim_id=claim.claim_id,
                        subject=claim.text,
                        predicate="HAS_QUALIFIER",
                        object=f"{qualifier.role}:{qualifier.text}",
                        evidence=qualifier.text,
                        subject_type="Claim",
                        object_type="ClaimQualifier",
                    ),
                    ContextTriple(
                        triple_id=stable_id("triple", review_run_id, claim.claim_id, "QUALIFIER_RAISES", qualifier.qualifier_id, qualifier.risk_reason),
                        claim_id=claim.claim_id,
                        subject=qualifier.text,
                        predicate="QUALIFIER_RAISES",
                        object=qualifier.risk_reason,
                        evidence=claim.text,
                        subject_type="ClaimQualifier",
                        object_type="RiskReason",
                    ),
                ]
            )
    return triples
