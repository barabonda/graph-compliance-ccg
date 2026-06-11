"use client";

import { PRINCIPLES, type PrincipleKey } from "@/lib/labels";
import { principleStatuses, type PrincipleStatus } from "@/lib/selectors";
import type { ReviewOutput } from "@/lib/types";

interface Props {
  result: ReviewOutput | null;
  selectedPrinciple: PrincipleKey | "";
  onToggle: (principle: PrincipleKey) => void;
}

const STATUS_CLASS: Record<PrincipleStatus, string> = {
  "위반 가능성": "text-danger",
  "수정 필요": "text-violet",
  "검토 필요": "text-warn",
  "문제 없음": "text-ok",
  "해당 없음": "text-muted",
};

export function RiskStrip({ result, selectedPrinciple, onToggle }: Props) {
  const statuses = result ? principleStatuses(result) : null;
  return (
    <section
      aria-label="6대 판매원칙 리스크"
      className="grid grid-cols-2 gap-2 rounded-lg border border-line bg-panel p-3 shadow-panel sm:grid-cols-3 lg:grid-cols-6"
    >
      {PRINCIPLES.map((principle) => {
        const status: PrincipleStatus = statuses?.[principle.key] ?? "해당 없음";
        const isActive = selectedPrinciple === principle.key;
        return (
          <button
            key={principle.key}
            type="button"
            onClick={() => onToggle(principle.key)}
            disabled={!result}
            className={`flex flex-col items-start gap-0.5 rounded-md border px-3 py-2 text-left transition disabled:cursor-default ${
              isActive ? "border-accent bg-accent/5 ring-1 ring-accent/30" : "border-line bg-panel-soft hover:border-line-strong"
            }`}
          >
            <span className="text-xs font-bold text-foreground">{principle.label}</span>
            <span className={`text-[11px] font-semibold ${STATUS_CLASS[status]}`}>{status}</span>
          </button>
        );
      })}
    </section>
  );
}
