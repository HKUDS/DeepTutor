import type { CoWriterDocument } from "@/lib/co-writer-api";

export interface ChatMarkdownNoteInput {
  title: string;
  content: string;
}

export interface SavedChatMarkdownNote {
  id: string;
  title: string;
  content: string;
}

export interface ChatMarkdownNoteDraft {
  title: string;
  content: string;
  saved: SavedChatMarkdownNote | null;
}

export const EMPTY_CHAT_MARKDOWN_NOTE_DRAFT: ChatMarkdownNoteDraft = {
  title: "",
  content: "",
  saved: null,
};

const CHAT_MARKDOWN_NOTE_KEY_PREFIX = "dt:chat-markdown-note:";

type ChatMarkdownNoteStorage = Pick<
  Storage,
  "getItem" | "setItem" | "removeItem"
>;

function storageKey(ownerId: string, sessionId: string | null): string {
  const owner = encodeURIComponent(ownerId);
  const session = sessionId ? encodeURIComponent(sessionId) : "pending";
  return `${CHAT_MARKDOWN_NOTE_KEY_PREFIX}${owner}:${session}`;
}

function parseDraft(raw: string | null): ChatMarkdownNoteDraft | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<ChatMarkdownNoteDraft>;
    if (
      typeof value.title !== "string" ||
      typeof value.content !== "string" ||
      (value.saved !== null &&
        (typeof value.saved !== "object" ||
          typeof value.saved?.id !== "string" ||
          typeof value.saved.title !== "string" ||
          typeof value.saved.content !== "string"))
    ) {
      return null;
    }
    return {
      title: value.title,
      content: value.content,
      saved: value.saved
        ? {
            id: value.saved.id,
            title: value.saved.title,
            content: value.saved.content,
          }
        : null,
    };
  } catch {
    return null;
  }
}

export function loadChatMarkdownNoteDraft(
  ownerId: string,
  sessionId: string | null,
  storage: ChatMarkdownNoteStorage | null = typeof window === "undefined"
    ? null
    : window.localStorage,
): ChatMarkdownNoteDraft {
  if (!storage) return EMPTY_CHAT_MARKDOWN_NOTE_DRAFT;

  const key = storageKey(ownerId, sessionId);
  const draft = parseDraft(storage.getItem(key));
  if (!sessionId) return draft ?? EMPTY_CHAT_MARKDOWN_NOTE_DRAFT;

  // A note started before a new chat receives its session id is adopted by
  // that session instead of leaking into the next new chat.
  const pending = parseDraft(storage.getItem(storageKey(ownerId, null)));
  if (!draft && pending) {
    try {
      storage.setItem(key, JSON.stringify(pending));
      storage.removeItem(storageKey(ownerId, null));
    } catch {
      // If adoption cannot be persisted, return the pending draft so this
      // session still gets the content in memory.
    }
    return pending;
  }
  return draft ?? EMPTY_CHAT_MARKDOWN_NOTE_DRAFT;
}

export function saveChatMarkdownNoteDraft(
  ownerId: string,
  sessionId: string | null,
  draft: ChatMarkdownNoteDraft,
  storage: ChatMarkdownNoteStorage | null = typeof window === "undefined"
    ? null
    : window.localStorage,
): void {
  if (!storage) return;
  try {
    storage.setItem(storageKey(ownerId, sessionId), JSON.stringify(draft));
  } catch {
    // Storage can be unavailable or full. The in-memory draft remains usable.
  }
}

export interface ChatMarkdownNoteStore {
  create(payload: {
    title?: string | null;
    content?: string;
  }): Promise<CoWriterDocument>;
  update(
    docId: string,
    payload: { title?: string | null; content?: string | null },
  ): Promise<CoWriterDocument>;
}

export function isChatMarkdownNoteDirty(
  input: ChatMarkdownNoteInput,
  saved: SavedChatMarkdownNote | null,
): boolean {
  const title = input.title.trim();
  if (!saved) return Boolean(title || input.content.trim());
  return title !== saved.title.trim() || input.content !== saved.content;
}

export async function persistChatMarkdownNote(
  input: ChatMarkdownNoteInput,
  saved: SavedChatMarkdownNote | null,
  store: ChatMarkdownNoteStore,
): Promise<SavedChatMarkdownNote> {
  const title = input.title.trim();
  const payload = { title: title || null, content: input.content };
  const document = saved
    ? await store.update(saved.id, payload)
    : await store.create(payload);

  return {
    id: document.id,
    title: document.title,
    content: document.content ?? "",
  };
}

export function reconcileChatMarkdownNoteAfterSave(
  latest: ChatMarkdownNoteInput,
  request: ChatMarkdownNoteInput,
  saved: SavedChatMarkdownNote,
): ChatMarkdownNoteInput {
  return {
    title: latest.title === request.title ? saved.title : latest.title,
    content:
      latest.content === request.content ? saved.content : latest.content,
  };
}
