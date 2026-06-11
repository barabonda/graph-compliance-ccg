import type { ReactNode } from "react";

export function PaneHeader({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex shrink-0 items-center gap-2.5 border-b border-line bg-surface px-4 py-3">
      <div className="min-w-0">
        <div className="text-sm leading-tight font-bold">{title}</div>
        {sub && <div className="mt-0.5 text-[11.5px] text-ink-3">{sub}</div>}
      </div>
      <div className="ml-auto">{right}</div>
    </div>
  );
}

export function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-t border-line py-3.5">
      <div className="mb-2 text-[11px] font-bold tracking-wider text-ink-4 uppercase">{label}</div>
      {children}
    </div>
  );
}
