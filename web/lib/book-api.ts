import { apiFetch, apiUrl, wsUrl } from "@/lib/api";
import {
  runBookSocketOperation,
  type BookWsEvent,
} from "@/lib/book-ws-operation";
import type {
  Book,
  BookDepth,
  BookDetail,
  LearningCapture,
  LearningCaptureStatus,
  BookProposal,
  Page,
  Progress,
  Spine,
  Block,
} from "@/lib/book-types";

const BASE = "/api/v1/book";

function requestOverSocket<T extends BookWsEvent>(
  message: BookWsEvent,
  resultType: string,
  onEvent?: (event: BookWsEvent) => void,
): Promise<T> {
  return runBookSocketOperation<T>(() => new WebSocket(wsUrl(`${BASE}/ws`)), {
    message,
    resultType,
    onEvent,
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(apiUrl(`${BASE}${path}`), {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail: string;
    try {
      const data = await res.json();
      detail = (data && (data.detail || data.message)) || res.statusText;
    } catch {
      detail = res.statusText;
    }
    throw new Error(`book api ${path} → ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

export interface CreateBookPayload {
  user_intent: string;
  chat_session_id?: string;
  chat_selections?: Array<{ session_id: string; message_ids: number[] }>;
  notebook_refs?: Array<Record<string, unknown>>;
  knowledge_bases?: string[];
  question_categories?: number[];
  question_entries?: number[];
  language?: string;
  depth?: BookDepth;
}

/** Per-chapter generation cost, keyed by content type. */
export interface EstimateBasis {
  [contentType: string]: { blocks: number; words: number; seconds: number };
}

export const bookApi = {
  list: () => request<{ books: Book[] }>("/books"),

  /**
   * Cost of one chapter of each content type, at a given depth.
   *
   * Fetched once; the spine editor sums it locally so the estimate stays live
   * while chapters are edited. The numbers derive from the same templates the
   * architect plans from, so they cannot drift from reality.
   */
  estimateBasis: (depth: BookDepth = "standard") =>
    request<{ depth: string; basis: EstimateBasis }>(
      `/estimate-basis?depth=${encodeURIComponent(depth)}`,
    ),
  /**
   * Load a book.
   *
   * `includeBlocks: false` returns chapter metadata without block payloads —
   * a compiled book's blocks carry their whole rendered content, so the full
   * response runs to hundreds of kilobytes. Views that only need the chapter
   * list should ask for summaries.
   */
  get: (book_id: string, options?: { includeBlocks?: boolean }) =>
    request<BookDetail>(
      `/books/${encodeURIComponent(book_id)}` +
        (options?.includeBlocks === false ? "?include_blocks=false" : ""),
    ),
  delete: (book_id: string) =>
    request<{ deleted: boolean; book_id: string }>(
      `/books/${encodeURIComponent(book_id)}`,
      { method: "DELETE" },
    ),
  getSpine: (book_id: string) =>
    request<{ spine: Spine }>(`/books/${encodeURIComponent(book_id)}/spine`),
  getPage: (book_id: string, page_id: string) =>
    request<{ page: Page }>(
      `/books/${encodeURIComponent(book_id)}/pages/${encodeURIComponent(page_id)}`,
    ),
  create: (
    payload: CreateBookPayload,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{
      type: "create_result";
      book: Book;
      proposal: BookProposal;
    }>({ type: "create", ...payload }, "create_result", onEvent),
  confirmProposal: (
    book_id: string,
    proposal?: BookProposal,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{
      type: "confirm_proposal_result";
      book: Book;
      spine: Spine;
    }>(
      { type: "confirm_proposal", book_id, proposal: proposal ?? null },
      "confirm_proposal_result",
      onEvent,
    ),
  confirmSpine: (book_id: string, spine?: Spine, auto_compile = true) =>
    request<{ pages: Page[] }>("/books/confirm-spine", {
      method: "POST",
      body: JSON.stringify({ book_id, spine: spine ?? null, auto_compile }),
    }),
  compilePage: (
    book_id: string,
    page_id: string,
    force = false,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{ type: "compile_page_result"; page: Page }>(
      { type: "compile_page", book_id, page_id, force },
      "compile_page_result",
      onEvent,
    ),
  regenerateBlock: (
    book_id: string,
    page_id: string,
    block_id: string,
    params_override?: Record<string, unknown>,
    onEvent?: (event: BookWsEvent) => void,
  ) =>
    requestOverSocket<{
      type: "regenerate_block_result";
      block: Block | null;
    }>(
      {
        type: "regenerate_block",
        book_id,
        page_id,
        block_id,
        params_override: params_override ?? null,
      },
      "regenerate_block_result",
      onEvent,
    ),

  insertBlock: (params: {
    book_id: string;
    page_id: string;
    block_type: string;
    params?: Record<string, unknown>;
    position?: number;
    compile_now?: boolean;
  }) =>
    request<{ block: Block }>("/books/insert-block", {
      method: "POST",
      body: JSON.stringify({
        compile_now: true,
        ...params,
      }),
    }),

  /** Edit a block's prose in place. Title/body only — see the backend note. */
  updateBlock: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    title?: string;
    body?: string;
  }) =>
    request<{ block: Block }>("/books/update-block", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  markVisited: (book_id: string, page_id: string) =>
    request<{ progress: Progress }>("/books/progress/visit", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id }),
    }),

  toggleBookmark: (book_id: string, page_id: string) =>
    request<{ progress: Progress }>("/books/progress/bookmark", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id }),
    }),

  /** Href for the Markdown download — a plain link, so the browser saves it. */
  exportUrl: (book_id: string) =>
    apiUrl(`${BASE}/books/${encodeURIComponent(book_id)}/export`),

  deleteBlock: (book_id: string, page_id: string, block_id: string) =>
    request<{ ok: boolean }>("/books/delete-block", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id, block_id }),
    }),

  moveBlock: (
    book_id: string,
    page_id: string,
    block_id: string,
    new_position: number,
  ) =>
    request<{ ok: boolean }>("/books/move-block", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id, block_id, new_position }),
    }),

  changeBlockType: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    new_type: string;
    params_override?: Record<string, unknown>;
  }) =>
    request<{ block: Block }>("/books/change-block-type", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  deepDive: (params: {
    book_id: string;
    parent_page_id: string;
    topic: string;
    block_id?: string;
    content_type?: string;
  }) =>
    request<{ page: Page }>("/books/deep-dive", {
      method: "POST",
      body: JSON.stringify({ content_type: "concept", ...params }),
    }),

  recordQuizAttempt: (params: {
    book_id: string;
    page_id: string;
    block_id: string;
    question_id?: string;
    user_answer?: string;
    /** Omit for a written answer the reader revealed but didn't self-grade. */
    is_correct?: boolean;
  }) =>
    request<{ progress: Progress }>("/books/quiz-attempt", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  supplement: (book_id: string, page_id: string, topic: string) =>
    request<{ block: Block }>("/books/supplement", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id, topic }),
    }),

  setPageChatSession: (book_id: string, page_id: string, session_id: string) =>
    request<{ book: Book }>("/books/page-chat-session", {
      method: "POST",
      body: JSON.stringify({ book_id, page_id, session_id }),
    }),

  /** Re-queue unfinished pages, keeping everything already compiled. */
  resume: (book_id: string) =>
    request<{ pages: Page[] }>("/books/resume", {
      method: "POST",
      body: JSON.stringify({ book_id }),
    }),

  /** Destructive: discards every page and regenerates from the spine. */
  rebuild: (book_id: string, auto_compile = true) =>
    request<{ pages: Page[] }>("/books/rebuild", {
      method: "POST",
      body: JSON.stringify({ book_id, auto_compile }),
    }),

  health: (book_id: string) =>
    request<{
      kb_drift: {
        book_id: string;
        has_drift: boolean;
        new_kbs?: string[];
        removed_kbs?: string[];
        changed_kbs?: string[];
        stale_page_ids?: string[];
      };
      log_health: {
        book_id: string;
        total_entries: number;
        error_entries: number;
        block_failures: number;
        last_compile_at?: string;
        last_error_at?: string;
        repeated_failures?: { signature: string; count: number }[];
      };
    }>(`/books/${encodeURIComponent(book_id)}/health`),

  /** Mark the current KB state as seen. Rejected with 409 while pages the last
   *  drift flagged are still awaiting recompilation; `force` dismisses anyway. */
  refreshFingerprints: (book_id: string, force = false) =>
    request<{
      book_id: string;
      kb_fingerprints: Record<string, string>;
      stale_page_ids: string[];
    }>(
      `/books/${encodeURIComponent(book_id)}/refresh-fingerprints${
        force ? "?force=true" : ""
      }`,
      { method: "POST" },
    ),

  listLearningCaptures: (book_id: string, status?: LearningCaptureStatus) =>
    request<{ captures: LearningCapture[] }>(
      `/books/${encodeURIComponent(
        book_id,
      )}/learning-captures${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),

  createLearningCapture: (
    book_id: string,
    payload: {
      page_id: string;
      block_id: string;
      source_text: string;
      context_before?: string;
      context_after?: string;
      source_locator?: string;
      book_title?: string;
      chapter_title?: string;
      user_note?: string;
      status?: LearningCaptureStatus;
    },
  ) =>
    request<{ capture: LearningCapture }>(
      `/books/${encodeURIComponent(book_id)}/learning-captures`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),

  updateLearningCapture: (
    book_id: string,
    capture_id: string,
    payload: {
      status?: LearningCaptureStatus;
      user_note?: string;
      rejected_reason?: string;
    },
  ) =>
    request<{ capture: LearningCapture }>(
      `/books/${encodeURIComponent(book_id)}/learning-captures/${encodeURIComponent(
        capture_id,
      )}`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
    ),
};

export interface LegacyChatSession {
  session_id: string;
  messages?: Array<{ role: string; content: string }>;
}

export async function getLegacyChatSession(
  session_id: string,
): Promise<LegacyChatSession | null> {
  const res = await apiFetch(
    apiUrl(`/api/v1/chat/sessions/${encodeURIComponent(session_id)}`),
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`chat session ${session_id} → ${res.status}`);
  return (await res.json()) as LegacyChatSession;
}

// Re-exported so callers can keep importing the event type from book-api.
export type { BookWsEvent } from "@/lib/book-ws-operation";
