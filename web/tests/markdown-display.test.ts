import test from "node:test";
import assert from "node:assert/strict";
import {
  escapeUnknownHtmlTagsForDisplay,
  hasVisibleMarkdownContent,
  normalizeMarkdownForDisplay,
} from "../lib/markdown-display";

test("normalizeMarkdownForDisplay removes empty details blocks", () => {
  const input = "Before\n\n<details><summary></summary></details>\n\nAfter";
  assert.equal(normalizeMarkdownForDisplay(input), "Before\n\nAfter");
});

test("normalizeMarkdownForDisplay removes raw html control placeholders", () => {
  const input =
    'Before\n\n<progress></progress>\n<input type="text" />\n<textarea> </textarea>\n\nAfter';
  assert.equal(normalizeMarkdownForDisplay(input), "Before\n\nAfter");
});

test("normalizeMarkdownForDisplay removes empty markdown tables", () => {
  const input = "Before\n\n| |\n|---|\n\nAfter";
  assert.equal(normalizeMarkdownForDisplay(input), "Before\n\nAfter");
});

test("normalizeMarkdownForDisplay removes empty html tables", () => {
  const input = "Before\n\n<table><tr><td>&nbsp;</td></tr></table>\n\nAfter";
  assert.equal(normalizeMarkdownForDisplay(input), "Before\n\nAfter");
});

test("normalizeMarkdownForDisplay keeps meaningful tables", () => {
  const input = "Before\n\n| Topic |\n|---|\n| Math |\n\nAfter";
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay linkifies bare citations in prose", () => {
  assert.equal(
    normalizeMarkdownForDisplay("Reference [1]."),
    'Reference [1](#references "citation").',
  );
});

test("normalizeMarkdownForDisplay keeps array indexes inside fenced code", () => {
  const input = "```js\nconst item = values[0];\n```";
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay keeps array indexes inside inline code", () => {
  const input = "Use `values[0]` for the first item.";
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay unwraps explicit citation code spans outside code", () => {
  assert.equal(
    normalizeMarkdownForDisplay("See `[web-1]` for details."),
    'See [web-1](#references "citation") for details.',
  );
});

test("escapeUnknownHtmlTagsForDisplay escapes LLM pseudo tags", () => {
  const input = "Before\n<think>internal scratchpad</think>\nAfter";
  assert.equal(
    escapeUnknownHtmlTagsForDisplay(input),
    "Before\n`<think>`internal scratchpad`</think>`\nAfter",
  );
});

test("escapeUnknownHtmlTagsForDisplay preserves line count for previews", () => {
  const input = "A\n\n<thinking>hidden</thinking>\nB";
  const output = escapeUnknownHtmlTagsForDisplay(input);
  assert.equal(output.split("\n").length, input.split("\n").length);
});

test("escapeUnknownHtmlTagsForDisplay keeps allowed html tags", () => {
  const input = "<details><summary>More</summary>Body</details>";
  assert.equal(escapeUnknownHtmlTagsForDisplay(input), input);
});

test("hasVisibleMarkdownContent rejects empty raw-html placeholders", () => {
  assert.equal(
    hasVisibleMarkdownContent("<details><summary></summary></details>"),
    false,
  );
});

test("hasVisibleMarkdownContent rejects raw html control placeholders", () => {
  assert.equal(
    hasVisibleMarkdownContent('<progress></progress>\n<input type="text" />'),
    false,
  );
});

test("hasVisibleMarkdownContent rejects empty markdown tables", () => {
  assert.equal(hasVisibleMarkdownContent("| |\n|---|"), false);
});

test("hasVisibleMarkdownContent keeps meaningful markdown", () => {
  assert.equal(
    hasVisibleMarkdownContent("这是一个正常回复。\n\n- 第一条"),
    true,
  );
});
