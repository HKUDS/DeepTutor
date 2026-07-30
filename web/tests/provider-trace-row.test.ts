/**
 * The wiring between what a turn actually emits and what the activity row shows.
 *
 * The fixture is not hand-written: it is the trace metadata recorded from real
 * LLM turns against a real MCP server (Wolfram) and a real installed CLI app
 * (mermaid), trimmed to the fields the row reads. That matters, because the first
 * attempt at verifying this in the browser produced a *false negative* — a
 * long-lived dev backend was serving code from before the change — and a fixture
 * copied from the real wire is the thing that keeps this honest without a server.
 */

import test from "node:test";
import assert from "node:assert/strict";

import recordedEvents from "./fixtures/provider-trace-events.json";
import {
  getLatestToolProgress,
  getToolProvider,
} from "../components/chat/home/TracePanels";
import { describeProviderTool } from "../lib/trace-tools";
import type { StreamEvent } from "../lib/unified-ws";

const recorded = recordedEvents as unknown as Record<string, StreamEvent[]>;

const t = (key: string, opts?: Record<string, unknown>) =>
  key.replace(/\{\{(\w+)\}\}/g, (_m, name) => String(opts?.[name] ?? ""));

/** The row a group of events resolves to, exactly as the component builds it. */
function rowFor(events: StreamEvent[]) {
  const provider = getToolProvider(events);
  const call = events.find((event) => event.type === "tool_call");
  const meta = (call?.metadata ?? {}) as Record<string, unknown>;
  const toolName = String(meta.tool_name ?? "");
  const args = meta.args as Record<string, unknown> | undefined;
  return { provider, row: describeProviderTool(toolName, args, provider, t) };
}

test("a recorded CLI app call resolves to a row naming the app and its arguments", () => {
  const { provider, row } = rowFor(recorded.cli);

  assert.deepEqual(provider, { source: "cli", id: "mermaid" });
  assert.deepEqual(row, {
    glyph: "command",
    verb: "Running mermaid",
    chip: "--help",
    mono: true,
  });
});

test("a recorded MCP call resolves to a row naming the service and its tool", () => {
  const { provider, row } = rowFor(recorded.mcp);

  assert.deepEqual(provider, { source: "mcp", id: "wolfram" });
  assert.deepEqual(row, {
    glyph: "link",
    verb: "Using wolfram",
    chip: "WolframAlpha",
    mono: true,
  });
});

test("every event of a recorded call carries the identity, not only the first", () => {
  // A reconnect mid-turn can drop the opening event; the row still has to be
  // labelled from whatever survived.
  for (const key of ["cli", "mcp"] as const) {
    const events = recorded[key];
    assert.ok(events.length > 1, `${key} fixture is too small to be meaningful`);
    for (let index = 0; index < events.length; index += 1) {
      const provider = getToolProvider(events.slice(index));
      assert.ok(provider?.source, `${key}: event ${index} onwards lost the provider`);
    }
  }
});

test("a recorded built-in call is not mistaken for a provider row", () => {
  // `load_tools` ran in the same turns and carries neither key.
  const builtin = [
    {
      type: "tool_call",
      content: "load_tools",
      metadata: { tool_name: "load_tools", trace_kind: "tool_call" },
    },
  ] as unknown as StreamEvent[];

  assert.equal(getToolProvider(builtin), null);
  assert.equal(rowFor(builtin).row, null);
});

test("the newest progress line wins, and non-progress events are ignored", () => {
  const events = [
    ...recorded.mcp,
    {
      type: "progress",
      content: "fetching pages (30%)",
      metadata: { trace_kind: "tool_progress", tool_source: "mcp", tool_provider: "wolfram" },
    },
    {
      type: "progress",
      content: "indexing (80%)",
      metadata: { trace_kind: "tool_progress", tool_source: "mcp", tool_provider: "wolfram" },
    },
  ] as unknown as StreamEvent[];

  assert.equal(getLatestToolProgress(events), "indexing (80%)");
});

test("a call that reported no progress leaves the row's own detail in place", () => {
  // Which is what actually happened in both recorded turns — most MCP servers
  // send no notifications — so the row must read fine without any.
  assert.equal(getLatestToolProgress(recorded.mcp), "");
  assert.equal(getLatestToolProgress(recorded.cli), "");
});

test("a call_status event is never mistaken for a progress line", () => {
  // Both are `progress` events; only `trace_kind` separates them, and
  // call_status carries an empty message that would blank the row's detail.
  const statuses = recorded.cli.filter(
    (event) => (event.metadata as Record<string, unknown> | undefined)?.trace_kind === "call_status",
  );
  assert.ok(statuses.length > 0, "the fixture should contain call_status events");
  assert.equal(getLatestToolProgress(statuses), "");
});
