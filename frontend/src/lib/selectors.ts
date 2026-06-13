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
// Issue cards — the right-hand evidence panel read model.
// One compact card per actionable finding; deep evidence stays in tabs.
// ---------------------------------------------------------------------------

export interface IssueCardModel {
  id: string;
  /** 화면용 순번 코드 (C1, C2 … / 고지 D1 … / Track B). 내부 해시 id 대체. */
  code: string;
  kind: "anchor" | "disclosure" | "trackB";
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
    const quote = qualifiers[0]?.text || anchor.span.text;
    const basis = [basisSummary(result, anchor.anchor_id), issues[0]?.risk_title]
      .filter(Boolean)
      .join(" · ");
    const risky = effective.filter((item) => ["NON_COMPLIANT", "INSUFFICIENT"].includes(item.verdict));
    const card: IssueCardModel = {
      id: anchor.anchor_id,
      code: "",
      kind: "anchor",
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
      tone: "review",
      label: "필수 고지 누락",
      quote: check.label,
      title: `필수 고지 누락 — ${check.label}`,
      basis: String(requirement?.source ?? "은행 광고심의 기준"),
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
      tone: score >= 0.7 ? "risk" : score >= 0.4 ? "review" : "keep",
      label: "소비자 오인 (Track B)",
      quote: `오인 위험 ${gradeLabel}`,
      title: `소비자 오인 (Track B) — 오인 위험 ${gradeLabel}`,
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
      name: "전체 인상 (Track B)",
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
