"""Build ProductFact-grounded synthetic evaluation records.

Pipeline:

1. Resolve a real product from the Neo4j Product Graph / JB metadata.
2. Read selected product documents and extract ProductFact evidence.
3. Generate a clean compliant ad from ProductFact evidence.
4. Mutate that clean ad with violation taxonomy controls.
5. Save JSONL records whose labels/spans are known from the mutation step.

This module deliberately keeps gold labels out of the review workflow. The
generated records are consumed later by ``evaluate.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

from env_loader import load_local_env
from jb_data_context import build_product_context
from llm_gateway import LLMGateway
from product_facts import MAX_DOCUMENTS, extract_document_snippet, load_disclosure_metadata, select_product_documents
from schemas import ReviewInput


DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parent / "eval" / "violation_taxonomy_v0_2.json"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "eval" / "synthetic_product_fact_seed.jsonl"
DEFAULT_PRODUCTS = [
    "(26년 JUMP UP) 특판 예금",
    "JB 햇살론 일반보증",
]
LOGGER = logging.getLogger(__name__)

CHANNEL_PROFILES: dict[str, dict[str, Any]] = {
    "web_page": {
        "headline_max_chars": 48,
        "subcopy_max_chars": 110,
        "body_max_chars": 520,
        "footnote_max_chars": 320,
        "style": "landing page copy with one clear headline and concise body",
    },
    "sns": {
        "headline_max_chars": 36,
        "subcopy_max_chars": 90,
        "body_max_chars": 180,
        "footnote_max_chars": 180,
        "style": "short SNS post with compact disclosures in the same visual hierarchy",
    },
    "banner": {
        "headline_max_chars": 28,
        "subcopy_max_chars": 70,
        "body_max_chars": 80,
        "footnote_max_chars": 120,
        "style": "compact banner copy; use fewer claims and only essential disclosures",
    },
    "mobile_push": {
        "headline_max_chars": 28,
        "subcopy_max_chars": 65,
        "body_max_chars": 80,
        "footnote_max_chars": 100,
        "style": "mobile push copy; one benefit claim plus a short disclosure",
    },
}


CLEAN_AD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "subcopy": {"type": "string"},
        "body": {"type": "string"},
        "footnote": {"type": "string"},
        "used_fact_ids": {"type": "array", "items": {"type": "string"}},
        "compliance_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "subcopy", "body", "footnote", "used_fact_ids", "compliance_notes"],
}


MUTATED_AD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "subcopy": {"type": "string"},
        "body": {"type": "string"},
        "footnote": {"type": "string"},
        "injected_span": {"type": "string"},
        "mutation_note": {"type": "string"},
    },
    "required": ["headline", "subcopy", "body", "footnote", "injected_span", "mutation_note"],
}


PRODUCT_FACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "product_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "fact_type": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": "string"},
                    "condition": {"type": "string"},
                    "source_document_id": {"type": "string"},
                    "page_or_chunk": {"type": "string"},
                    "evidence_text": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "fact_type",
                    "value",
                    "unit",
                    "condition",
                    "source_document_id",
                    "page_or_chunk",
                    "evidence_text",
                    "confidence",
                ],
            },
        }
    },
    "required": ["product_facts"],
}


def main() -> None:
    load_local_env(Path.cwd() / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    parser = argparse.ArgumentParser(description="Build ProductFact-grounded synthetic eval JSONL.")
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--workspace-id", default="graphcompliance_mvp_jb_20260530")
    parser.add_argument("--product", action="append", dest="products", help="Exact product name. Repeatable.")
    parser.add_argument("--auto-products", action="store_true", help="Sample product names from local JB disclosure metadata.")
    parser.add_argument("--product-group", default="auto")
    parser.add_argument("--channel", default="web_page")
    parser.add_argument("--channels", default=None, help="Comma-separated channels. Overrides --channel.")
    parser.add_argument("--max-products", type=int, default=2)
    parser.add_argument("--target-records", type=int, default=None, help="Stop after at least this many records.")
    parser.add_argument(
        "--codes-per-combo",
        type=int,
        default=None,
        help="Max mutation/hard-case codes emitted per product+channel combo. "
        "Deterministic rotation keeps pattern coverage balanced across products. "
        "None (default) emits all applicable codes (v0.1 behavior).",
    )
    args = parser.parse_args()

    products = resolve_generation_products(
        explicit_products=args.products,
        auto_products=args.auto_products,
        product_group=args.product_group,
        max_products=args.max_products,
    )
    channels = parse_channels(args.channels or args.channel)
    llm = LLMGateway()
    taxonomy = load_taxonomy(Path(args.taxonomy))
    records: list[dict[str, Any]] = []
    combo_index = 0
    for product_name in products[: args.max_products]:
        for channel in channels:
            try:
                bundle = build_product_fact_bundle(
                    product_name=product_name,
                    product_group=args.product_group,
                    channel=channel,
                    workspace_id=args.workspace_id,
                    llm=llm,
                )
                clean_ad = generate_clean_ad(bundle, llm=llm)
                records.extend(
                    build_records_from_product_facts(
                        taxonomy,
                        bundle,
                        clean_ad,
                        llm=llm,
                        codes_per_combo=args.codes_per_combo,
                        combo_index=combo_index,
                    )
                )
                combo_index += 1
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Skipping product/channel during synthetic generation: product=%s channel=%s error=%s", product_name, channel, exc)
                continue
            if args.target_records is not None and len(records) >= args.target_records:
                records = records[: args.target_records]
                break
        if args.target_records is not None and len(records) >= args.target_records:
            break

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, records)
    print(f"wrote {len(records)} records -> {output_path}")


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_channels(value: str) -> list[str]:
    channels = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [channel for channel in channels if channel not in CHANNEL_PROFILES]
    if unknown:
        raise ValueError(f"Unknown channels: {unknown}. Allowed: {sorted(CHANNEL_PROFILES)}")
    return channels or ["web_page"]


def resolve_generation_products(
    *,
    explicit_products: list[str] | None,
    auto_products: bool,
    product_group: str,
    max_products: int,
) -> list[str]:
    if explicit_products:
        return explicit_products[:max_products]
    if auto_products:
        products = product_names_from_metadata(product_group=product_group, limit=max_products)
        if products:
            return products
    return DEFAULT_PRODUCTS[:max_products]


def product_names_from_metadata(*, product_group: str, limit: int) -> list[str]:
    rows = load_disclosure_metadata()
    seen: set[str] = set()
    products: list[str] = []
    for row in rows:
        if str(row.get("extension") or "").lower() != ".pdf":
            continue
        product = str(row.get("product") or "").strip()
        if not product or product in seen:
            continue
        if product_group != "auto" and not row_matches_product_group(row, product_group):
            continue
        seen.add(product)
        products.append(product)
        if len(products) >= limit:
            break
    return products


def row_matches_product_group(row: dict[str, Any], product_group: str) -> bool:
    group_terms = {
        "deposit": ["예금", "적금", "입출금", "통장"],
        "loan": ["대출", "론", "햇살론", "마이너스"],
        "investment": ["펀드", "신탁", "els", "투자"],
        "insurance": ["보험", "보장성"],
    }
    haystack = " ".join(
        str(row.get(key) or "")
        for key in ("major", "category", "subcategory", "product", "label", "file_name", "relative_path")
    ).lower()
    if product_group == "deposit" and any(term in haystack for term in ("대출", "담보", "마이너스", "론")):
        return False
    return any(term.lower() in haystack for term in group_terms.get(product_group, [product_group]))


def channel_profile_for(channel: str) -> dict[str, Any]:
    return CHANNEL_PROFILES.get(channel, CHANNEL_PROFILES["web_page"])


def validate_ad_lengths(ad: dict[str, Any], channel: str, *, context: str) -> None:
    profile = channel_profile_for(channel)
    for field in ("headline", "subcopy", "body", "footnote"):
        limit = int(profile.get(f"{field}_max_chars") or 0)
        value = str(ad.get(field) or "")
        if limit and len(value) > limit:
            raise RuntimeError(
                f"{context} exceeds {channel} {field} length limit: {len(value)} > {limit}. "
                "Regenerate with fewer claims or shorter disclosure wording."
            )


def ensure_ad_lengths(
    ad: dict[str, Any],
    channel: str,
    *,
    context: str,
    llm: LLMGateway,
    schema: dict[str, Any],
    repair_payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        validate_ad_lengths(ad, channel, context=context)
        return ad
    except RuntimeError as exc:
        repaired = repair_ad_to_channel_limits(
            ad,
            channel=channel,
            context=context,
            length_error=str(exc),
            llm=llm,
            schema=schema,
            repair_payload=repair_payload,
        )
        validate_ad_lengths(repaired, channel, context=f"{context}_repair")
        return repaired


def repair_ad_to_channel_limits(
    ad: dict[str, Any],
    *,
    channel: str,
    context: str,
    length_error: str,
    llm: LLMGateway,
    schema: dict[str, Any],
    repair_payload: dict[str, Any],
) -> dict[str, Any]:
    return llm.structured(
        name="gc_ad_length_repair",
        schema=schema,
        system=(
            "You repair Korean financial advertisement JSON to fit the provided channel length limits. "
            "Preserve the compliance meaning and ProductFact grounding. Do not add new product facts. "
            "Use fewer claims, shorter disclosures, and compact wording. If injected_span exists, keep it "
            "as an exact substring of one returned field unless it is intentionally empty for a hard case."
        ),
        user=json.dumps(
            {
                "channel": channel,
                "channel_profile": channel_profile_for(channel),
                "length_error": length_error,
                "current_ad": ad,
                "repair_context": repair_payload,
            },
            ensure_ascii=False,
        ),
    )


def compact_product_facts_for_generation(product_facts: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
    priority_keywords = [
        "최고",
        "기본",
        "우대",
        "금리",
        "이자율",
        "가입기간",
        "계약기간",
        "가입대상",
        "한도",
        "예금자보호",
        "수수료",
        "중도해지",
        "심사",
        "연체",
        "원금손실",
        "위험",
    ]
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, fact in enumerate(product_facts):
        text = " ".join(str(fact.get(key) or "") for key in ("fact_type", "value", "condition", "evidence_text"))
        score = sum(1 for keyword in priority_keywords if keyword in text)
        scored.append((score, -index, fact))
    scored.sort(reverse=True)
    selected = [fact for _, _, fact in scored[:limit]]
    selected_ids = {str(fact.get("fact_id") or "") for fact in selected}
    for fact in product_facts:
        if len(selected) >= limit:
            break
        fact_id = str(fact.get("fact_id") or "")
        if fact_id not in selected_ids:
            selected.append(fact)
            selected_ids.add(fact_id)
    return selected


def build_product_fact_bundle(
    *,
    product_name: str,
    product_group: str,
    channel: str,
    workspace_id: str,
    llm: LLMGateway,
) -> dict[str, Any]:
    review_input = ReviewInput(
        workspace_id=workspace_id,
        product_group=product_group,
        channel=channel,
        content_text=f"{product_name} 광고 초안 생성을 위한 상품문서 확인",
    )
    product_context, disclosure_requirements = build_product_context(review_input, [])
    exact_products = [item for item in product_context.get("matched_products", []) if item.get("match_basis") == "exact_product_name"]
    if len(exact_products) != 1:
        raise RuntimeError(f"Product must resolve to one exact product before synthetic generation: {product_name}")

    matched_product = str(exact_products[0]["product"])
    documents = select_product_documents(matched_product)[:MAX_DOCUMENTS]
    if not documents:
        raise RuntimeError(f"No product documents found for {matched_product}")
    missing = [document for document in documents if not document.get("exists")]
    if missing:
        raise RuntimeError(f"Product documents missing on disk for {matched_product}: {missing}")

    snippets: list[dict[str, str]] = []
    usable_documents: list[dict[str, Any]] = []
    for document in documents:
        try:
            snippets.append(extract_document_snippet(document))
            usable_documents.append(document)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Skipping unreadable product document: product=%s document=%s error=%s",
                matched_product,
                document.get("file_name") or document.get("document_id"),
                exc,
            )
    if not snippets:
        raise RuntimeError(f"No readable product document snippets for {matched_product}")
    product_facts = extract_product_facts_from_snippets(
        llm=llm,
        product_name=matched_product,
        product_group=str(product_context.get("product_group") or product_group),
        snippets=snippets,
    )
    # 데이터 위생: 추출 LLM이 존재하지 않는 source_document_id를 반환한 fact만 버린다
    # (심사/판정 경로가 아닌 생성 경로의 데이터 정제 — 결정론 fallback이 아니다). 유효한
    # fact가 하나도 남지 않으면 아래 validate에서 명시적으로 실패한다.
    known_document_ids = {str(d.get("document_id") or "") for d in usable_documents if d.get("document_id")}
    kept: list[dict[str, Any]] = []
    for fact in product_facts:
        if str(fact.get("source_document_id") or "") in known_document_ids:
            kept.append(fact)
        else:
            LOGGER.warning(
                "Dropping ProductFact with unknown source_document_id: product=%s fact=%s source=%s",
                matched_product,
                fact.get("fact_id"),
                fact.get("source_document_id"),
            )
    product_facts = kept
    validate_product_facts(product_facts, usable_documents)
    if not product_facts:
        raise RuntimeError(f"No ProductFact extracted for {matched_product}")

    return {
        "product_name": matched_product,
        "product_group": str(product_context.get("product_group") or product_group),
        "channel": channel,
        "product_context": product_context,
        "disclosure_requirements": disclosure_requirements,
        "selected_documents": usable_documents,
        "product_facts": product_facts,
    }


def extract_product_facts_from_snippets(
    *,
    llm: LLMGateway,
    product_name: str,
    product_group: str,
    snippets: list[dict[str, str]],
) -> list[dict[str, Any]]:
    result = llm.structured(
        name="graphcompliance_synthetic_product_fact_extraction",
        schema=PRODUCT_FACT_SCHEMA,
        system=(
            "You extract Korean financial ProductFact evidence for synthetic compliance evaluation. "
            "Use only the provided product document snippets. Do not infer missing facts. Prefer facts "
            "needed to generate compliant ads and mutations: rate, term, eligibility, preferential "
            "conditions, fees, protection limits, screening conditions, repayment conditions, loss risk, "
            "and product-document cautions. Quote short evidence_text. source_document_id must exactly "
            "match one of the provided document_snippets.source_document_id values."
        ),
        user=(
            f"[product]\n{product_name}\n\n"
            f"[product_group]\n{product_group}\n\n"
            f"[document_snippets]\n{json.dumps(snippets, ensure_ascii=False)}"
        ),
    )
    facts: list[dict[str, Any]] = []
    for index, row in enumerate(result.get("product_facts", [])):
        value = str(row.get("value", "")).strip()
        condition = str(row.get("condition", "")).strip()
        evidence_text = str(row.get("evidence_text", "")).strip()
        facts.append(
            {
                "fact_id": f"pf_{index:03d}_{safe_slug(str(row.get('fact_type') or 'fact'))}",
                "fact_type": str(row.get("fact_type", "")),
                "value": value or condition or evidence_text,
                "unit": str(row.get("unit", "")),
                "condition": condition,
                "source_document_id": str(row.get("source_document_id", "")),
                "page_or_chunk": str(row.get("page_or_chunk", "")),
                "evidence_text": evidence_text,
                "confidence": float(row.get("confidence") or 0.0),
            }
        )
    return facts


def validate_product_facts(product_facts: list[dict[str, Any]], documents: list[dict[str, Any]]) -> None:
    known_document_ids = {str(document.get("document_id") or "") for document in documents if document.get("document_id")}
    if not product_facts:
        raise RuntimeError("ProductFact extraction returned no facts.")
    for fact in product_facts:
        fact_id = str(fact.get("fact_id") or "")
        source_document_id = str(fact.get("source_document_id") or "")
        evidence_text = str(fact.get("evidence_text") or "").strip()
        fact_type = str(fact.get("fact_type") or "").strip()
        value = str(fact.get("value") or "").strip()
        confidence = float(fact.get("confidence") or 0.0)
        if not fact_id or not fact_type:
            raise RuntimeError(f"ProductFact missing id/type: {fact}")
        if not value:
            raise RuntimeError(f"ProductFact missing value: {fact_id}")
        if not evidence_text:
            raise RuntimeError(f"ProductFact missing evidence_text: {fact_id}")
        if source_document_id not in known_document_ids:
            raise RuntimeError(
                f"ProductFact source_document_id must match selected documents: {fact_id} source={source_document_id}"
            )
        if confidence < 0.0 or confidence > 1.0:
            raise RuntimeError(f"ProductFact confidence out of range: {fact_id} confidence={confidence}")


def generate_clean_ad(bundle: dict[str, Any], *, llm: LLMGateway) -> dict[str, Any]:
    channel = str(bundle.get("channel") or "web_page")
    channel_profile = channel_profile_for(channel)
    result = llm.structured(
        name="graphcompliance_clean_ad_from_product_facts",
        schema=CLEAN_AD_SCHEMA,
        system=(
            "You generate a compliant Korean financial advertisement from ProductFact evidence. "
            "Use only the provided facts. Do not invent rates, conditions, eligibility, protection, "
            "screening, or risk information. Keep required disclosures near the related claim. "
            "Avoid guaranteed-return, 누구나, 조건 없이, 무조건, or unsupported superiority wording. "
            "Respect the channel profile length limits. If the channel is short, use fewer claims rather "
            "than hiding disclosures. Do not copy a full product table; choose one clear advertising angle."
        ),
        user=json.dumps(
            {
                "product_name": bundle["product_name"],
                "product_group": bundle["product_group"],
                "channel": bundle["channel"],
                "channel_profile": channel_profile,
                "product_facts": compact_product_facts_for_generation(bundle["product_facts"]),
                "disclosure_requirements": bundle["disclosure_requirements"],
            },
            ensure_ascii=False,
        ),
    )
    clean_ad = {
        "headline": str(result.get("headline", "")),
        "subcopy": str(result.get("subcopy", "")),
        "body": str(result.get("body", "")),
        "footnote": str(result.get("footnote", "")),
        "used_fact_ids": [str(item) for item in result.get("used_fact_ids", [])],
        "compliance_notes": [str(item) for item in result.get("compliance_notes", [])],
    }
    clean_ad = ensure_ad_lengths(
        clean_ad,
        channel,
        context="clean_ad",
        llm=llm,
        schema=CLEAN_AD_SCHEMA,
        repair_payload={
            "product_name": bundle["product_name"],
            "product_group": bundle["product_group"],
            "channel": bundle["channel"],
            "channel_profile": channel_profile,
            "product_facts": compact_product_facts_for_generation(bundle["product_facts"]),
            "disclosure_requirements": bundle["disclosure_requirements"],
        },
    )
    return clean_ad


def applicable_codes(taxonomy: dict[str, Any], bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """이 상품군·채널에 적용 가능한 코드(빈 product_groups=보험/투자 제외)를 스키마 순서대로."""
    product_group = bundle["product_group"]
    channel = bundle["channel"]
    selected: list[dict[str, Any]] = []
    for code in taxonomy.get("codes", []):
        if product_group not in (code.get("product_groups") or []):
            continue
        allowed_channels = code.get("channels") or []
        if allowed_channels and channel not in allowed_channels:
            continue
        selected.append(code)
    return selected


def select_codes_for_combo(
    codes: list[dict[str, Any]], *, codes_per_combo: int | None, combo_index: int
) -> list[dict[str, Any]]:
    """조합당 코드 수 제한 시, combo_index로 결정론적 회전 선택 — 상품 간 패턴 커버리지 균형.

    codes_per_combo가 None이면 전체(기존 v0_1 경로와 동일).
    """
    if not codes or codes_per_combo is None or codes_per_combo >= len(codes):
        return codes
    n = len(codes)
    start = (combo_index * codes_per_combo) % n
    return [codes[(start + offset) % n] for offset in range(codes_per_combo)]


def build_records_from_product_facts(
    taxonomy: dict[str, Any],
    bundle: dict[str, Any],
    clean_ad: dict[str, Any],
    *,
    llm: LLMGateway | None = None,
    codes_per_combo: int | None = None,
    combo_index: int = 0,
) -> list[dict[str, Any]]:
    records = [clean_record(bundle, clean_ad)]
    codes = select_codes_for_combo(
        applicable_codes(taxonomy, bundle),
        codes_per_combo=codes_per_combo,
        combo_index=combo_index,
    )
    for code in codes:
        # 한 코드의 변이 생성 실패(예: span 미포함)가 상품 전체를 버리지 않도록 코드 단위로
        # 격리한다. gold 무결성은 유지된다 — 검증 통과한 변이만 레코드로 남는다.
        try:
            if code.get("category") == "hard_case_compliant":
                records.append(hard_case_record(bundle, clean_ad, code, llm=llm))
            else:
                records.append(mutated_record(bundle, clean_ad, code, llm=llm))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Skipping code during mutation: product=%s channel=%s code=%s error=%s",
                bundle.get("product_name"),
                bundle.get("channel"),
                code.get("code"),
                exc,
            )
            continue
    return records


def clean_record(bundle: dict[str, Any], clean_ad: dict[str, Any]) -> dict[str, Any]:
    product_name = str(bundle["product_name"])
    product_id = safe_slug(product_name)
    channel_id = safe_slug(str(bundle["channel"]))
    return {
        "id": f"syn_{product_id}_{channel_id}_clean",
        "title": f"{product_name} clean compliant ad",
        "text": ad_to_text(clean_ad),
        "structured_ad": clean_ad,
        "facts": facts_payload(bundle, mutation_code="CLEAN", clean_ad=clean_ad),
        "product_group": bundle["product_group"],
        "channel": bundle["channel"],
        "language": "ko",
        "source_type": "synthetic_product_fact_clean",
        "labels": {
            "violation": False,
            "violation_types": [],
            "articles": [],
            "sales_principles": ["광고규제", "설명의무"],
            "required_disclosures": disclosure_labels(bundle),
            "risk_level": "low",
            "expected_routing": "pass_candidate",
            "review_basis": ["ProductFact clean pool", "금융광고규제 가이드라인", "은행 광고심의 기준"],
        },
    }


def mutated_record(
    bundle: dict[str, Any],
    clean_ad: dict[str, Any],
    code: dict[str, Any],
    *,
    llm: LLMGateway | None = None,
) -> dict[str, Any]:
    product_name = str(bundle["product_name"])
    mutated_ad = generate_mutated_ad(bundle, clean_ad, code, llm=llm)
    text = ad_to_text(mutated_ad)
    span = str(mutated_ad.get("injected_span") or mutation_span(code, bundle, text))
    if span and span not in text:
        raise RuntimeError(f"Mutation span must appear verbatim in mutated ad text: code={code['code']} span={span!r}")
    return {
        "id": f"syn_{safe_slug(product_name)}_{safe_slug(str(bundle['channel']))}_{str(code['code']).lower()}",
        "title": f"{product_name} mutated {code['code']}",
        "text": text,
        "structured_ad": {
            "headline": mutated_ad["headline"],
            "subcopy": mutated_ad["subcopy"],
            "body": mutated_ad["body"],
            "footnote": mutated_ad["footnote"],
            "mutation_note": mutated_ad.get("mutation_note", ""),
        },
        "facts": {
            **facts_payload(bundle, mutation_code=str(code["code"]), clean_ad=clean_ad),
            "injected_violation_code": code["code"],
            "expected_problem_spans": [span] if span else [],
            "mutation_instruction": code.get("mutation_instruction", ""),
        },
        "product_group": bundle["product_group"],
        "channel": bundle["channel"],
        "language": "ko",
        "source_type": "synthetic_product_fact_mutation",
        "labels": {
            "violation": True,
            "violation_types": [code["code"]],
            "articles": list(code.get("articles") or []),
            "sales_principles": list(code.get("sales_principles") or []),
            "required_disclosures": list(code.get("required_disclosures") or []),
            "risk_level": str(code.get("risk_level") or "medium"),
            "expected_routing": str(code.get("expected_routing") or "revise"),
            "review_basis": ["ProductFact mutation taxonomy v0.1", "금융광고규제 가이드라인", "은행 광고심의 기준"],
        },
    }


def hard_case_record(
    bundle: dict[str, Any],
    clean_ad: dict[str, Any],
    code: dict[str, Any],
    *,
    llm: LLMGateway | None = None,
) -> dict[str, Any]:
    product_name = str(bundle["product_name"])
    hard_case_ad = generate_mutated_ad(bundle, clean_ad, code, llm=llm)
    text = ad_to_text(hard_case_ad)
    return {
        "id": f"syn_{safe_slug(product_name)}_{safe_slug(str(bundle['channel']))}_{str(code['code']).lower()}",
        "title": f"{product_name} hard-case compliant ad",
        "text": text,
        "structured_ad": {
            "headline": hard_case_ad["headline"],
            "subcopy": hard_case_ad["subcopy"],
            "body": hard_case_ad["body"],
            "footnote": hard_case_ad["footnote"],
            "mutation_note": hard_case_ad.get("mutation_note", ""),
        },
        "facts": {
            **facts_payload(bundle, mutation_code=str(code["code"]), clean_ad=clean_ad),
            "hard_case": True,
        },
        "product_group": bundle["product_group"],
        "channel": bundle["channel"],
        "language": "ko",
        "source_type": "synthetic_product_fact_hard_case",
        "labels": {
            "violation": False,
            "violation_types": [],
            "articles": [],
            "sales_principles": list(code.get("sales_principles") or []),
            "required_disclosures": list(code.get("required_disclosures") or []),
            "risk_level": "low",
            "expected_routing": "pass_candidate",
            "review_basis": ["ProductFact hard-case taxonomy v0.1", "금융광고규제 가이드라인", "은행 광고심의 기준"],
        },
    }


def generate_mutated_ad(
    bundle: dict[str, Any],
    clean_ad: dict[str, Any],
    code: dict[str, Any],
    *,
    llm: LLMGateway | None,
) -> dict[str, str]:
    if llm is None:
        mutated_ad = template_mutated_ad(bundle, clean_ad, code)
        validate_ad_lengths(mutated_ad, str(bundle.get("channel") or "web_page"), context=str(code.get("code") or "template_mutation"))
        return mutated_ad

    is_hard_case = code.get("category") == "hard_case_compliant"
    channel = str(bundle.get("channel") or "web_page")
    channel_profile = channel_profile_for(channel)
    code = code_with_resolved_slots(code, bundle)
    result = llm.structured(
        name="graphcompliance_taxonomy_controlled_ad_mutation",
        schema=MUTATED_AD_SCHEMA,
        system=(
            "You create Korean financial-ad evaluation records from a clean compliant ad and ProductFact evidence. "
            "The taxonomy code is the control variable. Do not invent product facts. For violation mutations, "
            "inject exactly the requested risk into the ad while keeping the product recognizable. For hard-case "
            "compliant mutations, keep the risky-looking claim but include same-level disclosures that make the "
            "ad compliant. Return injected_span as the exact substring that carries the injected violation; for "
            "hard-case compliant records, return an empty injected_span. Respect the channel profile length limits. "
            "Do not wrap the injected phrase in square brackets or markup."
        ),
        user=json.dumps(
            {
                "product_name": bundle["product_name"],
                "product_group": bundle["product_group"],
                "channel": bundle["channel"],
                "channel_profile": channel_profile,
                "product_facts": compact_product_facts_for_generation(bundle["product_facts"]),
                "clean_ad": clean_ad,
                "taxonomy_code": code,
                "is_hard_case_compliant": is_hard_case,
                "slot_hints": fact_slots(bundle),
            },
            ensure_ascii=False,
        ),
    )
    mutated_ad = {
        "headline": str(result.get("headline") or ""),
        "subcopy": str(result.get("subcopy") or ""),
        "body": str(result.get("body") or ""),
        "footnote": str(result.get("footnote") or ""),
        "injected_span": str(result.get("injected_span") or ""),
        "mutation_note": str(result.get("mutation_note") or ""),
    }
    return ensure_ad_lengths(
        mutated_ad,
        channel,
        context=str(code.get("code") or "llm_mutation"),
        llm=llm,
        schema=MUTATED_AD_SCHEMA,
        repair_payload={
            "product_name": bundle["product_name"],
            "product_group": bundle["product_group"],
            "channel": bundle["channel"],
            "channel_profile": channel_profile,
            "product_facts": compact_product_facts_for_generation(bundle["product_facts"]),
            "clean_ad": clean_ad,
            "taxonomy_code": code,
            "is_hard_case_compliant": is_hard_case,
            "slot_hints": fact_slots(bundle),
        },
    )


def template_mutated_ad(bundle: dict[str, Any], clean_ad: dict[str, Any], code: dict[str, Any]) -> dict[str, str]:
    product_name = str(bundle["product_name"])
    phrase = mutation_phrase(code, bundle)
    if code.get("category") == "hard_case_compliant":
        return {
            "headline": f"{product_name} 안내",
            "subcopy": phrase,
            "body": "",
            "footnote": str(clean_ad.get("footnote") or "계약 전 상품설명서와 약관을 확인해 주세요."),
            "injected_span": "",
            "mutation_note": "Template hard-case generated for unit tests.",
        }
    return {
        "headline": f"{product_name} 안내",
        "subcopy": phrase,
        "body": "자세한 내용은 상품설명서를 확인해 주세요.",
        "footnote": "",
        "injected_span": mutation_span(code, bundle, phrase),
        "mutation_note": "Template violation generated for unit tests.",
    }


def facts_payload(bundle: dict[str, Any], *, mutation_code: str, clean_ad: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_name": bundle["product_name"],
        "product_group": bundle["product_group"],
        "source_product_documents": [
            {
                "document_id": document.get("document_id", ""),
                "label": document.get("label", ""),
                "file_name": document.get("file_name", ""),
                "relative_path": document.get("relative_path", ""),
            }
            for document in bundle.get("selected_documents", [])
        ],
        "product_facts": bundle.get("product_facts", []),
        "clean_reference_text": ad_to_text(clean_ad),
        "mutation_code": mutation_code,
    }


def mutation_phrase(code: dict[str, Any], bundle: dict[str, Any]) -> str:
    return str(code["mutation_phrase"]).format(**fact_slots(bundle))


def mutation_span(code: dict[str, Any], bundle: dict[str, Any], phrase: str) -> str:
    hint = str(code.get("gold_span_hint") or "")
    return hint.format(**fact_slots(bundle)) if hint else phrase


def code_with_resolved_slots(code: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    """LLM 페이로드용으로 mutation_phrase/gold_span_hint의 {rate}·{term} 등 슬롯을 실제
    ProductFact 값으로 치환한 코드 복사본. 원시 플레이스홀더가 LLM에 새어 injected_span으로
    그대로 반사되는 문제를 방지한다.
    """
    slots = fact_slots(bundle)
    resolved = dict(code)
    for key in ("mutation_phrase", "gold_span_hint"):
        value = str(code.get(key) or "")
        try:
            resolved[key] = value.format(**slots)
        except (KeyError, IndexError, ValueError):
            resolved[key] = value
    return resolved


def fact_slots(bundle: dict[str, Any]) -> dict[str, str]:
    facts = bundle.get("product_facts", [])
    return {
        "rate": display_rate(best_deposit_rate_value(facts) or first_rate_value(facts)) or "상품문서상 금리",
        "term": first_fact_value(facts, ["가입기간", "계약기간", "대출기간", "만기", "term"]) or "상품문서상 기간",
        "eligibility": first_fact_value(facts, ["가입대상", "대상", "eligibility"]) or "상품문서상 대상",
        "condition": first_preferential_condition(facts) or first_fact_condition(facts) or "상품문서상 조건",
        "protection": first_fact_value(facts, ["예금자보호", "보호한도", "depositor_protection"]) or "상품설명서와 약관 확인",
    }


def best_deposit_rate_value(facts: list[dict[str, Any]]) -> str:
    base_rates: list[float] = []
    preferential_rates: list[float] = []
    for fact in facts:
        fact_type = str(fact.get("fact_type") or "").lower()
        value = str(fact.get("value") or "")
        if not any(token in fact_type for token in ("interest_rate", "금리", "이자율")):
            continue
        numbers = parse_percent_numbers(value)
        if not numbers:
            continue
        if any(token in fact_type for token in ("basic", "기본")):
            base_rates.extend(numbers)
        elif any(token in fact_type for token in ("preferential", "우대")):
            preferential_rates.extend(numbers)
    if not base_rates:
        return ""
    best_rate = max(base_rates) + (max(preferential_rates) if preferential_rates else 0.0)
    formatted = f"{best_rate:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def first_rate_value(facts: list[dict[str, Any]]) -> str:
    priority_terms = [
        ["최고이자율", "최고금리"],
        ["기본이자율", "기본금리"],
        ["우대이자율", "우대금리"],
        ["이자율", "금리"],
    ]
    for names in priority_terms:
        candidates = [
            fact
            for fact in facts
            if any(name.lower() in str(fact.get("fact_type") or "").lower() for name in names)
            and "%" in str(fact.get("value") or "")
        ]
        if candidates:
            return str(candidates[-1].get("value") or "").strip()
    return ""


def first_fact_value(facts: list[dict[str, Any]], names: list[str]) -> str:
    for fact in facts:
        fact_type = str(fact.get("fact_type") or "").lower()
        if any(name.lower() in fact_type for name in names):
            return str(fact.get("value") or "").strip()
    return ""


def first_fact_condition(facts: list[dict[str, Any]]) -> str:
    for fact in facts:
        condition = str(fact.get("condition") or "").strip()
        if condition:
            return condition
    return ""


def first_preferential_condition(facts: list[dict[str, Any]]) -> str:
    for fact in facts:
        fact_type = str(fact.get("fact_type") or "")
        if "우대조건" not in fact_type:
            continue
        value = str(fact.get("value") or "").strip()
        condition = str(fact.get("condition") or "").strip()
        return condition or value
    return ""


def display_rate(value: str) -> str:
    value = value.strip()
    percentages = re.findall(r"\d+(?:\.\d+)?\s*%", value)
    if percentages:
        return percentages[-1].replace(" ", "")
    return value


def parse_percent_numbers(value: str) -> list[float]:
    return [float(match) for match in re.findall(r"(\d+(?:\.\d+)?)\s*%p?", value)]


def disclosure_labels(bundle: dict[str, Any]) -> list[str]:
    return [str(item.get("label") or item.get("name") or "") for item in bundle.get("disclosure_requirements", []) if item.get("label") or item.get("name")]


def ad_to_text(ad: dict[str, Any]) -> str:
    return " ".join(str(ad.get(key) or "").strip() for key in ("headline", "subcopy", "body", "footnote") if str(ad.get(key) or "").strip())


def safe_slug(value: str) -> str:
    keep = [char.lower() if char.isalnum() else "_" for char in value]
    slug = "_".join("".join(keep).split("_"))
    return slug[:80] or "product"


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
