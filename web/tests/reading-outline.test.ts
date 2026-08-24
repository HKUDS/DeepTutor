import assert from "node:assert/strict";
import test from "node:test";
import {
  buildOutlineTree,
  activeReaderHeading,
  extractReaderHeadings,
  filterReaderHeadings,
  filterOutlineNodes,
} from "@/lib/reading-outline";
import {
  goBackReadingHistory,
  goForwardReadingHistory,
  pushReadingHistory,
} from "@/lib/reading-history";
import type { OutlineRow } from "@/lib/reading-api";

function row(locator: number, title: string, level = 1): OutlineRow {
  return { locator, title, level, synthesised: false };
}

test("legacy KB tutorial paths recover the original index/child hierarchy", () => {
  const paths = [
    "index.md",
    "get-started.md",
    "get-started/pypi.md",
    "get-started/docker.md",
    "explore.md",
    "explore/reading.md",
  ];
  const tree = buildOutlineTree(
    [
      row(1, "Documentation home"),
      row(2, "Overview"),
      row(3, "Install from PyPI"),
      row(4, "Docker"),
      row(5, "Overview"),
      row(6, "Immersive Reading"),
    ],
    paths,
  );

  assert.deepEqual(
    tree.map((node) => [
      node.row.title,
      node.children.map((child) => child.row.title),
    ]),
    [
      ["Documentation home", []],
      ["Overview", ["Install from PyPI", "Docker"]],
      ["Overview", ["Immersive Reading"]],
    ],
  );
});

test("original navigation levels take precedence over path compatibility data", () => {
  const tree = buildOutlineTree(
    [
      row(1, "Home", 1),
      row(2, "Get Started", 2),
      row(3, "Install", 3),
    ],
    ["index.md", "index.md", "index.md"],
  );

  assert.deepEqual(
    tree.map((node) => [
      node.row.title,
      node.children.map((child) => [
        child.row.title,
        child.children.map((grandchild) => grandchild.row.title),
      ]),
    ]),
    [["Home", [["Get Started", ["Install"]]]]],
  );
});

test("reader heading extraction ignores fenced code and creates stable duplicate ids", () => {
  const source = [
    "# Documentation",
    "",
    "```md",
    "## Not navigation",
    "```",
    "",
    "## Install",
    "",
    "### Docker",
    "",
    "## Install",
  ].join("\n");
  const headings = extractReaderHeadings([source], 18);

  assert.deepEqual(headings, [
    { id: "dt-reader-heading-18-1", title: "Documentation", level: 1 },
    { id: "dt-reader-heading-18-2", title: "Install", level: 2 },
    { id: "dt-reader-heading-18-3", title: "Docker", level: 3 },
    { id: "dt-reader-heading-18-4", title: "Install", level: 2 },
  ]);
});

test("reader heading anchors stay stable for CJK and repeated titles", () => {
  const headings = extractReaderHeadings(["## 中文标题", "## 中文标题"], 4);

  assert.deepEqual(headings.map((heading) => heading.id), [
    "dt-reader-heading-4-1",
    "dt-reader-heading-4-2",
  ]);
});

test("outline filtering keeps ancestors of matching descendants", () => {
  const tree = buildOutlineTree([
    row(1, "Getting Started", 1),
    row(2, "Install", 2),
    row(3, "Docker", 3),
    row(4, "Partners", 1),
  ]);
  const filtered = filterOutlineNodes(tree, "docker");

  assert.deepEqual(
    filtered.map((node) => node.row.title),
    ["Getting Started"],
  );
  assert.equal(filtered[0].children[0].row.title, "Install");
  assert.equal(filtered[0].children[0].children[0].row.title, "Docker");
});

test("active and filtered page headings use the current source set", () => {
  const headings = extractReaderHeadings(
    ["## Install", "### Docker", "## Contributing"],
    3,
  );

  assert.deepEqual(
    filterReaderHeadings(headings, "dock").map((heading) => heading.title),
    ["Docker"],
  );
  assert.equal(
    activeReaderHeading(headings, (heading) =>
      heading.title === "Install"
        ? -20
        : heading.title === "Docker"
          ? 12
          : 80,
    ),
    "dt-reader-heading-3-2",
  );
});

test("reading history preserves explicit locations and clears forward jumps", () => {
  let state = pushReadingHistory(
    { back: [], current: { locator: 18 }, forward: [] },
    { locator: 3 },
  );
  state = pushReadingHistory(state, { locator: 12, headingId: "install" });
  state = goBackReadingHistory(state);

  assert.deepEqual(state.current, { locator: 3 });
  assert.deepEqual(state.back, [{ locator: 18 }]);
  assert.deepEqual(state.forward, [
    { locator: 12, headingId: "install" },
  ]);

  state = goForwardReadingHistory(state);
  assert.deepEqual(state.current, { locator: 12, headingId: "install" });

  state = pushReadingHistory(state, { locator: 20 });
  assert.deepEqual(state.forward, []);
});
