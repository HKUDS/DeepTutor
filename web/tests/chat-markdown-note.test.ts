import test from "node:test";
import assert from "node:assert/strict";
import {
  loadChatMarkdownNoteDraft,
  isChatMarkdownNoteDirty,
  persistChatMarkdownNote,
  reconcileChatMarkdownNoteAfterSave,
  saveChatMarkdownNoteDraft,
  type ChatMarkdownNoteStore,
  type SavedChatMarkdownNote,
} from "../lib/chat-markdown-note";
import type { CoWriterDocument } from "../lib/co-writer-api";

function document(fields: Partial<CoWriterDocument> = {}): CoWriterDocument {
  return {
    id: "doc-1",
    title: "Note",
    content: "# Note",
    created_at: 1,
    updated_at: 2,
    ...fields,
  };
}

test("a blank unsaved markdown note is not saveable", () => {
  assert.equal(
    isChatMarkdownNoteDirty({ title: "  ", content: " " }, null),
    false,
  );
});

test("an unsaved markdown note with a title or content is dirty", () => {
  assert.equal(
    isChatMarkdownNoteDirty({ title: "Idea", content: "" }, null),
    true,
  );
  assert.equal(
    isChatMarkdownNoteDirty({ title: "", content: "# Idea" }, null),
    true,
  );
});

test("saved markdown notes compare trimmed titles and exact content", () => {
  const saved: SavedChatMarkdownNote = {
    id: "doc-1",
    title: "Note",
    content: "# Note",
  };

  assert.equal(
    isChatMarkdownNoteDirty({ title: " Note ", content: "# Note" }, saved),
    false,
  );
  assert.equal(
    isChatMarkdownNoteDirty({ title: "New", content: "# Note" }, saved),
    true,
  );
  assert.equal(
    isChatMarkdownNoteDirty({ title: "Note", content: "# New" }, saved),
    true,
  );
});

test("the first markdown-note save creates a Co-Writer document", async () => {
  const created: string[] = [];
  const updated: string[] = [];
  const store: ChatMarkdownNoteStore = {
    async create(payload) {
      created.push(JSON.stringify(payload));
      return document({ id: "new-doc", title: "Derived", content: "# Idea" });
    },
    async update(docId) {
      updated.push(docId);
      return document();
    },
  };

  const saved = await persistChatMarkdownNote(
    { title: "  ", content: "# Idea" },
    null,
    store,
  );

  assert.deepEqual(created, ['{"title":null,"content":"# Idea"}']);
  assert.deepEqual(updated, []);
  assert.deepEqual(saved, {
    id: "new-doc",
    title: "Derived",
    content: "# Idea",
  });
});

test("later markdown-note saves update the existing Co-Writer document", async () => {
  const created: string[] = [];
  const updated: Array<{ docId: string; payload: string }> = [];
  const store: ChatMarkdownNoteStore = {
    async create() {
      created.push("create");
      return document();
    },
    async update(docId, payload) {
      updated.push({ docId, payload: JSON.stringify(payload) });
      return document({
        id: docId,
        title: payload.title ?? "",
        content: payload.content ?? "",
      });
    },
  };
  const saved: SavedChatMarkdownNote = {
    id: "doc-1",
    title: "Note",
    content: "# Note",
  };

  const next = await persistChatMarkdownNote(
    { title: " New note ", content: "# Updated" },
    saved,
    store,
  );

  assert.deepEqual(created, []);
  assert.deepEqual(updated, [
    { docId: "doc-1", payload: '{"title":"New note","content":"# Updated"}' },
  ]);
  assert.deepEqual(next, {
    id: "doc-1",
    title: "New note",
    content: "# Updated",
  });
});

test("a save response does not overwrite edits made while it was in flight", () => {
  const reconciled = reconcileChatMarkdownNoteAfterSave(
    { title: "New title", content: "# Newer content" },
    { title: "Old title", content: "# Older content" },
    { id: "doc-1", title: "Server title", content: "# Older content" },
  );

  assert.deepEqual(reconciled, {
    title: "New title",
    content: "# Newer content",
  });
});

test("markdown-note drafts persist and restore by chat session", () => {
  const storage = new Map<string, string>();
  const noteStorage = createStorage(storage);

  saveChatMarkdownNoteDraft(
    "user-1",
    "session-1",
    {
      title: "Session note",
      content: "# Session content",
      saved: { id: "doc-1", title: "Session note", content: "# Session" },
    },
    noteStorage,
  );

  assert.deepEqual(
    loadChatMarkdownNoteDraft("user-1", "session-1", noteStorage),
    {
      title: "Session note",
      content: "# Session content",
      saved: { id: "doc-1", title: "Session note", content: "# Session" },
    },
  );
  assert.deepEqual(
    loadChatMarkdownNoteDraft("user-1", "session-2", noteStorage),
    {
      title: "",
      content: "",
      saved: null,
    },
  );
});

test("a pending markdown-note draft is adopted by its chat session", () => {
  const storage = new Map<string, string>();
  const noteStorage = createStorage(storage);

  saveChatMarkdownNoteDraft(
    "user-1",
    null,
    {
      title: "Pending note",
      content: "# Pending",
      saved: null,
    },
    noteStorage,
  );

  assert.deepEqual(
    loadChatMarkdownNoteDraft("user-1", "session-1", noteStorage),
    {
      title: "Pending note",
      content: "# Pending",
      saved: null,
    },
  );
  assert.equal(storage.has("dt:chat-markdown-note:user-1:pending"), false);
  assert.equal(
    storage.get("dt:chat-markdown-note:user-1:session-1"),
    JSON.stringify({
      title: "Pending note",
      content: "# Pending",
      saved: null,
    }),
  );
});

test("markdown-note drafts are isolated when the signed-in account changes", () => {
  const storage = new Map<string, string>();
  const noteStorage = createStorage(storage);
  const draft = {
    title: "Private note",
    content: "Only user one can read this",
    saved: null,
  };

  saveChatMarkdownNoteDraft("user-1", "session-1", draft, noteStorage);

  assert.deepEqual(
    loadChatMarkdownNoteDraft("user-2", "session-1", noteStorage),
    { title: "", content: "", saved: null },
  );
  assert.deepEqual(
    loadChatMarkdownNoteDraft("user-1", "session-1", noteStorage),
    draft,
  );
});

function createStorage(
  values: Map<string, string>,
): Parameters<typeof saveChatMarkdownNoteDraft>[3] {
  return {
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}
