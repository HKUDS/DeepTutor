import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const quizViewer = readFileSync(
  path.resolve(process.cwd(), "components/quiz/QuizViewer.tsx"),
  "utf8",
);

test("fill-in-the-blank questions expose the existing image answer flow", () => {
  assert.match(
    quizViewer,
    /const canAttachImage = isFillBlank \|\| !isGradable;?/,
  );
  assert.match(quizViewer, /\{canAttachImage && \(/);
  assert.match(
    quizViewer,
    /if \(canAttachImage && ans\.images\.length > 0\) return false;?/,
  );
});

test("image-only fill-in-the-blank submissions wait for AI judgment", () => {
  assert.match(
    quizViewer,
    /const canShowCorrectness = isGradable && currentUserAnswer\.length > 0;?/,
  );
  assert.match(
    quizViewer,
    /done && answer && autoGradable && hasAutoGradableAnswer/,
  );
});
