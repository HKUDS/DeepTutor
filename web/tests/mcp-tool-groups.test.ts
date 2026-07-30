import test from "node:test";
import assert from "node:assert/strict";

import {
  groupProviderTools,
  groupSelection,
  providerGroupId,
  setGroupSelected,
  toggleToolName,
} from "../lib/mcp-tool-groups";

const NOTION = [
  { name: "mcp_notion_search", provider_id: "notion", server: "notion" },
  { name: "mcp_notion_create", provider_id: "notion", server: "notion" },
];
const GITHUB = [
  { name: "mcp_github_issues", provider_id: "github", server: "github" },
];
const ALL = [...NOTION, ...GITHUB];

test("groupProviderTools folds by provider and keeps backend order", () => {
  const groups = groupProviderTools([NOTION[0], GITHUB[0], NOTION[1]]);
  assert.deepEqual(
    groups.map((group) => [group.id, group.tools.map((tool) => tool.name)]),
    [
      ["notion", ["mcp_notion_search", "mcp_notion_create"]],
      ["github", ["mcp_github_issues"]],
    ],
  );
  assert.deepEqual(
    groups.map((group) => group.kind),
    ["mcp", "mcp"],
  );
});

test("providerGroupId falls back to the legacy server field then to other", () => {
  assert.equal(providerGroupId({ name: "a", server: "legacy" }), "legacy");
  assert.equal(providerGroupId({ name: "a" }), "other");
  // provider_id wins when both are present but disagree.
  assert.equal(
    providerGroupId({ name: "a", provider_id: "new", server: "old" }),
    "new",
  );
});

test("groupSelection reports all / none / partial for the group only", () => {
  assert.equal(groupSelection(NOTION, []), "none");
  assert.equal(
    groupSelection(NOTION, ["mcp_notion_search", "mcp_notion_create"]),
    "all",
  );
  assert.equal(groupSelection(NOTION, ["mcp_notion_search"]), "partial");
  // A name from another server must not count toward this group: a count-only
  // derivation would call this "all".
  assert.equal(
    groupSelection(NOTION, ["mcp_notion_search", "mcp_github_issues"]),
    "partial",
  );
  assert.equal(groupSelection(NOTION, ["mcp_github_issues"]), "none");
  // Unknown extras never inflate the state either.
  assert.equal(
    groupSelection(GITHUB, ["mcp_github_issues", "mcp_gone_stale"]),
    "all",
  );
  assert.equal(groupSelection([], ["mcp_notion_search"]), "none");
});

test("setGroupSelected flattens back to tool names and leaves others alone", () => {
  // Assigning a whole service is one click, but the saved value stays flat.
  const granted = setGroupSelected(["mcp_github_issues"], NOTION, true);
  assert.deepEqual(granted.slice().sort(), [
    "mcp_github_issues",
    "mcp_notion_create",
    "mcp_notion_search",
  ]);

  // Partial -> all fills the group without duplicating the already-picked name.
  const filled = setGroupSelected(["mcp_notion_search"], NOTION, true);
  assert.deepEqual(filled.slice().sort(), [
    "mcp_notion_create",
    "mcp_notion_search",
  ]);

  // Clearing a group drops exactly its names.
  assert.deepEqual(
    setGroupSelected(ALL.map((tool) => tool.name), NOTION, false),
    ["mcp_github_issues"],
  );
  assert.deepEqual(setGroupSelected(["mcp_github_issues"], NOTION, false), [
    "mcp_github_issues",
  ]);
});

test("toggleToolName flips a single name in the flat list", () => {
  assert.deepEqual(toggleToolName(["a"], "b"), ["a", "b"]);
  assert.deepEqual(toggleToolName(["a", "b"], "a"), ["b"]);
});
