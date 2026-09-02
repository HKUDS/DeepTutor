"use client";

import { useEffect, useMemo, useState } from "react";

import { bookApi } from "@/lib/book-api";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { SUBAGENT_KB_TYPE } from "@/lib/knowledge-helpers";
import type { TopicSourceInput, TopicSourceKind } from "@/lib/learning-api";
import { getNotebook, listNotebooks } from "@/lib/notebook-api";

export type SourceCandidateKind = Exclude<
  TopicSourceKind,
  "goal" | "file" | "chat"
>;

export interface SourceCandidate {
  key: string;
  kind: SourceCandidateKind;
  sourceId: string;
  label: string;
  detail: string;
  available: boolean;
}

export interface SourceLibrary {
  books: SourceCandidate[];
  notebooks: SourceCandidate[];
  knowledgeBases: SourceCandidate[];
  failures: string[];
}

const EMPTY_LIBRARY: SourceLibrary = {
  books: [],
  notebooks: [],
  knowledgeBases: [],
  failures: [],
};

type Translate = (cn: string, en: string) => string;

export function useTopicSourceLibrary(tr: Translate) {
  const [library, setLibrary] = useState<SourceLibrary>(EMPTY_LIBRARY);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let disposed = false;
    Promise.allSettled([
      bookApi.list(),
      listNotebooks(),
      listKnowledgeBases(),
    ]).then(([booksResult, notebooksResult, knowledgeResult]) => {
      if (disposed) return;
      const failures: string[] = [];
      if (booksResult.status === "rejected") failures.push(tr("书架", "Books"));
      if (notebooksResult.status === "rejected") {
        failures.push(tr("笔记本", "Notebooks"));
      }
      if (knowledgeResult.status === "rejected") {
        failures.push(tr("知识库", "Knowledge bases"));
      }
      setLibrary({
        books:
          booksResult.status === "fulfilled"
            ? booksResult.value.books.map((book) => ({
                key: `book:${book.id}`,
                kind: "book" as const,
                sourceId: book.id,
                label: book.title,
                detail: tr(
                  `${book.chapter_count} 章 · ${book.status}`,
                  `${book.chapter_count} chapters · ${book.status}`,
                ),
                available: book.status !== "error",
              }))
            : [],
        notebooks:
          notebooksResult.status === "fulfilled"
            ? notebooksResult.value.map((notebook) => ({
                key: `notebook:${notebook.id}`,
                kind: "notebook" as const,
                sourceId: notebook.id,
                label: notebook.name,
                detail: tr(
                  `${notebook.record_count ?? 0} 条记录`,
                  `${notebook.record_count ?? 0} records`,
                ),
                available: !notebook.unreadable,
              }))
            : [],
        knowledgeBases:
          knowledgeResult.status === "fulfilled"
            ? knowledgeResult.value
                .filter(
                  (knowledgeBase) =>
                    knowledgeBase.metadata?.type !== SUBAGENT_KB_TYPE,
                )
                .map((knowledgeBase) => ({
                  key: `knowledge_base:${knowledgeBase.id || knowledgeBase.name}`,
                  kind: "knowledge_base" as const,
                  sourceId: knowledgeBase.name,
                  label: knowledgeBase.name,
                  detail:
                    knowledgeBase.provenance_label ||
                    tr(
                      knowledgeBase.status === "ready"
                        ? "可检索"
                        : "索引状态未知",
                      knowledgeBase.status === "ready"
                        ? "Ready to retrieve"
                        : "Index status unknown",
                    ),
                  available: knowledgeBase.available !== false,
                }))
            : [],
        failures,
      });
      setLoading(false);
    });
    return () => {
      disposed = true;
    };
  }, [tr]);

  const candidates = useMemo(
    () => [...library.books, ...library.notebooks, ...library.knowledgeBases],
    [library],
  );
  return { library, loading, candidates };
}

/** Resolve a selected source to bounded prompt context; failures stay visible. */
export async function hydrateTopicSource(
  candidate: SourceCandidate,
): Promise<TopicSourceInput> {
  try {
    if (candidate.kind === "book") {
      const { spine } = await bookApi.getSpine(candidate.sourceId);
      return {
        kind: "book",
        source_id: candidate.sourceId,
        label: candidate.label,
        excerpt: spine.chapters
          .map(
            (chapter) =>
              `${chapter.title}: ${[
                ...chapter.learning_objectives,
                chapter.summary,
              ]
                .filter(Boolean)
                .join("; ")}`,
          )
          .join("\n")
          .slice(0, 8_000),
        available: true,
        metadata: { chapter_count: spine.chapters.length },
      };
    }
    if (candidate.kind === "notebook") {
      const notebook = await getNotebook(candidate.sourceId);
      return {
        kind: "notebook",
        source_id: candidate.sourceId,
        label: candidate.label,
        excerpt: notebook.records
          .slice(0, 16)
          .map(
            (record) =>
              `${record.title}\n${record.summary || record.user_query || ""}\n${record.output || ""}`,
          )
          .join("\n\n")
          .slice(0, 8_000),
        available: true,
        metadata: { record_count: notebook.records.length },
      };
    }
    return {
      kind: "knowledge_base",
      source_id: candidate.sourceId,
      label: candidate.label,
      excerpt: candidate.detail,
      available: candidate.available,
    };
  } catch {
    return {
      kind: candidate.kind,
      source_id: candidate.sourceId,
      label: candidate.label,
      excerpt: "",
      available: false,
      metadata: { unavailable_during_generation: true },
    };
  }
}
