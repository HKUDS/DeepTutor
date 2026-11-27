import test from "node:test";
import assert from "node:assert/strict";

import { parseModelThinkingSegments } from "../lib/think-segments";

for (const [name, input] of [
  ["tilde fence", "Before\n~~~html\n<think>literal HTML</think>\n~~~\nAfter"],
  ["long backtick fence", "Before\n````markdown\n```\n<think>literal example</think>\n```\n````\nAfter"],
  ["unfinished streaming fence", "Before\n```html\n<think>literal HTML"],
] as const) {
  test(`assistant thinking parser preserves ${name}`, () => {
    assert.deepEqual(parseModelThinkingSegments(input), [
      { kind: "text", content: input },
    ]);
  });
}

test("thinking after a closed tilde fence remains a thinking segment", () => {
  const code = "~~~html\n<think>literal HTML</think>\n~~~\n";
  assert.deepEqual(
    parseModelThinkingSegments(`${code}<think>actual reasoning</think>Answer`),
    [
      { kind: "text", content: code },
      { kind: "think", content: "actual reasoning", closed: true },
      { kind: "text", content: "Answer" },
    ],
  );
});
