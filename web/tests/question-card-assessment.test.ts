import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { questionResultBadge } from "../lib/question-bank-answers";

const card = readFileSync(
  path.resolve(process.cwd(), "components/space/question-bank/QuestionCard.tsx"),
  "utf8",
);
const english = readFileSync(
  path.resolve(process.cwd(), "locales/en/app.json"),
  "utf8",
);
const chinese = readFileSync(
  path.resolve(process.cwd(), "locales/zh/app.json"),
  "utf8",
);

test("question cards distinguish partial and ungraded results", () => {
  for (const is_correct of [true, false]) {
    assert.equal(questionResultBadge({ result: "partial", is_correct }).label, "Partially Correct");
    assert.equal(questionResultBadge({ result: "ungraded", is_correct }).label, "Not Graded");
  }
  assert.match(card, /questionResultBadge\(entry\)/);
  assert.match(card, /isUserAnswer && result === "incorrect"/);
  assert.match(card, /result === "incorrect"\s*\? "wrong"/);
  assert.match(card, /ASSESSMENT_TYPE_LABELS/);
  assert.match(card, /Focus Check/);
  assert.match(card, /source === "immersive_reading"/);
  assert.match(english, /"Partially Correct": "Partially Correct"/);
  assert.match(chinese, /"Partially Correct": "部分正确"/);
  assert.match(english, /"Not Graded": "Not Graded"/);
  assert.match(chinese, /"Not Graded": "未评分"/);
  assert.match(english, /"Focus Check": "Focus Check"/);
  assert.match(chinese, /"Focus Check": "专注检测"/);
});

test("choice cards mark the pick and reference from letter or option text", () => {
  assert.match(card, /optionIsAnswer/);
  assert.match(card, /from "@\/lib\/question-bank-answers"/);
  assert.match(card, /t\("Your pick"\)/);
  assert.doesNotMatch(
    card,
    /entry\.user_answer\?\.toUpperCase\(\) === key\.toUpperCase\(\)/,
  );
  assert.match(english, /"Your pick": "Your pick"/);
  assert.match(chinese, /"Your pick": "你的选择"/);
});
