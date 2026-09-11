import assert from "node:assert/strict";
import test from "node:test";

import {
  applyEditorEdit,
  clampPanelRatio,
  createEditorHistory,
  interpolateScrollMarker,
  redoEditorEdit,
  replaceSelectedText,
  shouldCommitAutosave,
  undoEditorEdit,
} from "../features/co-writer/model/editor-state";
import {
  DRAFT_STORAGE_PREFIX,
  LEGACY_DRAFT_STORAGE_PREFIX,
  clearDraft,
  loadDraft,
  saveDraft,
  type KeyValueStorage,
} from "../features/co-writer/storage/drafts";

class MemoryStorage implements KeyValueStorage {
  readonly values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
}

test("typing in one group creates one undo point and redo restores it", () => {
  let state = createEditorHistory("a");
  state = applyEditorEdit(state, "ab", { group: "typing-1" });
  state = applyEditorEdit(state, "abc", { group: "typing-1" });
  assert.deepEqual(state.undoStack, ["a"]);
  state = undoEditorEdit(state);
  assert.equal(state.content, "a");
  state = redoEditorEdit(state);
  assert.equal(state.content, "abc");
});

test("a new edit invalidates redo history", () => {
  let state = applyEditorEdit(createEditorHistory("a"), "b");
  state = undoEditorEdit(state);
  assert.equal(state.redoStack.length, 1);
  state = applyEditorEdit(state, "c");
  assert.deepEqual(state.redoStack, []);
});

test("selected text replacement rejects stale or malformed ranges", () => {
  const range = { start: 6, end: 11, text: "world", snapshot: "hello world" };
  assert.equal(
    replaceSelectedText("hello world", range, "reader"),
    "hello reader",
  );
  assert.equal(replaceSelectedText("hello world!", range, "reader"), null);
  assert.equal(
    replaceSelectedText("hello world", { ...range, text: "other" }, "reader"),
    null,
  );
});

test("panel ratios clamp and scroll markers interpolate", () => {
  assert.equal(clampPanelRatio(-1), 0.18);
  assert.equal(clampPanelRatio(2), 0.82);
  assert.equal(clampPanelRatio(Number.NaN), 0.5);
  assert.equal(
    interpolateScrollMarker(
      [
        { source: 0, target: 20 },
        { source: 100, target: 220 },
      ],
      25,
    ),
    70,
  );
});

test("autosave results only commit for the latest revision", () => {
  assert.equal(shouldCommitAutosave(3, 4), false);
  assert.equal(shouldCommitAutosave(4, 4), true);
});

test("draft storage validates v2 data and migrates the legacy raw draft", () => {
  const storage = new MemoryStorage();
  storage.setItem(`${LEGACY_DRAFT_STORAGE_PREFIX}doc/a`, "legacy text");
  const draft = loadDraft(storage, "doc/a");
  assert.equal(draft?.content, "legacy text");
  assert.equal(draft?.version, 2);
  assert.equal(storage.getItem(`${LEGACY_DRAFT_STORAGE_PREFIX}doc/a`), null);
  assert.notEqual(storage.getItem(`${DRAFT_STORAGE_PREFIX}doc%2Fa`), null);

  saveDraft(storage, "doc/a", "new text", 2, 123);
  assert.deepEqual(loadDraft(storage, "doc/a"), {
    version: 2,
    docId: "doc/a",
    content: "new text",
    revision: 2,
    updatedAt: 123,
  });
  assert.equal(clearDraft(storage, "doc/a"), true);
  assert.equal(loadDraft(storage, "doc/a"), null);
});

test("draft storage failures are nonfatal", () => {
  const broken: KeyValueStorage = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("quota");
    },
    removeItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(loadDraft(broken, "doc"), null);
  assert.equal(saveDraft(broken, "doc", "text", 1), null);
  assert.equal(clearDraft(broken, "doc"), false);
});
