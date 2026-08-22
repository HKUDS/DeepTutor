import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  createKidsPageTurnGestureTracker,
  getKidsPageTurnDirectionForLayout,
  resolveKidsPageTurnSwipe,
  shouldAllowKidsPageTurnGesture,
  shouldAllowKidsPageTurnKeyboard,
} from "../lib/kids-learning/page-turn";

const epubReaderSource = readFileSync(
  path.resolve(process.cwd(), "app/kids/[documentId]/page.tsx"),
  "utf8",
);
const interactiveReaderSource = readFileSync(
  path.resolve(process.cwd(), "app/kids/p/[profileId]/book/[bookId]/page.tsx"),
  "utf8",
);
const globalCss = readFileSync(path.resolve(process.cwd(), "app/globals.css"), "utf8");
const packageJson = JSON.parse(readFileSync(path.resolve(process.cwd(), "package.json"), "utf8"));
const packageLock = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "package-lock.json"), "utf8"),
);

test("kids page-turn swipes require a decisive horizontal movement", () => {
  assert.equal(resolveKidsPageTurnSwipe(100, 100, 51, 101), "next");
  assert.equal(resolveKidsPageTurnSwipe(100, 100, 149, 100), "previous");
  assert.equal(resolveKidsPageTurnSwipe(100, 100, 147, 100), null);
  assert.equal(resolveKidsPageTurnSwipe(100, 100, 180, 100), "previous");
  assert.equal(resolveKidsPageTurnSwipe(100, 100, 180, 180), null);
  assert.equal(resolveKidsPageTurnSwipe(100, 100, 20, 200), null);
});

test("kids page-turn tracker only accepts the pointer that started the gesture", () => {
  const tracker = createKidsPageTurnGestureTracker();
  tracker.begin(7, 100, 100);
  assert.equal(tracker.end(8, 200, 100), null);
  assert.equal(tracker.end(7, 200, 100), "previous");
  assert.equal(tracker.consumeClick(), true);
  assert.equal(tracker.consumeClick(), false);

  tracker.begin(9, 100, 100);
  tracker.end(9, 100, 100);
  assert.equal(tracker.consumeClick(), false);
});

test("RTL kids books reverse physical page-turn directions", () => {
  assert.equal(getKidsPageTurnDirectionForLayout("next", false), "next");
  assert.equal(getKidsPageTurnDirectionForLayout("previous", false), "previous");
  assert.equal(getKidsPageTurnDirectionForLayout("next", true), "previous");
  assert.equal(getKidsPageTurnDirectionForLayout("previous", true), "next");
});

test("keyboard page turns allow navigation buttons but not editable widgets", () => {
  const button = { closest: (selector: string) => (selector.includes("button") ? "button" : null) };
  const input = { closest: (selector: string) => (selector.includes("input") ? "input" : null) };
  const buttonTarget = button as unknown as EventTarget;
  const inputTarget = input as unknown as EventTarget;
  assert.equal(shouldAllowKidsPageTurnGesture(buttonTarget), false);
  assert.equal(shouldAllowKidsPageTurnKeyboard(buttonTarget), true);
  assert.equal(shouldAllowKidsPageTurnKeyboard(inputTarget), false);
});

test("kids EPUB reader adds safe page-turn zones without blocking iframe interaction", () => {
  assert.match(epubReaderSource, /pageTurnHotzone/);
  assert.match(epubReaderSource, /width: "min\(18vw, 96px\)"/);
  assert.match(epubReaderSource, /isRTL=\{isRtl\}/);
  assert.match(epubReaderSource, /rendition\.hooks\.content\.register/);
  assert.match(epubReaderSource, /addEventListener\("touchstart"/);
  assert.match(epubReaderSource, /addEventListener\("touchend"/);
  assert.match(epubReaderSource, /resolveKidsPageTurnSwipe/);
  assert.doesNotMatch(epubReaderSource, /swipeable=/);
  assert.match(epubReaderSource, /allowScriptedContent: false/);
});

test("kids interactive reader supports complete page-turn behavior and request safety", () => {
  assert.match(interactiveReaderSource, /aria-label=\{PREVIOUS_PAGE_LABEL\}/);
  assert.match(interactiveReaderSource, /aria-label=\{NEXT_PAGE_LABEL\}/);
  assert.match(interactiveReaderSource, /window\.addEventListener\("keydown", onKeyDown\)/);
  assert.match(interactiveReaderSource, /pageLoadTokenRef/);
  assert.match(interactiveReaderSource, /if \(loadToken !== pageLoadTokenRef\.current\) return;/);
  assert.match(interactiveReaderSource, /aria-busy=\{pageLoading\}/);
  assert.match(interactiveReaderSource, /height: "100dvh"/);
  assert.match(interactiveReaderSource, /minHeight: 48/);
  assert.match(interactiveReaderSource, /data-kids-no-page-swipe/);
  assert.match(interactiveReaderSource, /shouldAllowKidsPageTurnGesture/);
  assert.match(globalCss, /\.kids-interactive-footer/);
  assert.match(globalCss, /padding-bottom:\s*max\(12px,\s*env\(safe-area-inset-bottom\)\)/);
});

test("kids EPUB dependency is declared for clean installs", () => {
  assert.equal(packageJson.dependencies["react-reader"], "^2.0.15");
  assert.equal(
    packageLock.packages?.["node_modules/react-reader"]?.version,
    "2.0.15",
  );
});
