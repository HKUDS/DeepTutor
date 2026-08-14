import test from "node:test";
import assert from "node:assert/strict";

import { resolveKbLink } from "../lib/kb-links";
import type { KnowledgeBaseFile } from "../lib/knowledge-api";

const FILES: KnowledgeBaseFile[] = [
  "index.md",
  "get-started.md",
  "get-started/pypi.md",
  "get-started/docker.md",
  "explore.md",
  "explore/chat-workspace.md",
  "cli/commands.md",
].map((name) => ({ name, type: "file" as const }));

test("resolveKbLink maps a docs-site URL to the local file", () => {
  assert.equal(
    resolveKbLink("https://docs.deeptutor.info/get-started/pypi/", "index.md", FILES),
    "get-started/pypi.md",
  );
});

test("resolveKbLink maps a section-root URL to the section index file", () => {
  assert.equal(
    resolveKbLink("https://docs.deeptutor.info/get-started/", "index.md", FILES),
    "get-started.md",
  );
});

test("resolveKbLink strips a locale prefix so localized links reach the same page", () => {
  assert.equal(
    resolveKbLink("https://docs.deeptutor.info/zh-cn/get-started/", "index.md", FILES),
    "get-started.md",
  );
});

test("resolveKbLink resolves relative links against the current file's directory", () => {
  assert.equal(resolveKbLink("docker", "get-started/pypi.md", FILES), "get-started/docker.md");
  assert.equal(resolveKbLink("../explore", "get-started/pypi.md", FILES), "explore.md");
  assert.equal(resolveKbLink("./commands.md", "cli/server-api.md", FILES), "cli/commands.md");
});

test("resolveKbLink leaves unrelated external links alone", () => {
  assert.equal(resolveKbLink("https://github.com/HKUDS/DeepTutor", "index.md", FILES), null);
  assert.equal(resolveKbLink("https://discord.gg/abc", "index.md", FILES), null);
});

test("resolveKbLink ignores hash and query fragments", () => {
  assert.equal(
    resolveKbLink("https://docs.deeptutor.info/explore/chat-workspace/?q=1#top", "index.md", FILES),
    "explore/chat-workspace.md",
  );
});

test("resolveKbLink maps the site root to index.md", () => {
  assert.equal(resolveKbLink("https://docs.deeptutor.info/", "get-started/pypi.md", FILES), "index.md");
});
