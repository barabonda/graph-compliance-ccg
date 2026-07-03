"""Map CCG judgments to the team-share pre-review output schema."""

from __future__ import annotations

from disclosure_catalog import PROMINENCE_BALANCE_BASIS, disclosure_profile, resolve_representative_basis
from legal_hierarchy import parent_articles_for
from schemas import ExceptionReview, LLMJudgment, ReviewGraph, ReviewInput, ReviewOutput
from utils import to_jsonable


ACTIONABLE_ANCHOR_TYPES = {"claim_anchor", "risk_anchor"}
SCOPE_ANCHOR_TYPES = {"product_anchor", "target_consumer_anchor"}


def build_output(
    review_input: ReviewInput,
    graph: ReviewGraph,
    *,
    revision_suggestions: list[dict[str, object]] | None = None,
) -> ReviewOutput:
    effective = unique_judgments(effective_judgments(graph.judgments, graph.exception_reviews))
    anchor_by_id = {anchor.anchor_id: anchor for anchor in graph.anchors}
    actionable_effective = [
        judgment for judgment in effective if anchor_is_actionable_for_issues(graph, judgment.anchor_id)
    ]
    unmatched_actionable = [
        anchor
        for anchor in unmatched_anchors(graph, anchor_types=ACTIONABLE_ANCHOR_TYPES)
        if anchor_is_actionable_for_issues(graph, anchor.anchor_id)
    ]
    non_compliant = [j for j in actionable_effective if j.verdict == "NON_COMPLIANT"]
    insufficient = [j for j in actionable_effective if j.verdict == "INSUFFICIENT"]
    track_b = graph.overall_impression_judgment or {}
    misleading_score = float(track_b.get("misleading_risk_score") or 0.0)
    misleading_verdict = str(track_b.get("verdict") or "LOW")
    if any(j.score >= 0.82 for j in non_compliant):
        final = "reject"
    elif non_compliant:
        final = "revise"
    elif misleading_verdict == "HIGH" or misleading_score >= 0.75:
        final = "revise"
    elif insufficient:
        final = "needs_review"
    elif misleading_verdict == "MEDIUM" or misleading_score >= 0.45:
        final = "needs_review"
    elif unmatched_actionable:
        final = "needs_review"
    else:
        final = "pass_candidate"

    detected_issues = unique_detected_issues(
        [
            {
                "risk_code": judgment.cu_id,
                "principle": plan_item_for_judgment(graph, judgment).principle if plan_item_for_judgment(graph, judgment) else "",
                "source_article": plan_item_for_judgment(graph, judgment).source_article if plan_item_for_judgment(graph, judgment) else "",
                "risk_title": plan_item_for_judgment(graph, judgment).risk_title if plan_item_for_judgment(graph, judgment) else "",
                "subject": plan_item_for_judgment(graph, judgment).subject if plan_item_for_judgment(graph, judgment) else "",
                "constraint": plan_item_for_judgment(graph, judgment).constraint if plan_item_for_judgment(graph, judgment) else "",
                "severity": severity_from_score(judgment.score),
                "problem_span": judgment.evidence_span,
                "rationale": judgment.why,
                "required_action": action_for_verdict(judgment.verdict),
            }
            for judgment in actionable_effective
            if judgment.verdict in {"NON_COMPLIANT", "INSUFFICIENT"}
        ]
    )
    if misleading_verdict in {"HIGH", "MEDIUM"} or misleading_score >= 0.45:
        detected_issues.append(
            {
                "risk_code": "TRACK_B_OVERALL_IMPRESSION",
                "severity": severity_from_score(misleading_score),
                "problem_span": track_b.get("representative_consumer_impression", ""),
                "rationale": track_b.get("why", "광고 전체 인상 기준 소비자 오인 가능성을 검토해야 합니다."),
                "required_action": "전체 문안에서 조건, 제한, 위험, 고지를 더 균형 있게 표시하세요.",
            }
        )
    if graph.cu_plan and final != "pass_candidate":
        for diagnostic in graph.prominence_diagnostics:
            code = str(diagnostic.get("diagnostic_code") or "")
            if code not in {"PROMINENCE_INSUFFICIENT", "DISCLOSURE_MISSING"}:
                continue
            # 대표 근거 선택: 항목 부재(missing)는 법령 근거가 있으면 법령 대표,
            # 위계 미달(prominence)은 구체 기준을 정한 심의기준 대표 + '법 위반 아님' 문구.
            if code == "PROMINENCE_INSUFFICIENT":
                basis = {
                    "representative_basis": PROMINENCE_BALANCE_BASIS["guideline"],
                    "authority_tier": "guideline",
                    "co_basis": PROMINENCE_BALANCE_BASIS["law"],
                    "tier_note": "법령 위반이 아닌 심의기준 미흡입니다.",
                }
            else:
                basis = resolve_representative_basis(
                    disclosure_profile(str(diagnostic.get("check_id") or "")),
                    situation="missing",
                )
                if not basis["representative_basis"]:
                    basis = {"representative_basis": "금소법 제22조", "authority_tier": "law", "co_basis": "", "tier_note": ""}
            rationale = str(diagnostic.get("message") or "")
            if basis.get("tier_note"):
                rationale = f"{basis['tier_note']} {rationale}".strip()
            detected_issues.append(
                {
                    "risk_code": code,
                    "principle": "광고규제",
                    "source_article": basis["representative_basis"],
                    "authority_tier": basis["authority_tier"],
                    "co_basis": basis.get("co_basis", ""),
                    "risk_title": "필수고지 현저성 또는 누락",
                    "subject": "고지 표시",
                    "constraint": "혜택과 불이익을 균형 있게 명확히 전달해야 합니다.",
                    "severity": 2 if basis["authority_tier"] == "guideline" else 3,
                    "problem_span": str(diagnostic.get("evidence") or ""),
                    "rationale": rationale,
                    "required_action": "조건, 기간, 한도, 세전/세후, 예금자보호 등 필요한 고지를 혜택 문구와 같은 맥락에서 충분히 보이게 표시하세요.",
                }
            )
    system_review_items = system_review_items_for(graph)
    routing = {
        "ad_scope": "product_ad",
        "preapproval_required_status": "required",
        "review_phrase_required_before_publication": True,
        "review_phrase_expected_in_input": False,
        "review_phrase_input_status": "absent_expected",
    }
    return ReviewOutput(
        dataset_item_id=review_input.dataset_item_id,
        final_verdict=final,
        routing=routing,
        detected_issues=detected_issues,
        post_approval_required_actions=["assign_review_number", "insert_review_phrase_before_publication"],
        rationale=summary_rationale(final, actionable_effective, detected_issues),
        review_run_id=graph.review_run_id,
        context_frame=graph.context_frame,
        sentence_units=to_jsonable(graph.sentence_units),
        inter_sentence_relations=to_jsonable(graph.inter_sentence_relations),
        context_influences=to_jsonable(graph.context_influences),
        claims=to_jsonable(graph.claims),
        context_triples=to_jsonable(graph.context_triples),
        context_anchors=to_jsonable(graph.anchors),
        anchor_feature_sets=to_jsonable(graph.anchor_feature_sets),
        cu_plan=cu_plan_with_parent_articles(graph, review_input.workspace_id),
        judgments=to_jsonable(graph.judgments),
        effective_judgments=to_jsonable(effective),
        exception_reviews=to_jsonable(graph.exception_reviews),
        anchor_display=anchor_display(graph, effective),
        system_review_items=system_review_items,
        revision_suggestions=revision_suggestions or [],
        product_context=graph.product_context,
        product_fact_context=graph.product_fact_context,
        applicability_gate=graph.applicability_gate,
        prominence_analysis=graph.prominence_analysis,
        disclosure_links=graph.disclosure_links,
        prominence_diagnostics=graph.prominence_diagnostics,
        disclosure_requirements=graph.disclosure_requirements,
        policy_evidence_chains=graph.policy_evidence_chains,
        overall_impression_judgment=graph.overall_impression_judgment,
        track_c_summary=graph.track_c_summary,
        article_aggregation=article_aggregation(graph, effective),
        principle_aggregation=principle_aggregation(graph, effective),
        reference_paths_summary=reference_paths_summary(graph),
        graph_paths=graph.graph_paths,
        highlight_spans=highlight_spans(graph, effective),
    )


def cu_plan_with_parent_articles(graph: ReviewGraph, workspace_id: str) -> list[dict[str, object]]:
    """하위 규정을 인용한 CUPlan 항목에 모법 조문(금소법 제21·22조 등)을 병기한다."""
    rows = to_jsonable(graph.cu_plan)
    for row in rows:
        row["parent_articles"] = parent_articles_for(
            str(row.get("source_article") or ""), workspace_id=workspace_id
        )
    return rows


def effective_judgments(judgments: list[LLMJudgment], reviews: list[ExceptionReview]) -> list[LLMJudgment]:
    by_judgment = {review.judgment_id: review for review in reviews if review.applies}
    effective: list[LLMJudgment] = []
    for judgment in judgments:
        review = by_judgment.get(judgment.judgment_id)
        if not review:
            effective.append(judgment)
            continue
        if review.effect == "OVERRIDE_TO_COMPLIANT":
            effective.append(
                LLMJudgment(
                    **{
                        **judgment.__dict__,
                        "verdict": "COMPLIANT",
                        "why": f"{judgment.why} / 예외 override: {review.why}",
                    }
                )
            )
        elif review.effect == "DOWNGRADE_TO_REVIEW":
            effective.append(
                LLMJudgment(
                    **{
                        **judgment.__dict__,
                        "verdict": "INSUFFICIENT",
                        "why": f"{judgment.why} / 예외 검토 필요: {review.why}",
                    }
                )
            )
        else:
            effective.append(judgment)
    return effective


def unique_judgments(judgments: list[LLMJudgment]) -> list[LLMJudgment]:
    """Keep one effective judgment per CUPlan item.

    LLM structured outputs can occasionally repeat the same plan item. The
    workflow still guarantees coverage for every CUPlan item, but routing and
    UI counts should not be inflated by duplicated rows.
    """
    by_plan: dict[str, LLMJudgment] = {}
    for judgment in judgments:
        existing = by_plan.get(judgment.plan_item_id)
        if not existing or (verdict_rank(judgment.verdict), judgment.score) > (verdict_rank(existing.verdict), existing.score):
            by_plan[judgment.plan_item_id] = judgment
    return list(by_plan.values())


def unique_detected_issues(issues: list[dict[str, object]]) -> list[dict[str, object]]:
    by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    for issue in issues:
        key = (
            str(issue.get("risk_code") or ""),
            str(issue.get("problem_span") or ""),
            str(issue.get("source_article") or ""),
        )
        existing = by_key.get(key)
        if not existing or int(issue.get("severity") or 0) > int(existing.get("severity") or 0):
            by_key[key] = issue
    return list(by_key.values())


def plan_item_for_judgment(graph: ReviewGraph, judgment: LLMJudgment):
    for item in graph.cu_plan:
        if item.plan_item_id == judgment.plan_item_id:
            return item
    return None


def severity_from_score(score: float) -> int:
    if score >= 0.85:
        return 4
    if score >= 0.7:
        return 3
    if score >= 0.45:
        return 2
    return 1


def action_for_verdict(verdict: str) -> str:
    if verdict == "NON_COMPLIANT":
        return "위험 표현을 수정하고 누락된 근거/고지를 보완하세요."
    if verdict == "INSUFFICIENT":
        return "추가 근거, 상품조건, 고지 문구를 확인하세요."
    return "추가 조치 없음"


# 사용자(준법감시자)에게 보이는 판정 어휘. 내부 enum(needs_review 등)을 그대로
# 노출하지 않는다 — 화면·의견서의 언어는 심사 실무 용어여야 한다.
FINAL_VERDICT_KO = {
    "pass_candidate": "통과 후보",
    "needs_review": "검토 필요",
    "revise": "수정 권고",
    "reject": "반려 권고",
}


def summary_rationale(
    final: str,
    judgments: list[LLMJudgment],
    detected_issues: list[dict[str, object]] | None = None,
) -> str:
    final_ko = FINAL_VERDICT_KO.get(final, final)
    if not judgments:
        return "연결된 심의 기준이 없어 자동 통과하지 않고 심사자 추가 검토로 회부합니다."
    risky = [judgment for judgment in judgments if judgment.verdict in {"NON_COMPLIANT", "INSUFFICIENT"}]
    guideline_issues = [
        issue for issue in (detected_issues or []) if str(issue.get("authority_tier") or "") == "guideline"
    ]
    if not risky and not guideline_issues:
        return "연결된 심의 기준과 근거 자료를 기준으로 중대한 위반 신호가 확인되지 않았습니다."
    # 판정 어휘 원칙: 법령 근거 검토와 심의기준 미흡(자율규제 보완 권고)은 다른 말이다.
    parts: list[str] = []
    if risky:
        parts.append(f"법령 조문 근거 검토 대상 {len(risky)}건")
    if guideline_issues:
        parts.append(f"심의기준 미흡 {len(guideline_issues)}건")
    summary = f"{' · '.join(parts)}이 확인되어 '{final_ko}' 의견으로 회부합니다."
    if guideline_issues and not any(j.verdict == "NON_COMPLIANT" for j in risky):
        summary += " 심의기준 미흡은 법령 위반이 아닌 자율규제 보완 권고입니다."
    return summary


def article_aggregation(graph: ReviewGraph, effective: list[LLMJudgment]) -> list[dict[str, object]]:
    return aggregate_by_policy_axis(graph, effective, axis="article")


def principle_aggregation(graph: ReviewGraph, effective: list[LLMJudgment]) -> list[dict[str, object]]:
    return aggregate_by_policy_axis(graph, effective, axis="principle")


def aggregate_by_policy_axis(graph: ReviewGraph, effective: list[LLMJudgment], *, axis: str) -> list[dict[str, object]]:
    anchor_by_id = {anchor.anchor_id: anchor for anchor in graph.anchors}
    groups: dict[str, dict[str, object]] = {}
    for judgment in unique_judgments(effective):
        anchor = anchor_by_id.get(judgment.anchor_id)
        if not anchor or not anchor_is_actionable_for_issues(graph, judgment.anchor_id):
            continue
        plan_item = plan_item_for_judgment(graph, judgment)
        if not plan_item:
            continue
        key = plan_item.source_article if axis == "article" else plan_item.principle
        if not key:
            key = "근거 미상" if axis == "article" else "원칙 미상"
        row = groups.setdefault(
            key,
            {
                "key": key,
                "axis": axis,
                "article": plan_item.source_article,
                "principles": set(),
                "verdicts": [],
                "max_score": 0.0,
                "cu_ids": set(),
                "cu_titles": set(),
                "anchor_spans": set(),
                "issue_count": 0,
            },
        )
        row["principles"].add(plan_item.principle)
        row["verdicts"].append(judgment.verdict)
        row["max_score"] = max(float(row["max_score"]), float(judgment.score or 0.0))
        row["cu_ids"].add(judgment.cu_id)
        row["cu_titles"].add(plan_item.risk_title or plan_item.subject or judgment.cu_id)
        row["anchor_spans"].add(anchor.span.text)
        if judgment.verdict in {"NON_COMPLIANT", "INSUFFICIENT"}:
            row["issue_count"] = int(row["issue_count"]) + 1

    output: list[dict[str, object]] = []
    for row in groups.values():
        verdicts = [LLMJudgment("", "", "", "", verdict, 0.0, "", "", []) for verdict in row["verdicts"]]
        output.append(
            {
                "key": row["key"],
                "axis": row["axis"],
                "article": row["article"],
                "principles": sorted(row["principles"]),
                "effective_verdict": aggregate_verdict(verdicts),
                "max_score": row["max_score"],
                "cu_count": len(row["cu_ids"]),
                "issue_count": row["issue_count"],
                "cu_titles": sorted(row["cu_titles"])[:8],
                "anchor_spans": sorted(row["anchor_spans"])[:8],
            }
        )
    return sorted(output, key=lambda item: (verdict_rank(str(item["effective_verdict"])), float(item["max_score"])), reverse=True)


def reference_paths_summary(graph: ReviewGraph) -> list[dict[str, object]]:
    anchor_by_id = {anchor.anchor_id: anchor for anchor in graph.anchors}
    rows: list[dict[str, object]] = []
    for item in graph.cu_plan:
        anchor = anchor_by_id.get(item.anchor_id)
        if not anchor or anchor.anchor_type not in ACTIONABLE_ANCHOR_TYPES:
            continue
        path_labels = []
        for path in item.reference_paths:
            label = path.get("path") or path.get("relationship") or path.get("type") or ""
            if label:
                path_labels.append(str(label))
        evidence_labels = [
            {
                "id": evidence_id,
                "text": item.evidence_texts[index] if index < len(item.evidence_texts) else "",
            }
            for index, evidence_id in enumerate(item.legal_evidence_ids[:4])
        ]
        rows.append(
            {
                "anchor_id": item.anchor_id,
                "anchor_text": anchor.span.text,
                "cu_id": item.cu_id,
                "risk_title": item.risk_title or item.subject,
                "principle": item.principle,
                "source_article": item.source_article,
                "path_labels": path_labels[:6],
                "legal_evidence": evidence_labels,
                "has_exception_path": any("EXCEPTION" in label.upper() for label in path_labels),
                "has_disclosure_evidence": any("고지" in text or "표시" in text for text in item.evidence_texts),
            }
        )
    return rows[:40]


def anchor_display(graph: ReviewGraph, effective: list[LLMJudgment]) -> list[dict[str, object]]:
    raw_by_anchor = judgments_by_anchor(graph.judgments)
    effective_by_anchor = judgments_by_anchor(unique_judgments(effective))
    plan_counts = plan_count_by_anchor(graph)
    system_items = {item["anchor_id"]: item for item in system_review_items_for(graph)}
    diagnostics = graph.retrieval_diagnostics
    rows = []
    for anchor in graph.anchors:
        role = anchor_display_role(graph, anchor.anchor_id)
        is_actionable = role == "actionable"
        raw = raw_by_anchor.get(anchor.anchor_id, [])
        effective_items = effective_by_anchor.get(anchor.anchor_id, [])
        if role == "mitigation":
            display_verdict = "MITIGATION"
        elif not is_actionable:
            display_verdict = "SCOPE"
        elif not plan_counts.get(anchor.anchor_id, 0):
            display_verdict = "RETRIEVAL_FAILURE"
        else:
            display_verdict = aggregate_verdict(effective_items)
        rows.append(
            {
                "anchor_id": anchor.anchor_id,
                "anchor_type": anchor.anchor_type,
                "display_role": role,
                "is_actionable": is_actionable,
                "display_verdict": display_verdict,
                "raw_verdict": aggregate_verdict(raw),
                "effective_verdict": aggregate_verdict(effective_items),
                "score": max([item.score for item in effective_items] or [0.0]),
                "cu_count": plan_counts.get(anchor.anchor_id, 0),
                "system_review_required": anchor.anchor_id in system_items,
                "system_review_reason": system_items.get(anchor.anchor_id, {}).get("rationale", ""),
                "retrieval_failure_code": diagnostics.get(anchor.anchor_id, {}).get("failure_code", ""),
                "retrieval_diagnostic": diagnostics.get(anchor.anchor_id, {}),
            }
        )
    return rows


def highlight_spans(graph: ReviewGraph, effective: list[LLMJudgment]) -> list[dict[str, object]]:
    by_anchor = {anchor.anchor_id: anchor for anchor in graph.anchors}
    effective_by_anchor = judgments_by_anchor(unique_judgments(effective))
    spans = []
    for anchor in graph.anchors:
        judgments = effective_by_anchor.get(anchor.anchor_id, [])
        verdict = aggregate_verdict(judgments)
        role = anchor_display_role(graph, anchor.anchor_id)
        if role == "mitigation":
            verdict = "MITIGATION"
        elif role != "actionable":
            verdict = "SCOPE"
        if not judgments and role == "actionable":
            verdict = "RETRIEVAL_FAILURE"
        spans.append(
            {
                "anchor_id": anchor.anchor_id,
                "judgment_id": judgments[0].judgment_id if judgments else "",
                "cu_id": judgments[0].cu_id if judgments else "",
                "verdict": verdict,
                "start": anchor.span.start,
                "end": anchor.span.end,
                "text": anchor.span.text,
            }
        )
    return spans


def unmatched_anchors(graph: ReviewGraph, *, anchor_types: set[str] | None = None):
    planned_anchor_ids = {item.anchor_id for item in graph.cu_plan}
    return [
        anchor
        for anchor in graph.anchors
        if anchor.anchor_id not in planned_anchor_ids and (anchor_types is None or anchor.anchor_type in anchor_types)
    ]


def system_review_items_for(graph: ReviewGraph) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for anchor in unmatched_anchors(graph):
        if not anchor_is_actionable_for_issues(graph, anchor.anchor_id):
            continue
        diagnostic = graph.retrieval_diagnostics.get(anchor.anchor_id, {})
        code = str(diagnostic.get("failure_code") or "CU_PLAN_EMPTY")
        rows.append(
            {
                "anchor_id": anchor.anchor_id,
                "anchor_type": anchor.anchor_type,
                "risk_code": code,
                "severity": 3 if anchor.anchor_type in ACTIONABLE_ANCHOR_TYPES else 1,
                "problem_span": anchor.span.text,
                "rationale": retrieval_failure_rationale(code),
                "required_action": retrieval_failure_action(code),
                "diagnostic": diagnostic,
            }
        )
    return rows


def retrieval_failure_rationale(code: str) -> str:
    # 사용자 노출 문구 — 심사 실무 언어로. (내부 스키마·컴포넌트명 노출 금지)
    return {
        "NO_HYPERNYM_MATCH": "이 표현을 심의 정책 용어로 분류하지 못해 자동 판단이 완료되지 않았습니다.",
        "NO_ACTIVE_CU_AFTER_GATE": "관련 심의 기준 후보는 있었으나 이 상품군·채널에 적용되는 기준이 남지 않았습니다.",
        "RERANK_DROPPED_ALL": "관련 심의 기준 후보가 판단 대상으로 선정되지 않았습니다.",
        "MISSING_POLICY_COVERAGE": "이 표현과 연결할 수 있는 심의 기준이 부족합니다.",
        "NO_LEGAL_ELEMENT_MATCH": "이 표현이 관련 심의 기준의 행위요건(금소법상 구성요건)에 해당하는지 자동으로 확인되지 않았습니다.",
        "CU_PLAN_EMPTY": "이 표현에 연결된 심의 기준이 없어 자동 통과할 수 없습니다.",
    }.get(code, "정책 매칭 상태를 심사자가 확인해야 합니다.")


def retrieval_failure_action(code: str) -> str:
    # 심사자가 취할 행동 중심으로. 시스템 보강이 필요한 경우는 그렇게 말한다.
    return {
        "NO_HYPERNYM_MATCH": "해당 표현은 심사자가 직접 판단해 주세요. (시스템: 정책 용어 사전 보강 필요)",
        "NO_ACTIVE_CU_AFTER_GATE": "이 상품군·채널에 실제로 적용될 기준인지 심사자가 확인해 주세요.",
        "RERANK_DROPPED_ALL": "해당 표현의 위반 여부를 심사자가 직접 확인해 주세요.",
        "MISSING_POLICY_COVERAGE": "해당 표현은 심사자가 직접 판단해 주세요. (시스템: 심의 기준 연결 보강 필요)",
        "NO_LEGAL_ELEMENT_MATCH": "행위요건 해당 여부를 심사자가 직접 확인해 주세요.",
        "CU_PLAN_EMPTY": "해당 표현은 심사자가 직접 판단해 주세요. (시스템: 심의 기준 연결 보강 필요)",
    }.get(code, "정책 매칭 상태를 심사자가 확인해 주세요.")


def judgments_by_anchor(judgments: list[LLMJudgment]) -> dict[str, list[LLMJudgment]]:
    rows: dict[str, list[LLMJudgment]] = {}
    for judgment in judgments:
        rows.setdefault(judgment.anchor_id, []).append(judgment)
    return rows


def anchor_is_actionable_for_issues(graph: ReviewGraph, anchor_id: str) -> bool:
    return anchor_display_role(graph, anchor_id) == "actionable"


def anchor_display_role(graph: ReviewGraph, anchor_id: str) -> str:
    anchor_by_id = {anchor.anchor_id: anchor for anchor in graph.anchors}
    anchor = anchor_by_id.get(anchor_id)
    if not anchor or anchor.anchor_type not in ACTIONABLE_ANCHOR_TYPES:
        return "scope"
    sentence_role = sentence_role_for_anchor(graph, anchor_id)
    if sentence_role in {"condition_disclosure", "risk_disclosure", "protection_disclosure"}:
        return "mitigation"
    if sentence_role == "launch_notice":
        return "scope"
    return "actionable"


def sentence_role_for_anchor(graph: ReviewGraph, anchor_id: str) -> str:
    anchor_by_id = {anchor.anchor_id: anchor for anchor in graph.anchors}
    claim_by_id = {claim.claim_id: claim for claim in graph.claims}
    sentence_by_id = {sentence.sentence_id: sentence for sentence in graph.sentence_units}
    anchor = anchor_by_id.get(anchor_id)
    if not anchor:
        return ""
    claim = claim_by_id.get(anchor.claim_id)
    if not claim:
        return ""
    sentence = sentence_by_id.get(claim.sentence_id)
    return sentence.role if sentence else ""


def plan_count_by_anchor(graph: ReviewGraph) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    for item in graph.cu_plan:
        key = (item.anchor_id, item.cu_id)
        if key in seen:
            continue
        seen.add(key)
        counts[item.anchor_id] = counts.get(item.anchor_id, 0) + 1
    return counts


def aggregate_verdict(judgments: list[LLMJudgment]) -> str:
    if not judgments:
        return "ANCHOR"
    ranked = sorted(judgments, key=lambda item: (verdict_rank(item.verdict), item.score), reverse=True)
    return ranked[0].verdict


def verdict_rank(verdict: str) -> int:
    return {
        "NON_COMPLIANT": 4,
        "INSUFFICIENT": 3,
        "COMPLIANT": 2,
        "NOT_APPLICABLE": 1,
        "ANCHOR": 0,
    }.get(verdict, 0)
