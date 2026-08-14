import test from "node:test";
import assert from "node:assert/strict";

// Test the tree-building logic that the frontend uses to find paths.
// We can't import the component (it uses JSX), but the _findPathToFile
// helper is pure and can be extracted for testing.

interface WebNavNode {
  id: string;
  title: string;
  url: string;
  file_path: string;
  children: WebNavNode[];
}

function findPathToFile(
  nodes: WebNavNode[],
  filePath: string,
): WebNavNode[] | null {
  for (const node of nodes) {
    if (node.file_path === filePath) {
      return [node];
    }
    if (node.children.length > 0) {
      const found = findPathToFile(node.children, filePath);
      if (found) return [node, ...found];
    }
  }
  return null;
}

const TREE: WebNavNode[] = [
  {
    id: "0",
    title: "Root A",
    url: "https://x.com/a/",
    file_path: "a.md",
    children: [
      {
        id: "1",
        title: "Child 1",
        url: "https://x.com/a/1/",
        file_path: "a/1.md",
        children: [],
      },
      {
        id: "2",
        title: "Child 2",
        url: "https://x.com/a/2/",
        file_path: "a/2.md",
        children: [
          {
            id: "3",
            title: "Grandchild",
            url: "https://x.com/a/2/gc/",
            file_path: "a/2/gc.md",
            children: [],
          },
        ],
      },
    ],
  },
  {
    id: "4",
    title: "Root B",
    url: "https://x.com/b/",
    file_path: "b.md",
    children: [],
  },
];

test("findPathToFile finds a top-level file", () => {
  const path = findPathToFile(TREE, "b.md");
  assert.deepEqual(path?.map((n) => n.id), ["4"]);
});

test("findPathToFile finds a nested file and returns ancestors", () => {
  const path = findPathToFile(TREE, "a/2/gc.md");
  assert.deepEqual(path?.map((n) => n.id), ["0", "2", "3"]);
});

test("findPathToFile returns null for missing file", () => {
  const path = findPathToFile(TREE, "nonexistent.md");
  assert.equal(path, null);
});

test("findPathToFile handles empty tree", () => {
  const path = findPathToFile([], "anything.md");
  assert.equal(path, null);
});
