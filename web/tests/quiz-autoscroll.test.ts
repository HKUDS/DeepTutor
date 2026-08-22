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

test("autoscroll waits for late-mounted capability viewers after the stream", () => {
  assert.match(autoScroll, /LATE_VIEWER_AUTOSCROLL_WINDOW_MS/);
  assert.match(autoScroll, /\[data-chat-grow\]/);
  assert.match(autoScroll, /issue #955/);
});
