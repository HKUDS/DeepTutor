import test from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_READING_HISTORY,
  READING_HISTORY_LIMIT,
  moveReadingHistory,
  parseReadingHistory,
  pushReadingLocation,
  readingHistoryStorageKey,
  replaceCurrentReadingLocation,
  selectReadingHistoryIndex,
} from "../lib/reading-location-history";

const entry = (materialId: string, locator: number, title = materialId) => ({
  materialId,
  locator,
  title,
});

test("pushes cross-material locations and removes the forward branch", () => {
  let history = pushReadingLocation(
    EMPTY_READING_HISTORY,
    entry("aaaaaaaaaaaaaaaa", 1),
  );
  history = pushReadingLocation(history, entry("bbbbbbbbbbbbbbbb", 2));
  history = moveReadingHistory(history, -1);
  history = pushReadingLocation(history, entry("cccccccccccccccc", 3));

  assert.deepEqual(
    history.entries.map(({ materialId }) => materialId),
    ["aaaaaaaaaaaaaaaa", "cccccccccccccccc"],
  );
  assert.equal(history.index, 1);
});

test("manual scrolling replaces current instead of adding entries", () => {
  const first = pushReadingLocation(
    EMPTY_READING_HISTORY,
    entry("aaaaaaaaaaaaaaaa", 1, "A"),
  );
  const scrolled = replaceCurrentReadingLocation(
    first,
    entry("aaaaaaaaaaaaaaaa", 8, "A"),
  );

  assert.equal(scrolled.entries.length, 1);
  assert.equal(scrolled.entries[0].locator, 8);
});

test("consecutive duplicate pushes refresh metadata without growing", () => {
  const first = pushReadingLocation(
    EMPTY_READING_HISTORY,
    entry("aaaaaaaaaaaaaaaa", 2, "Old"),
  );
  const duplicate = pushReadingLocation(
    first,
    entry("aaaaaaaaaaaaaaaa", 2, "New"),
  );

  assert.equal(duplicate.entries.length, 1);
  assert.equal(duplicate.entries[0].title, "New");
});

test("caps history at fifty entries", () => {
  let history = EMPTY_READING_HISTORY;
  for (let locator = 1; locator <= READING_HISTORY_LIMIT + 7; locator += 1) {
    history = pushReadingLocation(history, entry("aaaaaaaaaaaaaaaa", locator));
  }
  assert.equal(history.entries.length, READING_HISTORY_LIMIT);
  assert.equal(history.entries[0].locator, 8);
  assert.equal(history.index, READING_HISTORY_LIMIT - 1);
});

test("parsing corrupt storage degrades to empty and filters unsafe entries", () => {
  assert.deepEqual(parseReadingHistory("not json"), EMPTY_READING_HISTORY);
  const parsed = parseReadingHistory(
    JSON.stringify({
      entries: [
        entry("../../etc", 1),
        entry("AAAAAAAAAAAAAAAA", 2, "A"),
        entry("bbbbbbbbbbbbbbbb", 0),
      ],
      index: 2,
    }),
  );
  assert.deepEqual(parsed, {
    entries: [entry("aaaaaaaaaaaaaaaa", 2, "A")],
    index: 0,
  });
});

test("parsing preserves the selected valid entry when later rows are corrupt", () => {
  const parsed = parseReadingHistory(
    JSON.stringify({
      entries: [
        entry("aaaaaaaaaaaaaaaa", 1, "A"),
        entry("bbbbbbbbbbbbbbbb", 2, "B"),
        entry("not-a-material-id", 3),
      ],
      index: 1,
    }),
  );

  assert.equal(parsed.index, 1);
  assert.equal(parsed.entries[parsed.index].title, "B");
});

test("parsing collapses persisted consecutive duplicates", () => {
  const parsed = parseReadingHistory(
    JSON.stringify({
      entries: [
        entry("aaaaaaaaaaaaaaaa", 1, "Old"),
        entry("aaaaaaaaaaaaaaaa", 1, "New"),
        entry("bbbbbbbbbbbbbbbb", 2, "B"),
      ],
      index: 1,
    }),
  );

  assert.deepEqual(parsed.entries, [
    entry("aaaaaaaaaaaaaaaa", 1, "New"),
    entry("bbbbbbbbbbbbbbbb", 2, "B"),
  ]);
  assert.equal(parsed.index, 0);
});

test("back, forward and direct selection stay bounded", () => {
  let history = pushReadingLocation(
    EMPTY_READING_HISTORY,
    entry("aaaaaaaaaaaaaaaa", 1),
  );
  history = pushReadingLocation(history, entry("bbbbbbbbbbbbbbbb", 1));
  assert.equal(moveReadingHistory(history, 1).index, 1);
  assert.equal(moveReadingHistory(history, -1).index, 0);
  assert.equal(selectReadingHistoryIndex(history, 0).index, 0);
  assert.equal(selectReadingHistoryIndex(history, 99), history);
});

test("storage keys are isolated by chat session", () => {
  assert.notEqual(
    readingHistoryStorageKey("session-a"),
    readingHistoryStorageKey("session-b"),
  );
});

test("navigation state preserves PDF, EPUB, and Markdown material metadata", () => {
  let history = EMPTY_READING_HISTORY;
  history = pushReadingLocation(history, {
    ...entry("aaaaaaaaaaaaaaaa", 4, "PDF"),
    source: { mime: "application/pdf", renderMode: "pdf", unit: "page" },
  });
  history = pushReadingLocation(history, {
    ...entry("bbbbbbbbbbbbbbbb", 2, "EPUB"),
    source: {
      mime: "application/epub+zip",
      renderMode: "epub",
      unit: "chapter",
    },
  });
  history = pushReadingLocation(history, {
    ...entry("cccccccccccccccc", 7, "Markdown"),
    source: { mime: "text/markdown", renderMode: "text", unit: "section" },
  });

  history = moveReadingHistory(history, -1);
  assert.deepEqual(history.entries[history.index], {
    ...entry("bbbbbbbbbbbbbbbb", 2, "EPUB"),
    source: {
      mime: "application/epub+zip",
      renderMode: "epub",
      unit: "chapter",
    },
  });
  history = moveReadingHistory(history, -1);
  assert.equal(history.entries[history.index].source?.renderMode, "pdf");
  history = moveReadingHistory(history, 1);
  history = moveReadingHistory(history, 1);
  assert.equal(history.entries[history.index].source?.mime, "text/markdown");
});
