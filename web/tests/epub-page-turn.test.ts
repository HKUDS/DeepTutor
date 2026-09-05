import assert from "node:assert/strict";
import test from "node:test";

import {
  bufferEpubPageTurn,
  canStartEpubPageTurn,
  directionForEpubLayout,
  epubEdgeTapDirection,
  epubPageTurnDirectionForDelta,
  epubPageTurnProgress,
  epubPageTurnSettleDuration,
  epubSpreadModeForWidth,
  hrefKey,
  isEpubPageTurnGesture,
  locatorForEpubHref,
  resolveEpubPageTurnRelease,
  resolveEpubPageTurnSwipe,
  shouldCommitEpubPageTurn,
} from "../lib/epub-page-turn";

test("book spread needs both the desktop breakpoint and useful leaf width", () => {
  assert.equal(epubSpreadModeForWidth(899), "single");
  assert.equal(epubSpreadModeForWidth(900), "double");
  assert.equal(epubSpreadModeForWidth(1440), "double");
});

test("page-turn guard respects animation lock and book boundaries", () => {
  assert.equal(
    canStartEpubPageTurn("previous", false, { atStart: true, atEnd: false }),
    false,
  );
  assert.equal(
    canStartEpubPageTurn("next", false, { atStart: true, atEnd: false }),
    true,
  );
  assert.equal(
    canStartEpubPageTurn("next", false, { atStart: false, atEnd: true }),
    false,
  );
  assert.equal(
    canStartEpubPageTurn("next", true, { atStart: false, atEnd: false }),
    false,
  );
});

test("horizontal swipes turn pages but vertical scrolls do not", () => {
  assert.equal(resolveEpubPageTurnSwipe(200, 100, 100, 105), "next");
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 200, 105), "previous");
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 140, 100), null);
  assert.equal(resolveEpubPageTurnSwipe(100, 100, 160, 180), null);
});

test("a touch drag activates only after horizontal intent is clear", () => {
  assert.equal(isEpubPageTurnGesture(9, 0), false);
  assert.equal(isEpubPageTurnGesture(12, 4), true);
  assert.equal(isEpubPageTurnGesture(12, 11), false);
  assert.equal(epubPageTurnProgress(90, 300), 0.3);
  assert.equal(epubPageTurnProgress(500, 300), 1);
  assert.equal(epubPageTurnProgress(10, 0), 0);
});

test("drag release commits by distance or by a deliberate fling", () => {
  assert.equal(
    shouldCommitEpubPageTurn({ progress: 0.28, velocityX: 0, distanceX: 84 }),
    true,
  );
  assert.equal(
    shouldCommitEpubPageTurn({ progress: 0.1, velocityX: 0.55, distanceX: 18 }),
    true,
  );
  assert.equal(
    shouldCommitEpubPageTurn({
      progress: 0.27,
      velocityX: 0.54,
      distanceX: 80,
    }),
    false,
  );
  assert.equal(
    shouldCommitEpubPageTurn({ progress: 0.1, velocityX: -0.7, distanceX: 30 }),
    false,
  );
  assert.equal(epubPageTurnSettleDuration(0), 220);
  assert.equal(epubPageTurnSettleDuration(1), 140);
});

test("release settles normally and becomes instant with reduced motion", () => {
  const release = {
    cancelled: false,
    hasSelection: false,
    directionMatches: true,
    progress: 0.12,
    velocityX: 0.2,
    distanceX: 36,
  };
  assert.equal(
    resolveEpubPageTurnRelease({ ...release, reducedMotion: false }),
    "settle",
  );
  assert.equal(
    resolveEpubPageTurnRelease({ ...release, reducedMotion: true }),
    "idle",
  );
  assert.equal(
    resolveEpubPageTurnRelease({
      ...release,
      progress: 0.28,
      reducedMotion: true,
    }),
    "commit",
  );
});

test("drag and edge directions follow the publication direction", () => {
  assert.equal(epubPageTurnDirectionForDelta(-30, false), "next");
  assert.equal(epubPageTurnDirectionForDelta(30, false), "previous");
  assert.equal(epubPageTurnDirectionForDelta(-30, true), "previous");
  assert.equal(epubPageTurnDirectionForDelta(30, true), "next");
  assert.equal(epubEdgeTapDirection(20, 1000, false), "previous");
  assert.equal(epubEdgeTapDirection(980, 1000, false), "next");
  assert.equal(epubEdgeTapDirection(20, 1000, true), "next");
  assert.equal(epubEdgeTapDirection(500, 1000, false), null);
});

test("only one matching request is buffered while a page settles", () => {
  assert.equal(bufferEpubPageTurn("next", null, "next"), "next");
  assert.equal(bufferEpubPageTurn("next", null, "previous"), null);
  assert.equal(bufferEpubPageTurn("next", "next", "next"), "next");
});

test("RTL reverses physical rendition direction", () => {
  assert.equal(directionForEpubLayout("next", false), "next");
  assert.equal(directionForEpubLayout("next", true), "previous");
  assert.equal(directionForEpubLayout("previous", true), "next");
});

test("source hrefs map to the server locator despite encoding and base paths", () => {
  const refs = [
    { locator: 1, source_href: "OEBPS/chapters/one.xhtml" },
    { locator: 2, source_href: "OEBPS/chapters/two%20words.xhtml" },
  ];
  assert.equal(locatorForEpubHref("OEBPS/chapters/one.xhtml#p1", refs), 1);
  assert.equal(locatorForEpubHref("chapters/two words.xhtml", refs), 2);
  assert.equal(locatorForEpubHref("missing.xhtml", refs), 0);
  assert.equal(hrefKey("./chapter.xhtml#here"), "chapter.xhtml");
});
