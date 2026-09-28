import assert from "node:assert/strict";
import test from "node:test";
import { optionIsAnswer } from "../lib/question-bank-answers";

test("option matching accepts a letter key", () => {
  assert.equal(
    optionIsAnswer("B", "To remove all trees from wide streets.", "B"),
    true,
  );
  assert.equal(
    optionIsAnswer("A", "To find places with little existing shade.", "B"),
    false,
  );
});

test("option matching accepts stored choice text from reading quizzes", () => {
  assert.equal(
    optionIsAnswer(
      "B",
      "To remove all trees from wide streets.",
      "To remove all trees from wide streets.",
    ),
    true,
  );
  assert.equal(
    optionIsAnswer(
      "A",
      "To find places with little existing shade.",
      "To find places with little existing shade.",
    ),
    true,
  );
  assert.equal(
    optionIsAnswer(
      "A",
      "To find places with little existing shade.",
      "To remove all trees from wide streets.",
    ),
    false,
  );
});

test("option matching ignores extra whitespace and letter prefixes", () => {
  assert.equal(
    optionIsAnswer("A", "Atlantic  ocean", "  atlantic ocean "),
    true,
  );
  assert.equal(optionIsAnswer("B", "Shade pavement", "B. Shade pavement"), true);
  assert.equal(
    optionIsAnswer("B", "Shade pavement", "B) Shade pavement"),
    true,
  );
  assert.equal(optionIsAnswer("A", "Shade pavement", ""), false);
});
