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

test("the post-stream window extends only for late-mounted viewers", () => {
  assert.match(autoScroll, /POST_STREAM_AUTOSCROLL_WINDOW_MS = 4000/);
  assert.match(autoScroll, /LATE_VIEWER_AUTOSCROLL_WINDOW_MS = 12_000/);
  // The extension must be gated on a newly appearing tagged node, not on one
  // merely being present — an old quiz card must not keep re-pinning the user.
  assert.match(autoScroll, /\[data-chat-grow\]/);
  assert.match(autoScroll, /tagged > growTargets/);
});

test("one post-stream observer owns the pin, not two", () => {
  // A second parallel observer would race the first and re-pin post-turn user
  // interactions that the short window deliberately excludes.
  const observers = autoScroll.match(/new MutationObserver\(/g) ?? [];
  assert.equal(observers.length, 2, "expected one streaming + one post-stream");
});
