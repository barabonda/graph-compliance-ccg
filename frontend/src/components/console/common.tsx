import type { ReactNode } from "react";
import { Icon } from "../Icon";

export function PaneHeader({
  icon,
  title,
  sub,
  right,
}: {
  icon: string;
  title: string;
  sub?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex shrink-0 items-center gap-2.5 border-b border-line bg-surface px-4 py-3">
      <Icon name={icon} size={18} color="var(--ink-3)" />
      <div className="min-w-0">
        <div className="text-sm leading-tight font-bold">{title}</div>
        {sub && <div className="mt-0.5 text-[11.5px] text-ink-3">{sub}</div>}
      </div>
      <div className="ml-auto">{right}</div>
    </div>
  );
}

export function DetailRow({ icon, label, children }: { icon: string; label: string; children: ReactNode }) {
  return (
    <div className="border-t border-line py-3.5">
      <div className="mb-2 flex items-center gap-1.5">
        <Icon name={icon} size={15} color="var(--ink-4)" />
        <span className="text-[11px] font-bold tracking-wider text-ink-4 uppercase">{label}</span>
      </div>
      {children}
    </div>
  );
}
