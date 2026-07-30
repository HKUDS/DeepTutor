/**
 * Session activity — folding a conversation's messages into what it touched.
 *
 * Pure data reduction over the message list: which tools ran, which knowledge
 * bases and Space objects were referenced, which files the user attached, and
 * which files the assistant produced. No React and no rendering, so the
 * `SessionActivityPanel` that draws it stays presentational and this fold is
 * directly testable.
 */

import type {
  MessageAttachment,
  MessageItem,
  MessageRequestSnapshot,
} from "@/context/UnifiedChatContext";
import type { StreamEvent } from "@/lib/unified-ws";

/** Artifact URLs are `/api/outputs/<path under the data root>`. */
const OUTPUTS_URL_PREFIX = "/api/outputs/";

/**
 * Where a generated file sits under the data root, for the row's hover title.
 * Derived from the URL rather than persisted separately, so the backend never
 * ships an absolute server path to the browser. Returns `null` for anything
 * that is not an outputs URL.
 */
export function artifactDiskPath(url?: string): string | null {
  if (!url || !url.startsWith(OUTPUTS_URL_PREFIX)) return null;
  const relative = url.slice(OUTPUTS_URL_PREFIX.length);
  try {
    return decodeURIComponent(relative) || null;
  } catch {
    // A malformed escape sequence: the raw form is still a usable hint.
    return relative || null;
  }
}

export interface ToolUsage {
  name: string;
  count: number;
}

export interface AttachmentWithOrigin {
  messageIndex: number;
  attachment: MessageAttachment;
}

export interface SpaceReferenceSummary {
  historySessionIds: string[];
  bookPageCount: number;
  bookIds: string[];
  bookPages: Map<string, string[]>;
  notebookRecordCount: number;
  notebookIds: string[];
  questionEntryIds: number[];
  personas: string[];
  memoryKinds: Array<"summary" | "profile">;
}

export interface SessionActivity {
  tools: ToolUsage[];
  knowledgeBases: string[];
  space: SpaceReferenceSummary;
  /** Files the user uploaded. */
  attachments: AttachmentWithOrigin[];
  /** Files the assistant produced (exec/code_execution/media artifacts).
   *  Split out from uploads so a session's output is one collected list
   *  instead of something you scroll the transcript to find again. */
  artifacts: AttachmentWithOrigin[];
  isEmpty: boolean;
}

export function buildSessionActivity(messages: MessageItem[]): SessionActivity {
  const toolCounts = new Map<string, number>();
  const kbs = new Set<string>();
  const historySessionIds = new Set<string>();
  const bookIds = new Set<string>();
  const bookPages = new Map<string, string[]>();
  let bookPageCount = 0;
  const notebookIds = new Set<string>();
  let notebookRecordCount = 0;
  const questionEntryIds = new Set<number>();
  const personas = new Set<string>();
  const memoryKinds = new Set<"summary" | "profile">();
  const attachments: AttachmentWithOrigin[] = [];
  const artifacts: AttachmentWithOrigin[] = [];

  messages.forEach((msg, idx) => {
    msg.events?.forEach((event: StreamEvent) => {
      if (event.type !== "tool_call") return;
      const name =
        String((event.metadata as { tool?: string } | undefined)?.tool || "") ||
        event.content?.trim() ||
        "tool";
      toolCounts.set(name, (toolCounts.get(name) ?? 0) + 1);
    });

    msg.attachments?.forEach((a) => {
      // `generated` marks files the assistant produced this turn; everything
      // else is something the user attached.
      (a.generated ? artifacts : attachments).push({
        messageIndex: idx,
        attachment: a,
      });
    });

    const snap: MessageRequestSnapshot | undefined = msg.requestSnapshot;
    if (snap) {
      snap.knowledgeBases?.forEach((k) => kbs.add(k));
      snap.historyReferences?.forEach((s) => historySessionIds.add(s));
      snap.bookReferences?.forEach((b) => {
        bookIds.add(b.book_id);
        bookPageCount += b.page_ids?.length ?? 0;
        const existing = bookPages.get(b.book_id) ?? [];
        bookPages.set(b.book_id, [...existing, ...(b.page_ids ?? [])]);
      });
      snap.notebookReferences?.forEach((n) => {
        notebookIds.add(n.notebook_id);
        notebookRecordCount += n.record_ids?.length ?? 0;
      });
      snap.questionNotebookReferences?.forEach((q) => questionEntryIds.add(q));
      if (snap.persona) personas.add(snap.persona);
      snap.memoryReferences?.forEach((k) => memoryKinds.add(k));
    }
  });

  const tools = Array.from(toolCounts.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));

  const space: SpaceReferenceSummary = {
    historySessionIds: Array.from(historySessionIds),
    bookPageCount,
    bookIds: Array.from(bookIds),
    bookPages,
    notebookRecordCount,
    notebookIds: Array.from(notebookIds),
    questionEntryIds: Array.from(questionEntryIds),
    personas: Array.from(personas),
    memoryKinds: Array.from(memoryKinds),
  };

  const isEmpty =
    tools.length === 0 &&
    kbs.size === 0 &&
    attachments.length === 0 &&
    artifacts.length === 0 &&
    space.historySessionIds.length === 0 &&
    space.bookIds.length === 0 &&
    space.notebookIds.length === 0 &&
    space.questionEntryIds.length === 0 &&
    space.personas.length === 0 &&
    space.memoryKinds.length === 0;

  return {
    tools,
    knowledgeBases: Array.from(kbs),
    space,
    attachments,
    artifacts,
    isEmpty,
  };
}
