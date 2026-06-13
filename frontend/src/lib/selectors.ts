/**
 * Pure read-model helpers over a `ReviewOutput`.
 * Ported from the legacy vanilla console (console/app.js) so the
 * Next.js UI renders the same review semantics.
 */

import {
  disclosureMeta as disclosureMetaResolved,
  DISCLOSURE_LABELS,
  HUMAN_ACTION_LABELS,
  HUMAN_FEATURE_LABELS,
  PRINCIPLES,
  QUALIFIER_LABELS,
  type PrincipleKey,
} from "./labels";
import type {
  AnchorDisplay,
  AggregationRow,
  ChainNode,
  Claim,
  ClaimFact,
  ClaimQualifier,
  ComparisonResult,
  ContextAnchor,
  CUPlanItem,
  LLMJudgment,
  PolicyEvidenceChain,
  ProductFact,
  ProminenceDiagnostic,
  ReviewOutput,
  SentenceUnit,
  Span,
} from "./types";

export function shorten(text: unknown, max: number): string {
  const value = String(text ?? "");
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

export function alignSpan(sourceText: string, span: Partial<Span> | undefined): { start: number; end: number } {
  const fallback = { start: span?.start ?? -1, end: span?.end ?? -1 };
  if (!span?.text) return fallback;
  if (
    Number.isInteger(span.start) &&
    Number.isInteger(span.end) &&
    sourceText.slice(span.start, span.end) === span.text
  ) {
    return { start: span.start as number, end: span.end as number };
  }
  const exactIndex = sourceText.indexOf(span.text);
  if (exactIndex >= 0) return { start: exactIndex, end: exactIndex + span.text.length };
  const compactNeedle = span.text.replace(/\s+/g, " ").trim();
  const compactIndex = sourceText.indexOf(compactNeedle);
  if (compactIndex >= 0) return { start: compactIndex, end: compactIndex + compactNeedle.length };
  return fallback;
}

export function anchorDisplay(result: ReviewOutput, anchorId: string): AnchorDisplay | undefined {
  return result.anchor_display?.find((item) => item.anchor_id === anchorId);
}

export function isActionableAnchor(result: ReviewOutput, anchorId: string): boolean {
  return anchorDisplay(result, anchorId)?.display_role === "actionable";
}

export function claimById(result: ReviewOutput, claimId: string): Claim | undefined {
  return result.claims?.find((item) => item.claim_id === claimId);
}

export function claimQualifiers(result: ReviewOutput, claimId: string): ClaimQualifier[] {
  return claimById(result, claimId)?.qualifiers ?? [];
}

export function sentenceById(result: ReviewOutput, sentenceId: string): SentenceUnit | undefined {
  return result.sentence_units?.find((item) => item.sentence_id === sentenceId);
}

export function claimsForSentence(result: ReviewOutput, sentenceId: string): Claim[] {
  return result.claims?.filter((item) => item.sentence_id === sentenceId) ?? [];
}

export function anchorForClaim(result: ReviewOutput, claimId: string): ContextAnchor | undefined {
  return result.context_anchors?.find((item) => item.claim_id === claimId);
}

export function anchorForSentence(result: ReviewOutput, sentenceId: string): ContextAnchor | undefined {
  const claim = claimsForSentence(result, sentenceId)[0];
  return claim ? anchorForClaim(result, claim.claim_id) : undefined;
}

export function planItemsForAnchor(result: ReviewOutput, anchorId: string): CUPlanItem[] {
  return result.cu_plan?.filter((item) => item.anchor_id === anchorId) ?? [];
}

export function judgmentsForAnchor(result: ReviewOutput, anchorId: string): LLMJudgment[] {
  const planIds = planItemsForAnchor(result, anchorId).map((item) => item.plan_item_id);
  return result.judgments?.filter((item) => planIds.includes(item.plan_item_id)) ?? [];
}

export function effectiveJudgmentsForAnchor(result: ReviewOutput, anchorId: string): LLMJudgment[] {
  const planIds = planItemsForAnchor(result, anchorId).map((item) => item.plan_item_id);
  return (result.effective_judgments ?? result.judgments ?? []).filter((item) =>
    planIds.includes(item.plan_item_id),
  );
}

export function rawJudgment(result: ReviewOutput, judgmentId: string): LLMJudgment | undefined {
  return result.judgments?.find((item) => item.judgment_id === judgmentId);
}

export function verdictRank(verdict: string): number {
  const map: Record<string, number> = {
    NON_COMPLIANT: 5,
    RETRIEVAL_FAILURE: 4,
    INSUFFICIENT: 3,
    COMPLIANT: 2,
    NOT_APPLICABLE: 1,
    ANCHOR: 0,
  };
  return map[verdict] ?? 0;
}

export function defaultAnchorId(result: ReviewOutput): string {
  const anchors = result.context_anchors ?? [];
  const ranked = [...anchors].sort(
    (a, b) =>
      verdictRank(anchorDisplay(result, b.anchor_id)?.display_verdict ?? "ANCHOR") -
      verdictRank(anchorDisplay(result, a.anchor_id)?.display_verdict ?? "ANCHOR"),
  );
  return ranked[0]?.anchor_id ?? anchors[0]?.anchor_id ?? "";
}

export function filteredAnchors(result: ReviewOutput, selectedPrinciple: PrincipleKey | ""): ContextAnchor[] {
  const anchors = result.context_anchors ?? [];
  if (!selectedPrinciple) return anchors;
  const principle = PRINCIPLES.find((item) => item.key === selectedPrinciple);
  if (!principle) return anchors;
  return anchors.filter((anchor) => {
    const texts = [
      anchor.span.text,
      ...anchor.hypernyms.map((item) => item.hypernym),
      ...planItemsForAnchor(result, anchor.anchor_id).map(
        (plan) => `${plan.principle} ${plan.subject} ${plan.constraint}`,
      ),
    ].join(" ");
    return principle.match.some((token) => texts.includes(token));
  });
}

export function unmatchedAnchors(result: ReviewOutput): ContextAnchor[] {
  return (result.context_anchors ?? []).filter(
    (anchor) => !(result.cu_plan ?? []).some((plan) => plan.anchor_id === anchor.anchor_id),
  );
}

export type PrincipleStatus = "위반 가능성" | "수정 필요" | "검토 필요" | "문제 없음" | "해당 없음";

export function principleStatuses(result: ReviewOutput): Record<PrincipleKey, PrincipleStatus> {
  const statuses = {} as Record<PrincipleKey, PrincipleStatus>;
  const actionableSystemItems = (result.system_review_items ?? []).filter((item) =>
    isActionableAnchor(result, String(item.anchor_id ?? "")),
  );
  if ((result.context_anchors ?? []).length && !(result.cu_plan ?? []).length && actionableSystemItems.length) {
    for (const principle of PRINCIPLES) statuses[principle.key] = "검토 필요";
    return statuses;
  }
  for (const principle of PRINCIPLES) {
    const related = (result.cu_plan ?? []).filter((item) =>
      principle.match.some((token) =>
        `${item.principle} ${item.subject} ${item.constraint} ${item.context}`.includes(token),
      ),
    );
    const unmatched = unmatchedAnchors(result).filter(
      (anchor) =>
        isActionableAnchor(result, anchor.anchor_id) &&
        principle.match.some((token) =>
          `${anchor.span.text} ${anchor.hypernyms?.map((item) => item.hypernym).join(" ")}`.includes(token),
        ),
    );
    if (!related.length) {
      statuses[principle.key] = unmatched.length ? "검토 필요" : "해당 없음";
      continue;
    }
    const judgments = (result.effective_judgments ?? result.judgments ?? []).filter((judgment) => {
      const row = anchorDisplay(result, judgment.anchor_id);
      return row?.display_role !== "scope" && related.some((item) => item.plan_item_id === judgment.plan_item_id);
    });
    if (judgments.some((item) => item.verdict === "NON_COMPLIANT" && Number(item.score ?? 0) >= 0.82)) {
      statuses[principle.key] = "위반 가능성";
    } else if (judgments.some((item) => item.verdict === "NON_COMPLIANT")) {
      statuses[principle.key] = "수정 필요";
    } else if (judgments.some((item) => item.verdict === "INSUFFICIENT")) {
      statuses[principle.key] = "검토 필요";
    } else if (unmatched.length) {
      statuses[principle.key] = "검토 필요";
    } else {
      statuses[principle.key] = "문제 없음";
    }
  }
  return statuses;
}

export function conditionalDisclosures(result: ReviewOutput, sourceText: string): string[] {
  const signals: string[] = [];
  if (/예금자보호|1억원|보호됩니다/.test(sourceText)) signals.push("예금자보호 한도 고지");
  if (/우대조건|가입기간|달라질 수|조건 충족/.test(sourceText)) signals.push("금리/우대조건 고지");
  if (/원금손실|손실 가능성|투자위험/.test(sourceText)) signals.push("원금손실/투자위험 고지");
  if (/과거.*미래|미래.*보장하지/.test(sourceText)) signals.push("과거성과 미래보장 아님 고지");
  if (result.final_verdict === "pass_candidate" && signals.length) return signals;
  return signals.filter((signal) => /고지/.test(signal));
}

export function disclosureSignals(anchor: ContextAnchor): string[] {
  const text = `${anchor.span.text} ${anchor.facts.join(" ")} ${anchor.hypernyms
    .map((item) => item.hypernym)
    .join(" ")}`;
  const signals: string[] = [];
  if (/예금자보호|1억원|보호/.test(text)) signals.push("예금자보호 고지 있음");
  if (/우대조건|가입기간|조건/.test(text)) signals.push("조건/우대금리 고지 있음");
  if (/원금손실|투자위험/.test(text)) signals.push("위험 고지 있음");
  if (!signals.length && /보장|확정|수익/.test(text)) signals.push("완화 고지 확인 필요");
  return signals;
}

export function safeAlternative(text: string): string {
  if (/고수익|보장|확정|조건 없이/.test(text)) {
    return "우대조건 충족 시 최고 금리가 적용될 수 있으며, 적용 조건과 제한사항은 상품설명서 및 약관을 확인하시기 바랍니다.";
  }
  if (/조기상환|성과|수익률/.test(text)) {
    return "과거 성과는 참고자료이며 미래 수익 또는 상환 가능성을 보장하지 않습니다. 상품 구조와 손실 가능성을 확인하시기 바랍니다.";
  }
  return "상품의 적용 조건, 위험, 수수료 및 필수고지를 함께 표시하는 문안으로 수정하시기 바랍니다.";
}

export function maxSeverity(result: ReviewOutput): number {
  return Math.max(0, ...(result.detected_issues ?? []).map((item) => Number(item.severity ?? 0)));
}

export function humanAnchorLabel(result: ReviewOutput, anchor: ContextAnchor): string {
  const featureSet =
    anchor.feature_set ??
    (result.anchor_feature_sets ?? []).find((item) => item.anchor_id === anchor.anchor_id);
  const action = (featureSet?.action_types ?? []).find((item) => HUMAN_ACTION_LABELS[item]);
  if (action) return HUMAN_ACTION_LABELS[action];
  const feature = (featureSet?.positive_features ?? []).find((item) => HUMAN_FEATURE_LABELS[item]);
  if (feature) return HUMAN_FEATURE_LABELS[feature];
  const qualifier = claimQualifiers(result, anchor.claim_id).find((item) => QUALIFIER_LABELS[item.role]);
  if (qualifier) return QUALIFIER_LABELS[qualifier.role];
  return "";
}

export function policyBasisForAnchor(result: ReviewOutput, anchor: ContextAnchor): string[] {
  return planItemsForAnchor(result, anchor.anchor_id)
    .map((item) => item.source_article || item.principle || item.subject)
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// Highlight model — two annotation layers over the original ad copy.
//
// The Context Graph hierarchy (SentenceUnit/Claim -> ClaimQualifier) maps
// directly onto the visual hierarchy:
//   * "area"  — claim/disclosure-sentence surface, rendered as a soft
//     background wash (the reading context).
//   * "token" — qualifier/expression span, rendered as an underline + chip
//     (the thing the reviewer acts on).
// Both layers are always rendered together; tone is a fixed 4-color system
// (risk/review/keep/scope) with shape encoding so color is never the only
// signal. Legal basis stays available via tooltip, not in the chip text.
// ---------------------------------------------------------------------------

export type HighlightTone = "risk" | "review" | "keep" | "keep-warning" | "scope";

export const TONE_RANK: Record<HighlightTone, number> = {
  risk: 5,
  review: 4,
  "keep-warning": 3,
  keep: 2,
  scope: 1,
};

export const TONE_WORD: Record<HighlightTone, string> = {
  risk: "위험",
  review: "검토",
  "keep-warning": "고지 · 위계 낮음",
  keep: "고지",
  scope: "범위",
};

export interface HighlightCandidate {
  id: string;
  kind: "area" | "token";
  anchorId: string;
  start: number;
  end: number;
  text: string;
  tone: HighlightTone;
  /** Human-first chip label, e.g. "확정 표현", "조건 고지". */
  label: string;
  /** Hover detail: tone word + label + legal basis summary. */
  tooltip: string;
  priority: number;
}

export function verdictTone(verdict: string): HighlightTone {
  if (verdict === "NON_COMPLIANT") return "risk";
  if (verdict === "INSUFFICIENT" || verdict === "RETRIEVAL_FAILURE") return "review";
  if (verdict === "COMPLIANT" || verdict === "NOT_APPLICABLE") return "keep";
  return "scope";
}

/** "금소법 시행령 제20조 ①-4 외 2건" 형태의 근거 요약. */
export function basisSummary(result: ReviewOutput, anchorId: string): string {
  const articles = [
    ...new Set(
      planItemsForAnchor(result, anchorId)
        .map((item) => item.source_article)
        .filter(Boolean),
    ),
  ];
  if (!articles.length) return "";
  return articles.length > 1 ? `${articles[0]} 외 ${articles.length - 1}건` : articles[0];
}

function areaPriority(tone: HighlightTone, anchorType: string): number {
  const typeScore = anchorType === "risk_anchor" ? 2 : anchorType === "claim_anchor" ? 1 : 0;
  return TONE_RANK[tone] * 10 + typeScore;
}

function tokenPriority(role: string, tone: HighlightTone): number {
  const roleScore: Record<string, number> = {
    guarantee: 98,
    certainty: 96,
    condition_scope: 92,
    target_scope: 90,
    risk_downplay: 88,
    benefit_scope: 82,
    comparison: 78,
    disclosure_qualifier: 58,
    other: 50,
  };
  return (roleScore[role] ?? 50) + TONE_RANK[tone];
}

function areaLabel(result: ReviewOutput, anchor: ContextAnchor, tone: HighlightTone): string {
  if (tone === "scope") return "범위";
  const human = humanAnchorLabel(result, anchor);
  if (human) return human;
  if (tone === "risk") return "위험 표현";
  if (tone === "review") return "검토 필요";
  if (tone === "keep") return "유지 고지";
  return "검토됨";
}

function withBasis(toneWord: string, label: string, basis: string, extra = ""): string {
  const parts = [`${toneWord} · ${label}`];
  if (extra) parts.push(extra);
  if (basis) parts.push(`근거 ${basis}`);
  return parts.join(" · ");
}

function validCandidate(text: string) {
  return (span: HighlightCandidate): boolean =>
    Number.isInteger(span.start) &&
    Number.isInteger(span.end) &&
    span.start >= 0 &&
    span.end <= text.length &&
    span.end > span.start;
}

export function highlightCandidates(
  result: ReviewOutput,
  text: string,
  selectedPrinciple: PrincipleKey | "",
): HighlightCandidate[] {
  const anchors = filteredAnchors(result, selectedPrinciple);

  // Area layer: claim surfaces (reading context, soft background).
  const claimAreas = anchors
    .map((anchor): HighlightCandidate => {
      const display = anchorDisplay(result, anchor.anchor_id);
      const aligned = alignSpan(text, anchor.span);
      const role = display?.display_role ?? (isActionableAnchor(result, anchor.anchor_id) ? "actionable" : "scope");
      const tone: HighlightTone =
        role === "scope" ? "scope" : verdictTone(display?.display_verdict ?? "ANCHOR");
      const label = areaLabel(result, anchor, tone);
      const basis = basisSummary(result, anchor.anchor_id);
      return {
        id: anchor.anchor_id,
        kind: "area",
        anchorId: anchor.anchor_id,
        start: aligned.start,
        end: aligned.end,
        text: anchor.span.text,
        tone,
        label,
        tooltip: withBasis(TONE_WORD[tone], label, basis),
        priority: areaPriority(tone, anchor.anchor_type),
      };
    })
    .filter(validCandidate(text));

  // Area layer: disclosure sentences. Green = "잘했음 + 수정 시 보존 필수".
  // PROMINENCE_INSUFFICIENT keeps the green base but adds the warning frame.
  const diagnostics = result.prominence_diagnostics ?? [];
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const disclosureAreas = (result.disclosure_links ?? [])
    .map((link, index): HighlightCandidate => {
      const evidence = link.disclosure_text || link.evidence || "";
      const aligned = alignSpan(text, { text: evidence, start: -1, end: -1 });
      const insufficient = (link.status ?? "") === "PROMINENCE_INSUFFICIENT";
      const diagnostic = diagnostics.find(
        (item) => item.disclosure_sentence_id === link.disclosure_sentence_id || item.evidence === evidence,
      );
      const check = checks.find((item) => item.check_id === link.check_id);
      const benefitAnchor = link.benefit_sentence_id
        ? anchorForSentence(result, String(link.benefit_sentence_id))
        : undefined;
      const tone: HighlightTone = insufficient ? "keep-warning" : "keep";
      const label = insufficient
        ? "고지 있음 · 위계 낮음"
        : DISCLOSURE_LABELS[String(link.check_id ?? "")] ?? check?.label ?? "유지 고지";
      return {
        id: `disclosure_${link.disclosure_sentence_id ?? index}`,
        kind: "area",
        anchorId: benefitAnchor?.anchor_id ?? "",
        start: aligned.start,
        end: aligned.end,
        text: evidence,
        tone,
        label,
        tooltip: withBasis(
          TONE_WORD[tone],
          label,
          "",
          diagnostic?.message || link.reason || "수정 시 유지해야 할 고지입니다.",
        ),
        priority: TONE_RANK[tone] * 10 + 3,
      };
    })
    .filter((span) => Boolean(span.text))
    .filter(validCandidate(text));

  // Token layer: claim qualifiers (the expression the reviewer acts on).
  const tokens = anchors
    .flatMap((anchor) => {
      const display = anchorDisplay(result, anchor.anchor_id);
      const claimTone = verdictTone(display?.display_verdict ?? "ANCHOR");
      const basis = basisSummary(result, anchor.anchor_id);
      return claimQualifiers(result, anchor.claim_id).map((qualifier): HighlightCandidate => {
        const aligned = alignSpan(text, qualifier.span ?? { text: qualifier.text, start: -1, end: -1 });
        const isDisclosure = qualifier.role === "disclosure_qualifier";
        const tone: HighlightTone = isDisclosure ? "keep" : claimTone === "scope" ? "review" : claimTone;
        const label = QUALIFIER_LABELS[qualifier.role] ?? "표현";
        return {
          id: qualifier.qualifier_id || `${anchor.anchor_id}_${qualifier.text}`,
          kind: "token",
          anchorId: anchor.anchor_id,
          start: aligned.start,
          end: aligned.end,
          text: qualifier.text,
          tone,
          label,
          tooltip: withBasis(TONE_WORD[tone], label, basis, qualifier.meaning || qualifier.risk_reason || ""),
          priority: tokenPriority(qualifier.role, tone),
        };
      });
    })
    .filter(validCandidate(text));

  // Multiple anchors (claim_anchor + risk_anchor) can alias the same claim,
  // producing identical spans twice. Keep only the strongest per span+label
  // so chip "+N" counts reflect genuinely different annotations.
  return [
    ...dedupeBySpan(claimAreas),
    ...dedupeBySpan(disclosureAreas),
    ...dedupeBySpan(tokens),
  ];
}

function dedupeBySpan(candidates: HighlightCandidate[]): HighlightCandidate[] {
  const byKey = new Map<string, HighlightCandidate>();
  for (const item of candidates) {
    const key = `${item.start}_${item.end}_${item.label}`;
    const existing = byKey.get(key);
    if (!existing || TONE_RANK[item.tone] > TONE_RANK[existing.tone] || (TONE_RANK[item.tone] === TONE_RANK[existing.tone] && item.priority > existing.priority)) {
      byKey.set(key, item);
    }
  }
  return [...byKey.values()];
}

export interface HighlightChip {
  anchorId: string;
  tone: HighlightTone;
  label: string;
  tooltip: string;
  /** Overlapping same-end candidates folded into this chip ("+N"). */
  hidden: number;
}

export interface LayeredSegment {
  key: string;
  text: string;
  area: HighlightCandidate | null;
  token: HighlightCandidate | null;
  /** Emitted where the area ends — the renderer decides visibility. */
  areaChip: HighlightChip | null;
  /** Emitted where the top token ends — the renderer decides visibility. */
  tokenChip: HighlightChip | null;
}

export interface AnnotatedText {
  segments: LayeredSegment[];
  visibleCount: number;
  hiddenByOverlap: number;
}

/**
 * Flatten both layers into renderable segments. Per segment at most one area
 * (background) and one token (underline) survive; overlap resolution follows
 * the fixed tone ranking (위반 의심 > 검토 필요 > 위계 낮음 > 유지 고지 > 범위)
 * and suppressed same-end candidates surface as "+N" on the winning chip.
 */
export function annotateText(text: string, candidates: HighlightCandidate[]): AnnotatedText {
  if (!text) return { segments: [], visibleCount: 0, hiddenByOverlap: 0 };
  const valid = candidates.filter((item) => item.start >= 0 && item.end <= text.length && item.end > item.start);
  const areas = valid.filter((item) => item.kind === "area");
  const tokens = valid.filter((item) => item.kind === "token");

  const boundaries = new Set<number>([0, text.length]);
  for (const item of valid) {
    boundaries.add(item.start);
    boundaries.add(item.end);
  }
  const points = [...boundaries].sort((a, b) => a - b);

  const byTone = (a: HighlightCandidate, b: HighlightCandidate) =>
    TONE_RANK[b.tone] - TONE_RANK[a.tone] || b.priority - a.priority;

  const segments: LayeredSegment[] = [];
  const visible = new Set<string>();
  const suppressed = new Set<string>();

  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (end <= start) continue;
    const segmentText = text.slice(start, end);
    const activeAreas = areas.filter((item) => item.start < end && start < item.end).sort(byTone);
    const activeTokens = tokens.filter((item) => item.start < end && start < item.end).sort(byTone);
    const area = activeAreas[0] ?? null;
    const token = activeTokens[0] ?? null;

    for (const item of activeAreas) (item === area ? visible : suppressed).add(item.id);
    for (const item of activeTokens) (item === token ? visible : suppressed).add(item.id);

    const chipFor = (
      winner: HighlightCandidate | null,
      siblings: HighlightCandidate[],
    ): HighlightChip | null => {
      if (!winner || winner.end !== end) return null;
      const hiddenSiblings = siblings.filter((item) => item !== winner && item.end === end);
      return {
        anchorId: winner.anchorId,
        tone: winner.tone,
        label: winner.label,
        tooltip: hiddenSiblings.length
          ? `${winner.tooltip} / 겹침: ${hiddenSiblings.map((item) => item.label).join(", ")}`
          : winner.tooltip,
        hidden: hiddenSiblings.length,
      };
    };

    segments.push({
      key: `seg_${start}`,
      text: segmentText,
      area,
      token,
      areaChip: chipFor(area, activeAreas),
      tokenChip: chipFor(token, activeTokens),
    });
  }

  for (const id of visible) suppressed.delete(id);
  return { segments, visibleCount: visible.size, hiddenByOverlap: suppressed.size };
}

// ---------------------------------------------------------------------------
// 원문 줄 분할 + 인라인 수정안 + 교정본 (심사 콘솔 AdPane).
// 코드리뷰 패러다임: 문장 단위로 원문을 쌓고, 선택된 이슈의 수정안을 그
// 문장 바로 아래에 펼친다. 교정본 모드는 적용된 수정안을 원문에 치환한다.
// ---------------------------------------------------------------------------

export interface AdLine {
  key: string;
  /** 이 줄을 차지하는 문장 id (gap 줄이면 빈 문자열). */
  sentenceId: string;
  text: string;
  /** 줄 내부 하이라이트 (offset은 줄 기준). */
  annotated: AnnotatedText;
}

/**
 * SentenceUnit 기준으로 원문을 줄(블록)로 나눈다. 문장 사이 공백/문장부호
 * gap도 보존한다. sentence_units가 없거나 정렬이 깨지면 전체를 한 줄로.
 */
export function buildAdLines(result: ReviewOutput, text: string): AdLine[] {
  if (!text) return [];
  const candidates = highlightCandidates(result, text, "");
  const annotateRange = (start: number, end: number): AnnotatedText => {
    const slice = text.slice(start, end);
    const local = candidates
      .filter((c) => c.start < end && start < c.end)
      .map((c) => ({ ...c, start: Math.max(0, c.start - start), end: Math.min(end - start, c.end - start) }));
    return annotateText(slice, local);
  };

  const sentences = (result.sentence_units ?? [])
    .map((unit) => ({ unit, span: alignSpan(text, unit.span) }))
    .filter(({ span }) => Number.isInteger(span.start) && span.start >= 0 && span.end <= text.length && span.end > span.start)
    .sort((a, b) => a.span.start - b.span.start);

  if (!sentences.length) {
    return [{ key: "line_full", sentenceId: "", text, annotated: annotateRange(0, text.length) }];
  }

  const lines: AdLine[] = [];
  let cursor = 0;
  for (const { unit, span } of sentences) {
    if (span.start < cursor) continue; // 겹치는 문장은 건너뛴다
    if (span.start > cursor) {
      const gap = text.slice(cursor, span.start);
      if (gap.trim()) {
        lines.push({ key: `gap_${cursor}`, sentenceId: "", text: gap, annotated: annotateRange(cursor, span.start) });
      } else if (gap) {
        lines.push({ key: `gap_${cursor}`, sentenceId: "", text: gap, annotated: { segments: [{ key: "g", text: gap, area: null, token: null, areaChip: null, tokenChip: null }], visibleCount: 0, hiddenByOverlap: 0 } });
      }
    }
    lines.push({
      key: `s_${unit.sentence_id}`,
      sentenceId: unit.sentence_id,
      text: text.slice(span.start, span.end),
      annotated: annotateRange(span.start, span.end),
    });
    cursor = span.end;
  }
  if (cursor < text.length) {
    const tail = text.slice(cursor);
    lines.push({ key: `gap_${cursor}`, sentenceId: "", text: tail, annotated: annotateRange(cursor, text.length) });
  }
  return lines;
}

/** anchor의 수정안(before/after). 제안이 없으면 safeAlternative로 대체. */
export function revisionFor(
  result: ReviewOutput,
  anchorId: string,
): { before: string; after: string; notes_for_reviewer?: string } | null {
  const anchor = result.context_anchors?.find((item) => item.anchor_id === anchorId);
  if (!anchor) return null;
  const display = anchorDisplay(result, anchorId);
  if (display?.display_role !== "actionable") return null;
  const tone = verdictTone(display?.display_verdict ?? "ANCHOR");
  if (tone !== "risk" && tone !== "review") return null;
  const suggestion = (result.revision_suggestions ?? []).find((item) => item.anchor_id === anchorId);
  return {
    before: suggestion?.before ?? anchor.span.text,
    after: suggestion?.after ?? safeAlternative(anchor.span.text),
    notes_for_reviewer: suggestion?.notes_for_reviewer,
  };
}

/** 선택된 anchor가 이 문장에 속하는지 (claim.sentence_id 기준). */
export function anchorSentenceId(result: ReviewOutput, anchorId: string): string {
  const anchor = result.context_anchors?.find((item) => item.anchor_id === anchorId);
  if (!anchor) return "";
  return claimById(result, anchor.claim_id)?.sentence_id ?? "";
}

export interface CorrectedSegment {
  text: string;
  changed: boolean;
}

/** 백엔드가 보낸 '전체 일관 교정본'(문서 단위 재작성). 없으면 null. */
export const DOCUMENT_REVISION_ANCHOR = "__document__";
export function correctedDocument(result: ReviewOutput): string | null {
  const doc = (result.revision_suggestions ?? []).find(
    (item) => item.anchor_id === DOCUMENT_REVISION_ANCHOR,
  );
  const after = String(doc?.after ?? "").trim();
  return after ? after : null;
}

/**
 * 원문 ↔ 교정본 문장 단위 diff. 비위험 텍스트는 verbatim 유지되므로, 원문에 없는
 * 교정본 문장을 '변경'으로 표시한다(짜깁기 대신 일관 재작성을 그대로 보여줌).
 * 문장 경계(마침표/물음표/느낌표 + 공백, 줄바꿈)로 나누되 구분자는 보존한다.
 */
export function buildDocumentDiff(
  original: string,
  corrected: string,
): { segments: CorrectedSegment[]; changedCount: number } {
  const normalize = (value: string) => value.replace(/[\s.!?]+$/g, "").trim();
  const originalSet = new Set(
    original.split(/[\n.!?]+/).map(normalize).filter(Boolean),
  );
  const parts = corrected.split(/(\n+|(?<=[다요.!?])\s+)/);
  const segments: CorrectedSegment[] = [];
  let changedCount = 0;
  for (const part of parts) {
    if (!part) continue;
    if (/^\s+$/.test(part)) {
      segments.push({ text: part, changed: false });
      continue;
    }
    const key = normalize(part);
    const changed = key.length > 0 && !originalSet.has(key);
    if (changed) changedCount += 1;
    segments.push({ text: part, changed });
  }
  return { segments, changedCount };
}

/** 적용된(resolved) anchor들의 span을 after 문안으로 치환한 교정본. */
export function buildCorrectedCopy(
  result: ReviewOutput,
  text: string,
  resolvedIds: Set<string>,
): { segments: CorrectedSegment[]; changedCount: number } {
  const spans = [...resolvedIds]
    .map((id) => {
      const anchor = result.context_anchors?.find((item) => item.anchor_id === id);
      if (!anchor) return null;
      const aligned = alignSpan(text, anchor.span);
      const revision = revisionFor(result, id);
      if (!revision || !Number.isInteger(aligned.start) || aligned.start < 0 || aligned.end > text.length || aligned.end <= aligned.start) {
        return null;
      }
      return { start: aligned.start, end: aligned.end, after: revision.after };
    })
    .filter((s): s is { start: number; end: number; after: string } => Boolean(s))
    .sort((a, b) => a.start - b.start);

  // 겹치는 치환은 앞선 것만 유지.
  const merged: typeof spans = [];
  let lastEnd = -1;
  for (const span of spans) {
    if (span.start >= lastEnd) {
      merged.push(span);
      lastEnd = span.end;
    }
  }

  const segments: CorrectedSegment[] = [];
  let cursor = 0;
  for (const span of merged) {
    if (span.start > cursor) segments.push({ text: text.slice(cursor, span.start), changed: false });
    segments.push({ text: span.after, changed: true });
    cursor = span.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), changed: false });
  return { segments, changedCount: merged.length };
}

// ---------------------------------------------------------------------------
// Issue cards — the right-hand evidence panel read model.
// One compact card per actionable finding; deep evidence stays in tabs.
// ---------------------------------------------------------------------------

export interface IssueCardModel {
  id: string;
  /** 화면용 순번 코드 (C1, C2 … / 고지 D1 … / 종합 심사 B). 내부 해시 id 대체. */
  code: string;
  kind: "anchor" | "disclosure" | "trackB";
  /** 판정 층: A=개별 심사(표현·고지를 조항별로), B=종합 심사(전체 인상). */
  track: "A" | "B";
  /** 위반 가능성 등급 (수치는 hover). */
  grade: "낮음" | "중간" | "높음";
  /** 원 점수 (hover 표기용, 0–1). */
  score?: number;
  /** 요건별 충족 요약, e.g. `요건 4개 중 2개 미충족`. */
  criteriaSummary?: string;
  tone: HighlightTone;
  anchorId?: string;
  /** 사람 말 위반 유형, e.g. `단정·보장 표현`. */
  label: string;
  /** 대상 문구 인용 (anchor 카드) 또는 고지 라벨. */
  quote: string;
  /** Human-first title, e.g. `단정·보장 표현 — “확정 제공”`. */
  title: string;
  /** Basis line, e.g. `시행령 §20①4 · 광고에서 단정적 판단/오인 유발 표현`. */
  basis: string;
  /** One-line rationale shown when the card is selected/expanded. */
  rationale: string;
}

/** 0–1 점수를 위반 가능성 등급으로. 수치는 hover에서만 노출. */
function gradeFromScore(score: number): "낮음" | "중간" | "높음" {
  return score >= 0.7 ? "높음" : score >= 0.4 ? "중간" : "낮음";
}

/** 누락 고지(check_id)의 주제가 상품설명서(product_facts)에 있는지 매칭할 토큰. */
const DISCLOSURE_DOC_TOKENS: Record<string, string[]> = {
  deposit_tax_basis: ["세전", "세후", "세금"],
  deposit_rate_condition: ["우대", "고시이율", "기본이자율", "조건"],
  deposit_term: ["계약기간", "가입기간", "만기", "기간"],
  depositor_protection_limit: ["예금자보호", "예금보험", "보호한도", "5천만원", "5,000만원"],
  loan_rate_range: ["대출금리", "금리"],
  loan_screening: ["심사", "승인"],
  loan_fee: ["수수료", "중도상환", "부대비용"],
  investment_loss_risk: ["원금", "손실", "투자위험"],
  past_performance_warning: ["과거", "수익률", "실적"],
};

export type DisclosureDocStatus = "in_doc" | "not_in_doc" | "no_doc";

export interface DisclosureDocCrossRef {
  status: DisclosureDocStatus;
  facts: ProductFact[];
}

/**
 * 광고에 누락된 필수 고지가 상품설명서(product_facts)에는 있는지 교차 확인.
 * - in_doc: 광고엔 없지만 상품설명서엔 명시 → 광고로 반영하면 됨
 * - not_in_doc: 상품설명서에서도 확인 안 됨 → 더 깊은 공백
 * - no_doc: 상품문서 미추출(대조 불가) 또는 대조 대상이 아닌 메타 고지
 */
export function disclosureDocCrossRef(
  result: ReviewOutput,
  checkId: string,
  label: string,
): DisclosureDocCrossRef {
  const ctx = result.product_fact_context;
  // 상품설명서·약관 '확인 안내'는 문서 내용이 아니라 메타 고지 → 대조 대상 아님.
  if (ctx?.extraction_status !== "EXTRACTED" || checkId.includes("document_notice")) {
    return { status: "no_doc", facts: [] };
  }
  // 백엔드(build_disclosure_checks)가 직접 연결한 근거를 단일 출처로 우선 사용.
  const check = (ctx.disclosure_checks ?? []).find((item) => item.check_id === checkId);
  const linked = check?.product_doc_evidence as ProductFact[] | undefined;
  if (linked !== undefined) {
    return { status: linked.length ? "in_doc" : "not_in_doc", facts: linked.slice(0, 4) };
  }
  // 폴백: 백엔드 연결이 없는 데이터는 프론트 토큰 휴리스틱으로 추정.
  const facts = ctx.product_facts ?? [];
  const tokens = DISCLOSURE_DOC_TOKENS[checkId] ?? [label];
  const matched = facts.filter((fact) => {
    const haystack = `${fact.fact_type} ${fact.condition ?? ""} ${fact.value} ${fact.evidence_text ?? ""}`;
    return tokens.some((token) => haystack.includes(token));
  });
  return { status: matched.length ? "in_doc" : "not_in_doc", facts: matched.slice(0, 4) };
}

// ---------------------------------------------------------------------------
// 전체 인상(Track B) 종합 그래프: 혜택 주장을 중심으로, 그것을 완화/강화하는
// 문장들을 InterSentenceRelation + 문장 역할로 연결한다. 70개 문장을 평면
// 나열하는 대신 "혜택 ← 무엇이 완화/강화하나"의 구조만 추린다.
// ---------------------------------------------------------------------------
export type OverallNodeKind = "benefit" | "mitigate" | "reinforce" | "prominence" | "fact";

export interface OverallGraphNode {
  kind: OverallNodeKind;
  title: string;
  text: string;
}

export interface OverallGraphEdge {
  label: string;
  node: OverallGraphNode;
}

export interface OverallImpressionGraphModel {
  benefit: OverallGraphNode | null;
  edges: OverallGraphEdge[];
  conclusion: { grade: "낮음" | "중간" | "높음"; text: string } | null;
}

const RELATION_KO: Record<string, string> = {
  QUALIFIES: "조건부 제한",
  MITIGATES: "위험 완화",
  REINFORCES: "인상 강화",
  AMPLIFIES_RISK: "위험 증폭",
};

// 노드 역할 → 그래프 종류/색. 색은 관계 타입이 아니라 '문장 역할'로 정한다
// (혜택=위험/빨강, 조건·위험 고지=완화/노랑, 보호 고지=강화/초록).
const ROLE_NODE: Record<string, { kind: OverallNodeKind; title: string }> = {
  condition_disclosure: { kind: "mitigate", title: "조건 고지" },
  risk_disclosure: { kind: "mitigate", title: "위험 고지" },
  protection_disclosure: { kind: "reinforce", title: "보호 고지" },
};

export function buildOverallImpressionGraph(result: ReviewOutput): OverallImpressionGraphModel {
  const tb = result.overall_impression_judgment;
  const sentences = new Map((result.sentence_units ?? []).map((item) => [item.sentence_id, item]));
  const relations = result.inter_sentence_relations ?? [];

  const score = Number(tb?.misleading_risk_score ?? 0);
  const conclusion = tb?.verdict
    ? { grade: gradeFromScore(score), text: tb.why || tb.representative_consumer_impression || "" }
    : null;

  // 혜택 주장: benefit_claim 중 관계 연결이 많고 '최고/확정/보장'이 강한 문장.
  const degree = (id: string) =>
    relations.filter((rel) => rel.source_sentence_id === id || rel.target_sentence_id === id).length;
  const salience = (text: string) => (/(최고|확정|보장)/.test(text) ? 2 : 0) + (/%/.test(text) ? 1 : 0);
  const benefitSentence = (result.sentence_units ?? [])
    .filter((item) => item.role === "benefit_claim")
    .sort(
      (a, b) =>
        salience(b.text) + degree(b.sentence_id) - (salience(a.text) + degree(a.sentence_id)),
    )[0];
  const benefit: OverallGraphNode | null = benefitSentence
    ? { kind: "benefit", title: "혜택 주장", text: benefitSentence.text }
    : null;

  // 엣지: benefit_claim ↔ (조건/위험/보호 고지) 관계만, 노드 역할로 완화/강화 분류.
  const edges: OverallGraphEdge[] = [];
  const seen = new Set<string>();
  for (const rel of relations) {
    const source = sentences.get(rel.source_sentence_id);
    const target = sentences.get(rel.target_sentence_id);
    if (!source || !target) continue;
    const benefitEnd = source.role === "benefit_claim" ? source : target.role === "benefit_claim" ? target : null;
    if (!benefitEnd) continue;
    const other = benefitEnd === source ? target : source;
    const mapping = ROLE_NODE[other.role];
    if (!mapping || seen.has(other.sentence_id)) continue;
    seen.add(other.sentence_id);
    const relKo = RELATION_KO[rel.relation_type] ?? "관계";
    edges.push({
      label: `${mapping.title} · ${relKo}`,
      node: { kind: mapping.kind, title: mapping.title, text: other.text },
    });
    if (edges.length >= 5) break;
  }

  return { benefit, edges, conclusion };
}

export function buildIssueCards(result: ReviewOutput): IssueCardModel[] {
  const cards: IssueCardModel[] = [];

  // claim_anchor + risk_anchor can alias the same claim — one card per claim,
  // keeping the strongest anchor and merging the basis lines.
  const byClaim = new Map<string, { card: IssueCardModel; score: number }>();
  for (const anchor of result.context_anchors ?? []) {
    const display = anchorDisplay(result, anchor.anchor_id);
    if (display?.display_role !== "actionable") continue;
    const tone = verdictTone(display?.display_verdict ?? "ANCHOR");
    if (tone !== "risk" && tone !== "review") continue;
    const effective = effectiveJudgmentsForAnchor(result, anchor.anchor_id);
    const issues = (result.detected_issues ?? []).filter((issue) =>
      effective.some((judgment) => judgment.cu_id === issue.risk_code),
    );
    const qualifiers = [...claimQualifiers(result, anchor.claim_id)].sort(
      (a, b) => tokenPriority(b.role, tone) - tokenPriority(a.role, tone),
    );
    const label = humanAnchorLabel(result, anchor) || (tone === "risk" ? "위험 표현" : "검토 필요");
    // 카드 인용은 실제 판정 근거(claim 전체)를 보여준다. 단일 qualifier("보장")만
    // 띄우면 결합 단정의 맥락이 사라져 무슨 위반인지 알기 어렵다.
    const quote = anchor.span.text || qualifiers[0]?.text || "";
    const basis = [basisSummary(result, anchor.anchor_id), issues[0]?.risk_title]
      .filter(Boolean)
      .join(" · ");
    const risky = effective.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
    const anchorScore = Number(display?.score ?? risky[0]?.score ?? 0);
    const findings = risky[0]?.criteria_findings ?? [];
    const unmet = findings.filter((finding) => !finding.satisfied).length;
    // 미충족이 있을 때만 노출. INSUFFICIENT(증거 불충분)에서 '0개 미충족'은 오해 소지.
    const criteriaSummary = unmet > 0 ? `요건 ${findings.length}개 중 ${unmet}개 미충족` : undefined;
    const card: IssueCardModel = {
      id: anchor.anchor_id,
      code: "",
      kind: "anchor",
      track: "A",
      grade: gradeFromScore(anchorScore),
      score: anchorScore,
      criteriaSummary,
      tone,
      anchorId: anchor.anchor_id,
      label,
      quote: shorten(quote, 32),
      title: `${label} — “${shorten(quote, 24)}”`,
      basis,
      rationale: issues[0]?.rationale || risky[0]?.why || "",
    };
    const score = TONE_RANK[tone] * 10 + Number(display?.score ?? 0);
    const existing = byClaim.get(anchor.claim_id);
    if (!existing) {
      byClaim.set(anchor.claim_id, { card, score });
    } else if (score > existing.score) {
      byClaim.set(anchor.claim_id, {
        card: { ...card, basis: mergeBasis(card.basis, existing.card.basis) },
        score,
      });
    } else {
      existing.card.basis = mergeBasis(existing.card.basis, card.basis);
    }
  }
  cards.push(...[...byClaim.values()].map((entry) => entry.card));

  const requirements = result.disclosure_requirements ?? [];
  for (const check of result.product_fact_context?.disclosure_checks ?? []) {
    if (check.present) continue;
    const requirement = requirements.find(
      (item) => item.label === check.label || String(item.check_id ?? "") === check.check_id,
    );
    cards.push({
      id: `disclosure_${check.check_id}`,
      code: "",
      kind: "disclosure",
      track: "A",
      grade: "중간",
      tone: "review",
      label: "필수 고지 누락",
      quote: check.label,
      title: `필수 고지 누락 — ${check.label}`,
      // 근거 조문은 데이터 기반(그래프 카탈로그가 내려준 check.source) 우선.
      basis: String(check.source ?? requirement?.source ?? "은행 광고심의 기준"),
      rationale: String(requirement?.why ?? "문안에서 해당 고지가 확인되지 않았습니다."),
    });
  }

  const trackB = result.overall_impression_judgment ?? {};
  if (trackB.verdict) {
    const score = Number(trackB.misleading_risk_score ?? 0);
    // 점수 1차 노출 금지 — 등급으로만 표기 (수치는 상세 hover에서).
    const gradeLabel = score >= 0.7 ? "높음" : score >= 0.4 ? "중간" : "낮음";
    cards.push({
      id: "trackB",
      code: "B",
      kind: "trackB",
      track: "B",
      grade: gradeLabel,
      score,
      tone: score >= 0.7 ? "risk" : score >= 0.4 ? "review" : "keep",
      label: "소비자 오인 · 종합 심사",
      quote: `오인 위험 ${gradeLabel}`,
      title: `소비자 오인 · 종합 심사 — 오인 위험 ${gradeLabel}`,
      basis: trackB.standard ?? "전체적·궁극적 인상 기준",
      rationale: trackB.why || trackB.representative_consumer_impression || "",
    });
  }

  // 표시 순서: 표현 이슈(C) → 전체 인상(B) → 필수 고지 누락(D), 각 그룹 내 위험도 내림차순.
  const KIND_ORDER: Record<IssueCardModel["kind"], number> = { anchor: 0, trackB: 1, disclosure: 2 };
  const sorted = cards.sort(
    (a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || TONE_RANK[b.tone] - TONE_RANK[a.tone],
  );
  let claimIndex = 0;
  let disclosureIndex = 0;
  for (const card of sorted) {
    if (card.kind === "anchor") card.code = `C${++claimIndex}`;
    if (card.kind === "disclosure") card.code = `D${++disclosureIndex}`;
  }
  return sorted;
}

function mergeBasis(primary: string, secondary: string): string {
  if (!secondary || secondary === primary) return primary;
  const extra = secondary.split(" · ")[0];
  return primary.includes(extra) ? primary : `${primary} / ${extra}`;
}

// ---------------------------------------------------------------------------
// 근거 경로 그래프 — 이 표현이 왜 이 규정으로 갔는지의 설명 체인.
//   광고 표현 → 위험 유형 → 정책어(Hypernym) → ComplianceUnit → 전제 → 근거 조문
//   종착: 필요 고지 / 예외
// ---------------------------------------------------------------------------

export type EvidenceNodeKind = "claim" | "risk" | "policy" | "cu" | "premise" | "clause";

export interface EvidenceNode {
  kind: EvidenceNodeKind;
  label: string;
  /** 보조 식별자 (CU id, 조문 수 등). */
  sub?: string;
  connected: boolean;
}

export interface EvidencePath {
  anchorId: string;
  quote: string;
  riskLabel: string;
  cuName: string;
  cuId: string;
  premise: string;
  articles: string[];
  nodes: EvidenceNode[];
  disclosure: string;
  /** 자연어 해설에 쓰는 톤(위반 의심/검토 필요). */
  tone: HighlightTone;
}

export function buildEvidencePath(result: ReviewOutput, anchorId: string): EvidencePath | null {
  const anchor = result.context_anchors?.find((item) => item.anchor_id === anchorId);
  if (!anchor) return null;

  const display = anchorDisplay(result, anchorId);
  const tone = verdictTone(display?.display_verdict ?? "ANCHOR");
  const effective = effectiveJudgmentsForAnchor(result, anchorId);
  const risky = effective.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
  const plans = planItemsForAnchor(result, anchorId);
  const topPlan = plans.find((item) => item.plan_item_id === (risky[0] ?? effective[0])?.plan_item_id) ?? plans[0];

  const riskLabel = humanAnchorLabel(result, anchor) || (tone === "risk" ? "위반 의심" : "검토 필요");
  const policy = anchor.hypernyms?.[0]?.hypernym ?? "";
  const cuName = topPlan?.risk_title || topPlan?.principle || "";
  const premise = topPlan?.constraint || topPlan?.context || "";
  const articles = [...new Set(plans.map((item) => item.source_article).filter(Boolean))];

  const suggestion = (result.revision_suggestions ?? []).find((item) => item.anchor_id === anchorId);
  const missingCheck = (result.product_fact_context?.disclosure_checks ?? []).find((check) => !check.present);
  const disclosure =
    suggestion?.required_disclosures?.[0] ||
    missingCheck?.label ||
    disclosureSignals(anchor)[0] ||
    "추가 고지 없음";

  const nodes: EvidenceNode[] = [
    { kind: "claim", label: anchor.span.text, connected: true },
    { kind: "risk", label: riskLabel, connected: true },
    { kind: "policy", label: policy || "정책어 미매칭", connected: Boolean(policy) },
    // CU 내부 id는 1차 화면 노출 금지 — 라벨(심의 기준명)만 보인다.
    { kind: "cu", label: cuName || "CU 미연결", connected: Boolean(cuName) },
    { kind: "premise", label: premise || "전제 미상", connected: Boolean(premise) },
    {
      kind: "clause",
      label: articles[0] || "법적 근거 미연결",
      sub: articles.length > 1 ? `외 ${articles.length - 1}건` : undefined,
      connected: articles.length > 0,
    },
  ];

  return {
    anchorId,
    quote: anchor.span.text,
    riskLabel,
    cuName,
    cuId: topPlan?.cu_id ?? "",
    premise,
    articles,
    nodes,
    disclosure,
    tone,
  };
}

// ---------------------------------------------------------------------------
// 예외 · 고지 검토 — Compliance Gate 타임라인 + 고지 충족 시뮬레이션
// ---------------------------------------------------------------------------

export type GateStatus = "ok" | "warn" | "fail";

export interface ComplianceGate {
  step: number;
  name: string;
  detail: string;
  meta: string;
  status: GateStatus;
}

export interface DisclosureItem {
  id: string;
  label: string;
  desc: string;
  required: boolean;
  present: boolean;
}

export function buildComplianceGates(result: ReviewOutput): ComplianceGate[] {
  const anchors = result.context_anchors ?? [];
  const withHypernym = anchors.filter((anchor) => (anchor.hypernyms?.length ?? 0) > 0).length;
  const cuPlan = result.cu_plan?.length ?? 0;
  const cards = buildIssueCards(result);
  const riskCount = cards.filter((card) => card.kind === "anchor" && card.tone === "risk").length;
  const reviewCount = cards.filter((card) => card.kind === "anchor" && card.tone === "review").length;
  const checks = result.product_fact_context?.disclosure_checks ?? [];
  const requiredChecks = checks.filter((check) => disclosureMetaResolved(check.check_id).required);
  const metRequired = requiredChecks.filter((check) => check.present).length;
  const trackBScore = Number(result.overall_impression_judgment?.misleading_risk_score ?? 0);
  const trackBGrade = trackBScore >= 0.7 ? "높음" : trackBScore >= 0.4 ? "중간" : "낮음";

  return [
    {
      step: 1,
      name: "적용 판단",
      detail: "광고 분류와 사전심의 대상 여부를 확인합니다.",
      meta: result.routing?.ad_scope === "product_ad" ? "금융상품 광고 · 심의 대상" : (result.routing?.ad_scope ?? "scope 미상"),
      status: "ok",
    },
    {
      step: 2,
      name: "정책 정규화",
      detail: "광고 표현을 승인된 정책어(PolicyHypernym)로 매핑합니다.",
      meta: `정책어 매칭 ${withHypernym}/${anchors.length}`,
      status: anchors.length && withHypernym === anchors.length ? "ok" : "warn",
    },
    {
      step: 3,
      name: "심의 기준 검색",
      detail: "정책어 기반으로 후보 ComplianceUnit을 검색합니다.",
      meta: `CU 후보 ${cuPlan}건`,
      status: cuPlan > 0 ? "ok" : "fail",
    },
    {
      step: 4,
      name: "표현 심사",
      detail: "각 표현을 심의 기준에 대조해 위반 여부를 판정합니다.",
      meta: `위반 의심 ${riskCount} · 검토 ${reviewCount}`,
      status: riskCount > 0 ? "fail" : reviewCount > 0 ? "warn" : "ok",
    },
    {
      step: 5,
      name: "종합 심사 (전체 인상)",
      detail: "개별 표현이 통과해도 전체적 인상의 오인 위험을 판단합니다.",
      meta: `오인 위험 ${trackBGrade}`,
      status: trackBScore >= 0.7 ? "fail" : trackBScore >= 0.4 ? "warn" : "ok",
    },
    {
      step: 6,
      name: "예외 · 고지 충족",
      detail: "필수 고지가 병기되면 위반이 완화될 수 있는지 검토합니다.",
      meta: `필수 고지 ${metRequired}/${requiredChecks.length}`,
      status: requiredChecks.length && metRequired < requiredChecks.length ? "fail" : "ok",
    },
  ];
}

export function buildDisclosureItems(result: ReviewOutput): DisclosureItem[] {
  return (result.product_fact_context?.disclosure_checks ?? []).map((check) => {
    const meta = disclosureMetaResolved(check.check_id);
    return {
      id: check.check_id,
      label: check.label,
      desc: meta.desc,
      required: meta.required,
      present: Boolean(check.present),
    };
  });
}

/** `단정·보장 표현 1건 · 필수 고지 누락 2건` 형태의 상단 요약. */
export function issueHeadline(cards: IssueCardModel[]): string {
  const groups = new Map<string, number>();
  for (const card of cards) {
    if (card.kind === "trackB") continue;
    const name = card.title.split(" — ")[0];
    groups.set(name, (groups.get(name) ?? 0) + 1);
  }
  return [...groups.entries()]
    .slice(0, 3)
    .map(([name, count]) => `${name} ${count}건`)
    .join(" · ");
}

/** 원문에서 "유지해야 할 고지"로 표시되는 구간 수. */
export function keepNoticeCount(result: ReviewOutput): number {
  return new Set(
    (result.disclosure_links ?? []).map((link) => link.disclosure_text || link.evidence || "").filter(Boolean),
  ).size;
}

// ---------------------------------------------------------------------------
// Product fact helpers
// ---------------------------------------------------------------------------

export function productFactSummary(result: ReviewOutput): Record<string, number> {
  const summary: Record<string, number> = {};
  for (const item of result.product_fact_context?.comparison_results ?? []) {
    const status = item.status || "UNKNOWN";
    summary[status] = (summary[status] ?? 0) + 1;
  }
  return summary;
}

export function productClaimFactsForAnchor(result: ReviewOutput, anchor: ContextAnchor): ClaimFact[] {
  return (result.product_fact_context?.claim_facts ?? []).filter((item) => item.claim_id === anchor.claim_id);
}

export function productComparisonsForClaimFact(result: ReviewOutput, claimFactId: string): ComparisonResult[] {
  return (result.product_fact_context?.comparison_results ?? []).filter(
    (item) => item.claim_fact_id === claimFactId,
  );
}

export function claimFactById(result: ReviewOutput, claimFactId: string): ClaimFact | undefined {
  return (result.product_fact_context?.claim_facts ?? []).find((item) => item.claim_fact_id === claimFactId);
}

export function productFactById(result: ReviewOutput, productFactId: string): ProductFact | undefined {
  return (result.product_fact_context?.product_facts ?? []).find((item) => item.fact_id === productFactId);
}

export function prominenceDiagnosticsForAnchor(result: ReviewOutput, anchor: ContextAnchor): ProminenceDiagnostic[] {
  const claim = claimById(result, anchor.claim_id);
  const sentenceId = claim?.sentence_id ?? "";
  return (result.prominence_diagnostics ?? []).filter(
    (item) => item.benefit_sentence_id === sentenceId || item.evidence?.includes(anchor.span.text),
  );
}

// ---------------------------------------------------------------------------
// Policy evidence chains
// ---------------------------------------------------------------------------

export function chainsForAnchor(rows: PolicyEvidenceChain[] | undefined, anchorId: string): PolicyEvidenceChain[] {
  return (rows ?? []).filter((chain) => chain.anchor_id === anchorId);
}

export function chainNodeLabel(node: Record<string, unknown> | undefined | null): string {
  if (!node) return "-";
  return String(node.title ?? node.name ?? node.label ?? node.article ?? node.id ?? JSON.stringify(node));
}

// ---------------------------------------------------------------------------
// 법령 위임 사슬 — 온톨로지 DELEGATES_TO 위계를 심사원이 읽는 형태로.
//   법률 → 시행령 → 감독규정 → 심의기준 (위임 단계)
// ---------------------------------------------------------------------------

/** node_type/role → 위임 위계 단계(낮을수록 상위 법령) + 한국어 레이어 라벨. */
export function delegationTierOf(node: ChainNode): { tier: number; layer: string } {
  const role = String(node.role ?? "");
  const type = String(node.node_type ?? "");
  const label = String(node.label ?? "");
  // 라벨에서 법령 단계 추론 (role/type가 비어도 동작하도록 fallback).
  const text = `${role} ${label}`;
  if (/심의기준|self.?regul|supervisory_standard|협회/i.test(text)) return { tier: 3, layer: "심의기준" };
  if (/감독규정|supervisory/i.test(text)) return { tier: 2, layer: "감독규정" };
  if (/시행령|enforcement_decree|decree|시행세칙/i.test(text)) return { tier: 1, layer: "시행령" };
  if (type === "SalesPrinciple" || role === "principle") return { tier: 9, layer: "판매원칙" };
  if (/법률|^법|root_article|article/i.test(text)) return { tier: 0, layer: "법률" };
  if (type === "DelegatedStandard") return { tier: 2, layer: "위임기준" };
  return { tier: 5, layer: type || "근거" };
}

export interface DelegationStep {
  layer: string; // 법률 / 시행령 / 감독규정 / 심의기준 / 판매원칙
  label: string;
  why?: string;
}

/**
 * legal_basis_chain을 법령 위임 단계 순서(법률→시행령→감독규정→심의기준)로 정렬한
 * 사슬로 변환. 판매원칙(SalesPrinciple)은 별도로 분리해 반환.
 */
export function delegationChain(chain: PolicyEvidenceChain): {
  steps: DelegationStep[];
  principles: string[];
} {
  const whyByTarget = new Map<string, string>();
  for (const edge of chain.delegation_edges ?? []) {
    if (edge.target_id && edge.why) whyByTarget.set(edge.target_id, edge.why);
    if (edge.target_node?.id && edge.why) whyByTarget.set(String(edge.target_node.id), edge.why);
  }
  const principles: string[] = [];
  const steps: DelegationStep[] = [];
  const seen = new Set<string>();
  for (const node of chain.basis_nodes ?? []) {
    const { tier, layer } = delegationTierOf(node);
    const label = chainNodeLabel(node);
    if (layer === "판매원칙") {
      if (!principles.includes(label)) principles.push(label);
      continue;
    }
    const key = `${layer}:${label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    steps.push({ layer, label, why: whyByTarget.get(String(node.id ?? "")) });
    void tier;
  }
  steps.sort((a, b) => layerTier(a.layer) - layerTier(b.layer));
  return { steps, principles };
}

function layerTier(layer: string): number {
  return { 법률: 0, 시행령: 1, 위임기준: 2, 감독규정: 2, 심의기준: 3 }[layer] ?? 5;
}

/** anchor의 FOUND legal_basis_chain들을 위임 사슬로. */
export function delegationChainsForAnchor(result: ReviewOutput, anchorId: string): {
  steps: DelegationStep[];
  principles: string[];
  summary: string;
}[] {
  return chainsForAnchor(result.policy_evidence_chains?.legal_basis_chains, anchorId)
    .filter((chain) => chain.status === "FOUND")
    .map((chain) => ({ ...delegationChain(chain), summary: String(chain.summary ?? "") }));
}

export interface PrincipleDelegation {
  principle: string;
  steps: DelegationStep[];
}

/**
 * 위임 사슬을 '판매원칙'별로 그룹핑 — 부당권유(§20)와 설명의무(§18·§14)가 한
 * 사슬에 섞이는 오염을 막는다. 각 원칙 아래 법률→시행령→감독규정→심의기준 단계.
 */
export function delegationByPrinciple(result: ReviewOutput, anchorId: string): PrincipleDelegation[] {
  const chains = delegationChainsForAnchor(result, anchorId);
  const byPrinciple = new Map<string, DelegationStep[]>();
  for (const chain of chains) {
    const principle = chain.principles[0] ?? "근거";
    const bucket = byPrinciple.get(principle) ?? [];
    byPrinciple.set(principle, [...bucket, ...chain.steps]);
  }
  return [...byPrinciple.entries()].map(([principle, steps]) => ({
    principle,
    steps: sortDelegationStepsLocal(steps),
  }));
}

function sortDelegationStepsLocal(steps: DelegationStep[]): DelegationStep[] {
  const order = ["법률", "시행령", "위임기준", "감독규정", "심의기준"];
  const seen = new Set<string>();
  return steps
    .filter((s) => {
      const key = `${s.layer}:${s.label}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => {
      const ai = order.indexOf(a.layer);
      const bi = order.indexOf(b.layer);
      return (ai < 0 ? 9 : ai) - (bi < 0 ? 9 : bi);
    });
}

/** anchor의 모든 조문 원문(중복 제거, 난수 id 제외) — 조문 드릴다운용. */
export function clauseEvidenceForAnchor(result: ReviewOutput, anchorId: string): {
  article: string;
  principle: string;
  constraint: string;
  texts: string[];
}[] {
  const plans = planItemsForAnchor(result, anchorId);
  const byArticle = new Map<string, { article: string; principle: string; constraint: string; texts: Set<string> }>();
  for (const item of plans) {
    const article = item.source_article || "근거 조항";
    const entry = byArticle.get(article) ?? {
      article,
      principle: item.principle ?? "",
      constraint: item.constraint ?? item.context ?? "",
      texts: new Set<string>(),
    };
    for (const text of item.evidence_texts ?? []) if (text) entry.texts.add(text);
    byArticle.set(article, entry);
  }
  return [...byArticle.values()].map((e) => ({
    article: e.article,
    principle: e.principle,
    constraint: e.constraint,
    texts: [...e.texts],
  }));
}

/** 조항/원칙 집계 행을 anchor의 문구로 필터. */
export function aggregationForAnchor(result: ReviewOutput, anchor: ContextAnchor): AggregationRow[] {
  const inAnchor = (rows: AggregationRow[]) =>
    rows.filter((row) => (row.anchor_spans ?? []).includes(anchor.span.text));
  const articles = inAnchor(result.article_aggregation ?? []);
  const principles = inAnchor(result.principle_aggregation ?? []).filter(
    (row) => !articles.some((a) => a.key === row.key),
  );
  return [...articles, ...principles];
}
