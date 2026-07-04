"use client";

import {
  principleColor,
  verdictBadgeTone,
  VERDICT_LABELS,
  abbreviateLawNames,
  HUMAN_ACTION_LABELS,
  HUMAN_FEATURE_LABELS,
  QUALIFIER_LABELS,
} from "@/lib/labels";
import {
  useLocale,
  tr,
  verdictLabel,
  principleDisplay,
  dataTitleDisplay,
  HUMAN_ACTION_LABELS_EN,
  HUMAN_FEATURE_LABELS_EN,
  QUALIFIER_LABELS_EN,
  JUDGMENT_STATUS_EN,
  type Locale,
} from "@/lib/i18n";
import {
  buildEvidencePath,
  buildIssueCards,
  delegationChain,
  judgmentsForAnchor,
  planItemsForAnchor,
  type EvidenceNodeKind,
} from "@/lib/selectors";
import type { FinalVerdict, LLMJudgment, ReviewOutput } from "@/lib/types";
import { Icon } from "../Icon";
import { EmptyState, Tag } from "../ui";
import { DelegationChain } from "./DelegationChain";
import { PaneHeader } from "./common";
import { TONE_BG, TONE_COLOR, TONE_WORD_SHORT } from "./RiskList";

interface Props {
  result: ReviewOutput | null;
  selectedAnchorId: string;
  onSelectAnchor: (anchorId: string) => void;
}

/** 해설 문장 칩 색 — 경로 해설에서 재사용. */
const NODE_META: Record<EvidenceNodeKind, { color: string }> = {
  claim: { color: "var(--reject)" },
  risk: { color: "#e0701a" },
  policy: { color: "#a07200" },
  cu: { color: "var(--brand)" },
  premise: { color: "#7c5cde" },
  clause: { color: "var(--pass)" },
};

/** 개별 판정 verdict → 심사 실무 언어·색. */
const JUDGMENT_LABEL: Record<string, { word: string; color: string }> = {
  NON_COMPLIANT: { word: "위반 의심", color: "var(--reject)" },
  INSUFFICIENT: { word: "검토 필요", color: "var(--revise)" },
  COMPLIANT: { word: "적합", color: "var(--pass)" },
  NOT_APPLICABLE: { word: "해당 없음", color: "var(--ink-4)" },
};

/** 개별 판정 단어 — en 로케일에서는 i18n 의 판정 상태 EN 맵으로 분기. */
function judgmentWord(locale: Locale, verdict: string, koWord: string): string {
  return locale === "en" ? (JUDGMENT_STATUS_EN[verdict] ?? koWord) : koWord;
}

/** RiskList 의 톤 단어(한국어)와 짝을 이루는 EN 표시 — 렌더 지점에서만 분기. */
const TONE_WORD_SHORT_EN: Record<string, string> = {
  risk: "Suspected violation",
  review: "Review required",
  "keep-warning": "Low prominence",
  keep: "Disclosure",
  scope: "Scope",
};

function toneWordShort(locale: Locale, tone: keyof typeof TONE_WORD_SHORT): string {
  return locale === "en" ? (TONE_WORD_SHORT_EN[tone] ?? TONE_WORD_SHORT[tone]) : TONE_WORD_SHORT[tone];
}

/** selectors 가 만들어 주는 위험 라벨(한국어 값) → EN 표시 역매핑. */
const RISK_LABEL_EN: Record<string, string> = {
  "위반 의심": "Suspected violation",
  "검토 필요": "Review required",
  "위험 표현": "Risky wording",
  "유지 고지": "Keep disclosure",
  검토됨: "Reviewed",
};
for (const [koMap, enMap] of [
  [HUMAN_ACTION_LABELS, HUMAN_ACTION_LABELS_EN],
  [HUMAN_FEATURE_LABELS, HUMAN_FEATURE_LABELS_EN],
  [QUALIFIER_LABELS, QUALIFIER_LABELS_EN],
] as const) {
  for (const [key, ko] of Object.entries(koMap)) {
    if (enMap[key]) RISK_LABEL_EN[ko] = enMap[key];
  }
}

function riskLabelDisplay(locale: Locale, label: string): string {
  if (locale !== "en") return label;
  return RISK_LABEL_EN[label] ?? dataTitleDisplay(locale, label);
}

const FINAL_TONE_BG: Record<string, string> = {
  pass: "linear-gradient(150deg,#0a7550,#0a5f42)",
  review: "linear-gradient(150deg,#2760d8,#1d4bb0)",
  revise: "linear-gradient(150deg,#a86a00,#8a5700)",
  reject: "linear-gradient(150deg,#c2372c,#9e2c23)",
};

/** 한 지점 ↔ N개 브랜치 사이 부챗살 엣지. invert=true 면 N→1 수렴. */
function FanEdges({ n, invert }: { n: number; invert?: boolean }) {
  if (n <= 0) return null;
  const H = 34;
  return (
    <svg viewBox={`0 0 1000 ${H}`} preserveAspectRatio="none" className="block h-8 w-full" aria-hidden>
      {Array.from({ length: n }, (_, i) => {
        const cx = ((i + 0.5) / n) * 1000;
        const d = invert
          ? `M ${cx} 0 C ${cx} ${H * 0.55}, 500 ${H * 0.45}, 500 ${H}`
          : `M 500 0 C 500 ${H * 0.45}, ${cx} ${H * 0.55}, ${cx} ${H}`;
        return <path key={i} d={d} fill="none" stroke="var(--line-2)" strokeWidth={2} vectorEffect="non-scaling-stroke" />;
      })}
    </svg>
  );
}

/** 연결 근거 원문 정제 — 그래프 노드 메타데이터(적재 일자 스탬프·플래그·중복
 * 항 마커·번호 접두)를 걷어내 심사자가 읽을 문장만 남긴다. */
function cleanEvidenceText(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .replace(/^\d+\s*조문\s*/, "") // "20 조문 " 적재 인덱스 접두
    .replace(/\b20\d{6}\b/g, "") // 20260428 같은 적재 일자 스탬프
    .replace(/\s[NY]\s/g, " ") // 플래그 컬럼 잔재
    .replace(/^\d+\.\s*/, "") // "5. " 항목 번호 접두
    .replace(/([①-⑮])\s*\1/g, "$1") // 중복 항 마커 "① ①"
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** 정제 후 사실상 같은 문장(앞 40자 기준) 제거 — 같은 조문이 청크로 중복 적재된 경우. */
function dedupeEvidence(texts: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of texts) {
    const cleaned = cleanEvidenceText(raw);
    if (!cleaned) continue;
    const key = cleaned.slice(0, 40);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(cleaned);
  }
  return out;
}

/** 브랜치 내부 세로 커넥터(미니). */
function BranchLink({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center py-0.5" aria-hidden>
      <span className="h-2.5 w-0.5 bg-line-2" />
      {label && <span className="my-0.5 text-[11px] font-bold text-ink-4">{label}</span>}
      <span className="h-2.5 w-0.5 bg-line-2" />
    </div>
  );
}

/** 레이어 컨테이너 — 좌측 세로 라벨 + 내용. 계층이 위→아래로 읽히게 한다. */
function Layer({ no, title, sub, children }: { no: string; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[13px] border border-line bg-surface-2 px-4 py-3.5">
      <div className="mb-2.5 flex items-baseline gap-2">
        <span className="font-mono text-[11px] font-bold text-ink-4">{no}</span>
        <span className="text-[12px] font-extrabold tracking-wide text-ink-2 uppercase">{title}</span>
        {sub && <span className="text-[11px] text-ink-4">{sub}</span>}
      </div>
      {children}
    </section>
  );
}

export function GraphView({ result, selectedAnchorId, onSelectAnchor }: Props) {
  const locale = useLocale();
  if (!result) {
    return (
      <EmptyState>
        {tr(locale, "Review를 실행하면 근거 경로 그래프가 표시됩니다.", "Run a review to see the evidence path graph.")}
      </EmptyState>
    );
  }
  const anchorCards = buildIssueCards(result, locale).filter((card) => card.kind === "anchor" && card.anchorId);
  const activeId =
    anchorCards.find((card) => card.anchorId === selectedAnchorId)?.anchorId ?? anchorCards[0]?.anchorId ?? "";
  const path = activeId ? buildEvidencePath(result, activeId) : null;

  if (!path) {
    return (
      <EmptyState>
        {tr(locale, "경로를 추적할 Claim anchor가 없습니다.", "No claim anchor available to trace.")}
      </EmptyState>
    );
  }

  const activeCard = anchorCards.find((card) => card.anchorId === activeId);
  const anchor = result.context_anchors?.find((item) => item.anchor_id === activeId);
  const hypernyms = (anchor?.hypernyms ?? []).slice(0, 4);
  const plans = planItemsForAnchor(result, activeId);
  const judgments = judgmentsForAnchor(result, activeId);
  const judgmentByPlan = new Map<string, LLMJudgment>(judgments.map((j) => [j.plan_item_id, j]));
  const finalVerdict = (result.final_verdict ?? "needs_review") as FinalVerdict;
  const finalTone = verdictBadgeTone(finalVerdict);
  const verdictCounts = judgments.reduce<Record<string, number>>((acc, j) => {
    acc[j.verdict] = (acc[j.verdict] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="grid h-full gap-4" style={{ gridTemplateColumns: "248px minmax(0,1fr)" }}>
      {/* 좌: claim 선택 */}
      <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
        <div className="border-b border-line px-4 py-3.5">
          <div className="text-[11px] font-bold tracking-wider text-ink-4 uppercase">
            {tr(locale, "설명 경로 선택", "Select explanation path")}
          </div>
          <div className="mt-1 text-[12.5px] text-ink-3">
            {tr(locale, "Claim을 선택해 근거 경로를 추적합니다.", "Select a claim to trace its evidence path.")}
          </div>
        </div>
        <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-2.5">
          {anchorCards.map((card) => {
            const selected = card.anchorId === activeId;
            const color = TONE_COLOR[card.tone];
            return (
              <button
                key={card.id}
                type="button"
                onClick={() => card.anchorId && onSelectAnchor(card.anchorId)}
                className="rounded-[9px] px-2.5 py-2.5 text-left"
                style={{
                  border: selected ? `1.5px solid ${color}` : "1px solid var(--line)",
                  background: selected ? TONE_BG[card.tone] : "var(--surface)",
                }}
              >
                <div className="mb-1 flex items-center gap-1.5">
                  <span className="font-mono text-[11px] font-bold text-ink-4">{card.code}</span>
                  <span className="ml-auto h-1.5 w-1.5 rounded-full" style={{ background: color }} />
                </div>
                <div className="text-[12.5px] leading-snug font-semibold break-keep text-ink">“{card.quote}”</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 우: 계층형 근거 경로 — Context Graph → 심의 기준 → 법령 위임 사슬 → 판정.
          변호사의 추론 순서 그대로 위에서 아래로 읽힌다(평탄한 가로 체인 폐기). */}
      <div className="flex min-h-0 flex-col overflow-hidden rounded-[14px] border border-line bg-surface shadow-card">
        <PaneHeader
          icon="graph"
          title={tr(locale, "근거 경로", "Evidence path")}
          sub={`${activeCard?.code ?? ""} · ${tr(locale, "광고 표현 → 법령 위임 사슬 → 판정", "Ad expression → Legal delegation chain → Verdict")}`}
          right={
            <span
              className="rounded-full px-2 py-0.5 text-[11px] font-bold"
              style={{ color: TONE_COLOR[path.tone], background: TONE_BG[path.tone] }}
            >
              {toneWordShort(locale, path.tone)}
            </span>
          }
        />
        <div className="flex-1 overflow-y-auto px-5 py-5">
          {/* ① Context Graph — 광고 표현과 그 의미(위험 유형·정책어 정규화) */}
          <Layer
            no="①"
            title="Context Graph"
            sub={tr(locale, "광고 표현 · 위험 분류 · 정책어 정규화", "Ad expression · Risk classification · Policy term normalization")}
          >
            <div className="rounded-[11px] border bg-surface p-3" style={{ borderColor: "color-mix(in srgb, var(--reject) 35%, var(--line))" }}>
              <div className="text-[14px] leading-snug font-bold break-keep text-ink">“{path.quote}”</div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="rounded-md px-2 py-0.5 text-[11px] font-bold" style={{ color: "#b45309", background: "#fdf3e3" }}>
                  {tr(locale, "위험 유형", "Risk type")} · {riskLabelDisplay(locale, path.riskLabel)}
                </span>
                {hypernyms.map((h) => (
                  <span
                    key={h.proposal_id}
                    className="rounded-md bg-surface-3 px-2 py-0.5 text-[11px] font-semibold text-ink-2"
                    title={tr(
                      locale,
                      `정책어 정규화 (confidence ${(h.confidence * 100).toFixed(0)}%)`,
                      `Policy term normalization (confidence ${(h.confidence * 100).toFixed(0)}%)`,
                    )}
                  >
                    {h.hypernym}
                    {h.support === "STRONG" ? " ●" : ""}
                  </span>
                ))}
              </div>
            </div>
          </Layer>

          {/* ② CU Plan 브랜치 — 논문(GraphCompliance Fig.2)의 anchor → CU Plan fan-out.
              각 CU 가 자기 조문·위임 사슬을 따로 갖는다는 사실을 브랜치(가지)로 표현:
              CU 카드 → 그 CU 의 위임 사슬 → 그 CU 의 개별 판정 (ŷ, s). */}
          <div className="flex flex-col items-center pt-1">
            <span className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-[11px] font-bold text-ink-3">
              {tr(
                locale,
                `grounding — 심의 기준 ${plans.length}건, 각자 다른 근거 법령으로`,
                `grounding — ${plans.length} review criteria, each with its own legal basis`,
              )}
            </span>
          </div>
          <FanEdges n={plans.length} />
          <div className="overflow-x-auto">
            <div
              className="grid items-stretch gap-3"
              style={{ gridTemplateColumns: `repeat(${Math.max(plans.length, 1)}, minmax(240px, 1fr))`, minWidth: plans.length * 252 }}
            >
              {plans.map((item) => {
                const judgment = judgmentByPlan.get(item.plan_item_id);
                const meta = judgment ? JUDGMENT_LABEL[judgment.verdict] : null;
                // 이 CU 전용 위임 사슬 — 체인 행이 plan_item_id 를 들고 있다.
                const chain = (result.policy_evidence_chains?.legal_basis_chains ?? []).find(
                  (row) => String(row["plan_item_id"] ?? "") === item.plan_item_id && row.status === "FOUND",
                );
                const deleg = chain ? delegationChain(chain) : null;
                return (
                  <div key={item.plan_item_id} className="flex min-w-0 flex-col">
                    {/* CU 노드 — 논문의 4-tuple(subject·constraint) 요약 */}
                    <div
                      className="flex flex-col gap-1.5 rounded-[11px] border-2 bg-surface p-3"
                      style={{ borderColor: meta ? `color-mix(in srgb, ${meta.color} 45%, var(--line))` : "var(--line)" }}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-[11px] font-bold text-ink-4">CU</span>
                        {item.principle && (
                          <Tag color={principleColor(item.principle)}>{principleDisplay(locale, item.principle)}</Tag>
                        )}
                      </div>
                      <div className="line-clamp-2 text-[12.5px] leading-snug font-semibold break-keep text-ink">
                        {dataTitleDisplay(locale, item.risk_title || item.constraint || item.subject)}
                      </div>
                      {item.subject && item.constraint && (
                        <div className="line-clamp-2 text-[11px] leading-relaxed text-ink-3">
                          {dataTitleDisplay(locale, item.subject)} · {dataTitleDisplay(locale, item.constraint)}
                        </div>
                      )}
                    </div>
                    <BranchLink label={tr(locale, "대표 근거 경로", "Representative evidence path")} />
                    {/* 이 CU 의 법령 위임 사슬 — CU는 여러 조문·심의기준 원문과 연결되지만
                        (전부 판정 증거창에 투입), 사슬 요약은 CU가 형식화된 모(母)조문
                        기준의 대표 경로다. 나머지 연결 근거는 아래 접이식으로 공개. */}
                    <div className="flex-1 rounded-[11px] border border-line bg-surface px-3.5 py-3">
                      <div
                        className="mb-2 flex items-center gap-1 text-[11px] font-bold text-ink-4"
                        title={tr(
                          locale,
                          "이 CU가 형식화된 원천(모조문)을 뿌리로 한 위임 경로입니다. CU에 연결된 다른 조문·심의기준 원문도 판정 증거로 함께 투입됩니다.",
                          "Delegation path rooted at the parent article this CU was formalized from. Other clauses and guideline texts linked to this CU are also fed in as judgment evidence.",
                        )}
                      >
                        {tr(locale, "대표 근거 경로", "Representative evidence path")}{" "}
                        <span className="font-normal">· {tr(locale, "모조문 기준", "based on parent article")}</span>
                      </div>
                      {deleg && deleg.steps.length > 0 ? (
                        <DelegationChain steps={deleg.steps} />
                      ) : (
                        <div className="text-[11.5px] leading-relaxed text-ink-3">
                          <span className="mr-1.5 inline-block rounded bg-surface-3 px-1.5 py-0.5 text-[11px] font-bold text-ink-2">
                            {tr(locale, "조문", "Clause")}
                          </span>
                          {abbreviateLawNames(item.source_article) ||
                            tr(locale, "근거 조문 확인 필요", "Source clause needs confirmation")}
                        </div>
                      )}
                      {(() => {
                        // 적재 메타데이터 정제 + 중복 청크 제거 후 표시.
                        const evidence = dedupeEvidence(item.evidence_texts ?? []);
                        if (evidence.length === 0) return null;
                        return (
                          <details className="mt-2 border-t border-line pt-2">
                            <summary className="cursor-pointer text-[11px] font-bold text-ink-3 select-none">
                              {tr(locale, `연결 근거 ${evidence.length}건`, `${evidence.length} linked evidence items`)}
                              {judgment?.used_policy_evidence?.length
                                ? tr(
                                    locale,
                                    ` · 판정 인용 ${judgment.used_policy_evidence.length}건`,
                                    ` · ${judgment.used_policy_evidence.length} cited in judgment`,
                                  )
                                : ""}
                              <span className="ml-1 font-normal text-ink-4">
                                {tr(locale, "— 전부 판정 증거로 투입됨", "— all fed in as judgment evidence")}
                              </span>
                            </summary>
                            <ul className="mt-1.5 space-y-1 pl-0.5">
                              {evidence.slice(0, 4).map((text, i) => (
                                <li key={i} className="line-clamp-2 text-[11px] leading-relaxed text-ink-3" title={text}>
                                  · {abbreviateLawNames(text)}
                                </li>
                              ))}
                              {evidence.length > 4 && (
                                <li className="text-[11px] text-ink-4">
                                  {tr(
                                    locale,
                                    `외 ${evidence.length - 4}건 — 판정 상세에서 확인`,
                                    `${evidence.length - 4} more — see judgment details`,
                                  )}
                                </li>
                              )}
                            </ul>
                          </details>
                        );
                      })()}
                    </div>
                    <BranchLink label={tr(locale, "판정", "Verdict")} />
                    {/* 이 CU 의 개별 판정 (ŷ, s) */}
                    <div
                      className="rounded-[11px] px-3 py-2 text-center text-[12.5px] font-bold"
                      style={{
                        color: meta?.color ?? "var(--ink-4)",
                        background: meta ? `color-mix(in srgb, ${meta.color} 10%, white)` : "var(--surface-2)",
                        border: `1px solid ${meta ? `color-mix(in srgb, ${meta.color} 35%, var(--line))` : "var(--line)"}`,
                      }}
                    >
                      {meta && judgment ? judgmentWord(locale, judgment.verdict, meta.word) : tr(locale, "판정 없음", "No judgment")}
                      {judgment && judgment.verdict !== "NOT_APPLICABLE"
                        ? tr(
                            locale,
                            ` · 위반 가능성 ${(judgment.score * 100).toFixed(0)}%`,
                            ` · violation likelihood ${(judgment.score * 100).toFixed(0)}%`,
                          )
                        : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          <FanEdges n={plans.length} invert />
          <div className="flex flex-col items-center pb-1">
            <span className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-[11px] font-bold text-ink-3">
              {tr(
                locale,
                "판정 종합 — 기준별 판정이 최종 결과로 수렴",
                "Verdict aggregation — per-criterion judgments converge to the final result",
              )}
            </span>
          </div>

          {/* ③ 최종 결과 — 수렴 노드 */}
          <Layer
            no="③"
            title={tr(locale, "최종 결과", "Final result")}
            sub={tr(locale, "이 표현의 판정 집계 → 광고 전체 판정", "Judgment aggregation for this expression → verdict for the whole ad")}
          >
            <div className="flex flex-wrap items-stretch gap-3">
              <div className="min-w-[200px] flex-1 rounded-[11px] border border-line bg-surface p-3">
                <div className="mb-1.5 text-[11px] font-bold text-ink-4">
                  {tr(locale, "이 표현의 개별 판정", "Individual judgments for this expression")}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(verdictCounts).map(([verdict, count]) => {
                    const meta = JUDGMENT_LABEL[verdict];
                    if (!meta) return null;
                    return (
                      <span
                        key={verdict}
                        className="rounded-md px-2 py-1 text-[12px] font-bold"
                        style={{ color: meta.color, background: `color-mix(in srgb, ${meta.color} 10%, white)` }}
                      >
                        {tr(locale, `${meta.word} ${count}건`, `${judgmentWord(locale, verdict, meta.word)} × ${count}`)}
                      </span>
                    );
                  })}
                  {judgments.length === 0 && (
                    <span className="text-[12px] text-ink-4">
                      {tr(locale, "판정 없음 — 심사자 확인 필요", "No judgment — reviewer confirmation required")}
                    </span>
                  )}
                </div>
                {path.disclosure && (
                  <div className="mt-2 border-t border-line pt-2 text-[11.5px] leading-relaxed text-ink-3">
                    <b className="text-ink-2">{tr(locale, "필요 고지/예외", "Required disclosures / exceptions")}</b> ·{" "}
                    {dataTitleDisplay(locale, path.disclosure)}
                  </div>
                )}
              </div>
              <div
                className="flex min-w-[190px] flex-col justify-center gap-1 rounded-[11px] px-4 py-3 text-white"
                style={{ background: FINAL_TONE_BG[finalTone] }}
              >
                <div className="text-[11px] font-bold tracking-wider uppercase opacity-85">
                  {tr(locale, "최종 결과 · 광고 전체", "Final result · Whole ad")}
                </div>
                <div className="text-[18px] font-extrabold">
                  {verdictLabel(locale, finalVerdict, VERDICT_LABELS)?.[0] ?? finalVerdict}
                </div>
                <div className="text-[11px] opacity-85">
                  {tr(
                    locale,
                    "이 표현을 포함한 전체 판정의 종합 — 최종 승인은 심사자",
                    "Aggregate of all judgments including this expression — final approval rests with the reviewer",
                  )}
                </div>
              </div>
            </div>
          </Layer>

          {/* 자연어 해설 */}
          <div className="mt-5">
            <div className="mb-2.5 text-[11px] font-bold tracking-wider text-ink-4 uppercase">
              {tr(locale, "경로 해설", "Path explanation")}
            </div>
            <div className="rounded-[12px] border border-line bg-surface-2 px-4.5 py-4">
              {locale === "en" ? (
                <p className="m-0 text-[13.5px] leading-[1.75] text-ink-2">
                  The ad expression <b className="text-ink">“{path.quote}”</b> was classified as a{" "}
                  <b style={{ color: NODE_META.risk.color }}>{riskLabelDisplay(locale, path.riskLabel)}</b> risk
                  {hypernyms.length > 0 ? (
                    <>
                      {" "}and, through the policy term <b style={{ color: NODE_META.policy.color }}>{hypernyms[0].hypernym}</b>
                      {hypernyms.length > 1 ? ` and ${hypernyms.length - 1} more` : ""},
                    </>
                  ) : null}{" "}
                  {path.cuName ? (
                    <>
                      was linked to the review criterion{" "}
                      <b style={{ color: NODE_META.cu.color }}>{dataTitleDisplay(locale, path.cuName)}</b>
                      {plans.length > 1 ? ` and ${plans.length - 1} more` : ""}.{" "}
                    </>
                  ) : (
                    <>has no linked review criterion yet, so further review is required. </>
                  )}
                  {path.articles.length > 0 ? (
                    <>
                      The legal basis is{" "}
                      <b style={{ color: NODE_META.clause.color }}>{abbreviateLawNames(path.articles.join(", "))}</b>, applied along
                      the delegation chain,{" "}
                    </>
                  ) : null}
                  and it contributed to the final{" "}
                  <b style={{ color: TONE_COLOR[path.tone] }}>{toneWordShort(locale, path.tone)}</b> assessment.{" "}
                  <span className="text-ink-4">— AI recommendation; the final decision follows reviewer review.</span>
                </p>
              ) : (
                <p className="m-0 text-[13.5px] leading-[1.75] text-ink-2">
                  광고 표현 <b className="text-ink">“{path.quote}”</b> 은(는){" "}
                  <b style={{ color: NODE_META.risk.color }}>{path.riskLabel}</b> 위험으로 분류되어,{" "}
                  {hypernyms.length > 0 ? (
                    <>
                      정책어 <b style={{ color: NODE_META.policy.color }}>{hypernyms[0].hypernym}</b>
                      {hypernyms.length > 1 ? ` 외 ${hypernyms.length - 1}건` : ""}을 통해{" "}
                    </>
                  ) : null}
                  {path.cuName ? (
                    <>
                      심의 기준 <b style={{ color: NODE_META.cu.color }}>{path.cuName}</b>
                      {plans.length > 1 ? ` 외 ${plans.length - 1}건` : ""}에 연결되었습니다.{" "}
                    </>
                  ) : (
                    <>관련 심의 기준이 아직 연결되지 않아 검토가 필요합니다. </>
                  )}
                  {path.articles.length > 0 ? (
                    <>
                      법적 근거는 <b style={{ color: NODE_META.clause.color }}>{abbreviateLawNames(path.articles.join(", "))}</b> 이며,
                      위임 사슬을 따라 적용되어{" "}
                    </>
                  ) : null}
                  최종적으로 <b style={{ color: TONE_COLOR[path.tone] }}>{TONE_WORD_SHORT[path.tone]}</b> 판정에 기여했습니다.{" "}
                  <span className="text-ink-4">— AI 권고이며 최종 판단은 심사자 검토를 따릅니다.</span>
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
