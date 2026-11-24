"use client";

import { useState } from "react";
import Link from "next/link";
import { Compass } from "lucide-react";
import { useTranslation } from "react-i18next";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { renderConceptGraphMermaid } from "@/lib/concept-graph";
import type { Block, ConceptGraph } from "@/lib/book-types";
import { bookRoute } from "@/lib/learning-routes";

export interface ConceptGraphBlockProps {
  block: Block;
  bookId?: string;
  currentPageId?: string;
  language?: string;
}

interface ChapterIndexEntry {
  id: string;
  title: string;
  summary?: string;
  objectives?: string[];
  order?: number;
  content_type?: string;
  page_id?: string;
}

interface IndexPayload {
  chapters: ChapterIndexEntry[];
  node_to_chapter: Record<string, string>;
}

function asGraph(payload: unknown): ConceptGraph | null {
  if (!payload || typeof payload !== "object") return null;
  const candidate = payload as Partial<ConceptGraph>;
  if (!Array.isArray(candidate.nodes) || !Array.isArray(candidate.edges)) {
    return null;
  }
  return candidate as ConceptGraph;
}

function asIndex(payload: unknown): IndexPayload {
  if (!payload || typeof payload !== "object") {
    return { chapters: [], node_to_chapter: {} };
  }
  const candidate = payload as Partial<IndexPayload>;
  return {
    chapters: Array.isArray(candidate.chapters) ? candidate.chapters : [],
    node_to_chapter:
      candidate.node_to_chapter && typeof candidate.node_to_chapter === "object"
        ? candidate.node_to_chapter
        : {},
  };
}

export default function ConceptGraphBlock({
  block,
  bookId,
  currentPageId: _currentPageId,
  language: _language,
}: ConceptGraphBlockProps) {
  const { t } = useTranslation();
  const code =
    (block.payload?.code as
      | { language?: string; content?: string }
      | undefined) || {};
  const graph = asGraph(block.payload?.graph);
  const mermaidSrc = graph
    ? renderConceptGraphMermaid(graph)
    : String(code.content || "").trim();
  const index = asIndex(block.payload?.index);

  const fenced = mermaidSrc
    ? `\`\`\`mermaid\n${mermaidSrc}\n\`\`\``
    : '```mermaid\ngraph TD\n  empty["(no concepts yet)"]\n```';

  const chapterNodes = graph?.nodes.filter((n) => n.chapter_id) ?? [];
  const isChapterMap = chapterNodes.length > 0;
  const nodeCount = graph?.nodes.length ?? 0;
  const edgeCount = graph?.edges.length ?? 0;
  // Clicking a node reveals its stored explanation. The mermaid renderer has
  // no click directives, so the nodes stay a static visual and this list is
  // the interaction surface.
  const [activeNodeId, setActiveNodeId] = useState<string | null>(null);
  const activeNode =
    graph?.nodes.find((node) => node.id === activeNodeId) ?? null;

  return (
    <section className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,260px)]">
      <figure className="overflow-hidden rounded-2xl bg-[rgb(var(--dt-ink,55_53_47)/0.028)] p-3">
        <header className="mb-2 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
          <Compass className="h-3.5 w-3.5" />
          <span>
            {isChapterMap
              ? t(
                  "Chapter map · {{chapters}} chapters · {{dependencies}} dependencies",
                  {
                    chapters: chapterNodes.length,
                    dependencies: edgeCount,
                  },
                )
              : t(
                  "Concept map · {{concepts}} concepts · {{relations}} relations",
                  {
                    concepts: nodeCount,
                    relations: edgeCount,
                  },
                )}
          </span>
        </header>
        <div className="max-h-[60vh] overflow-auto">
          <MarkdownRenderer content={fenced} variant="default" />
        </div>
        {graph && nodeCount > 0 && (
          <div className="mt-3 border-t border-[rgb(var(--dt-ink,55_53_47)/0.08)] pt-3">
            <div
              className="flex flex-wrap gap-1.5"
              role="group"
              aria-label={t("Concept map")}
            >
              {graph.nodes.map((node) => {
                const active = node.id === activeNodeId;
                return (
                  <button
                    key={node.id}
                    type="button"
                    aria-expanded={active}
                    onClick={() =>
                      setActiveNodeId(active ? null : node.id)
                    }
                    className={`rounded-md border px-2 py-1 text-left text-xs font-medium transition-colors ${
                      active
                        ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
                        : "border-transparent bg-[rgb(var(--dt-ink,55_53_47)/0.035)] text-[var(--muted-foreground)] hover:bg-[rgb(var(--dt-ink,55_53_47)/0.06)] hover:text-[var(--foreground)]"
                    }`}
                  >
                    {node.label}
                  </button>
                );
              })}
            </div>
            {activeNode && (
              <div className="mt-2 rounded-lg bg-[var(--background)] px-3 py-2">
                <div className="mb-1 text-xs font-semibold text-[var(--foreground)]">
                  {activeNode.label}
                </div>
                {activeNode.description && (
                  <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                    {activeNode.description}
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </figure>

      <aside className="rounded-2xl bg-[rgb(var(--dt-ink,55_53_47)/0.028)] p-3">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          {t("Chapter index")}
        </h3>
        <ol className="space-y-1.5">
          {index.chapters.length === 0 && (
            <li className="text-xs italic text-[var(--muted-foreground)]">
              {t("(No chapters yet)")}
            </li>
          )}
          {index.chapters.map((chapter, idx) => {
            const label = (
              <span className="flex items-baseline gap-2">
                <span className="text-[10px] font-mono text-[var(--muted-foreground)]">
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <span className="text-xs font-medium leading-snug text-[var(--foreground)]">
                  {chapter.title}
                </span>
              </span>
            );
            if (bookId && chapter.page_id) {
              return (
                <li key={chapter.id}>
                  <Link
                    href={bookRoute(bookId, chapter.page_id)}
                    className="block rounded-md px-2 py-1.5 hover:bg-[var(--background)]"
                  >
                    {label}
                  </Link>
                </li>
              );
            }
            return (
              <li
                key={chapter.id}
                className="rounded-md px-2 py-1.5 text-[var(--foreground)]"
              >
                {label}
              </li>
            );
          })}
        </ol>
      </aside>
    </section>
  );
}
