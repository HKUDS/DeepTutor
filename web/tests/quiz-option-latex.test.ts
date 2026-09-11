import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function markdownTagContaining(source: string, marker: string): string {
  const markerIndex =
    marker === ": q.correct_answer"
      ? source.lastIndexOf(marker)
      : source.indexOf(marker);
  assert.notEqual(
    markerIndex,
    -1,
    `missing Markdown content marker: ${marker}`,
  );
  const tagStart = source.lastIndexOf("<MarkdownRenderer", markerIndex);
  const tagEnd = source.indexOf("/>", markerIndex);
  assert.notEqual(tagStart, -1, `missing MarkdownRenderer before: ${marker}`);
  assert.notEqual(tagEnd, -1, `unterminated MarkdownRenderer for: ${marker}`);
  return source.slice(tagStart, tagEnd + 2);
}

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

test("QuizViewer enables math for the question and every generated review field", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components/quiz/QuizViewer.tsx"),
    "utf8",
  );

  for (const marker of [
    "content={q.question}",
    "content={judgment.text}",
    ": q.correct_answer",
    "content={q.explanation}",
  ]) {
    assert.match(markdownTagContaining(source, marker), /\benableMath\b/);
  }
});

test("saved and book quiz options use the math-capable Markdown renderer", () => {
  const sources = [
    readFileSync(
      path.join(
        process.cwd(),
        "app/(workspace)/books/components/blocks/QuizBlock.tsx",
      ),
      "utf8",
    ),
    readFileSync(
      path.join(
        process.cwd(),
        "components/space/question-bank/QuestionCard.tsx",
      ),
      "utf8",
    ),
  ];

  for (const source of sources) {
    const marker = source.includes("content={label}")
      ? "content={label}"
      : "content={text}";
    assert.match(markdownTagContaining(source, marker), /\benableMath\b/);
  }
});
