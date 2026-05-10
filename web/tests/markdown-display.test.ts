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

test("normalizeMarkdownForDisplay preserves array indexing in fenced code blocks", () => {
  const input = "Some text\n\n```python\n# Base case\nfor i in range(m + 1): dp[i][0] = i\nfor j in range(n + 1): dp[0][j] = j\n```\n\nMore text";
  const output = normalizeMarkdownForDisplay(input);
  assert.equal(output.includes("dp[i][0]"), true, "dp[i][0] should be preserved");
  assert.equal(output.includes("dp[0][j]"), true, "dp[0][j] should be preserved");
  assert.equal(output.includes("#references"), false, "citation markers should not be injected into code blocks");
});

test("normalizeMarkdownForDisplay preserves single bracket indexing in code blocks", () => {
  const input = "```\narr[0] = 1\nitems[i] = value\n```";
  const output = normalizeMarkdownForDisplay(input);
  assert.equal(output.includes("arr[0]"), true);
  assert.equal(output.includes("items[i]"), true);
  assert.equal(output.includes("#references"), false);
});

test("normalizeMarkdownForDisplay still linkifies citations outside code blocks", () => {
  const input = "This is a citation [1] and another [web-2]";
  const output = normalizeMarkdownForDisplay(input);
  assert.equal(output.includes('[1](#references "citation")'), true);
  assert.equal(output.includes('[web-2](#references "citation")'), true);
});

test("normalizeMarkdownForDisplay preserves code with multiple bracket patterns", () => {
  const input = "```python\nmatrix[i][j] = matrix[i-1][j-1] + matrix[i+1][j+1]\narr[0] = 0\nhash[key] = value\n```";
  const output = normalizeMarkdownForDisplay(input);
  assert.equal(output.includes("matrix[i][j]"), true);
  assert.equal(output.includes("matrix[i-1][j-1]"), true);
  assert.equal(output.includes("matrix[i+1][j+1]"), true);
  assert.equal(output.includes("arr[0]"), true);
  assert.equal(output.includes("hash[key]"), true);
  assert.equal(output.includes("#references"), false);
});
