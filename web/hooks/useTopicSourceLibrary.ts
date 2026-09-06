"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { bookApi } from "@/lib/book-api";
import { listKnowledgeBases } from "@/features/knowledge/api/catalog";
import { listKnowledgeBaseFiles } from "@/features/knowledge/api/client";
import { SUBAGENT_KB_TYPE } from "@/lib/knowledge-helpers";
import type { TopicSourceInput, TopicSourceKind } from "@/lib/learning-api";
import { listCoWriterDocuments } from "@/lib/co-writer-api";
import {
  getNotebook,
  listCategories,
  listNotebookEntries,
  listNotebooks,
} from "@/lib/notebook-api";
import { listPartnerGroups, listPartnerGroupSessions } from "@/lib/partner-groups-api";
import { getPartnerSessions, listPartners } from "@/lib/partners-api";
import { listSessions } from "@/lib/session-api";

export type SourceCandidateKind = Exclude<TopicSourceKind, "goal">;

/**
 * A row that only exists to be opened: a question-bank category, a study
 * partner, a partner group. It holds no text of its own — its children do —
 * so it renders without a checkbox and never enters the selection.
 */
export type SourceContainerKind = "category" | "partner" | "partner_group_root";

export interface SourceCandidate {
  key: string;
  kind: SourceCandidateKind | SourceContainerKind;
  sourceId: string;
  label: string;
  detail: string;
  available: boolean;
  /**
   * False for a container row — one that is opened rather than chosen. The
   * selection and the hydration both skip these, so a partner or a category
   * can never travel to the server as a material.
   */
  selectable?: boolean;
  /** Whether opening this row fetches a child list. */
  expandable?: boolean;
  /**
   * Prompt context carried from the listing that produced this row, so
   * hydration does not re-fetch what the list already showed. Only the
   * outline generator reads it; tutoring reads the real text server-side.
   */
  excerpt?: string;
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
  /** Past conversations — what the learner has already worked through. */
  chats: SourceCandidate[];
  /** Question-bank categories; their entries load on open. */
  questionSets: SourceCandidate[];
  /** Co-Writer drafts — the learner's own writing on the subject. */
  drafts: SourceCandidate[];
  /** Study partners and partner groups; their transcripts load on open. */
  partners: SourceCandidate[];
  failures: string[];
}

/** What one expandable row's child list is doing right now. */
export interface SourceChildren {
  candidates: SourceCandidate[];
  loading: boolean;
  error: string;
}

/** @deprecated Kept as the old name for {@link SourceChildren}. */
export type KnowledgeBaseFiles = SourceChildren;

const EMPTY_LIBRARY: SourceLibrary = {
  books: [],
  notebooks: [],
  knowledgeBases: [],
  chats: [],
  questionSets: [],
  drafts: [],
  partners: [],
  failures: [],
};

//: How many rows one flat listing contributes. A picker is a place to choose
//: from recent work, not a full archive browser.
const MAX_FLAT_ROWS = 30;
//: Entries listed under one question-bank category.
const MAX_CATEGORY_ENTRIES = 50;

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
      listSessions(MAX_FLAT_ROWS, 0),
      listCategories(),
      listCoWriterDocuments(),
      listPartners(),
      listPartnerGroups(),
    ]).then(([
      booksResult,
      notebooksResult,
      knowledgeResult,
      chatResult,
      categoryResult,
      draftResult,
      partnerResult,
      groupResult,
    ]) => {
      if (disposed) return;
      const failures: string[] = [];
      if (booksResult.status === "rejected") failures.push(tr("书架", "Books"));
      if (notebooksResult.status === "rejected") {
        failures.push(tr("笔记本", "Notebooks"));
      }
      if (knowledgeResult.status === "rejected") {
        failures.push(tr("知识库", "Knowledge bases"));
      }
      if (chatResult.status === "rejected") {
        failures.push(tr("聊天历史", "Conversations"));
      }
      if (categoryResult.status === "rejected") {
        failures.push(tr("题库", "Question bank"));
      }
      if (draftResult.status === "rejected") {
        failures.push(tr("智能写作", "Co-Writer"));
      }
      // Partners are admin-scoped: a learner without access gets an empty
      // section, not an error they can do nothing about.
      const partnerRows =
        partnerResult.status === "fulfilled" ? partnerResult.value : [];
      const groupRows =
        groupResult.status === "fulfilled" ? groupResult.value : [];
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
                  expandable: true,
                }))
            : [],
        chats:
          chatResult.status === "fulfilled"
            ? chatResult.value.map((session) => ({
                key: `chat:${session.session_id}`,
                kind: "chat" as const,
                sourceId: session.session_id,
                label: session.title || tr("未命名会话", "Untitled session"),
                detail: tr(
                  `${session.message_count ?? 0} 条消息`,
                  `${session.message_count ?? 0} messages`,
                ),
                available: true,
                excerpt: session.last_message || "",
              }))
            : [],
        questionSets:
          categoryResult.status === "fulfilled"
            ? categoryResult.value.map((category) => ({
                key: `category:${category.id}`,
                kind: "category" as const,
                sourceId: String(category.id),
                label: category.name,
                detail: tr(
                  `${category.entry_count} 道题`,
                  `${category.entry_count} questions`,
                ),
                available: category.entry_count > 0,
                // A category is a folder over questions; only a question
                // carries text, so the folder is opened, never chosen.
                selectable: false,
                expandable: true,
              }))
            : [],
        drafts:
          draftResult.status === "fulfilled"
            ? draftResult.value.map((document) => ({
                key: `cowriter:${document.id}`,
                kind: "cowriter" as const,
                sourceId: document.id,
                label: document.title || tr("未命名草稿", "Untitled draft"),
                detail: document.preview || "",
                available: true,
                excerpt: document.preview || "",
              }))
            : [],
        partners: [
          ...partnerRows.map((partner) => ({
            key: `partner:${partner.partner_id}`,
            kind: "partner" as const,
            sourceId: partner.partner_id,
            label: partner.name,
            detail: tr("学习伙伴", "Study partner"),
            available: true,
            selectable: false,
            expandable: true,
          })),
          ...groupRows.map((group) => ({
            key: `partner_group_root:${group.group_id}`,
            kind: "partner_group_root" as const,
            sourceId: group.group_id,
            label: group.name,
            detail: tr("伙伴组", "Partner group"),
            available: true,
            selectable: false,
            expandable: true,
          })),
        ],
        failures,
      });
      setLoading(false);
    });
    return () => {
      disposed = true;
    };
  }, [tr]);

  // Child lists are fetched per row, only when the learner opens one: a
  // workspace with a dozen libraries, categories and partners would otherwise
  // pay for every listing to answer a question about one of them.
  const [childLists, setChildLists] = useState<Record<string, SourceChildren>>({});

  const loadChildren = useCallback(
    async (candidate: SourceCandidate) => {
      const parentKey = candidate.key;
      setChildLists((previous) =>
        previous[parentKey]?.candidates.length
          ? previous
          : {
              ...previous,
              [parentKey]: { candidates: [], loading: true, error: "" },
            },
      );
      try {
        const listed = await fetchChildren(candidate, tr);
        setChildLists((previous) => ({
          ...previous,
          [parentKey]: { loading: false, error: "", candidates: listed },
        }));
      } catch (reason) {
        setChildLists((previous) => ({
          ...previous,
          [parentKey]: {
            candidates: [],
            loading: false,
            error:
              reason instanceof Error
                ? reason.message
                : tr("无法读取列表", "Could not load the list"),
          },
        }));
      }
    },
    [tr],
  );

  const candidates = useMemo(
    () =>
      [
        ...library.books,
        ...library.notebooks,
        ...library.knowledgeBases,
        ...library.chats,
        ...library.questionSets,
        ...library.drafts,
        ...library.partners,
        ...Object.values(childLists).flatMap((entry) => entry.candidates),
        // Containers are opened, never chosen — keeping them out here means
        // neither the selection nor hydration has to know about them.
      ].filter((candidate) => candidate.selectable !== false),
    [library, childLists],
  );
  return { library, loading, candidates, childLists, loadChildren };
}

/** One expandable row's children, by kind. Throws so the caller can show why. */
async function fetchChildren(
  candidate: SourceCandidate,
  tr: Translate,
): Promise<SourceCandidate[]> {
  const parentKey = candidate.key;
  if (candidate.kind === "knowledge_base") {
    const kbName = candidate.sourceId;
    const listed = await listKnowledgeBaseFiles(kbName);
    return (
      listed
        // Folders are organisational only — they hold no text to ground an
        // outline in, and their files are listed by full path anyway.
        .filter((entry) => entry.type !== "folder")
        .map((entry) => ({
          key: `file:${kbName}:${entry.name}`,
          kind: "file" as const,
          sourceId: entry.name,
          label: entry.name,
          detail: tr(`${kbName} 中的文件`, `File in ${kbName}`),
          available: true,
          kbName,
          path: entry.name,
          parentKey,
        }))
    );
  }
  if (candidate.kind === "category") {
    const { items } = await listNotebookEntries({
      category_id: Number(candidate.sourceId),
      limit: MAX_CATEGORY_ENTRIES,
    });
    return items.map((entry) => ({
      key: `question_bank:${entry.id}`,
      kind: "question_bank" as const,
      sourceId: String(entry.id),
      label: entry.question.slice(0, 80) || tr("未命名题目", "Untitled question"),
      detail: entry.is_correct
        ? tr("已答对", "Answered correctly")
        : tr("答错过", "Answered wrong"),
      available: true,
      excerpt: entry.question,
      parentKey,
    }));
  }
  if (candidate.kind === "partner") {
    const sessions = await getPartnerSessions(candidate.sourceId);
    return sessions.map((session) => ({
      key: `chat:partner:${candidate.sourceId}:${session.session_key}`,
      kind: "chat" as const,
      // The reference form chat's own transcript reader understands.
      sourceId: `partner:${candidate.sourceId}:${session.session_key}`,
      label: session.title || tr("未命名对话", "Untitled conversation"),
      detail: tr(
        `${session.message_count} 条消息`,
        `${session.message_count} messages`,
      ),
      available: true,
      excerpt: session.last_message || "",
      parentKey,
    }));
  }
  if (candidate.kind === "partner_group_root") {
    const sessions = await listPartnerGroupSessions(candidate.sourceId);
    return sessions.map((session) => ({
      key: `partner_group:${candidate.sourceId}:${session.session_key}`,
      kind: "partner_group" as const,
      sourceId: `${candidate.sourceId}:${session.session_key}`,
      label: session.title || tr("未命名讨论", "Untitled discussion"),
      detail: tr(
        `${session.message_count} 条消息`,
        `${session.message_count} messages`,
      ),
      available: true,
      parentKey,
    }));
  }
  return [];
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
    if (
      candidate.kind === "chat" ||
      candidate.kind === "question_bank" ||
      candidate.kind === "cowriter" ||
      candidate.kind === "partner_group"
    ) {
      // The listing already showed enough to ground an outline, and the full
      // text is read server-side during tutoring — so hydration here is an
      // address plus what the learner just looked at, not another fetch.
      return {
        kind: candidate.kind,
        source_id: candidate.sourceId,
        label: candidate.label,
        excerpt: (candidate.excerpt || candidate.detail).slice(0, 4_000),
        available: candidate.available,
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
      // Containers never reach hydration (they are filtered out of
      // `candidates`), so the cast is narrowing a type, not a guess.
      kind: candidate.kind as TopicSourceKind,
      source_id: candidate.sourceId,
      label: candidate.label,
      excerpt: "",
      available: false,
      metadata: { unavailable_during_generation: true },
    };
  }
}
