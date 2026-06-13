import { principleColor } from "@/lib/labels";
import type { DelegationStep } from "@/lib/selectors";
import { Tag } from "../ui";

/** 법령 단계 배지 색. 법률→시행령→감독규정→심의기준 위임 위계. */
export const LAYER_STYLE: Record<string, string> = {
  법률: "bg-brand text-white",
  시행령: "bg-brand-tint2 text-brand-2",
  감독규정: "bg-revise-bg text-revise",
  위임기준: "bg-revise-bg text-revise",
  심의기준: "bg-surface-3 text-ink-2",
  판매원칙: "bg-reject-bg text-reject",
};

/** 온톨로지 DELEGATES_TO 위계를 세로 사슬로. 법률→시행령→감독규정→심의기준. */
export function DelegationChain({ steps }: { steps: DelegationStep[] }) {
  return (
    <ol className="relative space-y-0">
      {steps.map((step, i) => (
        <li key={`${step.layer}_${i}`} className="relative flex gap-2.5 pb-3 last:pb-0">
          {i < steps.length - 1 && <span className="absolute top-5 left-[7px] h-full w-px bg-line-2" />}
          <span className="mt-1.5 h-3.5 w-3.5 shrink-0 rounded-full border-2 border-brand bg-surface" />
          <div className="min-w-0 flex-1">
            <span
              className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold ${LAYER_STYLE[step.layer] ?? "bg-surface-3 text-ink-2"}`}
            >
              {step.layer}
            </span>
            <span className="ml-1.5 font-mono text-[12px] font-bold text-ink">{step.label}</span>
            {step.why && (
              <p className="mt-0.5 flex items-center gap-1 text-[11px] leading-relaxed text-ink-3">
                <span className="text-ink-4">↳ 위임</span> {step.why}
              </p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** 병합된 위임 단계를 법률→시행령→감독규정→심의기준 순으로 전역 정렬. */
export function sortDelegationSteps(steps: DelegationStep[]): DelegationStep[] {
  const order = ["법률", "시행령", "위임기준", "감독규정", "심의기준"];
  const seen = new Set<string>();
  const merged = steps.filter((s) => {
    const key = `${s.layer}:${s.label}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return merged.sort((a, b) => {
    const ai = order.indexOf(a.layer);
    const bi = order.indexOf(b.layer);
    return (ai < 0 ? 9 : ai) - (bi < 0 ? 9 : bi);
  });
}

export function PrincipleTags({ principles }: { principles: string[] }) {
  if (!principles.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[10.5px] font-bold tracking-wider text-ink-4">판매원칙</span>
      {principles.map((p) => (
        <Tag key={p} color={principleColor(p)} tone="danger">
          {p}
        </Tag>
      ))}
    </div>
  );
}
