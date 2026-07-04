"""LLM context-graph extraction for advertising drafts."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import re
import time
from typing import Any

from llm_gateway import LLMGateway
from parallel import ordered_parallel_map, worker_count
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
from utils import stable_id, uses_korean_law_context


LOGGER = logging.getLogger(__name__)

# 비-KR(영어 우선) 워크스페이스에서만 추출 프롬프트에 덧붙이는 오버라이드.
# KH run 에서 추출기가 영어 원문을 한국어로 번역해 claim/span/meaning 이 전부
# 한국어로 오염됐다(anchor 인용·evidence_span·하이라이트까지 전파). 원문은
# 절대 번역하지 않고(스팬은 원문 그대로), 분석 필드는 영어로 쓰게 한다.
# KR 워크스페이스에서는 append 되지 않아 프롬프트가 바이트 단위로 동일하다.
NON_KR_EXTRACTION_OVERRIDE = (
    " OUTPUT LANGUAGE OVERRIDE: this workspace reviews ads in a non-Korean (English-first) "
    "jurisdiction. NEVER translate or paraphrase the original ad text: every text/span field "
    "(sentence_units.text, claims.text, qualifier text, entity name, evidence, evidence_span) "
    "MUST be a VERBATIM substring copied from the original content_text in its original language. "
    "Write ALL free-text analysis fields (summary, primary_message, product_purpose, tone, "
    "representative_consumer_impression, risk_axes, local_meaning, context_effect, meaning, "
    "implicature, consumer_effect, risk_hypernym, qualifier meaning/risk_reason, explanation, "
    "effect) in ENGLISH."
)


def _extraction_language_tail(korean: bool) -> str:
    return "" if korean else NON_KR_EXTRACTION_OVERRIDE

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

FRAME_SENTENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "context_frame": EXTRACTION_SCHEMA["properties"]["context_frame"],
        "sentence_units": EXTRACTION_SCHEMA["properties"]["sentence_units"],
    },
    "required": ["context_frame", "sentence_units"],
}

CLAIM_CHUNK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "claims": EXTRACTION_SCHEMA["properties"]["claims"],
    },
    "required": ["claims"],
}

RELATION_INFLUENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "inter_sentence_relations": EXTRACTION_SCHEMA["properties"]["inter_sentence_relations"],
        "context_influences": EXTRACTION_SCHEMA["properties"]["context_influences"],
    },
    "required": ["inter_sentence_relations", "context_influences"],
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
        started = time.perf_counter()
        timeout_seconds = float(os.environ.get("CCG_CONTEXT_EXTRACTION_TIMEOUT_SECONDS", "360"))
        model = os.environ.get("CCG_CONTEXT_EXTRACTION_MODEL") or None
        # 적응형 추출: 짧은 광고는 단일콜(legacy)로 충분하고 빠르다. 긴 문서는
        # 단일콜의 timeout·누락 위험이 커서 staged(프레임/클레임청크/관계 분리)로
        # 자동 승격한다. env 로 강제 지정도 가능(1=항상 staged, 0=항상 legacy).
        staged_env = os.environ.get("CCG_CONTEXT_EXTRACTION_STAGED", "").lower()
        if staged_env in {"1", "true", "yes"}:
            use_staged = True
        elif staged_env in {"0", "false", "no"}:
            use_staged = False
        else:
            min_sentences = int(os.environ.get("CCG_CONTEXT_STAGED_AUTO_MIN_SENTENCES", "9"))
            estimated = estimate_sentence_count(review_input.content_text)
            use_staged = estimated >= min_sentences
            LOGGER.info(
                "context extraction mode=%s (estimated_sentences=%d, threshold=%d)",
                "staged" if use_staged else "legacy", estimated, min_sentences,
            )
        korean = uses_korean_law_context(review_input.workspace_id)
        if use_staged:
            return self._extract_hierarchical_staged(
                review_input,
                review_run_id=review_run_id,
                timeout_seconds=timeout_seconds,
                model=model,
                started=started,
                korean=korean,
            )
        return self._extract_hierarchical_legacy(
            review_input,
            review_run_id=review_run_id,
            timeout_seconds=timeout_seconds,
            model=model,
            started=started,
            korean=korean,
        )

    def _extract_hierarchical_legacy(
        self,
        review_input: ReviewInput,
        *,
        review_run_id: str,
        timeout_seconds: float,
        model: str | None,
        started: float,
        korean: bool = True,
    ) -> HierarchicalContextExtraction:
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
                + _extraction_language_tail(korean)
            ),
            user=(
                f"[title]\n{review_input.title}\n\n"
                f"[channel]\n{review_input.channel}\n\n"
                f"[content_text]\n{review_input.content_text}"
            ),
            timeout_seconds=timeout_seconds,
            model=model,
        )
        return self._build_extraction_from_result(result, review_run_id=review_run_id, started=started)

    def _extract_hierarchical_staged(
        self,
        review_input: ReviewInput,
        *,
        review_run_id: str,
        timeout_seconds: float,
        model: str | None,
        started: float,
        korean: bool = True,
    ) -> HierarchicalContextExtraction:
        frame_sentence_started = time.perf_counter()
        frame_sentence_result = self.llm.structured(
            name="graphcompliance_context_sentences",
            schema=FRAME_SENTENCE_SCHEMA,
            system=(
                "You are a Korean financial-advertising context graph extractor. "
                "Stage 1: build only ContextFrame and ordered SentenceUnit objects. Do not judge compliance. "
                "Use the original text only; do not invent facts. Split the original ad into reviewable "
                "sentence or bullet units, preserving source spans. Classify each unit role and prominence. "
                "Keep local_meaning and context_effect concise; detailed claim explanations are extracted "
                "in a later stage."
                + _extraction_language_tail(korean)
            ),
            user=(
                f"[title]\n{review_input.title}\n\n"
                f"[channel]\n{review_input.channel}\n\n"
                f"[content_text]\n{review_input.content_text}"
            ),
            timeout_seconds=timeout_seconds,
            model=model,
        )
        LOGGER.info(
            "context_extractor.stage_sentences_returned review_run_id=%s seconds=%.2f sentence_count=%d",
            review_run_id,
            time.perf_counter() - frame_sentence_started,
            len(frame_sentence_result.get("sentence_units", [])),
        )

        sentence_units_payload = frame_sentence_result.get("sentence_units", [])
        chunk_size = int(os.environ.get("CCG_CONTEXT_CLAIM_CHUNK_SENTENCES", "8"))
        claim_rows: list[dict[str, Any]] = []
        claim_stage_started = time.perf_counter()
        chunks = chunked(sentence_units_payload, chunk_size)

        def _extract_claim_chunk(indexed_chunk: tuple[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
            # Each chunk is a disjoint SentenceUnit set extracted with the same
            # prompt and schema — the calls are independent. A per-chunk failure
            # propagates (loud failure), matching the previous sequential loop.
            chunk_index, chunk = indexed_chunk
            chunk_result = self.llm.structured(
                name="graphcompliance_context_claims",
                schema=CLAIM_CHUNK_SCHEMA,
                system=(
                    "You are a Korean financial-advertising claim extractor. "
                    "Stage 2: extract atomic Claim records only from the provided SentenceUnit chunk. "
                    "Do not judge compliance. Extract distinct material benefits, rates, eligibility, "
                    "fees, guarantees, safety claims, approvals, calls-to-action, and disclosure statements. "
                    "Keep meaning, implicature, consumer_effect, and risk_hypernym concise. "
                    "Do not collapse a risky claim into a later mitigating disclosure. For example, extract "
                    "'최고 연 5.0% 금리를 확정 제공' as its own benefit/definitive-rate claim even if a later "
                    "sentence says rates may vary by conditions. Also extract the later condition disclosure "
                    "as a separate disclosure claim. "
                    "Generic scope words like '누구나', '조건 없이', '확정', and '보장' must stay as "
                    "ClaimQualifier items inside the parent claim, not standalone target-consumer claims. "
                    "Use sentence_index values exactly as provided."
                    + _extraction_language_tail(korean)
                ),
                user=(
                    f"[title]\n{review_input.title}\n\n"
                    f"[channel]\n{review_input.channel}\n\n"
                    "[sentence_units]\n"
                    f"{chunk}"
                ),
                timeout_seconds=timeout_seconds,
                model=model,
            )
            rows = claim_chunk_rows(chunk_result.get("claims", []), valid_sentence_indexes={int(item["index"]) for item in chunk})
            LOGGER.info(
                "context_extractor.claim_chunk_returned review_run_id=%s chunk_index=%d sentence_count=%d claim_count=%d",
                review_run_id,
                chunk_index,
                len(chunk),
                len(rows),
            )
            return rows

        # Parallelize disjoint claim chunks, then reassemble claim_rows in
        # chunk_index order so the concatenated result is byte-identical to the
        # sequential extend() order.
        chunk_row_lists = ordered_parallel_map(
            _extract_claim_chunk,
            list(enumerate(chunks)),
            workers=worker_count("CCG_PARALLEL_CLAIM_WORKERS", 4),
            label="claim_chunk_extraction",
        )
        for rows in chunk_row_lists:
            claim_rows.extend(rows)
        LOGGER.info(
            "context_extractor.stage_claims_returned review_run_id=%s seconds=%.2f claim_count=%d",
            review_run_id,
            time.perf_counter() - claim_stage_started,
            len(claim_rows),
        )

        relation_stage_started = time.perf_counter()
        relation_result = self.llm.structured(
            name="graphcompliance_context_relations",
            schema=RELATION_INFLUENCE_SCHEMA,
            system=(
                "You are linking a Korean financial-advertising context graph. "
                "Stage 3: choose only meaningful inter-sentence relations and context influences from "
                "the provided sentence and claim summaries. Do not restate every pair. Prefer relations "
                "where a disclosure QUALIFIES/MITIGATES a benefit claim or a later sentence "
                "REINFORCES/AMPLIFIES_RISK an earlier claim. Use source_index and target_index from "
                "the provided sentences."
                + _extraction_language_tail(korean)
            ),
            user=(
                "[context_frame]\n"
                f"{frame_sentence_result.get('context_frame', {})}\n\n"
                "[sentence_units]\n"
                f"{sentence_relation_view(sentence_units_payload)}\n\n"
                "[claim_summaries]\n"
                f"{claim_relation_view(claim_rows)}"
            ),
            timeout_seconds=timeout_seconds,
            model=model,
        )
        LOGGER.info(
            "context_extractor.stage_relations_returned review_run_id=%s seconds=%.2f relation_count=%d influence_count=%d",
            review_run_id,
            time.perf_counter() - relation_stage_started,
            len(relation_result.get("inter_sentence_relations", [])),
            len(relation_result.get("context_influences", [])),
        )
        result = {
            "context_frame": frame_sentence_result["context_frame"],
            "sentence_units": sentence_units_payload,
            "inter_sentence_relations": relation_result.get("inter_sentence_relations", []),
            "context_influences": relation_result.get("context_influences", []),
            "claims": claim_rows,
        }
        return self._build_extraction_from_result(result, review_run_id=review_run_id, started=started)

    def _build_extraction_from_result(
        self,
        result: dict[str, Any],
        *,
        review_run_id: str,
        started: float,
    ) -> HierarchicalContextExtraction:
        structured_returned = time.perf_counter()
        LOGGER.info(
            "context_extractor.structured_returned review_run_id=%s seconds=%.2f counts=%s",
            review_run_id,
            structured_returned - started,
            {
                "sentence_units": len(result.get("sentence_units", [])),
                "inter_sentence_relations": len(result.get("inter_sentence_relations", [])),
                "context_influences": len(result.get("context_influences", [])),
                "claims": len(result.get("claims", [])),
            },
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
        sentences_finished = time.perf_counter()
        LOGGER.info(
            "context_extractor.sentences_built review_run_id=%s count=%d seconds=%.2f",
            review_run_id,
            len(sentence_units),
            sentences_finished - structured_returned,
        )
        relations_by_index = {
            (int(row["source_index"]), int(row["target_index"]), row["relation_type"], row["evidence"]): row
            for row in (result.get("inter_sentence_relations") or [])
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
        relations_finished = time.perf_counter()
        LOGGER.info(
            "context_extractor.relations_built review_run_id=%s count=%d seconds=%.2f",
            review_run_id,
            len(inter_sentence_relations),
            relations_finished - sentences_finished,
        )
        claims: list[Claim] = []
        claim_id_by_index: dict[int, str] = {}
        for index, item in enumerate(result["claims"]):
            claim_id = stable_id("claim", review_run_id, index, item["text"], item["start"], item["end"])
            claim_id_by_index[index] = claim_id
            claim_ref = f"claim[{index}]:{claim_id}"
            entities = [
                ContextEntity(
                    entity_id=stable_id("entity", claim_id, entity["name"], entity["start"], entity["end"]),
                    name=entity["name"],
                    entity_type=entity["entity_type"],
                    span=Span(start=entity["start"], end=entity["end"], text=entity["name"]),
                )
                # Claude 비-strict 폴백 경로에서는 스키마의 required 가 문법으로
                # 강제되지 않아 목록 키가 통째로 빠질 수 있다 — 빈 목록으로 관용.
                for entity in (item.get("entities") or [])
            ]
            by_name = {entity.name: entity.entity_id for entity in entities}
            relations = [
                ContextRelation(
                    source_id=by_name.get(rel["source_name"], stable_id("entity_ref", claim_id, rel["source_name"])),
                    predicate=rel["predicate"],
                    target_id=by_name.get(rel["target_name"], stable_id("entity_ref", claim_id, rel["target_name"])),
                    evidence=rel["evidence"],
                )
                for rel in (item.get("relations") or [])
            ]
            qualifiers = [
                ClaimQualifier(
                    qualifier_id=stable_id("qualifier", claim_id, qualifier["text"], qualifier["role"], qualifier["start"], qualifier["end"]),
                    text=qualifier["text"],
                    role=qualifier["role"],
                    span=Span(start=qualifier["start"], end=qualifier["end"], text=qualifier["text"]),
                    meaning=_required_claim_str(
                        qualifier, "meaning", review_run_id=review_run_id, ref=f"{claim_ref}.qualifier:{qualifier.get('text', '')}"
                    ),
                    risk_reason=_required_claim_str(
                        qualifier, "risk_reason", review_run_id=review_run_id, ref=f"{claim_ref}.qualifier:{qualifier.get('text', '')}"
                    ),
                    confidence=float(qualifier["confidence"]),
                    prominence_tier=qualifier.get("prominence_tier") or "unknown",
                )
                for qualifier in (item.get("qualifiers") or [])
            ]
            claims.append(
                Claim(
                    claim_id=claim_id,
                    text=item["text"],
                    span=Span(start=item["start"], end=item["end"], text=item["text"]),
                    meaning=_required_claim_str(item, "meaning", review_run_id=review_run_id, ref=claim_ref),
                    implicature=_required_claim_str(item, "implicature", review_run_id=review_run_id, ref=claim_ref),
                    consumer_effect=_required_claim_str(item, "consumer_effect", review_run_id=review_run_id, ref=claim_ref),
                    risk_hypernym=_required_claim_str(item, "risk_hypernym", review_run_id=review_run_id, ref=claim_ref),
                    risk_severity=_required_claim_str(
                        item, "risk_severity", review_run_id=review_run_id, ref=claim_ref, default="MEDIUM"
                    ),
                    sentence_id=sentence_id_by_index.get(int(item["sentence_index"]), ""),
                    entities=entities,
                    relations=relations,
                    qualifiers=qualifiers,
                )
            )
        claims_finished = time.perf_counter()
        LOGGER.info(
            "context_extractor.claims_built review_run_id=%s count=%d qualifier_count=%d entity_count=%d relation_count=%d seconds=%.2f",
            review_run_id,
            len(claims),
            sum(len(claim.qualifiers or []) for claim in claims),
            sum(len(claim.entities or []) for claim in claims),
            sum(len(claim.relations or []) for claim in claims),
            claims_finished - relations_finished,
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
        influences_finished = time.perf_counter()
        LOGGER.info(
            "context_extractor.finished review_run_id=%s influence_count=%d transform_seconds=%.2f total_seconds=%.2f",
            review_run_id,
            len(context_influences),
            influences_finished - structured_returned,
            influences_finished - started,
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



def estimate_sentence_count(text: str) -> int:
    """LLM 호출 전 결정론적 문장 수 추정 (적응형 추출 분기용)."""
    segments = [seg for seg in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")) if seg.strip()]
    return len(segments)


def _required_claim_str(
    item: dict[str, Any],
    key: str,
    *,
    review_run_id: str,
    ref: str,
    default: str = "",
) -> str:
    """Defensively read a claim/qualifier field the schema marks ``required``.

    Claude's non-strict tool-use fallback path (triggered when the extraction
    schema is too large for strict grammar compilation — see
    ``llm_gateway._anthropic_structured``) does not enforce ``required`` at the
    grammar level; it is only restated in the prompt text. The model
    occasionally still omits a required string field (observed for
    ``meaning``), which previously raised an unhandled ``KeyError`` and failed
    the whole review. Missing the field is tolerated here — but only with a
    loud warning, never silently — because a silent low-quality fallback would
    hide a real extraction-quality regression (project contract: no silent
    deterministic/degraded fallback).
    """
    if key in item:
        return str(item[key])
    LOGGER.warning(
        "context_extractor.required_field_missing review_run_id=%s ref=%s field=%s",
        review_run_id,
        ref,
        key,
    )
    return default


def chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    chunk_size = max(1, size)
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def claim_chunk_rows(rows: list[dict[str, Any]], *, valid_sentence_indexes: set[int]) -> list[dict[str, Any]]:
    """Keep chunk extraction rows scoped to the sentence indexes the model saw."""
    scoped: list[dict[str, Any]] = []
    for row in rows:
        try:
            sentence_index = int(row["sentence_index"])
        except (KeyError, TypeError, ValueError):
            continue
        if sentence_index in valid_sentence_indexes:
            scoped.append(row)
    return scoped


def sentence_relation_view(sentence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "index": item.get("index"),
            "text": item.get("text", ""),
            "role": item.get("role", ""),
            "risk_level": item.get("risk_level", ""),
            "prominence_tier": item.get("prominence_tier", "unknown"),
        }
        for item in sentence_rows
    ]


def claim_relation_view(claim_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sentence_index": row.get("sentence_index"),
            "text": row.get("text", ""),
            "risk_hypernym": row.get("risk_hypernym", ""),
            "risk_severity": row.get("risk_severity", ""),
            "qualifiers": [
                {
                    "text": qualifier.get("text", ""),
                    "role": qualifier.get("role", ""),
                }
                for qualifier in row.get("qualifiers", [])
            ],
        }
        for row in claim_rows
    ]


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
