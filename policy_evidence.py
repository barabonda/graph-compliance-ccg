"""Purpose-specific policy evidence chains for review-time explanation.

These chains are runtime artifacts. They intentionally avoid creating Neo4j
chain/hop nodes in v1 so the review graph does not accumulate noisy traversal
artifacts before human approval or audit export.
"""

from __future__ import annotations

from typing import Any

from schemas import CUPlanItem
from utils import stable_id, uses_korean_law_context


def build_policy_evidence_chains(
    *,
    review_run_id: str,
    cu_plan: list[CUPlanItem],
    disclosure_requirements: list[dict[str, Any]],
    product_context: dict[str, Any],
    workspace_id: str = "",
) -> dict[str, list[dict[str, Any]]]:
    legal_basis = [legal_basis_chain(review_run_id, item, workspace_id) for item in cu_plan]
    disclosures = [
        disclosure_chain(
            review_run_id,
            item,
            disclosure_requirements=matching_disclosures(item, disclosure_requirements),
            product_context=product_context,
        )
        for item in cu_plan
    ]
    exceptions = [exception_chain(review_run_id, item) for item in cu_plan]
    diagnostics = [
        diagnostic
        for chain in [*legal_basis, *disclosures, *exceptions]
        if (diagnostic := chain_diagnostic(chain))
    ]
    return {
        "legal_basis_chains": legal_basis,
        "disclosure_chains": disclosures,
        "exception_chains": exceptions,
        "chain_diagnostics": diagnostics,
    }


def legal_basis_chain(review_run_id: str, item: CUPlanItem, workspace_id: str = "") -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    if item.source_article:
        nodes.append(
            {
                "id": stable_id("legal_basis_node", item.cu_id, item.source_article),
                "label": item.source_article,
                "node_type": "ArticleClause",
                "role": "root_article",
            }
        )
    if item.principle:
        nodes.append(
            {
                "id": stable_id("legal_basis_node", item.cu_id, item.principle),
                "label": item.principle,
                "node_type": "SalesPrinciple",
                "role": "principle",
            }
        )
    delegation_edges = delegation_edges_for(item, workspace_id)
    nodes.extend(edge["target_node"] for edge in delegation_edges)
    status = "FOUND" if nodes else "INCOMPLETE"
    summary = (
        f"{item.risk_title or item.subject or item.cu_id} 판단은 "
        f"{item.source_article or item.principle or '명시 근거 미상'} 근거에 연결됩니다."
    )
    return {
        "chain_id": stable_id("legal_basis_chain", review_run_id, item.plan_item_id),
        "chain_type": "LegalBasisChain",
        "status": status,
        "anchor_id": item.anchor_id,
        "plan_item_id": item.plan_item_id,
        "cu_id": item.cu_id,
        "summary": summary,
        "basis_nodes": nodes,
        "delegation_edges": delegation_edges,
        "provenance_snippets": provenance_snippets(item),
    }


def delegation_edges_for(item: CUPlanItem, workspace_id: str = "") -> list[dict[str, Any]]:
    # Korean-law delegation (법률→시행령→감독규정→심의기준) only applies to Korean
    # workspaces. Non-KR workspaces (e.g. the Cambodia PoC) must not have Korean
    # statutes injected into their legal-basis chain / judgment rationale.
    if not uses_korean_law_context(workspace_id):
        return []
    text = " ".join([item.source_article, item.principle, item.subject, item.constraint, item.context, item.risk_title])
    if not any(token in text for token in ["광고", "금소법 제22조", "금융상품등에 관한 광고", "표시", "고지"]):
        return []
    edges = []
    source_id = stable_id("legal_basis_node", item.cu_id, item.source_article or item.cu_id)
    for label, role in [
        ("금융소비자보호법 시행령 광고 방법·절차/금지행위", "delegated_enforcement_decree"),
        ("금융소비자보호 감독규정 및 금융광고 심의기준", "delegated_supervisory_standard"),
    ]:
        target = {
            "id": stable_id("legal_basis_node", item.cu_id, label),
            "label": label,
            "node_type": "DelegatedStandard",
            "role": role,
        }
        edges.append(
            {
                "relationship_type": "DELEGATES_TO",
                "source_id": source_id,
                "target_id": target["id"],
                "target_node": target,
                "why": "금소법 광고규제는 시행령과 감독규정/심의기준으로 세부 방법·절차·표시기준이 위임됩니다.",
            }
        )
    return edges


def disclosure_chain(
    review_run_id: str,
    item: CUPlanItem,
    *,
    disclosure_requirements: list[dict[str, Any]],
    product_context: dict[str, Any],
) -> dict[str, Any]:
    status = "FOUND" if disclosure_requirements else "NOT_FOUND"
    product_group = str(product_context.get("product_group") or "auto")
    labels = [str(row.get("label") or row.get("id") or "") for row in disclosure_requirements]
    summary = (
        f"{product_group} 상품군 기준 보완 고지 후보: {', '.join(labels[:4])}"
        if labels
        else "이 CU에 직접 연결된 필수고지 후보가 없습니다."
    )
    return {
        "chain_id": stable_id("disclosure_chain", review_run_id, item.plan_item_id),
        "chain_type": "DisclosureChain",
        "status": status,
        "anchor_id": item.anchor_id,
        "plan_item_id": item.plan_item_id,
        "cu_id": item.cu_id,
        "summary": summary,
        "disclosure_nodes": [
            {
                "id": str(row.get("id") or ""),
                "label": str(row.get("label") or ""),
                "source": str(row.get("source") or ""),
                "why": str(row.get("why") or ""),
                "node_type": "DisclosureRequirement",
            }
            for row in disclosure_requirements
        ],
        "provenance_snippets": provenance_snippets(item),
    }


def exception_chain(review_run_id: str, item: CUPlanItem) -> dict[str, Any]:
    eligible = bool(item.legal_element_profile and item.legal_element_profile.exception_eligible)
    status = "INCOMPLETE" if eligible else "NOT_FOUND"
    summary = (
        "이 CU는 예외/완화 가능성이 있으나 현재 runtime chain에는 명시적 예외 증거가 연결되지 않았습니다."
        if eligible
        else "이 CU는 v1 runtime 기준 직접 예외 chain 대상으로 분류되지 않았습니다."
    )
    return {
        "chain_id": stable_id("exception_chain", review_run_id, item.plan_item_id),
        "chain_type": "ExceptionChain",
        "status": status,
        "anchor_id": item.anchor_id,
        "plan_item_id": item.plan_item_id,
        "cu_id": item.cu_id,
        "summary": summary,
        "exception_nodes": [],
        "provenance_snippets": [],
    }


def matching_disclosures(item: CUPlanItem, disclosure_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = " ".join(
        str(value or "")
        for value in [
            item.risk_title,
            item.subject,
            item.condition,
            item.constraint,
            item.context,
            item.principle,
            " ".join(item.matched_required_features),
        ]
    )
    token_groups = {
        "rate": ["금리", "이자율", "수익", "수익률", "benefit_claim_expression", "product_fact_assertion"],
        "condition": ["조건", "우대", "기간", "누구나", "조건 없이", "unconditional_expression", "universal_scope_expression"],
        "protection": ["예금자보호", "부보", "보호"],
        "risk": ["원금손실", "위험", "과거", "성과", "past_performance_claim", "risk_downplay_expression"],
        "fee": ["수수료", "부대비용"],
        "review": ["심의필", "사전승인", "준법감시인"],
    }
    matched: list[dict[str, Any]] = []
    for row in disclosure_requirements:
        haystack = " ".join([str(row.get("id", "")), str(row.get("label", "")), str(row.get("why", ""))])
        if any(any(token in text for token in tokens) and any(token in haystack for token in tokens) for tokens in token_groups.values()):
            matched.append(row)
    if matched:
        return matched[:5]
    if any(token in text for token in ["광고", "고지", "표시", "설명", "보장", "확정", "조건"]):
        return disclosure_requirements[:3]
    return []


def provenance_snippets(item: CUPlanItem) -> list[dict[str, str]]:
    return [
        {
            "id": evidence_id,
            "text": item.evidence_texts[index] if index < len(item.evidence_texts) else "",
        }
        for index, evidence_id in enumerate(item.legal_evidence_ids[:3])
    ]


def chain_diagnostic(chain: dict[str, Any]) -> dict[str, Any] | None:
    if chain.get("status") == "FOUND":
        return None
    return {
        "chain_id": chain.get("chain_id", ""),
        "chain_type": chain.get("chain_type", ""),
        "anchor_id": chain.get("anchor_id", ""),
        "plan_item_id": chain.get("plan_item_id", ""),
        "cu_id": chain.get("cu_id", ""),
        "status": chain.get("status", ""),
        "summary": chain.get("summary", ""),
    }
