import type { ReactNode } from "react";

export type BadgeTone = "pass" | "review" | "revise" | "reject" | "neutral";

const BADGE_TONES: Record<BadgeTone, string> = {
  pass: "bg-ok/10 text-ok border-ok/30",
  review: "bg-warn/10 text-warn border-warn/30",
  revise: "bg-violet/10 text-violet border-violet/30",
  reject: "bg-danger/10 text-danger border-danger/30",
  neutral: "bg-panel-soft text-muted border-line",
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
      ? "border-ok/40 text-ok"
      : tone === "review"
        ? "border-warn/40 text-warn"
        : tone === "danger"
          ? "border-danger/40 text-danger"
          : "border-line text-muted";
  const base = `inline-flex max-w-full items-center truncate rounded border bg-panel-soft px-1.5 py-0.5 text-[11px] font-medium ${toneClass}`;
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={`${base} cursor-pointer hover:border-accent hover:text-accent`}>
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
    <article className={`rounded-lg border border-line bg-panel p-4 ${className}`}>
      {(title || actions) && (
        <div className="mb-2 flex items-start justify-between gap-2">
          {title && <h3 className="text-sm font-bold text-foreground">{title}</h3>}
          {actions}
        </div>
      )}
      {children}
    </article>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-panel-soft px-4 py-6 text-center text-sm text-muted">
      {children}
    </div>
  );
}

export function MetricCell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-20 rounded-lg border border-line bg-panel-soft px-3 py-2 text-center">
      <span className="block text-[11px] font-semibold tracking-wide text-muted uppercase">{label}</span>
      <div className="text-lg font-extrabold text-foreground">{value}</div>
    </div>
  );
}

export function KeyValueText({ items }: { items: [string, ReactNode][] }) {
  return (
    <div className="space-y-2 text-[13px] leading-relaxed text-foreground/90">
      {items.map(([label, value]) => (
        <p key={label}>
          <b className="mr-1 text-foreground">{label}</b>
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
