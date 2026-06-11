import type { ReactNode } from "react";

export type BadgeTone = "pass" | "review" | "revise" | "reject" | "neutral";

const BADGE_TONES: Record<BadgeTone, string> = {
  pass: "bg-pass/10 text-pass border-pass/30",
  review: "bg-revise/10 text-revise border-revise/30",
  revise: "bg-revise/10 text-revise border-revise/30",
  reject: "bg-reject/10 text-reject border-reject/30",
  neutral: "bg-surface-2 text-ink-3 border-line",
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-bold whitespace-nowrap ${BADGE_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function Tag({
  tone,
  children,
  onClick,
}: {
  tone?: "ok" | "review" | "danger";
  children: ReactNode;
  onClick?: () => void;
}) {
  const toneClass =
    tone === "ok"
      ? "border-pass/40 text-pass"
      : tone === "review"
        ? "border-revise/40 text-revise"
        : tone === "danger"
          ? "border-reject/40 text-reject"
          : "border-line text-ink-3";
  const base = `inline-flex max-w-full items-center truncate rounded border bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium ${toneClass}`;
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={`${base} cursor-pointer hover:border-brand hover:text-brand`}>
        {children}
      </button>
    );
  }
  return <span className={base}>{children}</span>;
}

export function Card({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <article className={`rounded-lg border border-line bg-surface p-4 ${className}`}>
      {(title || actions) && (
        <div className="mb-2 flex items-start justify-between gap-2">
          {title && <h3 className="text-sm font-bold text-ink">{title}</h3>}
          {actions}
        </div>
      )}
      {children}
    </article>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-surface-2 px-4 py-6 text-center text-sm text-ink-3">
      {children}
    </div>
  );
}

export function MetricCell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-20 rounded-lg border border-line bg-surface-2 px-3 py-2 text-center">
      <span className="block text-[11px] font-semibold tracking-wide text-ink-3 uppercase">{label}</span>
      <div className="text-lg font-extrabold text-ink">{value}</div>
    </div>
  );
}

export function KeyValueText({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="space-y-2 text-[13px] leading-relaxed text-ink/90">
      {items.map(([label, value]) => (
        <p key={label}>
          <b className="mr-1 text-ink">{label}</b>
          <br />
          {value ?? "-"}
        </p>
      ))}
    </div>
  );
}

export function SectionDivider() {
  return <hr className="my-3 border-line" />;
}
