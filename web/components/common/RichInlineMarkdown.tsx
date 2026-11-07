"use client";

import "katex/dist/katex.min.css";
import React, { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { processLatexContent } from "@/lib/latex";

type Plugins = {
  remarkMath?: unknown;
  rehypeKatex?: unknown;
};

/**
 * Phrasing-first components, with table support.
 *
 * The host is frequently a `<button>` or a `<span>`, whose content model is
 * phrasing content — a `<p>` there is invalid markup and drags the block
 * spacing of the surrounding renderer in with it. Paragraphs and headings
 * therefore collapse to their children.
 *
 * A question stem is the exception: a tutor may put a small comparison table
 * in it (``| tool_call | 性质 | 结果 |``), which is a block construct. It is
 * rendered here rather than left as raw pipe text, so the table keeps the
 * stem's typography instead of the prose renderer's.
 */
const COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  h1: ({ children }: { children?: React.ReactNode }) => (
    <strong>{children}</strong>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <strong>{children}</strong>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <strong>{children}</strong>
  ),
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)] px-1 py-px font-mono text-[0.92em]">
      {children}
    </code>
  ),
  a: ({ children }: { children?: React.ReactNode }) => (
    <span className="underline underline-offset-2">{children}</span>
  ),
  // A question stem is one line; a hard break inside it should not open a
  // block box the card then has to lay out around.
  br: () => <span> </span>,
  table: ({ children }: { children?: React.ReactNode }) => (
    <span className="my-2 block overflow-x-auto">
      <table className="min-w-full border-collapse text-[0.92em]">
        {children}
      </table>
    </span>
  ),
  thead: ({ children }: { children?: React.ReactNode }) => (
    <thead className="bg-[var(--muted)]">{children}</thead>
  ),
  tbody: ({ children }: { children?: React.ReactNode }) => (
    <tbody>{children}</tbody>
  ),
  tr: ({ children }: { children?: React.ReactNode }) => <tr>{children}</tr>,
  th: ({ children }: { children?: React.ReactNode }) => (
    <th className="border border-[var(--border)] px-2 py-1 text-left font-semibold">
      {children}
    </th>
  ),
  td: ({ children }: { children?: React.ReactNode }) => (
    <td className="border border-[var(--border)] px-2 py-1">{children}</td>
  ),
} as const;

export default function RichInlineMarkdown({ content }: { content: string }) {
  const [plugins, setPlugins] = useState<Plugins>({});

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [remarkMath, rehypeKatex] = await Promise.all([
        import("remark-math"),
        import("rehype-katex"),
      ]);
      if (!cancelled) {
        setPlugins({
          remarkMath: remarkMath.default,
          rehypeKatex: rehypeKatex.default,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const remarkPlugins: any[] = [remarkGfm];
  if (plugins.remarkMath) remarkPlugins.push(plugins.remarkMath);
  const rehypePlugins: any[] = plugins.rehypeKatex ? [plugins.rehypeKatex] : [];

  return (
    <ReactMarkdown
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={COMPONENTS as any}
    >
      {processLatexContent(content)}
    </ReactMarkdown>
  );
}
