"""Applicability gates for disclosure requirements and CU candidates.

The gate is evidence routing, not final compliance judgment. It decides which
requirements are in scope for the current product/channel/context and records
why unrelated criteria were skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from disclosure_catalog import PRODUCT_GROUP_TO_GRAPH
from schemas import ContextAnchor, PolicyCandidate, ReviewInput


@dataclass(frozen=True)
class GateDecision:
    enabled: bool
    reason: str


def normalized_product_group(product_group: str) -> str:
    value = (product_group or "auto").strip().lower()
    if value == "auto":
        return value
    return PRODUCT_GROUP_TO_GRAPH.get(value, value)


def normalized_channel(channel: str) -> str:
    value = (channel or "").strip().lower()
    aliases = {
        "bank_event_page_text": "web_page",
        "event_page": "web_page",
        "web": "web_page",
        "homepage": "web_page",
        "instagram": "sns",
        "facebook": "sns",
        "blog": "sns",
        "youtube_short": "youtube",
        "sms_text": "sms",
    }
    return aliases.get(value, value or "web_page")


def context_features_from_text(text: str) -> set[str]:
    features: set[str] = set()
    lowered = (text or "").lower()
    if any(token in text for token in ["금리", "이자", "%", "연 "]):
        features.add("rate_claim")
    if any(token in text for token in ["보장", "확정", "확실", "무조건"]):
        features.add("guarantee_expression")
    if any(token in text for token in ["조건 없이", "누구나", "제한 없이"]):
        features.add("unconditional_or_universal_expression")
    if any(token in text for token in ["보다", "타 은행", "타사", "업계", "최고", "1위", "유일"]):
        features.add("comparison_claim")
    if any(token in text for token in ["가입 필수", "대출 조건", "조건으로 적금", "강요", "끼워"]):
        features.add("coercion_or_tie_in_context")
    if any(token in lowered for token in ["els", "펀드", "투자", "수익률"]):
        features.add("investment_context")
    return features


def gate_disclosure_catalog(
    *,
    review_input: ReviewInput,
    catalog: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    product_group = normalized_product_group(review_input.product_group)
    channel = normalized_channel(review_input.channel)
    features = sorted(context_features_from_text(review_input.content_text))
    enabled: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in catalog:
        row = dict(item)
        decision = disclosure_gate_decision(row, product_group=product_group, channel=channel)
        row["gate_status"] = "ON" if decision.enabled else "OFF"
        row["gate_reason"] = decision.reason
        if decision.enabled:
            enabled.append(row)
        else:
            skipped.append(row)
    summary = {
        "product_group": product_group,
        "channel": channel,
        "context_features": features,
        "enabled_requirements": [
            {"check_id": row.get("check_id"), "label": row.get("label"), "gate_reason": row.get("gate_reason")}
            for row in enabled
        ],
        "skipped_requirements": [
            {"check_id": row.get("check_id"), "label": row.get("label"), "gate_reason": row.get("gate_reason")}
            for row in skipped
        ],
        "gate_diagnostics": [
            {
                "diagnostic_code": "DISCLOSURE_REQUIREMENT_SKIPPED",
                "check_id": row.get("check_id"),
                "reason": row.get("gate_reason"),
            }
            for row in skipped
        ],
    }
    return enabled, skipped, summary


def disclosure_gate_decision(item: dict[str, Any], *, product_group: str, channel: str) -> GateDecision:
    groups = {PRODUCT_GROUP_TO_GRAPH.get(str(group), str(group)) for group in item.get("product_groups", []) or []}
    if groups and product_group != "auto" and product_group not in groups:
        return GateDecision(False, f"상품군 {product_group}에는 적용되지 않는 고지입니다.")
    channels = {normalized_channel(str(channel_item)) for channel_item in item.get("channels", []) or []}
    if channels and channel not in channels:
        return GateDecision(False, f"채널 {channel}에서는 적용하지 않는 고지입니다.")
    return GateDecision(True, "상품군/채널 적용범위에 해당합니다.")


def summarize_cu_gate(
    *,
    review_input: ReviewInput,
    anchors: list[ContextAnchor],
    candidates_by_anchor: dict[str, list[PolicyCandidate]],
    retrieval_diagnostics: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    product_group = normalized_product_group(review_input.product_group)
    channel = normalized_channel(review_input.channel)
    enabled_cus: list[dict[str, Any]] = []
    for anchor in anchors:
        for candidate in candidates_by_anchor.get(anchor.anchor_id, []):
            enabled_cus.append(
                    {
                        "anchor_id": anchor.anchor_id,
                        "cu_id": candidate.cu_id,
                        "title": candidate.risk_title or candidate.subject or candidate.cu_id,
                        "action_type": (
                        candidate.legal_element_profile.action_type
                        if candidate.legal_element_profile
                        else ""
                    ),
                    "gate_status": candidate.gate_status or "ON",
                }
            )
    skipped_cus = []
    for anchor_id, diagnostic in (retrieval_diagnostics or {}).items():
        failure_code = diagnostic.get("failure_code")
        if failure_code and failure_code != "MATCHED":
            skipped_cus.append(
                {
                    "anchor_id": anchor_id,
                    "failure_code": failure_code,
                    "reason": diagnostic.get("message", ""),
                }
            )
    return {
        "product_group": product_group,
        "channel": channel,
        "enabled_cus": enabled_cus,
        "skipped_cus": skipped_cus,
        "gate_diagnostics": [
            {"diagnostic_code": "CU_GATE_DIAGNOSTIC", **row} for row in skipped_cus
        ],
    }
