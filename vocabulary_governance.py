"""Govern PolicyHypernym labels into Korean canonical vocabulary.

This is an offline governance pass. It preserves node ids and relationships,
keeps the original generated label as an alias, and updates `name` to a Korean
canonical label so runtime normalization shows stable Korean policy terms.

There is no deterministic translation fallback; canonicalization is done through
LLM structured output and validated before writing.
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from typing import Any

from llm_gateway import LLMGateway
from policy_compiler import DOMAIN_VALUES, is_korean_canonical_label


LOGGER = logging.getLogger(__name__)

GOVERNANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "hypernym_id": {"type": "string"},
                    "canonical_name_ko": {"type": "string"},
                    "domain": {"type": "string", "enum": DOMAIN_VALUES},
                    "description_ko": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "merge_key": {"type": "string"},
                    "confidence": {"type": "number"},
                    "why": {"type": "string"},
                },
                "required": [
                    "hypernym_id",
                    "canonical_name_ko",
                    "domain",
                    "description_ko",
                    "aliases",
                    "merge_key",
                    "confidence",
                    "why",
                ],
            },
        }
    },
    "required": ["items"],
}


class VocabularyGovernance:
    def __init__(
        self,
        *,
        llm: LLMGateway | None = None,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        from neo4j import GraphDatabase

        self.llm = llm or LLMGateway()
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

    def govern(
        self,
        *,
        workspace_id: str,
        batch_size: int = 40,
        max_batches: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, int]:
        rows = self._load_hypernyms(workspace_id=workspace_id)
        batches = [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]
        if max_batches is not None:
            batches = batches[:max_batches]
        counts = {"batches": 0, "reviewed": 0, "updated": 0}
        for batch in batches:
            governed: dict[str, Any] = {"items": []}
            errors: list[str] = []
            repair_note = ""
            for attempt in range(3):
                governed = self._govern_batch(batch, repair_note=repair_note)
                errors = validate_governance_output(governed, {str(row["hypernym_id"]) for row in batch})
                if not errors:
                    break
                LOGGER.warning("vocabulary governance validation failed on attempt %s: %s", attempt + 1, errors)
                repair_note = (
                    "[previous_output_validation_errors]\n"
                    f"{errors}\n"
                    "Repair the output. Return exactly one item for every input hypernym_id.\n\n"
                )
            if errors:
                raise RuntimeError(f"Vocabulary governance validation failed after retries: {errors}")
            counts["batches"] += 1
            counts["reviewed"] += len(governed["items"])
            if dry_run:
                LOGGER.info("dry-run governed sample: %s", str(governed["items"][:5])[:1200])
                continue
            self._write_governed(workspace_id=workspace_id, items=governed["items"])
            counts["updated"] += len(governed["items"])
        return counts

    def _load_hypernyms(self, *, workspace_id: str) -> list[dict[str, Any]]:
        with self.driver.session(**self._session_kwargs()) as session:
            return [
                dict(record)
                for record in session.run(
                    """
                    MATCH (h:PolicyHypernym {workspace_id: $workspace_id})
                    RETURN h.id AS hypernym_id,
                           h.name AS name,
                           h.domain AS domain,
                           h.description AS description,
                           h.aliases AS aliases,
                           h.canonical_name_ko AS canonical_name_ko
                    ORDER BY h.domain, h.name
                    """,
                    workspace_id=workspace_id,
                )
            ]

    def _govern_batch(self, batch: list[dict[str, Any]], *, repair_note: str = "") -> dict[str, Any]:
        return self.llm.structured(
            name="graphcompliance_policy_hypernym_governance",
            schema=GOVERNANCE_SCHEMA,
            system=(
                "You govern a Korean financial compliance PolicyHypernym vocabulary. "
                "For each input id, return one Korean canonical policy label. Keep legal/regulatory meaning, "
                "prefer concise noun phrases used in Korean financial regulation, and preserve useful English "
                "acronyms only with Korean context, e.g. '주가연계증권(ELS)'. Do not use English-only labels, "
                "snake_case, generic labels like actor/claim/risk, or broad translations that lose the domain. "
                "Add the original name and useful variants to aliases."
            ),
            user=f"{repair_note}[required_hypernym_ids]\n{[row['hypernym_id'] for row in batch]}\n\n[policy_hypernyms]\n{batch}",
        )

    def _write_governed(self, *, workspace_id: str, items: list[dict[str, Any]]) -> None:
        now = datetime.now(UTC).isoformat()
        with self.driver.session(**self._session_kwargs()) as session:
            session.run(
                """
                UNWIND $items AS row
                MATCH (h:PolicyHypernym {id: row.hypernym_id, workspace_id: $workspace_id})
                SET h.original_name = coalesce(h.original_name, h.name),
                    h.name = row.canonical_name_ko,
                    h.canonical_name_ko = row.canonical_name_ko,
                    h.domain = row.domain,
                    h.description_ko = row.description_ko,
                    h.aliases = row.aliases,
                    h.merge_key = row.merge_key,
                    h.governance_status = 'canonicalized',
                    h.governance_confidence = row.confidence,
                    h.governance_reason = row.why,
                    h.governed_at = $now
                """,
                workspace_id=workspace_id,
                now=now,
                items=items,
            )


def validate_governance_output(governed: dict[str, Any], expected_ids: set[str]) -> list[str]:
    rows = governed.get("items", [])
    output_ids = {str(row.get("hypernym_id")) for row in rows}
    errors: list[str] = []
    if missing := sorted(expected_ids - output_ids):
        errors.append(f"missing governed ids: {missing}")
    if extra := sorted(output_ids - expected_ids):
        errors.append(f"unknown governed ids: {extra}")
    for row in rows:
        name = str(row.get("canonical_name_ko", ""))
        if not is_korean_canonical_label(name):
            errors.append(f"non-Korean canonical_name_ko for {row.get('hypernym_id')}: {name}")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or not aliases:
            errors.append(f"aliases missing for {row.get('hypernym_id')}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonicalize PolicyHypernym labels into Korean.")
    parser.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")
    governance = VocabularyGovernance()
    try:
        counts = governance.govern(
            workspace_id=args.workspace_id,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
            dry_run=args.dry_run,
        )
    finally:
        governance.close()
    LOGGER.info("vocabulary governance counts: %s", counts)


if __name__ == "__main__":
    main()
