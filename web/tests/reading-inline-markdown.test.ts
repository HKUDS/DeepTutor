import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InlineMarkdown, MarkdownLine } from "../lib/reading-inline-markdown";

/**
 * Strips tags to approximate `Element.textContent` for markup this module
 * produces — no nested tags swallow text and no fixture uses `<`, `>`, `&`,
 * so this is exact for the cases under test.
 */
function flatten(html: string): string {
  // React HTML-escapes text nodes on serialization (e.g. `>` becomes `&gt;`);
  // decoding here mirrors what a real `Element.textContent` read would give
  // back, since the escaping is a serialization detail, not a content change.
  return html
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'");
}

function renderLine(text: string): string {
  return renderToStaticMarkup(React.createElement(MarkdownLine, { text }));
}

function renderInline(text: string): string {
  return renderToStaticMarkup(React.createElement(InlineMarkdown, { text }));
}

test("bold and italic render as elements but stay exact-match selectable", () => {
  const source = "This is **bold** and *italic* text.";
  const html = renderInline(source);

  assert.match(html, /<strong>bold<\/strong>/);
  assert.match(html, /<em>italic<\/em>/);
  assert.equal(
    flatten(html),
    source,
    "hidden markers must reproduce every stripped Markdown character",
  );
});

test("links render as anchors while remaining exact-match selectable", () => {
  const source = "See [the docs](https://example.com/x) for details.";
  const html = renderInline(source);

  assert.match(html, /href="https:\/\/example\.com\/x"/);
  assert.match(html, />the docs</);
  assert.equal(flatten(html), source);
});

test("inline code renders as a code element", () => {
  const source = "Run `pytest -q` first.";
  const html = renderInline(source);

  assert.match(html, /<code[^>]*>pytest -q<\/code>/);
  assert.equal(flatten(html), source);
});

test("plain prose with no Markdown syntax passes through untouched", () => {
  const source = "Nothing special about this sentence at all.";
  const html = renderInline(source);

  assert.equal(html, source);
});

test("a bullet line keeps its marker selectable and adds no stray characters", () => {
  const source = "- first item";
  const html = renderLine(source);

  assert.equal(flatten(html), source);
});

test("a blockquote line keeps its marker selectable", () => {
  const source = "> a quoted remark";
  const html = renderLine(source);

  assert.equal(flatten(html), source);
});

test("a horizontal rule renders an <hr> while the source text survives hidden", () => {
  const source = "---";
  const html = renderLine(source);

  assert.match(html, /<hr\b/);
  assert.equal(flatten(html), source);
});

test("does not misparse an arithmetic expression as italics", () => {
  const source = "3 * 4 = 12, not italic.";
  const html = renderInline(source);

  assert.equal(html, source);
});
