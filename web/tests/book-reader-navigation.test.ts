import test from "node:test";
import assert from "node:assert/strict";
import {
  chapterReadingPercent,
  sequentialReadTarget,
} from "../lib/book-reader-navigation";

test("long chapters advance by one readable screen with overlap", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 0, scrollHeight: 3000, clientHeight: 600 },
      "next",
    ),
    540,
  );
});

test("long chapters retreat by one readable screen with overlap", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 700, scrollHeight: 3000, clientHeight: 600 },
      "previous",
    ),
    160,
  );
});

test("scroll targets clamp at chapter boundaries", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 2_300, scrollHeight: 3_000, clientHeight: 600 },
      "next",
    ),
    2_400,
  );
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 300, scrollHeight: 3_000, clientHeight: 600 },
      "previous",
    ),
    0,
  );
});

test("chapter edges and non-scrolling chapters request a page turn", () => {
  const atStart = { scrollTop: 0, scrollHeight: 3_000, clientHeight: 600 };
  const atEnd = { scrollTop: 2_400, scrollHeight: 3_000, clientHeight: 600 };
  const withoutScroll = {
    scrollTop: 0,
    scrollHeight: 600,
    clientHeight: 600,
  };

  assert.equal(sequentialReadTarget(atStart, "previous"), null);
  assert.equal(sequentialReadTarget(atEnd, "next"), null);
  assert.equal(sequentialReadTarget(withoutScroll, "next"), null);
  assert.equal(sequentialReadTarget(withoutScroll, "previous"), null);
});

test("hidden or detached readers do not fabricate scroll positions", () => {
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 0, scrollHeight: 3_000, clientHeight: 0 },
      "next",
    ),
    null,
  );
  assert.equal(
    sequentialReadTarget(
      { scrollTop: 0, scrollHeight: 3_000, clientHeight: 1 },
      "previous",
    ),
    null,
  );
});

test("sub-pixel edges do not hide an unread remainder", () => {
  const nearEnd = { scrollTop: 2_399, scrollHeight: 3_000, clientHeight: 600 };
  assert.equal(sequentialReadTarget(nearEnd, "next"), null);
  assert.equal(chapterReadingPercent(nearEnd), 100);
});

test("chapter progress is bounded and zero when scrolling is unavailable", () => {
  assert.equal(
    chapterReadingPercent({
      scrollTop: 1_200,
      scrollHeight: 3_000,
      clientHeight: 600,
    }),
    50,
  );
  assert.equal(
    chapterReadingPercent({
      scrollTop: -20,
      scrollHeight: 3_000,
      clientHeight: 600,
    }),
    0,
  );
  assert.equal(
    chapterReadingPercent({
      scrollTop: 9_999,
      scrollHeight: 3_000,
      clientHeight: 600,
    }),
    100,
  );
  assert.equal(
    chapterReadingPercent({
      scrollTop: 0,
      scrollHeight: 601,
      clientHeight: 600,
    }),
    0,
  );
});
