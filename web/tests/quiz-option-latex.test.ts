import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

test("QuizViewer renders multiple-choice options through MarkdownRenderer", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components/quiz/QuizViewer.tsx"),
    "utf8",
  );
  const optionsStart = source.indexOf(
    "{Object.entries(q.options!).map(([key, text]) => {",
  );
  assert.notEqual(optionsStart, -1, "choice option renderer not found");

  const optionsEnd = source.indexOf(") : isConcept ?", optionsStart);
  assert.notEqual(optionsEnd, -1, "choice option branch end not found");

  const optionsBranch = source.slice(optionsStart, optionsEnd);
  assert.match(
    optionsBranch,
    /<MarkdownRenderer[\s\S]*content=\{text\}[\s\S]*variant="compact"[\s\S]*enableMath/,
  );
  assert.doesNotMatch(
    optionsBranch,
    /<span className="leading-relaxed">\{text\}<\/span>/,
  );
});
