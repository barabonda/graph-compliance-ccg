"use client";

import { trackBBadgeTone } from "@/lib/labels";
import { anchorForClaim, claimsForSentence, sentenceById } from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";
import { Badge, EmptyState, KeyValueText, Tag } from "../ui";

interface Props {
  result: ReviewOutput | null;
  onSelectAnchor: (anchorId: string) => void;
}

export function SentenceMapTab({ result, onSelectAnchor }: Props) {
  if (!result) {
    return <EmptyState>Review를 실행하면 SentenceUnit과 문장 간 관계가 여기에 표시됩니다.</EmptyState>;
  }
  const sentences = result.sentence_units ?? [];
  const relations = result.inter_sentence_relations ?? [];
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="space-y-2">
        <h3 className="text-sm font-bold">SentenceUnit</h3>
        {sentences.length ? (
          sentences.map((sentence) => {
            const claims = claimsForSentence(result, sentence.sentence_id);
            return (
              <article key={sentence.sentence_id} className="rounded-lg border border-line bg-surface p-3">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <strong className="text-[13px] leading-snug">{sentence.text || "-"}</strong>
                  <Badge
                    tone={trackBBadgeTone(
                      sentence.risk_level,
                      sentence.risk_level === "HIGH" ? 1 : sentence.risk_level === "MEDIUM" ? 0.55 : 0.2,
                    )}
                  >
                    {sentence.role || "other"}
                  </Badge>
                </div>
                <KeyValueText
                  items={[
                    ["문장 의미", sentence.local_meaning || "-"],
                    ["전체 맥락 영향", sentence.context_effect || "-"],
                  ]}
                />
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {claims.length ? (
                    claims.map((claim) => {
                      const anchor = anchorForClaim(result, claim.claim_id);
                      return anchor ? (
                        <Tag key={claim.claim_id} onClick={() => onSelectAnchor(anchor.anchor_id)}>
                          {claim.text}
                        </Tag>
                      ) : (
                        <Tag key={claim.claim_id}>{claim.text}</Tag>
                      );
                    })
                  ) : (
                    <Tag>독립 Claim 없음</Tag>
                  )}
                </div>
              </article>
            );
          })
        ) : (
          <EmptyState>문장 단위가 없습니다.</EmptyState>
        )}
      </section>
      <section className="space-y-2">
        <h3 className="text-sm font-bold">InterSentenceRelation</h3>
        {relations.length ? (
          relations.map((relation) => (
            <article key={relation.relation_id} className="rounded-lg border border-line bg-surface p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <strong className="text-[13px]">{relation.relation_type || "OTHER"}</strong>
                <Tag>문장 간 영향</Tag>
              </div>
              <KeyValueText
                items={[
                  ["From", sentenceById(result, relation.source_sentence_id)?.text || relation.source_sentence_id || "-"],
                  ["To", sentenceById(result, relation.target_sentence_id)?.text || relation.target_sentence_id || "-"],
                  ["Why", relation.explanation || "-"],
                  ["Evidence", relation.evidence || "-"],
                ]}
              />
            </article>
          ))
        ) : (
          <EmptyState>문장 간 관계가 없습니다.</EmptyState>
        )}
      </section>
    </div>
  );
}
