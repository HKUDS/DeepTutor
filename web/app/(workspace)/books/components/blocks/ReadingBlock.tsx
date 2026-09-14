"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Block } from "@/lib/book-types";

export interface ReadingBlockProps {
  block: Block;
}

const VARIANT_LABELS: Record<string, string> = {
  prose: "",
  activity: "探究与分享",
  link: "相关链接",
  quote: "引文",
};

/**
 * Verbatim textbook canon (imported TOC/books). Same zero-LLM guarantee as
 * user_note, but rendered as textbook prose; 栏目 variants (探究与分享…)
 * render as labelled boxes instead of note-card chrome.
 */
export default function ReadingBlock({ block }: ReadingBlockProps) {
  const body = String(block.payload?.body ?? "");
  const variant = String(block.payload?.variant ?? "prose");
  const sourceLabel = String(block.payload?.source_label ?? "");
  const label = VARIANT_LABELS[variant] ?? "";

  if (variant === "prose") {
    return (
      <div className="text-[var(--foreground)]">
        <MarkdownRenderer content={body} variant="prose" />
        {sourceLabel ? (
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            源：{sourceLabel}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <aside
      className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-4 py-3"
      data-variant={variant}
    >
      {label ? (
        <p className="mb-1 text-sm font-medium text-[var(--foreground)]">{label}</p>
      ) : null}
      <MarkdownRenderer content={body} variant="prose" />
      {sourceLabel ? (
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          源：{sourceLabel}
        </p>
      ) : null}
    </aside>
  );
}
