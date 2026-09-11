import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  activeReaderHeading,
  buildOutlineTree,
  extractEpubHeadings,
  extractReaderHeadings,
  filterReaderHeadings,
  filterOutlineNodes,
  readerLinesWithHeadings,
} from "../lib/reading-outline";

function source(relativePath: string): string {
  return readFileSync(path.join(process.cwd(), relativePath), "utf8");
}

test("builds a nested outline without inventing impossible levels", () => {
  const tree = buildOutlineTree([
    { locator: 1, title: "Part", level: 1, synthesised: false },
    { locator: 2, title: "Suddenly deep", level: 6, synthesised: false },
    { locator: 3, title: "Nested", level: 3, synthesised: false },
  ]);

  assert.deepEqual(
    tree.map((node) => node.row.title),
    ["Part"],
  );
  assert.deepEqual(
    tree[0].children.map((node) => node.row.title),
    ["Suddenly deep"],
  );
  assert.deepEqual(
    tree[0].children[0].children.map((node) => node.row.title),
    ["Nested"],
  );
});

test("keeps an ancestor when only its child matches a filter", () => {
  const tree = buildOutlineTree([
    { locator: 1, title: "Installation", level: 1, synthesised: false },
    { locator: 2, title: "Docker", level: 2, synthesised: false },
    { locator: 3, title: "Providers", level: 2, synthesised: false },
  ]);
  const filtered = filterOutlineNodes(tree, "docker");

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].row.title, "Installation");
  assert.equal(filtered[0].children.length, 1);
  assert.equal(filtered[0].children[0].row.title, "Docker");
});

test("extracts Markdown headings and skips fenced code", () => {
  const headings = extractReaderHeadings(
    ["# Title\n\n```ts\n// # Not a heading\n```\n\n## Section ##"],
    3,
  );

  assert.deepEqual(headings, [
    { id: "dt-reader-heading-3-1", title: "Title", level: 1 },
    { id: "dt-reader-heading-3-2", title: "Section", level: 2 },
  ]);
});

test("extracts every EPUB heading level and preserves explicit anchors", () => {
  const headings = extractEpubHeadings(
    [
      { id: "publisher-title", tagName: "h1", textContent: " Title " },
      { tagName: "h2", textContent: "Section" },
      { tagName: "H3", textContent: "Subsection" },
      { tagName: "h4", textContent: "Detail" },
      { tagName: "h5", textContent: "Fine detail" },
      { tagName: "h6", textContent: "Notes" },
      { tagName: "p", textContent: "Not a heading" },
      { tagName: "h2", textContent: "   " },
    ],
    7,
    "OPS/chapter.xhtml",
  );

  assert.deepEqual(headings, [
    {
      id: "publisher-title",
      title: "Title",
      level: 1,
      locator: 7,
      sourceHref: "OPS/chapter.xhtml",
    },
    {
      id: "dt-reader-heading-7-2",
      title: "Section",
      level: 2,
      locator: 7,
      sourceHref: "OPS/chapter.xhtml",
    },
    {
      id: "dt-reader-heading-7-3",
      title: "Subsection",
      level: 3,
      locator: 7,
      sourceHref: "OPS/chapter.xhtml",
    },
    {
      id: "dt-reader-heading-7-4",
      title: "Detail",
      level: 4,
      locator: 7,
      sourceHref: "OPS/chapter.xhtml",
    },
    {
      id: "dt-reader-heading-7-5",
      title: "Fine detail",
      level: 5,
      locator: 7,
      sourceHref: "OPS/chapter.xhtml",
    },
    {
      id: "dt-reader-heading-7-6",
      title: "Notes",
      level: 6,
      locator: 7,
      sourceHref: "OPS/chapter.xhtml",
    },
  ]);
});

test("heading anchors preserve the exact source used by annotation selectors", () => {
  const sourceText = "  # Title ##\r\nBody\n```md\n# Code\n```\n## Next\n";
  const headings = extractReaderHeadings([sourceText], 4);
  const lines = readerLinesWithHeadings(sourceText, headings);

  assert.equal(lines[0].heading?.id, "dt-reader-heading-4-1");
  assert.equal(lines[3].heading, null);
  assert.equal(lines[5].heading?.id, "dt-reader-heading-4-2");
  assert.equal(
    lines.map((line) => line.text).join("\n"),
    sourceText,
    "DOM text must retain Markdown markers, CRLF characters, and final newline",
  );
});

test("active heading follows the reading container", () => {
  const headings = extractReaderHeadings(["# One\n## Two\n### Three"], 1);
  const active = activeReaderHeading(headings, (heading) =>
    heading.title === "One" ? -20 : heading.title === "Two" ? 12 : 80,
  );

  assert.equal(active, "dt-reader-heading-1-2");
});

test("page-heading filtering stays scoped to the current tab", () => {
  const headings = extractReaderHeadings(["# Install\n## Docker\n## Use"], 2);

  assert.deepEqual(
    filterReaderHeadings(headings, "dock").map((heading) => heading.title),
    ["Docker"],
  );
});

test("page headings are searchable from the workspace navigator", () => {
  const workspace = source("components/reading/workspace/ReadingWorkspace.tsx");
  const navigator = source("components/reading/workspace/SourceNavigator.tsx");
  const reader = source("components/reading/ReaderPane.tsx");
  const textReader = source("components/reading/TextUnitView.tsx");
  const epubReader = source("components/reading/EpubDocumentView.tsx");

  // Only the rendered document can discover headings, but the navigator is
  // where a reader looks for structure — so the reader reports them up and
  // owns none of the navigation UI itself.
  assert.match(reader, /onHeadingsChange/);
  assert.match(reader, /headingJump=\{headingJump\}/);
  assert.match(workspace, /onHeadingsChange=\{setPageHeadings\}/);
  assert.match(navigator, /filterReaderHeadings/);
  assert.match(navigator, /aria-label=\{t\("On this page"\)\}/);
  assert.match(navigator, /onNavigateHeading\(heading\)/);
  assert.match(epubReader, /h1,h2,h3,h4,h5,h6/);
  assert.match(epubReader, /extractEpubHeadings/);
  assert.match(epubReader, /sourceHref\}#\$\{headingJump\.id\}/);
  assert.match(epubReader, /headingsByLocatorRef/);
  assert.match(reader, /onHeadingsChange=\{onHeadingsChange\}/);
  assert.match(textReader, /data-reader-heading-id/);
  assert.match(textReader, /container\.scrollTo\(/);
  assert.match(textReader, /elementRect\.top - containerRect\.top/);
  assert.doesNotMatch(textReader, /element\.offsetTop - 72/);
  assert.doesNotMatch(textReader, /segmentTextByQuotes|<mark/);
});

test("lines inside a fenced code block are flagged so the renderer skips Markdown", () => {
  const sourceText = "Intro paragraph.\n```md\n**not bold**\n```\nAfter.";
  const lines = readerLinesWithHeadings(sourceText, []);

  assert.deepEqual(
    lines.map((line) => line.fence),
    [false, true, true, true, false],
  );
  assert.equal(lines.map((line) => line.text).join("\n"), sourceText);
});
