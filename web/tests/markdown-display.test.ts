import test from "node:test";
import assert from "node:assert/strict";
import {
  escapeUnknownHtmlTagsForDisplay,
  hasVisibleMarkdownContent,
  markdownUrlTransform,
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

test("normalizeMarkdownForDisplay links research citations to exact references", () => {
  assert.equal(
    normalizeMarkdownForDisplay(
      "Agentic loops [CIT-1-01] and plans [PLAN-01].",
    ),
    'Agentic loops [1](#ref-cit-1-01 "citation") and plans [2](#ref-plan-01 "citation").',
  );
});

test("normalizeMarkdownForDisplay numbers research citations from reference list order", () => {
  const refs =
    '<details id="references" open><summary>参考资料</summary><ol>' +
    '<li id="ref-cit-1-01" data-citation-id="CIT-1-01">' +
    "<strong>[1]</strong> <code>CIT-1-01</code> A</li>" +
    '<li id="ref-cit-2-01" data-citation-id="CIT-2-01">' +
    "<strong>[2]</strong> <code>CIT-2-01</code> B</li>" +
    "</ol></details>";
  const input = `First [CIT-2-01], then [CIT-1-01].\n\n${refs}`;
  assert.equal(
    normalizeMarkdownForDisplay(input),
    `First [2](#ref-cit-2-01 "citation"), then [1](#ref-cit-1-01 "citation").\n\n${refs}`,
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

test("normalizeMarkdownForDisplay keeps bracketed vectors inside display math", () => {
  const input = ["The row for `sat` is:", "", "\\[", "[1, 1, 2]", "\\]"].join(
    "\n",
  );
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay keeps bracketed vectors inside weighted math", () => {
  const input = ["\\[", "0.212[1, 1] + 0.212[2, 0] + 0.576[0, 3]", "\\]"].join(
    "\n",
  );
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay keeps number arrays in prose untouched", () => {
  const input = "线性卷积结果 [1, 5, 9, 5, 3, 2, 7] 与 [8, 5, 3, 6]。";
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay keeps number arrays inside inline math", () => {
  const input = "序列 $x = [1, 5, 9, 5, 3, 2, 7]$ 与 $h = [8, 5, 3, 6]$。";
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay still linkifies small distinct numeric citation groups", () => {
  assert.equal(
    normalizeMarkdownForDisplay("See [1, 3] for details."),
    'See [1, 3](#references "citation") for details.',
  );
});

test("normalizeMarkdownForDisplay keeps backticked number arrays as code", () => {
  const input = "Result `[1, 5, 9, 5, 3, 2, 7]` here.";
  assert.equal(normalizeMarkdownForDisplay(input), input);
});

test("normalizeMarkdownForDisplay unwraps explicit citation code spans outside code", () => {
  assert.equal(
    normalizeMarkdownForDisplay("See `[web-1]` for details."),
    'See [web-1](#references "citation") for details.',
  );
});

test("normalizeMarkdownForDisplay unwraps research citation code spans", () => {
  assert.equal(
    normalizeMarkdownForDisplay("See `[CIT-1-01]` for details."),
    'See [1](#ref-cit-1-01 "citation") for details.',
  );
});

test("normalizeMarkdownForDisplay does not linkify research reference list ids", () => {
  const input =
    '<details id="references" open><summary>参考资料</summary><ol>' +
    '<li id="ref-cit-1-01" data-citation-id="CIT-1-01">' +
    "<strong>[1]</strong> <code>CIT-1-01</code> Web Search: q</li>" +
    "</ol></details>";
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

test("escapeUnknownHtmlTagsForDisplay escapes active html containers", () => {
  const input = '<iframe src="https://example.com"></iframe>';
  assert.equal(
    escapeUnknownHtmlTagsForDisplay(input),
    '`<iframe src="https://example.com">``</iframe>`',
  );
});

test("escapeUnknownHtmlTagsForDisplay strips unsafe html attributes", () => {
  const input =
    '<a href="javascript:alert(1)" onclick="alert(2)" style="color:red">link</a>';
  assert.equal(escapeUnknownHtmlTagsForDisplay(input), "<a>link</a>");
});

test("markdownUrlTransform keeps raster data images on img src", () => {
  const png = "data:image/png;base64,iVBORw0KGgo=";
  assert.equal(markdownUrlTransform(png, "src", { tagName: "img" }), png);
});

test("markdownUrlTransform rejects active data URLs", () => {
  assert.equal(
    markdownUrlTransform("data:text/html;base64,PHNjcmlwdD4=", "src", {
      tagName: "img",
    }),
    "",
  );
  assert.equal(
    markdownUrlTransform(
      "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+",
      "src",
      { tagName: "img" },
    ),
    "",
  );
});

test("markdownUrlTransform only allows data images on img src", () => {
  assert.equal(
    markdownUrlTransform("data:image/png;base64,iVBORw0KGgo=", "href", {
      tagName: "a",
    }),
    "",
  );
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
