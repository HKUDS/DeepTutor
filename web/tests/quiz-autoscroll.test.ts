import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const quizViewer = readFileSync(
  path.resolve(process.cwd(), "components/quiz/QuizViewer.tsx"),
  "utf8",
);
const autoScroll = readFileSync(
  path.resolve(process.cwd(), "hooks/useChatAutoScroll.ts"),
  "utf8",
);

test("QuizViewer marks itself as late-growing chat content", () => {
  assert.match(quizViewer, /data-chat-grow="quiz"/);
});

test("late-growing viewers use native content-size observation, not a deadline", () => {
  assert.match(autoScroll, /new ResizeObserver\(schedule\)/);
  assert.match(autoScroll, /container\.children/);
  assert.doesNotMatch(autoScroll, /AUTOSCROLL_WINDOW_MS/);
});

test("one observer lifecycle owns follow throughout streaming and settlement", () => {
  const observers = autoScroll.match(/new MutationObserver\(/g) ?? [];
  assert.equal(observers.length, 1, "expected one content observer lifecycle");
  assert.match(autoScroll, /pointerdown/);
});
