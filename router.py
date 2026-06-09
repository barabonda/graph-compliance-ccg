"""Map CCG judgments to the team-share pre-review output schema."""

from __future__ import annotations

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
    effective = effective_judgments(graph.judgments, graph.exception_reviews)
    anchor_by_id = {anchor.anchor_id: anchor for anchor in graph.anchors}
    actionable_effective = [
        judgment for judgment in effective if anchor_by_id[judgment.anchor_id].anchor_type in ACTIONABLE_ANCHOR_TYPES
    ]
    unmatched_actionable = unmatched_anchors(graph, anchor_types=ACTIONABLE_ANCHOR_TYPES)
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

    detected_issues = [
        {
            "risk_code": judgment.cu_id,
            "severity": severity_from_score(judgment.score),
            "problem_span": judgment.evidence_span,
            "rationale": judgment.why,
            "required_action": action_for_verdict(judgment.verdict),
        }
        for judgment in actionable_effective
        if judgment.verdict in {"NON_COMPLIANT", "INSUFFICIENT"}
    ]
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
        rationale=summary_rationale(final, actionable_effective),
        review_run_id=graph.review_run_id,
        context_triples=to_jsonable(graph.context_triples),
        context_anchors=to_jsonable(graph.anchors),
        cu_plan=to_jsonable(graph.cu_plan),
        judgments=to_jsonable(graph.judgments),
        effective_judgments=to_jsonable(effective),
        exception_reviews=to_jsonable(graph.exception_reviews),
        anchor_display=anchor_display(graph, effective),
        system_review_items=system_review_items,
        revision_suggestions=revision_suggestions or [],
        product_context=graph.product_context,
        disclosure_requirements=graph.disclosure_requirements,
        overall_impression_judgment=graph.overall_impression_judgment,
        track_c_summary=graph.track_c_summary,
        graph_paths=graph.graph_paths,
        highlight_spans=highlight_spans(graph, effective),
    )


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


def summary_rationale(final: str, judgments: list[LLMJudgment]) -> str:
    if not judgments:
        return "CUPlan 기준 판단 대상이 없어 자동 통과하지 않고 추가 검토로 라우팅했습니다."
    risky = [judgment for judgment in judgments if judgment.verdict in {"NON_COMPLIANT", "INSUFFICIENT"}]
    if not risky:
        return "선택된 CUPlan과 evidence window 기준으로 중대한 위반 신호가 확인되지 않았습니다."
    return f"{len(risky)}개 CU에서 위반 또는 추가 검토 필요 판단이 확인되어 {final}로 라우팅했습니다."


def anchor_display(graph: ReviewGraph, effective: list[LLMJudgment]) -> list[dict[str, object]]:
    raw_by_anchor = judgments_by_anchor(graph.judgments)
    effective_by_anchor = judgments_by_anchor(effective)
    plan_counts = plan_count_by_anchor(graph)
    system_items = {item["anchor_id"]: item for item in system_review_items_for(graph)}
    diagnostics = graph.retrieval_diagnostics
    rows = []
    for anchor in graph.anchors:
        is_actionable = anchor.anchor_type in ACTIONABLE_ANCHOR_TYPES
        raw = raw_by_anchor.get(anchor.anchor_id, [])
        effective_items = effective_by_anchor.get(anchor.anchor_id, [])
        if not is_actionable:
            display_verdict = "SCOPE"
        elif not plan_counts.get(anchor.anchor_id, 0):
            display_verdict = "RETRIEVAL_FAILURE"
        else:
            display_verdict = aggregate_verdict(effective_items)
        rows.append(
            {
                "anchor_id": anchor.anchor_id,
                "anchor_type": anchor.anchor_type,
                "display_role": "actionable" if is_actionable else "scope",
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
    effective_by_anchor = judgments_by_anchor(effective)
    spans = []
    for anchor in graph.anchors:
        judgments = effective_by_anchor.get(anchor.anchor_id, [])
        verdict = aggregate_verdict(judgments)
        if anchor.anchor_type not in ACTIONABLE_ANCHOR_TYPES:
            verdict = "SCOPE"
        if not judgments and anchor.anchor_type in ACTIONABLE_ANCHOR_TYPES:
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
    return {
        "NO_HYPERNYM_MATCH": "ContextAnchor는 생성됐지만 승인된 PolicyHypernym으로 정규화되지 않았습니다.",
        "NO_ACTIVE_CU_AFTER_GATE": "후보 CU는 있었지만 상품군/채널/광고유형 gate 이후 활성 CU가 남지 않았습니다.",
        "RERANK_DROPPED_ALL": "후보 CU는 있었지만 LLM rerank가 판단 계획에 포함하지 않았습니다.",
        "MISSING_POLICY_COVERAGE": "정책어는 잡혔지만 연결 가능한 CU 후보가 부족합니다.",
        "CU_PLAN_EMPTY": "ContextAnchor는 생성됐지만 연결 가능한 CUPlan이 없어 자동 통과할 수 없습니다.",
    }.get(code, "정책 매칭 상태를 확인해야 합니다.")


def retrieval_failure_action(code: str) -> str:
    return {
        "NO_HYPERNYM_MATCH": "PolicyHypernym vocabulary와 normalization prompt를 보강하세요.",
        "NO_ACTIVE_CU_AFTER_GATE": "MetaCU gate 적용범위와 상품군/채널 scope를 확인하세요.",
        "RERANK_DROPPED_ALL": "CUEmbeddingProfile, rerank prompt, 후보 evidence를 확인하세요.",
        "MISSING_POLICY_COVERAGE": "해당 PolicyHypernym과 ComplianceUnit/DisclosureRequirement 연결을 보강하세요.",
        "CU_PLAN_EMPTY": "Policy compiler와 CUEmbeddingProfile/PolicyHypernym 연결 상태를 확인하세요.",
    }.get(code, "Policy Graph와 후보검색 상태를 확인하세요.")


def judgments_by_anchor(judgments: list[LLMJudgment]) -> dict[str, list[LLMJudgment]]:
    rows: dict[str, list[LLMJudgment]] = {}
    for judgment in judgments:
        rows.setdefault(judgment.anchor_id, []).append(judgment)
    return rows


def plan_count_by_anchor(graph: ReviewGraph) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in graph.cu_plan:
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
