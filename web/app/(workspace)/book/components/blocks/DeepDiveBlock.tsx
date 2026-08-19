"use client";

import { useState } from "react";
import { ArrowUpRight, ChevronRight, Sparkles, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Block } from "@/lib/book-types";

interface Suggestion {
  topic?: string;
  rationale?: string;
}

export interface DeepDiveBlockProps {
  block: Block;
  onDeepDive?: (topic: string, blockId: string) => Promise<void> | void;
  onOpenPage?: (pageId: string) => void;
  pendingTopic?: string | null;
}

export default function DeepDiveBlock({
  block,
  onDeepDive,
  onOpenPage,
  pendingTopic,
}: DeepDiveBlockProps) {
  const { t } = useTranslation();
  const suggestions =
    (block.payload?.suggestions as Suggestion[] | undefined) || [];

  // Each suggested topic tracks its own sub-page. Books written before this was
  // keyed by topic carry a single `deep_dive_page_id`; treat that as belonging
  // to the first topic rather than to all of them.
  const pagesByTopic =
    (block.metadata?.deep_dive_pages as Record<string, string> | undefined) ||
    {};
  const legacyPageId = block.metadata?.deep_dive_page_id as string | undefined;

  const [busy, setBusy] = useState<string | null>(null);

  if (suggestions.length === 0) return null;

  const pageFor = (topic: string, index: number): string | undefined =>
    pagesByTopic[topic] ||
    (index === 0 && Object.keys(pagesByTopic).length === 0
      ? legacyPageId
      : undefined);

  return (
    <div className="rounded-2xl border border-[var(--primary)]/30 bg-gradient-to-br from-[var(--primary)]/5 to-transparent p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-[var(--primary)]" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--primary)]">
          {t("Go Deeper")}
        </span>
      </div>
      <ul className="space-y-2">
        {suggestions.map((s, i) => {
          const topic = s.topic || "";
          const isPending = busy === topic || pendingTopic === topic;
          const existingPageId = pageFor(topic, i);
          const anyPending = !!busy || !!pendingTopic;

          return (
            <li key={topic || i}>
              <button
                onClick={async () => {
                  if (!topic) return;
                  // Already expanded → this is the way back to that chapter.
                  if (existingPageId) {
                    onOpenPage?.(existingPageId);
                    return;
                  }
                  if (!onDeepDive) return;
                  setBusy(topic);
                  try {
                    await onDeepDive(topic, block.id);
                  } finally {
                    setBusy(null);
                  }
                }}
                // Only the topic being generated locks, plus the others while a
                // generation is in flight. Choosing one no longer retires the rest.
                disabled={isPending || (anyPending && !existingPageId)}
                title={
                  existingPageId
                    ? t("Open the chapter this created")
                    : t("Generate a chapter on this")
                }
                className="group flex w-full items-start justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-left transition hover:border-[var(--primary)]/40 disabled:opacity-60"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-1.5 text-sm font-medium text-[var(--foreground)]">
                    {topic}
                    {existingPageId && (
                      <span className="rounded-full bg-[var(--primary)]/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-[var(--primary)]">
                        {t("Created")}
                      </span>
                    )}
                  </div>
                  {s.rationale && (
                    <div className="mt-0.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
                      {s.rationale}
                    </div>
                  )}
                </div>
                {isPending ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[var(--primary)]" />
                ) : existingPageId ? (
                  <ArrowUpRight className="h-4 w-4 shrink-0 text-[var(--primary)]" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition group-hover:translate-x-0.5 group-hover:text-[var(--primary)]" />
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
