"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { bookApi } from "@/lib/book-api";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { listKnowledgeBaseFiles } from "@/features/knowledge/api/client";
import { SUBAGENT_KB_TYPE } from "@/lib/knowledge-helpers";
import type { TopicSourceInput, TopicSourceKind } from "@/lib/learning-api";
import { getNotebook, listNotebooks } from "@/lib/notebook-api";

export type SourceCandidateKind = Exclude<TopicSourceKind, "goal" | "chat">;

export interface SourceCandidate {
  key: string;
  kind: SourceCandidateKind;
  sourceId: string;
  label: string;
  detail: string;
  available: boolean;
  /**
   * For a `file` candidate, the knowledge base it lives in.
   *
   * Both halves are needed to read it: the KB resolves access, the path
   * resolves the document inside it. `parentKey` is what lets selecting a
   * whole library and one of its files be mutually exclusive.
   */
  kbName?: string;
  path?: string;
  parentKey?: string;
}

export interface SourceLibrary {
  books: SourceCandidate[];
  notebooks: SourceCandidate[];
  knowledgeBases: SourceCandidate[];
  failures: string[];
}

/** What one knowledge base's document list is doing right now. */
export interface KnowledgeBaseFiles {
  candidates: SourceCandidate[];
  loading: boolean;
  error: string;
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

  // Document lists are fetched per knowledge base, only when the learner
  // opens one: a workspace with a dozen libraries would otherwise pay for
  // every listing to answer a question about one of them.
  const [files, setFiles] = useState<Record<string, KnowledgeBaseFiles>>({});

  const loadKnowledgeBaseFiles = useCallback(
    async (candidate: SourceCandidate) => {
      const parentKey = candidate.key;
      const kbName = candidate.sourceId;
      setFiles((previous) =>
        previous[parentKey]?.candidates.length
          ? previous
          : {
              ...previous,
              [parentKey]: { candidates: [], loading: true, error: "" },
            },
      );
      try {
        const listed = await listKnowledgeBaseFiles(kbName);
        setFiles((previous) => ({
          ...previous,
          [parentKey]: {
            loading: false,
            error: "",
            candidates: listed
              // Folders are organisational only — they hold no text to ground
              // an outline in, and their files are listed by full path anyway.
              .filter((entry) => entry.type !== "folder")
              .map((entry) => ({
                key: `file:${kbName}:${entry.name}`,
                kind: "file" as const,
                sourceId: entry.name,
                label: entry.name,
                detail: tr(
                  `${kbName} 中的文件`,
                  `File in ${kbName}`,
                ),
                available: true,
                kbName,
                path: entry.name,
                parentKey,
              })),
          },
        }));
      } catch (reason) {
        setFiles((previous) => ({
          ...previous,
          [parentKey]: {
            candidates: [],
            loading: false,
            error:
              reason instanceof Error
                ? reason.message
                : tr("无法读取文件列表", "Could not list files"),
          },
        }));
      }
    },
    [tr],
  );

  const candidates = useMemo(
    () => [
      ...library.books,
      ...library.notebooks,
      ...library.knowledgeBases,
      ...Object.values(files).flatMap((entry) => entry.candidates),
    ],
    [library, files],
  );
  return { library, loading, candidates, files, loadKnowledgeBaseFiles };
}

/**
 * Add or remove one source from the selection.
 *
 * The rule that needs stating: selecting a whole knowledge base drops the
 * individual documents picked out of it. Sending both means the same material
 * arrives twice — once as retrieval over the library, once as extracted file
 * text — and is counted twice when the outline's coverage is measured.
 *
 * Pure, and exported, so the wizard and its test cannot disagree about it.
 */
export function toggleSourceSelection(
  selected: Set<string>,
  key: string,
  candidates: readonly SourceCandidate[],
): Set<string> {
  const next = new Set(selected);
  if (next.has(key)) {
    next.delete(key);
    return next;
  }
  next.add(key);
  for (const candidate of candidates) {
    if (candidate.parentKey === key) next.delete(candidate.key);
  }
  return next;
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
    if (candidate.kind === "file") {
      // No excerpt: the browser cannot read a PDF out of the knowledge base,
      // so the server extracts the text while grounding the outline (see
      // `_ground_file_source`). What travels from here is the address.
      return {
        kind: "file",
        source_id: candidate.path || candidate.sourceId,
        label: candidate.label,
        excerpt: "",
        available: candidate.available,
        metadata: {
          kb_name: candidate.kbName || "",
          path: candidate.path || candidate.sourceId,
        },
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
