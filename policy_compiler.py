"""Compile Neo4j legal corpus into GraphCompliance policy alignment nodes.

This is an offline governance/compiler step, not the runtime judge. It turns the
existing legal corpus and curated CUs into the paper-shaped alignment layer:

    LegalClause/LegalChunk -> Premise -> PolicyHypernym
    Premise -> ComplianceUnit -> CUEmbeddingProfile

The compiler uses LLM structured outputs and OpenAI embeddings. It intentionally
has no deterministic policy-term fallback.
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from typing import Any

from ccg_embeddings import EmbeddingGateway
from llm_gateway import LLMGateway
from utils import stable_id, to_jsonable


LOGGER = logging.getLogger(__name__)

DOMAIN_VALUES = ["product", "claim", "risk", "actor", "disclosure", "suitability", "channel", "obligation"]
PREMISE_TYPES = [
    "definition",
    "scope",
    "role",
    "product_type",
    "risk_type",
    "obligation",
    "condition",
    "exception_scope",
    "sanction_basis",
]

COMPILER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "policy_hypernyms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "domain": {"type": "string", "enum": DOMAIN_VALUES},
                    "description": {"type": "string"},
                    "priority": {"type": "integer"},
                },
                "required": ["name", "domain", "description", "priority"],
            },
        },
        "premises": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "statement": {"type": "string"},
                    "premise_type": {"type": "string", "enum": PREMISE_TYPES},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "source_cu_ids": {"type": "array", "items": {"type": "string"}},
                    "hypernym_names": {"type": "array", "items": {"type": "string"}},
                    "support_strength": {"type": "string", "enum": ["STRONG", "WEAK"]},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "statement",
                    "premise_type",
                    "source_ids",
                    "source_cu_ids",
                    "hypernym_names",
                    "support_strength",
                    "confidence",
                ],
            },
        },
        "cu_profiles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "cu_id": {"type": "string"},
                    "subject_hypernym_names": {"type": "array", "items": {"type": "string"}},
                    "profile_summary": {"type": "string"},
                    "embedding_text": {"type": "string"},
                },
                "required": ["cu_id", "subject_hypernym_names", "profile_summary", "embedding_text"],
            },
        },
    },
    "required": ["policy_hypernyms", "premises", "cu_profiles"],
}


class PolicyAlignmentCompiler:
    def __init__(
        self,
        *,
        llm: LLMGateway | None = None,
        embedder: EmbeddingGateway | None = None,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        from neo4j import GraphDatabase

        self.llm = llm or LLMGateway()
        self.embedder = embedder or EmbeddingGateway()
        self.uri = uri or os.environ.get("NEO4J_URI", "")
        self.user = user or os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "")
        if not self.uri or not self.user or not self.password:
            raise RuntimeError("NEO4J_URI, NEO4J_USER/NEO4J_USERNAME, and NEO4J_PASSWORD are required.")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        self.database = os.environ.get("NEO4J_DATABASE")

    def close(self) -> None:
        self.driver.close()

    def _session_kwargs(self) -> dict[str, str]:
        return {"database": self.database} if self.database else {}

    def compile(
        self,
        *,
        workspace_id: str,
        batch_size: int = 16,
        max_batches: int | None = None,
        missing_active_links_only: bool = False,
        dry_run: bool = False,
    ) -> dict[str, int]:
        sources = self._load_policy_sources(workspace_id=workspace_id, missing_active_links_only=missing_active_links_only)
        if not sources:
            raise RuntimeError("No active ComplianceUnit sources found in Neo4j.")
        batches = [sources[index : index + batch_size] for index in range(0, len(sources), batch_size)]
        if max_batches is not None:
            batches = batches[:max_batches]
        counts = {"batches": 0, "policy_hypernyms": 0, "premises": 0, "cu_profiles": 0}
        embedding_dimension = 0
        for batch in batches:
            compiled = self._compile_batch(batch)
            normalized = self._normalize_compiled(workspace_id, compiled)
            if normalized["premises"] and not embedding_dimension:
                embedding_dimension = len(normalized["premises"][0]["embedding"])
            if normalized["cu_profiles"] and not embedding_dimension:
                embedding_dimension = len(normalized["cu_profiles"][0]["embedding"])
            counts["batches"] += 1
            counts["policy_hypernyms"] += len(normalized["policy_hypernyms"])
            counts["premises"] += len(normalized["premises"])
            counts["cu_profiles"] += len(normalized["cu_profiles"])
            if dry_run:
                LOGGER.info("dry-run compiled batch sample: %s", str(to_jsonable(normalized))[:1000])
                continue
            self._write_compiled(workspace_id=workspace_id, compiled=normalized)
        if not dry_run:
            self._ensure_vector_indexes(embedding_dimension or 1536)
        return counts

    def _load_policy_sources(self, *, workspace_id: str, missing_active_links_only: bool) -> list[dict[str, Any]]:
        with self.driver.session(**self._session_kwargs()) as session:
            return [
                dict(record)
                for record in session.run(
                    """
                    MATCH (cu:ComplianceUnit {workspace_id: $workspace_id})
                    WHERE coalesce(cu.active_for_gate, false) = true
                      AND (
                        $missing_active_links_only = false
                        OR NOT (cu)-[:HAS_SUBJECT_HYPERNYM]->(:PolicyHypernym {workspace_id: $workspace_id})
                        OR NOT (cu)-[:HAS_EMBEDDING_PROFILE]->(:CUEmbeddingProfile {workspace_id: $workspace_id})
                      )
                    OPTIONAL MATCH (clause:LegalClause)-[:GROUNDS_CU]->(cu)
                    OPTIONAL MATCH (chunk:LegalChunk)-[:EVIDENCES_CU]->(cu)
                    OPTIONAL MATCH (cu)-[:GROUNDED_IN|HAS_SOURCE_CHUNK]->(direct)
                    RETURN cu.id AS cu_id,
                           labels(cu) AS cu_labels,
                           coalesce(cu.principle, '') AS principle,
                           coalesce(cu.subject, '') AS subject,
                           coalesce(cu.condition, '') AS condition,
                           coalesce(cu.constraint, '') AS constraint,
                           coalesce(cu.context, '') AS context,
                           coalesce(cu.cu_type, '') AS cu_type,
                           coalesce(cu.severity, '') AS severity,
                           coalesce(cu.source_evidence, cu.summary, cu.text, '') AS cu_evidence,
                           collect(DISTINCT {
                             id: clause.id,
                             text: clause.text,
                             article_no: clause.article_no,
                             document_title: clause.document_title
                           })[0..4] AS clauses,
                           collect(DISTINCT {
                             id: chunk.id,
                             text: chunk.text,
                             article_no: chunk.article_no,
                             document_title: chunk.document_title
                           })[0..4] AS chunks,
                           collect(DISTINCT {
                             id: direct.id,
                             text: coalesce(direct.text, direct.summary, direct.article_title, direct.title, '')
                           })[0..4] AS direct_evidence
                    ORDER BY severity, cu_id
                    """,
                    workspace_id=workspace_id,
                    missing_active_links_only=missing_active_links_only,
                )
            ]

    def _compile_batch(self, batch: list[dict[str, Any]]) -> dict[str, Any]:
        required_cu_ids = {str(row["cu_id"]) for row in batch}
        validation_note = ""
        for attempt in range(3):
            compiled = self.llm.structured(
                name="graphcompliance_policy_alignment_compile",
                schema=COMPILER_SCHEMA,
                system=(
                    "You compile Korean financial compliance policy graph sources into GraphCompliance "
                    "alignment nodes. Extract policy-level hypernyms, concise premises, and CU embedding "
                    "profiles. Use only provided sources. Do not invent laws. Hypernyms must be reusable "
                    "policy terms suitable for normalizing financial ad context entities and risks. "
                    "Every policy_hypernyms.name must be a Korean canonical label. English acronyms are "
                    "allowed only with Korean context, for example '주가연계증권(ELS)'. Do not use snake_case, "
                    "English-only labels, or generic labels such as 'actor' or 'claim'. "
                    "Return exactly one cu_profiles item for every input cu_id, even when the CU is broad; "
                    "use the most policy-relevant subject hypernyms supported by the source."
                ),
                user=f"{validation_note}[required_cu_ids]\n{sorted(required_cu_ids)}\n\n[policy_sources]\n{batch}",
            )
            errors = validate_compiler_output(compiled, required_cu_ids)
            if not errors:
                return compiled
            validation_note = (
                "[previous_output_validation_errors]\n"
                f"{errors}\n"
                "Repair the output. Do not omit any required cu_id and define every hypernym name used by profiles.\n\n"
            )
            LOGGER.warning("policy compiler batch validation failed on attempt %s: %s", attempt + 1, errors)
        raise RuntimeError(f"Policy compiler LLM omitted required CU profiles after retries: {sorted(required_cu_ids)}")

    def _normalize_compiled(self, workspace_id: str, compiled: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        hypernyms_by_name: dict[str, dict[str, Any]] = {}
        for row in compiled["policy_hypernyms"]:
            name = " ".join(str(row["name"]).split())
            domain = str(row["domain"])
            hypernym_id = stable_id("policy_hypernym", workspace_id, domain, name)
            hypernyms_by_name[name] = {
                "id": hypernym_id,
                "name": name,
                "domain": domain,
                "description": str(row["description"]),
                "priority": int(row["priority"]),
                "status": "approved",
            }

        premise_rows: list[dict[str, Any]] = []
        for row in compiled["premises"]:
            statement = " ".join(str(row["statement"]).split())
            premise_id = stable_id("premise", workspace_id, statement)
            hypernym_ids = [hypernyms_by_name[name]["id"] for name in row["hypernym_names"] if name in hypernyms_by_name]
            source_cu_ids = [str(item) for item in row["source_cu_ids"]]
            source_ids = [str(item) for item in row["source_ids"]]
            premise_rows.append(
                {
                    "id": premise_id,
                    "statement": statement,
                    "premise_type": str(row["premise_type"]),
                    "source_ids": source_ids,
                    "source_cu_ids": source_cu_ids,
                    "hypernym_ids": hypernym_ids,
                    "support_strength": str(row["support_strength"]),
                    "confidence": float(row["confidence"]),
                }
            )
        premise_embeddings = self.embedder.embed_many([row["statement"] for row in premise_rows])
        premises = [{**row, "embedding": embedding} for row, embedding in zip(premise_rows, premise_embeddings, strict=True)]

        profile_rows: list[dict[str, Any]] = []
        for row in compiled["cu_profiles"]:
            embedding_text = " ".join(str(row["embedding_text"]).split())
            hypernym_ids = [
                hypernyms_by_name[name]["id"] for name in row["subject_hypernym_names"] if name in hypernyms_by_name
            ]
            profile_rows.append(
                {
                    "id": stable_id("cu_embedding_profile", workspace_id, row["cu_id"], embedding_text),
                    "cu_id": str(row["cu_id"]),
                    "subject_hypernym_ids": hypernym_ids,
                    "profile_summary": str(row["profile_summary"]),
                    "embedding_text": embedding_text,
                }
            )
        profile_embeddings = self.embedder.embed_many([row["embedding_text"] for row in profile_rows])
        profiles = [{**row, "embedding": embedding} for row, embedding in zip(profile_rows, profile_embeddings, strict=True)]

        return {
            "policy_hypernyms": list(hypernyms_by_name.values()),
            "premises": premises,
            "cu_profiles": profiles,
        }

    def _write_compiled(self, *, workspace_id: str, compiled: dict[str, list[dict[str, Any]]]) -> None:
        now = datetime.now(UTC).isoformat()
        with self.driver.session(**self._session_kwargs()) as session:
            session.run(
                """
                UNWIND $rows AS row
                MERGE (h:PolicyHypernym {id: row.id, workspace_id: $workspace_id})
                SET h += row, h.workspace_id = $workspace_id, h.updated_at = $now
                """,
                workspace_id=workspace_id,
                now=now,
                rows=compiled["policy_hypernyms"],
            )
            for premise in compiled["premises"]:
                session.run(
                    """
                    MERGE (p:Premise {id: $id, workspace_id: $workspace_id})
                    SET p += $props, p.workspace_id = $workspace_id, p.updated_at = $now
                    WITH p
                    UNWIND $source_ids AS source_id
                    OPTIONAL MATCH (source {id: source_id, workspace_id: $workspace_id})
                    FOREACH (_ IN CASE WHEN source IS NULL THEN [] ELSE [1] END |
                      MERGE (source)-[:DERIVES_PREMISE {workspace_id: $workspace_id, source: 'graphcompliance_ccg_policy_compiler'}]->(p)
                    )
                    WITH p
                    UNWIND $hypernym_ids AS hypernym_id
                    MATCH (h:PolicyHypernym {id: hypernym_id, workspace_id: $workspace_id})
                    FOREACH (_ IN CASE WHEN $premise_type = 'definition' THEN [1] ELSE [] END |
                      MERGE (p)-[:DEFINES_HYPERNYM {workspace_id: $workspace_id, source: 'graphcompliance_ccg_policy_compiler'}]->(h)
                    )
                    FOREACH (_ IN CASE WHEN $premise_type <> 'definition' THEN [1] ELSE [] END |
                      MERGE (p)-[:SUPPORTS_HYPERNYM {workspace_id: $workspace_id, source: 'graphcompliance_ccg_policy_compiler'}]->(h)
                    )
                    WITH p
                    UNWIND $source_cu_ids AS cu_id
                    OPTIONAL MATCH (cu:ComplianceUnit {id: cu_id, workspace_id: $workspace_id})
                    FOREACH (_ IN CASE WHEN cu IS NULL THEN [] ELSE [1] END |
                      MERGE (p)-[:SUPPORTS_CU {workspace_id: $workspace_id, source: 'graphcompliance_ccg_policy_compiler'}]->(cu)
                    )
                    """,
                    workspace_id=workspace_id,
                    now=now,
                    id=premise["id"],
                    props=premise,
                    source_ids=premise["source_ids"],
                    source_cu_ids=premise["source_cu_ids"],
                    hypernym_ids=premise["hypernym_ids"],
                    premise_type=premise["premise_type"],
                )
            for profile in compiled["cu_profiles"]:
                session.run(
                    """
                    MATCH (cu:ComplianceUnit {id: $cu_id, workspace_id: $workspace_id})
                    MERGE (profile:CUEmbeddingProfile {id: $profile_id, workspace_id: $workspace_id})
                    SET profile += $props, profile.workspace_id = $workspace_id, profile.updated_at = $now
                    MERGE (cu)-[:HAS_EMBEDDING_PROFILE {workspace_id: $workspace_id, source: 'graphcompliance_ccg_policy_compiler'}]->(profile)
                    WITH cu
                    UNWIND $hypernym_ids AS hypernym_id
                    MATCH (h:PolicyHypernym {id: hypernym_id, workspace_id: $workspace_id})
                    MERGE (cu)-[:HAS_SUBJECT_HYPERNYM {workspace_id: $workspace_id, source: 'graphcompliance_ccg_policy_compiler'}]->(h)
                    """,
                    workspace_id=workspace_id,
                    now=now,
                    cu_id=profile["cu_id"],
                    profile_id=profile["id"],
                    props=profile,
                    hypernym_ids=profile["subject_hypernym_ids"],
                )

    def _ensure_vector_indexes(self, dimension: int) -> None:
        dimension = int(dimension)
        if dimension <= 0:
            raise RuntimeError("Embedding dimension must be positive before creating vector indexes.")
        with self.driver.session(**self._session_kwargs()) as session:
            session.run(
                f"""
                CREATE VECTOR INDEX premise_embedding_vector IF NOT EXISTS
                FOR (p:Premise) ON (p.embedding)
                OPTIONS {{indexConfig: {{`vector.dimensions`: {dimension}, `vector.similarity_function`: 'cosine'}}}}
                """
            )
            session.run(
                f"""
                CREATE VECTOR INDEX cu_embedding_profile_vector IF NOT EXISTS
                FOR (p:CUEmbeddingProfile) ON (p.embedding)
                OPTIONS {{indexConfig: {{`vector.dimensions`: {dimension}, `vector.similarity_function`: 'cosine'}}}}
                """
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile GraphCompliance policy alignment layer.")
    parser.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--missing-active-links-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    compiler = PolicyAlignmentCompiler()
    try:
        counts = compiler.compile(
            workspace_id=args.workspace_id,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
            missing_active_links_only=args.missing_active_links_only,
            dry_run=args.dry_run,
        )
    finally:
        compiler.close()
    LOGGER.info("compiled policy alignment counts: %s", counts)


def validate_compiler_output(compiled: dict[str, Any], required_cu_ids: set[str]) -> list[str]:
    errors: list[str] = []
    hypernym_names = {str(row["name"]) for row in compiled.get("policy_hypernyms", [])}
    non_korean = sorted(name for name in hypernym_names if not is_korean_canonical_label(name))
    if non_korean:
        errors.append(f"policy_hypernyms contain non-Korean canonical labels: {non_korean}")
    profile_cu_ids = {str(row["cu_id"]) for row in compiled.get("cu_profiles", [])}
    missing_profiles = sorted(required_cu_ids - profile_cu_ids)
    extra_profiles = sorted(profile_cu_ids - required_cu_ids)
    if missing_profiles:
        errors.append(f"missing cu_profiles for cu_id: {missing_profiles}")
    if extra_profiles:
        errors.append(f"cu_profiles contain unknown cu_id: {extra_profiles}")
    for profile in compiled.get("cu_profiles", []):
        names = [str(name) for name in profile.get("subject_hypernym_names", [])]
        if not names:
            errors.append(f"cu_profile has no subject_hypernym_names: {profile.get('cu_id')}")
        unknown = sorted(set(names) - hypernym_names)
        if unknown:
            errors.append(f"cu_profile references undefined hypernyms for {profile.get('cu_id')}: {unknown}")
    for premise in compiled.get("premises", []):
        unknown = sorted(set(str(name) for name in premise.get("hypernym_names", [])) - hypernym_names)
        if unknown:
            errors.append(f"premise references undefined hypernyms: {unknown}")
    return errors


def is_korean_canonical_label(name: str) -> bool:
    normalized = " ".join(str(name).split())
    if "_" in normalized:
        return False
    if not any("\uac00" <= char <= "\ud7a3" for char in normalized):
        return False
    return True


if __name__ == "__main__":
    main()
