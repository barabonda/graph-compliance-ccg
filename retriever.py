"""Neo4j policy retrieval for GraphCompliance ContextAnchor -> CUPlan.

LegalChunk fulltext is not used as the main CU candidate engine. The retrieval
path follows the paper-shaped graph contract:

    ContextAnchor -> PolicyHypernym -> ComplianceUnit -> Premise -> LegalChunk

Vector scores are computed against CUEmbeddingProfile text, while LegalChunk
and LegalClause remain provenance/evidence window material.
"""

from __future__ import annotations

import math
import os
from dataclasses import replace
from typing import Any, Protocol

from ccg_embeddings import EmbeddingGateway
from legal_elements import candidate_satisfies_legal_elements, profile_from_row
from schemas import ContextAnchor, PolicyCandidate


ACTIONABLE_VECTOR_THRESHOLD = 0.68


# Policy-alignment readiness thresholds. Defaults are calibrated for the full KR
# corpus. Small workspaces (e.g. a jurisdiction PoC) may lower them via env:
#   CCG_MIN_HYPERNYM / CCG_MIN_PREMISE                     -> global default override
#   CCG_MIN_HYPERNYM_<workspace_id> / CCG_MIN_PREMISE_<ws> -> per-workspace override (wins)
# The link-ratio quality gate (>= 0.80) is intentionally NOT configurable.
# NOTE: the GLOBAL vars apply to EVERY workspace, including KR — setting them would
# also lower KR's gate. To relax only a small corpus, use the per-workspace keys
# (as .env does for the KH workspace) and leave the global vars unset.
DEFAULT_MIN_HYPERNYM = 30
DEFAULT_MIN_PREMISE = 100
MIN_LINK_RATIO = 0.8


def _readiness_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    # A readiness threshold below 1 would silently disable that part of the gate;
    # treat a non-positive (e.g. typo'd 0 or negative) override as unset.
    return value if value >= 1 else default


def alignment_min_thresholds(workspace_id: str) -> tuple[int, int]:
    """Return (min_hypernym, min_premise) for a workspace.

    Precedence: per-workspace env override > global env override > KR-calibrated
    defaults (30 / 100). KR keeps its exact defaults unless explicitly
    overridden, so existing KR behavior is unchanged.
    """
    min_hypernym = _readiness_env_int("CCG_MIN_HYPERNYM", DEFAULT_MIN_HYPERNYM)
    min_premise = _readiness_env_int("CCG_MIN_PREMISE", DEFAULT_MIN_PREMISE)
    min_hypernym = _readiness_env_int(f"CCG_MIN_HYPERNYM_{workspace_id}", min_hypernym)
    min_premise = _readiness_env_int(f"CCG_MIN_PREMISE_{workspace_id}", min_premise)
    return min_hypernym, min_premise


class PolicyRetriever(Protocol):
    def assert_policy_alignment_ready(self, *, workspace_id: str) -> None:
        ...

    def policy_context_for_claims(self, *, workspace_id: str, query_text: str, limit: int = 80) -> dict[str, Any]:
        ...

    def candidates_for_anchor(
        self,
        *,
        workspace_id: str,
        anchor: ContextAnchor,
        product_group: str = "auto",
        channel: str = "",
        limit: int = 30,
    ) -> list[PolicyCandidate]:
        ...

    def exception_closure(self, *, workspace_id: str, cu_id: str, max_depth: int = 4) -> list[dict[str, Any]]:
        ...


class Neo4jPolicyRetriever:
    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        embedder: EmbeddingGateway | None = None,
    ) -> None:
        from neo4j import GraphDatabase

        self.uri = uri or os.environ.get("NEO4J_URI", "")
        self.user = user or os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "")
        if not self.uri or not self.user or not self.password:
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, and NEO4J_PASSWORD are required.")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self.database = os.environ.get("NEO4J_DATABASE")
        self.embedder = embedder or EmbeddingGateway()
        # 팀 공용 Aura(예: KR 법령 코퍼스) 읽기 전용 라우팅. TEAM_NEO4J_WORKSPACES에
        # 등록된 workspace의 코퍼스 조회(retriever는 전부 읽기 쿼리)는 팀 DB로 보낸다.
        # 심사 산출물 쓰기(persistence/run_store)는 여기와 무관하게 기본 DB에만 저장
        # 되므로, "팀 DB에 새 노드/엣지 생성 금지" 합의가 지켜진다.
        self._team_driver = None
        self._team_database = os.environ.get("TEAM_NEO4J_DATABASE", "")

    def _team_workspaces(self) -> set[str]:
        raw = os.environ.get("TEAM_NEO4J_WORKSPACES", "")
        return {token.strip() for token in raw.replace(",", " ").split() if token.strip()}

    def _get_team_driver(self):
        if self._team_driver is None:
            from neo4j import GraphDatabase

            uri = os.environ.get("TEAM_NEO4J_URI", "")
            user = os.environ.get("TEAM_NEO4J_USER", "")
            password = os.environ.get("TEAM_NEO4J_PASSWORD", "")
            if not uri or not user or not password:
                return None
            self._team_driver = GraphDatabase.driver(uri, auth=(user, password))
        return self._team_driver

    def _session_for(self, workspace_id: str):
        """workspace 기반 세션: 팀 workspace면 팀 DB(읽기 전용 용도), 그 외 기본 DB."""
        if workspace_id in self._team_workspaces():
            team = self._get_team_driver()
            if team is not None:
                # 팀 Aura는 DB 이름이 다르므로 기본 NEO4J_DATABASE를 쓰지 않는다.
                return team.session(database=self._team_database) if self._team_database else team.session()
        return self.driver.session(**self._session_kwargs())

    def close(self) -> None:
        self.driver.close()
        if self._team_driver is not None:
            self._team_driver.close()

    def _session_kwargs(self) -> dict[str, str]:
        return {"database": self.database} if self.database else {}

    def assert_policy_alignment_ready(self, *, workspace_id: str) -> None:
        min_hypernym, min_premise = alignment_min_thresholds(workspace_id)
        with self._session_for(workspace_id) as session:
            row = session.run(
                """
                MATCH (h:PolicyHypernym {workspace_id: $workspace_id})
                WHERE coalesce(h.status, 'approved') = 'approved'
                WITH count(h) AS hypernym_count
                MATCH (p:Premise {workspace_id: $workspace_id})
                WITH hypernym_count, count(p) AS premise_count
                MATCH (cu:ComplianceUnit {workspace_id: $workspace_id})
                WHERE coalesce(cu.active_for_gate, false) = true
                WITH hypernym_count, premise_count, count(cu) AS active_cu_count
                MATCH (cu:ComplianceUnit {workspace_id: $workspace_id})-[:HAS_SUBJECT_HYPERNYM]->(:PolicyHypernym)
                WHERE coalesce(cu.active_for_gate, false) = true
                RETURN hypernym_count, premise_count, active_cu_count, count(DISTINCT cu) AS linked_active_cu_count
                """,
                workspace_id=workspace_id,
            ).single()
        if not row:
            raise RuntimeError("Policy alignment graph is missing; run the policy compiler before review.")
        hypernym_count = int(row["hypernym_count"])
        premise_count = int(row["premise_count"])
        active_cu_count = int(row["active_cu_count"])
        linked_active_cu_count = int(row["linked_active_cu_count"])
        linked_ratio = linked_active_cu_count / active_cu_count if active_cu_count else 0.0
        if hypernym_count < min_hypernym or premise_count < min_premise or linked_ratio < MIN_LINK_RATIO:
            raise RuntimeError(
                "Policy alignment graph is not ready: "
                f"PolicyHypernym={hypernym_count} (min {min_hypernym}), "
                f"Premise={premise_count} (min {min_premise}), "
                f"active CU hypernym link ratio={linked_ratio:.2f} (min {MIN_LINK_RATIO:.2f}). "
                "Run policy_compiler.py and reload before review."
            )

    def policy_context_for_claims(self, *, workspace_id: str, query_text: str, limit: int = 80) -> dict[str, Any]:
        query_embedding = self.embedder.embed(query_text[:3000])
        with self._session_for(workspace_id) as session:
            hypernyms = [
                dict(record)
                for record in session.run(
                    """
                    MATCH (h:PolicyHypernym {workspace_id: $workspace_id})
                    WHERE coalesce(h.status, 'approved') = 'approved'
                    RETURN h.id AS hypernym_id,
                           coalesce(h.canonical_name_ko, h.name) AS name,
                           h.domain AS domain,
                           coalesce(h.description_ko, h.description) AS description
                    ORDER BY coalesce(h.priority, 1000), h.domain, h.name
                    LIMIT $limit
                    """,
                    workspace_id=workspace_id,
                    limit=max(limit, 2000),
                )
            ]
            premise_rows = [
                dict(record)
                for record in session.run(
                    """
                    MATCH (p:Premise {workspace_id: $workspace_id})-[:DEFINES_HYPERNYM|SUPPORTS_HYPERNYM]->(h:PolicyHypernym)
                    WHERE coalesce(h.status, 'approved') = 'approved'
                    OPTIONAL MATCH (p)<-[:DERIVES_PREMISE]-(source)
                    RETURN p.id AS id,
                           p.statement AS text,
                           p.premise_type AS premise_type,
                           h.id AS hypernym_id,
                           coalesce(h.canonical_name_ko, h.name) AS hypernym,
                           collect(DISTINCT source.id)[0..4] AS source_ids
                    LIMIT $limit
                    """,
                    workspace_id=workspace_id,
                    limit=limit,
                )
            ]
            fragments = self._similar_policy_fragments(session, workspace_id, query_embedding, limit=min(limit, 40))
        return {"hypernyms": hypernyms, "premises": premise_rows, "fragments": fragments}

    def candidates_for_anchor(
        self,
        *,
        workspace_id: str,
        anchor: ContextAnchor,
        product_group: str = "auto",
        channel: str = "",
        limit: int = 30,
    ) -> list[PolicyCandidate]:
        hypernym_ids = [proposal.hypernym_id for proposal in anchor.hypernyms]
        if not hypernym_ids:
            return []
        anchor_text = " ".join(
            [
                anchor.span.text,
                *anchor.facts,
                *(f"{proposal.hypernym} {proposal.why}" for proposal in anchor.hypernyms),
            ]
        ).strip()
        anchor_embedding = self.embedder.embed(anchor_text[:3000])
        with self._session_for(workspace_id) as session:
            rows = [
                dict(record)
                for record in session.run(
                    """
                    MATCH (seed:PolicyHypernym {workspace_id: $workspace_id})
                    WHERE seed.id IN $hypernym_ids
                    WITH collect(DISTINCT seed.id) AS seed_ids,
                         collect(DISTINCT coalesce(seed.canonical_name_ko, seed.name)) AS seed_names
                    MATCH (cu:ComplianceUnit {workspace_id: $workspace_id})-[:HAS_EMBEDDING_PROFILE]->(profile:CUEmbeddingProfile)
                    WHERE coalesce(cu.active_for_gate, false) = true
                      AND profile.embedding IS NOT NULL
                    OPTIONAL MATCH (cu)-[:HAS_SUBJECT_HYPERNYM]->(h:PolicyHypernym {workspace_id: $workspace_id})
                    WITH seed_ids,
                         seed_names,
                         cu,
                         profile,
                         collect(DISTINCT h.id) AS matched_hypernym_ids,
                         collect(DISTINCT coalesce(h.canonical_name_ko, h.name)) AS matched_hypernym_names,
                         vector.similarity.cosine(profile.embedding, $anchor_embedding) AS profile_vector_score
                    WITH seed_ids,
                         seed_names,
                         cu,
                         profile,
                         matched_hypernym_ids,
                         matched_hypernym_names,
                         profile_vector_score,
                         size([id IN matched_hypernym_ids WHERE id IN seed_ids]) AS id_overlap_count,
                         size([name IN matched_hypernym_names WHERE name IN seed_names]) AS name_overlap_count
                    WHERE id_overlap_count > 0
                       OR name_overlap_count > 0
                       OR (
                           profile_vector_score >= $vector_threshold
                           AND coalesce(cu.principle, '') <> '제재'
                         )
                    OPTIONAL MATCH (cu)<-[:SUPPORTS_CU]-(premise:Premise)
                    OPTIONAL MATCH (premise)<-[:DERIVES_PREMISE]-(source)
                    OPTIONAL MATCH (cu)-[:GROUNDED_IN|HAS_SOURCE_CHUNK|EVIDENCES_CU]-(direct_evidence)
                    OPTIONAL MATCH (cu)-[:HAS_LEGAL_ELEMENT_PROFILE]->(legal_profile:CULegalElementProfile {workspace_id: $workspace_id})
                    WITH seed_ids,
                         seed_names,
                         cu,
                         matched_hypernym_ids,
                         matched_hypernym_names,
                         id_overlap_count,
                         name_overlap_count,
                         profile_vector_score,
                         profile,
                         legal_profile,
                         collect(DISTINCT {
                            id: premise.id,
                            text: premise.statement,
                            type: 'Premise'
                         })[0..6] AS premise_evidence,
                         collect(DISTINCT {
                            id: source.id,
                            text: coalesce(source.text, source.summary, source.article_title, source.title, ''),
                            type: head(labels(source))
                         })[0..4] AS premise_sources,
                         collect(DISTINCT {
                            id: direct_evidence.id,
                            text: coalesce(direct_evidence.text, direct_evidence.summary, direct_evidence.article_title, direct_evidence.title, ''),
                            type: head(labels(direct_evidence))
                         })[0..4] AS direct_evidence
                    RETURN cu.id AS cu_id,
                           coalesce(cu.principle, '') AS principle,
                           coalesce(cu.subject, '') AS subject,
                           coalesce(cu.condition, '') AS condition,
                           coalesce(cu.constraint, '') AS constraint,
                           coalesce(cu.context, '') AS context,
                           coalesce(cu.cu_type, '') AS cu_type,
                           coalesce(cu.source_article, cu.article_no, '') AS source_article,
                           coalesce(cu.active_for_gate, false) AS active_for_gate,
                           matched_hypernym_ids,
                           matched_hypernym_names,
                           id_overlap_count,
                           name_overlap_count,
                           profile_vector_score,
                           profile.embedding AS profile_embedding,
                           legal_profile.id AS legal_profile_id,
                           legal_profile.action_type AS action_type,
                           legal_profile.required_positive_features AS required_positive_features,
                           legal_profile.applicability_scope AS applicability_scope,
                           legal_profile.risk_title AS risk_title,
                           coalesce(legal_profile.exception_eligible, false) AS exception_eligible,
                           legal_profile.rationale AS legal_profile_rationale,
                           premise_evidence + premise_sources + direct_evidence AS evidence
                    ORDER BY (0.55 * profile_vector_score)
                           + (0.35 * CASE
                               WHEN size(seed_ids) = 0 THEN 0
                               ELSE toFloat(id_overlap_count + name_overlap_count) / toFloat(size(seed_ids) + size(seed_names))
                             END)
                           + 0.10 DESC
                    LIMIT 300
                    """,
                    workspace_id=workspace_id,
                    hypernym_ids=hypernym_ids,
                    anchor_embedding=anchor_embedding,
                    vector_threshold=ACTIONABLE_VECTOR_THRESHOLD,
                )
            ]
        requested_hypernym_names = [proposal.hypernym for proposal in anchor.hypernyms]
        scored = [
            candidate_from_row(
                row,
                anchor_embedding=anchor_embedding,
                requested_hypernym_ids=hypernym_ids,
                requested_hypernym_names=requested_hypernym_names,
            )
            for row in rows
        ]
        scored = [
            with_scope_gate(candidate, product_group=product_group, channel=channel)
            for candidate in scored
        ]
        scored = [with_legal_element_gate(candidate, anchor) for candidate in scored]
        scored = [candidate for candidate in scored if candidate_allowed_for_anchor(candidate, anchor, product_group=product_group)]
        scored.sort(key=lambda item: item.retrieval_scores["combined_score"], reverse=True)
        return scored[:limit]

    def exception_closure(self, *, workspace_id: str, cu_id: str, max_depth: int = 4) -> list[dict[str, Any]]:
        depth = max(1, min(max_depth, 4))
        query = f"""
        MATCH (cu:ComplianceUnit {{workspace_id: $workspace_id, id: $cu_id}})
        MATCH path = (cu)-[:REFERS_TO|DERIVES|GROUNDED_IN|HAS_SOURCE_CHUNK|HAS_EXCEPTION|REQUIRES_EVIDENCE*1..{depth}]->(node)
        RETURN DISTINCT labels(node) AS labels,
               node.id AS id,
               coalesce(node.statement, node.text, node.summary, node.label, node.constraint, node.title, node.article_title, '') AS text
        LIMIT 40
        """
        with self._session_for(workspace_id) as session:
            return [dict(record) for record in session.run(query, workspace_id=workspace_id, cu_id=cu_id)]

    def _similar_policy_fragments(
        self,
        session: Any,
        workspace_id: str,
        query_embedding: list[float],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = [
            dict(record)
            for record in session.run(
                """
                MATCH (p:Premise {workspace_id: $workspace_id})
                WHERE p.embedding IS NOT NULL
                WITH p, vector.similarity.cosine(p.embedding, $embedding) AS score
                OPTIONAL MATCH (p)<-[:DERIVES_PREMISE]-(source)
                RETURN p.id AS id,
                       p.statement AS text,
                       p.premise_type AS premise_type,
                       collect(DISTINCT source.id)[0..4] AS source_ids,
                       score
                ORDER BY score DESC
                LIMIT $limit
                """,
                workspace_id=workspace_id,
                embedding=query_embedding,
                limit=limit,
            )
        ]
        if not rows:
            raise RuntimeError("No embedded Premise nodes found; run policy_compiler.py before review.")
        return rows


def candidate_from_row(
    row: dict[str, Any],
    *,
    anchor_embedding: list[float],
    requested_hypernym_ids: list[str],
    requested_hypernym_names: list[str],
) -> PolicyCandidate:
    evidence = [item for item in row.get("evidence", []) if item and item.get("id")]
    profile_embedding = row.get("profile_embedding") or []
    if not profile_embedding:
        raise RuntimeError(f"CUEmbeddingProfile missing embedding for CU: {row.get('cu_id')}")
    vector_score = float(row.get("profile_vector_score") or cosine(anchor_embedding, [float(value) for value in profile_embedding]))
    matched = [str(item) for item in row.get("matched_hypernym_ids", [])]
    matched_names = [str(item) for item in row.get("matched_hypernym_names", [])]
    id_overlap = len(set(matched) & set(requested_hypernym_ids)) / max(1, len(set(requested_hypernym_ids)))
    name_overlap = len(set(matched_names) & set(requested_hypernym_names)) / max(1, len(set(requested_hypernym_names)))
    overlap_score = max(id_overlap, name_overlap)
    active_score = 1.0 if row.get("active_for_gate") else 0.0
    legal_profile = profile_from_row(row)
    legal_match, matched_required_features, missing_required_features = candidate_satisfies_legal_elements(
        feature_set=getattr(row.get("anchor"), "feature_set", None),
        profile=legal_profile,
    )
    # The caller re-evaluates legal_match with the actual anchor below. Keep the
    # row-level score neutral here so candidate_from_row remains easy to unit test.
    legal_element_score = 1.0 if legal_profile else 0.0
    combined_score = 0.40 * vector_score + 0.25 * overlap_score + 0.25 * legal_element_score + 0.10 * active_score
    retrieval_basis = "hypernym_overlap" if overlap_score > 0 else "embedding_profile"
    return PolicyCandidate(
        cu_id=str(row["cu_id"]),
        principle=str(row.get("principle", "")),
        subject=str(row.get("subject", "")),
        condition=str(row.get("condition", "")),
        constraint=str(row.get("constraint", "")),
        context=str(row.get("context", "")),
        cu_type=str(row.get("cu_type", "")),
        source_article=str(row.get("source_article", "")),
        active_for_gate=bool(row.get("active_for_gate")),
        matched_hypernym_ids=matched,
        legal_evidence_ids=[str(item["id"]) for item in evidence],
        evidence_texts=[str(item.get("text", "")) for item in evidence],
        retrieval_scores={
            "vector_score": vector_score,
            "hypernym_overlap": overlap_score,
            "active_for_gate": active_score,
            "combined_score": combined_score,
            "legal_element_match": legal_element_score,
        },
        retrieval_basis=retrieval_basis,
        gate_status="active" if row.get("active_for_gate") else "unknown",
        legal_element_profile=legal_profile,
        matched_required_features=matched_required_features,
        missing_required_features=missing_required_features,
        legal_element_match=legal_match,
        risk_title=legal_profile.risk_title if legal_profile else "",
    )


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def candidate_allowed_for_anchor(candidate: PolicyCandidate, anchor: ContextAnchor, *, product_group: str = "auto") -> bool:
    if candidate.gate_status == "suppressed":
        return False
    if is_operational_candidate(candidate):
        return False
    if not candidate.legal_element_match:
        return False
    if anchor.anchor_type in {"product_anchor", "target_consumer_anchor"}:
        return False
    if candidate.retrieval_scores.get("hypernym_overlap", 0.0) > 0:
        return True
    if candidate.principle == "제재":
        return False
    return candidate.retrieval_scores.get("vector_score", 0.0) >= ACTIONABLE_VECTOR_THRESHOLD


def with_legal_element_gate(candidate: PolicyCandidate, anchor: ContextAnchor) -> PolicyCandidate:
    legal_match, matched, missing = candidate_satisfies_legal_elements(
        feature_set=anchor.feature_set,
        profile=candidate.legal_element_profile,
    )
    legal_profile = candidate.legal_element_profile
    if legal_profile:
        from legal_elements import canonicalize_required_features

        legal_profile = replace(
            legal_profile,
            required_positive_features=canonicalize_required_features(
                legal_profile.required_positive_features,
                action_type=legal_profile.action_type,
            ),
        )
    scores = {
        **candidate.retrieval_scores,
        "legal_element_match": 1.0 if legal_match else 0.0,
    }
    scores["combined_score"] = (
        0.40 * scores.get("vector_score", 0.0)
        + 0.25 * scores.get("hypernym_overlap", 0.0)
        + 0.25 * scores.get("legal_element_match", 0.0)
        + 0.10 * scores.get("active_for_gate", 0.0)
    )
    return replace(
        candidate,
        retrieval_scores=scores,
        legal_element_match=legal_match,
        legal_element_profile=legal_profile,
        matched_required_features=matched,
        missing_required_features=missing,
        risk_title=legal_profile.risk_title if legal_profile else "",
    )


def with_scope_gate(candidate: PolicyCandidate, *, product_group: str, channel: str) -> PolicyCandidate:
    gate_status = "active" if candidate.active_for_gate else "unknown"
    gate_reason = ""
    if is_product_scope_mismatch(candidate, product_group):
        gate_status = "suppressed"
        gate_reason = "product_group_text_mismatch"
    else:
        profile_scope_reason = profile_scope_mismatch_reason(candidate, product_group=product_group, channel=channel)
    if gate_status != "suppressed" and profile_scope_reason:
        gate_status = "suppressed"
        gate_reason = profile_scope_reason
    return PolicyCandidate(
        **{
            **candidate.__dict__,
            "gate_status": gate_status,
            "retrieval_scores": {
                **candidate.retrieval_scores,
                "scope_gate": 0.0 if gate_status == "suppressed" else 1.0,
                "product_scope_gate": 0.0 if gate_status == "suppressed" and "product" in gate_reason else 1.0,
                "channel_scope_gate": 0.0 if gate_status == "suppressed" and "channel" in gate_reason else 1.0,
                "scope_gate_reason": gate_reason,
            },
        }
    )


PRODUCT_SCOPE_ALIASES = {
    "deposit": {"deposit", "예금", "적금", "예금성", "수신", "deposit_product"},
    "loan": {"loan", "대출", "대출성", "여신", "credit_product"},
    "investment": {"investment", "투자", "투자성", "펀드", "els", "파생", "financial_investment"},
    "insurance": {"insurance", "보험", "보장성", "insurance_product"},
}

CHANNEL_SCOPE_ALIASES = {
    "web_page": {"web_page", "web", "homepage", "웹", "웹페이지", "인터넷"},
    "sns": {"sns", "social", "instagram", "facebook", "블로그", "인스타그램"},
    "youtube": {"youtube", "유튜브", "video"},
    "sms": {"sms", "문자", "message", "lms", "mms"},
    "banner": {"banner", "배너"},
}

GENERIC_SCOPE_TOKENS = {
    "all",
    "common",
    "generic",
    "전체",
    "공통",
    "금융상품",
    "금융상품광고",
    "financial_advertising",
    "product_ad",
    "상품광고",
}


def is_profile_scope_mismatch(candidate: PolicyCandidate, *, product_group: str, channel: str) -> bool:
    return bool(profile_scope_mismatch_reason(candidate, product_group=product_group, channel=channel))


def profile_scope_mismatch_reason(candidate: PolicyCandidate, *, product_group: str, channel: str) -> str:
    profile = candidate.legal_element_profile
    if not profile:
        return ""
    scopes = {normalize_scope_token(item) for item in profile.applicability_scope if item}
    scopes = {item for item in scopes if item}
    if not scopes or scopes & GENERIC_SCOPE_TOKENS:
        return ""

    product = normalize_product_group(product_group)
    if product != "auto":
        product_related = set().union(*PRODUCT_SCOPE_ALIASES.values())
        scoped_products = scopes & product_related
        if scoped_products and not (scopes & PRODUCT_SCOPE_ALIASES.get(product, set())):
            return "product_scope_mismatch"

    normalized_channel = normalize_scope_token(channel)
    if normalized_channel:
        channel_related = set().union(*CHANNEL_SCOPE_ALIASES.values())
        scoped_channels = scopes & channel_related
        accepted_channels = CHANNEL_SCOPE_ALIASES.get(normalized_channel, {normalized_channel})
        if scoped_channels and not (scopes & accepted_channels):
            return "channel_scope_mismatch"

    return ""


def normalize_scope_token(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def normalize_product_group(value: str) -> str:
    token = normalize_scope_token(value or "auto")
    for canonical, aliases in PRODUCT_SCOPE_ALIASES.items():
        if token in aliases:
            return canonical
    return token or "auto"


def is_product_scope_mismatch(candidate: PolicyCandidate, product_group: str) -> bool:
    group = (product_group or "auto").lower()
    if group == "auto":
        return False
    text = " ".join([candidate.principle, candidate.subject, candidate.condition, candidate.constraint, candidate.context])
    group_tokens = {
        "deposit": ["예금", "적금", "예금성", "부보", "예금자보호"],
        "loan": ["대출", "대출성", "차주", "상환", "연체"],
        "investment": ["투자", "투자성", "펀드", "수익률", "원금손실", "ELS", "파생"],
        "insurance": ["보험", "보장성", "보험료", "해지환급"],
    }
    other_tokens = [
        token
        for key, values in group_tokens.items()
        if key != group
        for token in values
    ]
    own_tokens = group_tokens.get(group, [])
    return any(token in text for token in other_tokens) and not any(token in text for token in own_tokens)


def is_operational_candidate(candidate: PolicyCandidate) -> bool:
    text = " ".join([candidate.principle, candidate.subject, candidate.condition, candidate.constraint, candidate.context, candidate.cu_type])
    operational_tokens = [
        "제재",
        "제재금",
        "벌점",
        "시정요구",
        "사용중단",
        "준법감시인",
        "연합회 심의",
        "심의필",
        "사전승인",
        "광고심의",
        "심의대상",
        "협회",
        "연합회",
        "확인 표시",
        "직접판매업자 확인",
        "실태점검",
    ]
    if any(token in text for token in operational_tokens):
        return True
    return candidate.cu_type.upper() in {"SANCTION", "SANCTION_RULE", "REVIEW_PROCEDURE", "PROCEDURE"}
