"""Optional cross-encoder CU reranking.

The first-stage graph retriever is responsible for legal-element eligibility.
This module only reorders already-eligible CU candidates by jointly scoring the
anchor packet and the CU packet.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Protocol

from schemas import ContextAnchor, PolicyCandidate


DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


class CUReranker(Protocol):
    @property
    def enabled(self) -> bool:
        ...

    def rerank(
        self,
        *,
        candidates_by_anchor: dict[str, list[PolicyCandidate]],
        anchors: list[ContextAnchor],
        limit_per_anchor: int,
    ) -> dict[str, list[PolicyCandidate]]:
        ...


class NoopCUReranker:
    @property
    def enabled(self) -> bool:
        return False

    def rerank(
        self,
        *,
        candidates_by_anchor: dict[str, list[PolicyCandidate]],
        anchors: list[ContextAnchor],
        limit_per_anchor: int,
    ) -> dict[str, list[PolicyCandidate]]:
        return candidates_by_anchor


class FlagEmbeddingCrossEncoderCUReranker:
    def __init__(self, *, model_name: str = DEFAULT_MODEL, use_fp16: bool = True) -> None:
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RuntimeError(
                "Cross-encoder reranking requires FlagEmbedding. "
                "Install it or unset CCG_ENABLE_CROSS_ENCODER_RERANKER."
            ) from exc

        self.model_name = model_name
        self._reranker = FlagReranker(model_name, use_fp16=use_fp16)

    @property
    def enabled(self) -> bool:
        return True

    def rerank(
        self,
        *,
        candidates_by_anchor: dict[str, list[PolicyCandidate]],
        anchors: list[ContextAnchor],
        limit_per_anchor: int,
    ) -> dict[str, list[PolicyCandidate]]:
        anchor_by_id = {anchor.anchor_id: anchor for anchor in anchors}
        reranked: dict[str, list[PolicyCandidate]] = {}
        for anchor_id, candidates in candidates_by_anchor.items():
            anchor = anchor_by_id.get(anchor_id)
            if not anchor or not candidates:
                reranked[anchor_id] = candidates
                continue
            pairs = [[anchor_packet(anchor), candidate_packet(candidate)] for candidate in candidates]
            raw_scores = self._reranker.compute_score(pairs, normalize=True)
            scores = raw_scores if isinstance(raw_scores, list) else [float(raw_scores)]
            scored = [
                with_cross_encoder_score(candidate, float(score))
                for candidate, score in zip(candidates, scores, strict=False)
            ]
            scored.sort(
                key=lambda candidate: candidate.retrieval_scores.get("cross_encoder_combined_score", 0.0),
                reverse=True,
            )
            reranked[anchor_id] = scored[:limit_per_anchor]
        return reranked


def create_cross_encoder_reranker_from_env() -> CUReranker:
    enabled = os.environ.get("CCG_ENABLE_CROSS_ENCODER_RERANKER", "").strip().lower()
    if enabled not in {"1", "true", "yes", "y"}:
        return NoopCUReranker()
    model_name = os.environ.get("CCG_CROSS_ENCODER_RERANKER_MODEL", DEFAULT_MODEL)
    use_fp16 = os.environ.get("CCG_CROSS_ENCODER_USE_FP16", "true").strip().lower() not in {"0", "false", "no"}
    return FlagEmbeddingCrossEncoderCUReranker(model_name=model_name, use_fp16=use_fp16)


def with_cross_encoder_score(candidate: PolicyCandidate, score: float) -> PolicyCandidate:
    legal_element = candidate.retrieval_scores.get("legal_element_match", 0.0)
    hypernym = candidate.retrieval_scores.get("hypernym_overlap", 0.0)
    scope = candidate.retrieval_scores.get("scope_gate", 1.0)
    if not candidate.legal_element_match:
        combined = 0.0
    else:
        combined = (0.60 * score) + (0.20 * legal_element) + (0.15 * hypernym) + (0.05 * scope)
    return replace(
        candidate,
        retrieval_scores={
            **candidate.retrieval_scores,
            "cross_encoder_score": score,
            "cross_encoder_combined_score": combined,
        },
        retrieval_basis=f"{candidate.retrieval_basis}+cross_encoder",
    )


def anchor_packet(anchor: ContextAnchor) -> str:
    feature_set = anchor.feature_set
    return "\n".join(
        [
            f"anchor_type: {anchor.anchor_type}",
            f"claim_text: {anchor.span.text}",
            f"context_facts: {' | '.join(anchor.facts)}",
            f"policy_hypernyms: {' | '.join(proposal.hypernym for proposal in anchor.hypernyms)}",
            f"action_types: {' | '.join(feature_set.action_types if feature_set else [])}",
            f"positive_features: {' | '.join(feature_set.positive_features if feature_set else [])}",
            f"missing_context: {' | '.join(feature_set.missing_context if feature_set else [])}",
        ]
    )


def candidate_packet(candidate: PolicyCandidate) -> str:
    profile = candidate.legal_element_profile
    return "\n".join(
        [
            f"risk_title: {candidate.risk_title}",
            f"principle: {candidate.principle}",
            f"source_article: {candidate.source_article}",
            f"subject: {candidate.subject}",
            f"condition: {candidate.condition}",
            f"constraint: {candidate.constraint}",
            f"context: {candidate.context}",
            f"cu_type: {candidate.cu_type}",
            f"action_type: {profile.action_type if profile else ''}",
            f"required_positive_features: {' | '.join(profile.required_positive_features if profile else [])}",
            f"applicability_scope: {' | '.join(profile.applicability_scope if profile else [])}",
            f"matched_required_features: {' | '.join(candidate.matched_required_features)}",
            f"missing_required_features: {' | '.join(candidate.missing_required_features)}",
            f"evidence: {' | '.join(candidate.evidence_texts[:3])}",
        ]
    )
