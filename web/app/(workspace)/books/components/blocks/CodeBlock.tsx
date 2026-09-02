"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import type { Block } from "@/lib/book-types";

export interface CodeBlockProps {
  block: Block;
}

export default function CodeBlock({ block }: CodeBlockProps) {
  const language = String(block.payload?.language || "python");
  const code = String(block.payload?.code || "");
  const explanation = String(block.payload?.explanation || "");
  const fenced = `\`\`\`${language}\n${code}\n\`\`\``;
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <MarkdownRenderer content={fenced} variant="default" />
      {explanation && (
        <p className="mt-2 text-xs text-[var(--muted-foreground)]">
          {explanation}
        </p>
      )}
    </div>
  );
}
