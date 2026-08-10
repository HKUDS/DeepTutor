import test from "node:test";
import assert from "node:assert/strict";

import {
  cliArgvLabel,
  clipLabel,
  describeProviderTool,
  formatProgressLabel,
  mcpToolLabel,
} from "../lib/trace-tools";

/** Stands in for i18next: interpolates so assertions read like the UI does. */
const t = (key: string, opts?: Record<string, unknown>) =>
  key.replace(/\{\{(\w+)\}\}/g, (_m, name) => String(opts?.[name] ?? ""));

test("an MCP tool is named without its generated prefix", () => {
  assert.equal(
    mcpToolLabel("mcp_wolfram_WolframAlpha", "wolfram"),
    "WolframAlpha",
  );
});

test("a server whose own name contains an underscore is still stripped correctly", () => {
  // The reason the server id travels in metadata at all: splitting on
  // underscores here would name the tool "server_search" or "search" depending
  // on which split you guessed.
  assert.equal(
    mcpToolLabel("mcp_my_server_deep_search", "my_server"),
    "deep_search",
  );
});

test("a name that does not carry the expected prefix is left alone", () => {
  // Degrades to something true rather than slicing off a real part of the name.
  assert.equal(mcpToolLabel("search", "wolfram"), "search");
  assert.equal(mcpToolLabel("mcp_other_search", "wolfram"), "mcp_other_search");
});

test("a missing server id does not produce a bogus prefix", () => {
  assert.equal(mcpToolLabel("mcp_x_y", ""), "mcp_x_y");
});

test("CLI arguments join for display and nothing re-splits them", () => {
  assert.equal(
    cliArgvLabel(["diagram", "render", "--out", "a.png"]),
    "diagram render --out a.png",
  );
});

test("an argument containing a space is shown as it is", () => {
  // This is a label, not a command to copy: quoting it would imply a shell that
  // is deliberately not involved.
  assert.equal(cliArgvLabel(["export", "my file.png"]), "export my file.png");
});

test("a non-array args value degrades instead of rendering [object Object]", () => {
  assert.equal(cliArgvLabel("scene list"), "scene list");
  assert.equal(cliArgvLabel(undefined), "");
  assert.equal(cliArgvLabel({ a: 1 }), "");
});

test("a short label is untouched", () => {
  assert.equal(clipLabel("fetching pages", 40), "fetching pages");
});

test("a long label is clipped on a word boundary when one is near the cut", () => {
  const clipped = clipLabel(
    "fetching page seventeen of two hundred and twelve",
    20,
  );
  assert.ok(clipped.endsWith("…"));
  assert.ok(!clipped.includes("seventee…"), `mid-word cut: ${clipped}`);
  assert.ok(clipped.length <= 21);
});

test("a long unbroken label is still cut rather than overflowing", () => {
  const clipped = clipLabel("a".repeat(80), 20);
  assert.equal(clipped, `${"a".repeat(20)}…`);
});

test("surrounding whitespace never survives into the row", () => {
  assert.equal(formatProgressLabel("  indexing  "), "indexing");
});

// ── the whole row decision ───────────────────────────────────────────────

test("an MCP call names the service, with its tool trailing", () => {
  const row = describeProviderTool(
    "mcp_wolfram_WolframAlpha",
    { input: "2+2" },
    { source: "mcp", id: "wolfram" },
    t,
  );

  assert.deepEqual(row, {
    glyph: "link",
    verb: "Using wolfram",
    chip: "WolframAlpha",
    mono: true,
  });
});

test("a CLI call names the app, with its arguments trailing", () => {
  const row = describeProviderTool(
    "cli_blender",
    { args: ["render", "--out", "scene.png"] },
    { source: "cli", id: "blender" },
    t,
  );

  assert.deepEqual(row, {
    glyph: "command",
    verb: "Running blender",
    chip: "render --out scene.png",
    mono: true,
  });
});

test("a CLI call with no arguments still reads as a row", () => {
  const row = describeProviderTool(
    "cli_blender",
    {},
    { source: "cli", id: "blender" },
    t,
  );
  assert.equal(row?.verb, "Running blender");
  assert.equal(row?.chip, null);
});

test("a long argument list is clipped rather than pushing the row wide", () => {
  const row = describeProviderTool(
    "cli_blender",
    { args: ["render", "--input", "a".repeat(80)] },
    { source: "cli", id: "blender" },
    t,
  );
  assert.ok((row?.chip ?? "").length <= 49, row?.chip ?? "(no chip)");
});

test("a built-in tool is not a provider row", () => {
  // Returning something here would take over the hand-written descriptor for
  // every built-in and label them all generically.
  assert.equal(
    describeProviderTool("read_file", { path: "a.txt" }, null, t),
    null,
  );
  assert.equal(
    describeProviderTool("read_file", {}, { source: "", id: "" }, t),
    null,
  );
});

test("a provider kind this build does not know falls through to the generic row", () => {
  // Honest generic beats a confident wrong label.
  assert.equal(
    describeProviderTool(
      "xyz_thing",
      {},
      { source: "future-provider", id: "thing" },
      t,
    ),
    null,
  );
});

test("a provider with no id still names something rather than nothing", () => {
  const row = describeProviderTool("mcp_x_y", {}, { source: "mcp", id: "" }, t);
  assert.equal(row?.verb, "Using mcp_x_y");
});
