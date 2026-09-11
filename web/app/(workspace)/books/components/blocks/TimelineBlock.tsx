"use client";

import type { Block } from "@/lib/book-types";

interface TimelineEvent {
  date?: string;
  title?: string;
  description?: string;
}

export interface TimelineBlockProps {
  block: Block;
}

export default function TimelineBlock({ block }: TimelineBlockProps) {
  const events = (block.payload?.events as TimelineEvent[] | undefined) || [];
  if (events.length === 0) return null;
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <ol className="relative ml-3 space-y-4 border-l border-[var(--border)] pl-4">
        {events.map((ev, idx) => (
          <li key={idx} className="relative">
            <span className="absolute -left-[19px] top-1 inline-flex h-3 w-3 rounded-full border-2 border-[var(--card)] bg-[var(--primary)]" />
            <div className="text-xs font-mono uppercase tracking-wider text-[var(--muted-foreground)]">
              {ev.date || ""}
            </div>
            <div className="text-sm font-semibold text-[var(--foreground)]">
              {ev.title}
            </div>
            {ev.description && (
              <div className="mt-0.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
                {ev.description}
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
