"use client";

import { type ReactNode } from "react";
import { type LucideIcon } from "lucide-react";

interface SpaceSectionHeaderProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  meta?: ReactNode;
}

export default function SpaceSectionHeader({
  icon: Icon,
  title,
  description,
  action,
  meta,
}: SpaceSectionHeaderProps) {
  return (
    <header className="mb-6 flex flex-col gap-4 border-b border-[var(--border)]/60 pb-5 md:flex-row md:items-end md:justify-between">
      <div className="flex items-start gap-3.5">
        <span
          aria-hidden
          className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-[var(--border)]/60 bg-[var(--card)] text-[var(--foreground)] shadow-sm"
        >
          <Icon size={16} strokeWidth={1.6} />
        </span>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-serif text-[19px] font-semibold leading-tight tracking-tight text-[var(--foreground)]">
              {title}
            </h1>
            {meta}
          </div>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        </div>
      </div>
      {action && (
        <div className="shrink-0 self-start md:self-end">{action}</div>
      )}
    </header>
  );
}
