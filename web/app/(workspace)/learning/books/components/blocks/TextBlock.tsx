"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Block } from "@/lib/book-types";

export interface TextBlockProps {
  block: Block;
}

export default function TextBlock({ block }: TextBlockProps) {
  // Generated text blocks store prose under `body`; the deterministically
  // built overview blocks use `content`. Accept both — reading only one meant
  // the overview intro and chapter index rendered as empty divs.
  const body = String(block.payload?.body ?? block.payload?.content ?? "");

  return (
    <div className="text-[var(--foreground)]">
      <MarkdownRenderer content={body} variant="prose" />
    </div>
  );
}
