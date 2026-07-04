/**
 * 수정안 unified diff — GitHub 코드리뷰 문법으로 원문↔교정안을 한 화면에.
 *
 * 줄 단위 `-`(위험 문구 삭제) / `+`(교정 문안 추가) 쌍으로 만들고, 각 줄에
 * hover 용 메타(위험 이유·수정 이유·근거 조문·anchor 연결)를 붙인다.
 * 두 경로:
 *  A. 개별 span 수정만 있을 때 — 원문 줄에서 수정 대상 span 을 치환한 쌍 생성
 *  B. 백엔드 전체 일관 교정본(correctedDocument)이 있을 때 — 문장 단위 LCS diff
 * 공통으로 누락 필수 고지 블록은 문서 끝에 `+` 줄로 붙는다.
 */
import {
  alignSpan,
  buildIssueCards,
  correctedDisclosureBlock,
  correctedDocument,
  requiredDisclosureSlots,
  revisionFor,
} from "./selectors";
import type { ReviewOutput } from "./types";

export interface RevisionDiffLine {
  type: "context" | "del" | "add";
  text: string;
  /** 판정 상세로 연결되는 anchor (클릭 시 선택). */
  anchorId?: string;
  /** del=위험 이유, add=수정 이유. */
  reason?: string;
  /** 근거 조문 요약. */
  basis?: string;
  /** 위반 유형 라벨 (예: 단정·보장 표현). */
  label?: string;
  /** 줄 내부 강조(intra-line) — strong=실제 바뀐 단어 구간 (GitHub word diff). */
  segments?: { text: string; strong: boolean }[];
}

export interface RevisionDiff {
  lines: RevisionDiffLine[];
  /** 본문 del/add 쌍 수 (고지 추가 제외). */
  changedCount: number;
  /** 하단에 추가된 필수 고지 줄 수. */
  disclosureAddCount: number;
}

interface RevisionMeta {
  anchorId: string;
  start: number;
  end: number;
  after: string;
  riskReason: string;
  fixReason: string;
  basis: string;
  label: string;
}

/** anchor 카드에서 diff 메타(수정안 + 이유 + 근거)를 수집한다. */
function collectRevisions(result: ReviewOutput, text: string): RevisionMeta[] {
  const cards = buildIssueCards(result).filter((card) => card.kind === "anchor" && card.anchorId);
  const spans: RevisionMeta[] = [];
  for (const card of cards) {
    const anchorId = card.anchorId!;
    const revision = revisionFor(result, anchorId);
    if (!revision) continue;
    const anchor = result.context_anchors?.find((item) => item.anchor_id === anchorId);
    if (!anchor) continue;
    const aligned = alignSpan(text, anchor.span);
    if (!Number.isInteger(aligned.start) || aligned.start < 0 || aligned.end <= aligned.start || aligned.end > text.length) {
      continue;
    }
    spans.push({
      anchorId,
      start: aligned.start,
      end: aligned.end,
      after: revision.after,
      riskReason: revision.why_problematic || card.rationale || "",
      fixReason: revision.notes_for_reviewer || revision.why_problematic || card.rationale || "",
      basis: card.basis,
      label: card.label,
    });
  }
  // 겹치는 span 은 앞선 것만 (buildCorrectedCopy 와 동일 규칙)
  spans.sort((a, b) => a.start - b.start);
  const merged: RevisionMeta[] = [];
  let lastEnd = -1;
  for (const span of spans) {
    if (span.start >= lastEnd) {
      merged.push(span);
      lastEnd = span.end;
    }
  }
  return merged;
}

/** 경로 A — 원문 줄 단위로 span 치환 del/add 쌍 생성. */
function diffFromSpans(text: string, revisions: RevisionMeta[]): { lines: RevisionDiffLine[]; changedCount: number } {
  const lines: RevisionDiffLine[] = [];
  let changedCount = 0;
  let cursor = 0;
  const rawLines = text.split("\n");
  for (const raw of rawLines) {
    const lineStart = cursor;
    const lineEnd = cursor + raw.length;
    cursor = lineEnd + 1; // '\n'
    const trimmed = raw.trim();
    const hits = revisions.filter((span) => span.start < lineEnd && span.end > lineStart);
    if (!hits.length || !trimmed) {
      lines.push({ type: "context", text: raw });
      continue;
    }
    // del: 원문 줄 그대로 / add: 줄 안의 span 을 after 로 치환.
    // segments 로 '실제 바뀐 단어 구간'을 함께 실어 GitHub word-diff 처럼 강조한다.
    let after = "";
    const delSegments: { text: string; strong: boolean }[] = [];
    const addSegments: { text: string; strong: boolean }[] = [];
    let localCursor = lineStart;
    for (const hit of hits) {
      const s = Math.max(hit.start, lineStart);
      const e = Math.min(hit.end, lineEnd);
      const before = text.slice(localCursor, s);
      if (before) {
        delSegments.push({ text: before, strong: false });
        addSegments.push({ text: before, strong: false });
      }
      delSegments.push({ text: text.slice(s, e), strong: true });
      addSegments.push({ text: hit.after, strong: true });
      after += before + hit.after;
      localCursor = e;
    }
    const tail = text.slice(localCursor, lineEnd);
    if (tail) {
      delSegments.push({ text: tail, strong: false });
      addSegments.push({ text: tail, strong: false });
    }
    after += tail;
    const first = hits[0];
    changedCount += 1;
    lines.push({ type: "del", text: raw, segments: delSegments, anchorId: first.anchorId, reason: first.riskReason, basis: first.basis, label: first.label });
    lines.push({ type: "add", text: after, segments: addSegments, anchorId: first.anchorId, reason: first.fixReason, basis: first.basis, label: first.label });
  }
  // 여러 원문 줄이 같은 교정문 하나로 합쳐질 때(문단 재작성) 중복 `+` 를 접는다.
  const collapsed = collapseRepeatedAdds(lines);
  return { lines: collapsed.lines, changedCount: changedCount - collapsed.removedPairs };
}

/**
 * 백엔드가 한 문단을 재작성하면서 그 문단에 속한 여러 anchor 에 '같은 교정문
 * 전체'를 after 로 넣으면(또는 한 span 이 여러 줄을 덮으면), diffFromSpans 는
 * 원문 줄마다 동일한 after 로 치환해 `+` 줄이 반복된다. 인접한 del/add 쌍에서
 * add 텍스트가 같으면 "여러 del(취소선) → 교정문 한 줄"로 병합한다(GitHub N→1).
 * removedPairs 로 접힌 쌍 수를 돌려주어 changedCount 를 논리적 변경 1건으로 보정.
 */
function collapseRepeatedAdds(lines: RevisionDiffLine[]): { lines: RevisionDiffLine[]; removedPairs: number } {
  const out: RevisionDiffLine[] = [];
  let removedPairs = 0;
  let i = 0;
  while (i < lines.length) {
    if (lines[i]?.type === "del" && lines[i + 1]?.type === "add") {
      const addKey = normalize(lines[i + 1].text);
      const dels: RevisionDiffLine[] = [lines[i]];
      const survivingAdd = lines[i + 1];
      let j = i + 2;
      while (
        addKey.length > 0 &&
        lines[j]?.type === "del" &&
        lines[j + 1]?.type === "add" &&
        normalize(lines[j + 1].text) === addKey
      ) {
        dels.push(lines[j]);
        removedPairs += 1; // 이 add 는 앞 add 와 동일 — 버린다.
        j += 2;
      }
      if (dels.length > 1) {
        for (const del of dels) out.push(del);
        // 병합된 교정문은 통문장 재작성이라 line1 기준 intra-line 강조가 오히려
        // 오해를 부른다 — segments 를 떼고 순수 교정문만 `+` 로 보여준다.
        out.push({ ...survivingAdd, segments: undefined });
        i = j;
        continue;
      }
      out.push(lines[i], lines[i + 1]);
      i += 2;
      continue;
    }
    out.push(lines[i]);
    i += 1;
  }
  return { lines: out, removedPairs };
}

/** 문장(줄) 토큰화 — \n 우선, 긴 줄은 문장 경계로 추가 분할. */
function tokenize(text: string): string[] {
  return text
    .split(/\n+/)
    .flatMap((line) => line.split(/(?<=[.!?])\s+/))
    .map((line) => line.trim())
    .filter(Boolean);
}

const normalize = (value: string) => value.replace(/\s+/g, " ").replace(/[\s.!?]+$/g, "").trim();

/** 경로 B — 전체 교정본과 원문의 문장 단위 LCS unified diff. */
function diffFromDocument(
  original: string,
  corrected: string,
  revisions: RevisionMeta[],
  originalText: string,
): { lines: RevisionDiffLine[]; changedCount: number } {
  const a = tokenize(original);
  const b = tokenize(corrected);
  const an = a.map(normalize);
  const bn = b.map(normalize);
  // LCS DP (문장 수 기준 — 광고 문안은 수십~수백 문장이라 충분히 작다)
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = an[i] === bn[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const lines: RevisionDiffLine[] = [];
  let changedCount = 0;
  const metaForDel = (line: string): Partial<RevisionDiffLine> => {
    const hit = revisions.find((rev) => {
      const before = originalText.slice(rev.start, rev.end);
      return before && (line.includes(before) || before.includes(line));
    });
    return hit
      ? { anchorId: hit.anchorId, reason: hit.riskReason, basis: hit.basis, label: hit.label }
      : { reason: "일관 재작성 교정안에서 대체·삭제된 문장입니다." };
  };
  const metaForAdd = (line: string): Partial<RevisionDiffLine> => {
    const hit = revisions.find((rev) => rev.after && (line.includes(rev.after) || rev.after.includes(line)));
    return hit
      ? { anchorId: hit.anchorId, reason: hit.fixReason, basis: hit.basis, label: hit.label }
      : { reason: "일관 재작성 교정안에서 새로 쓴 문장입니다." };
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (an[i] === bn[j]) {
      lines.push({ type: "context", text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      lines.push({ type: "del", text: a[i], ...metaForDel(a[i]) });
      changedCount += 1;
      i += 1;
    } else {
      lines.push({ type: "add", text: b[j], ...metaForAdd(b[j]) });
      j += 1;
    }
  }
  while (i < a.length) {
    lines.push({ type: "del", text: a[i], ...metaForDel(a[i]) });
    changedCount += 1;
    i += 1;
  }
  while (j < b.length) {
    lines.push({ type: "add", text: b[j], ...metaForAdd(b[j]) });
    j += 1;
  }
  return { lines, changedCount };
}

export function buildRevisionDiff(result: ReviewOutput, reviewedText: string): RevisionDiff {
  const revisions = collectRevisions(result, reviewedText);
  const docRevision = correctedDocument(result);
  const body = docRevision
    ? diffFromDocument(reviewedText, docRevision, revisions, reviewedText)
    : diffFromSpans(reviewedText, revisions);

  const lines = [...body.lines];
  let disclosureAddCount = 0;
  const block = correctedDisclosureBlock(result);
  if (block) {
    const slots = requiredDisclosureSlots(result);
    const sourceByCheck = new Map(slots.map((slot) => [slot.checkId, slot.source]));
    const hasNoticeHeader = /꼭\s*확인해\s*주세요|유의\s*사항/.test(reviewedText);
    if (!hasNoticeHeader) lines.push({ type: "add", text: "꼭 확인해 주세요", reason: "누락된 필수 고지를 모으는 하단 고지 블록 헤더입니다." });
    for (const item of block.items) {
      disclosureAddCount += 1;
      lines.push({
        type: "add",
        text: item.status === "add" ? item.text : `${item.label} — 심사자 보완 (심의필 번호 등 상품별 정보)`,
        reason:
          item.status === "add"
            ? `누락된 필수 고지(${item.label})를 추가합니다.`
            : `필수 고지(${item.label})가 필요하지만 상품별 정보가 있어야 완성됩니다 — 심사자 보완 항목.`,
        basis: sourceByCheck.get(item.check_id),
        label: "필수 고지",
      });
    }
  }
  return { lines, changedCount: body.changedCount, disclosureAddCount };
}

/** diff 에서 '게시 가능 교정안' 전문을 재구성 (context + add 줄). 복사 버튼용. */
export function correctedTextFromDiff(diff: RevisionDiff): string {
  return diff.lines
    .filter((line) => line.type !== "del")
    .map((line) => line.text)
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
