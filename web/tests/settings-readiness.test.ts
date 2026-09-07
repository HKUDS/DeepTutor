import assert from "node:assert/strict";
import test from "node:test";

import {
  groupReadinessRows,
  isProminentReadinessRow,
  readinessRowHref,
  readinessRowSeverity,
  summarizeReadinessRows,
  type SettingsReadinessRow,
} from "../lib/settings-readiness";

function row(
  id: string,
  section: string,
  state: SettingsReadinessRow["state"],
  required = false,
): SettingsReadinessRow {
  return {
    id,
    section,
    state,
    required,
    label: id,
    detail_code: "test",
    enabled: state === "enabled_verified",
    available: state !== "unavailable",
    configured: state === "enabled_verified",
    verified: state === "enabled_verified",
  };
}

test("readiness summary always contains all five states", () => {
  const summary = summarizeReadinessRows([
    row("catalog.llm", "catalog", "enabled_verified"),
    row("tool.imagegen", "tools", "misconfigured"),
  ]);

  assert.deepEqual(summary, {
    enabled_verified: 1,
    available_disabled: 0,
    unavailable: 0,
    misconfigured: 1,
    not_selected: 0,
  });
});

test("readiness sections read in declared order, unknown sections last", () => {
  const groups = groupReadinessRows([
    row("parser.text", "document_parsing", "enabled_verified"),
    row("plugin.a", "plugins", "enabled_verified"),
    row("catalog.llm", "catalog", "enabled_verified"),
    row("parser.tika", "document_parsing", "available_disabled"),
  ]);

  assert.deepEqual(
    groups.map(([section, rows]) => [section, rows.map((item) => item.id)]),
    [
      ["catalog", ["catalog.llm"]],
      ["document_parsing", ["parser.text", "parser.tika"]],
      ["plugins", ["plugin.a"]],
    ],
  );
});

test("an optional capability nobody set up is not a problem", () => {
  // The whole point of the panel: a fresh install ships with no video model
  // and its tool still on, and that must not read as something to fix.
  assert.equal(
    readinessRowSeverity(row("catalog.videogen", "catalog", "not_selected")),
    null,
  );
  assert.equal(
    readinessRowSeverity(row("tool.videogen", "tools", "unavailable")),
    null,
  );

  // A required capability that cannot run blocks; a selection that broke warns.
  assert.equal(
    readinessRowSeverity(row("catalog.llm", "catalog", "not_selected", true)),
    "blocker",
  );
  assert.equal(
    readinessRowSeverity(row("parser.tika", "document_parsing", "misconfigured")),
    "warning",
  );
});

test("only running and troubled rows stay unfolded", () => {
  assert.equal(
    isProminentReadinessRow(row("catalog.llm", "catalog", "enabled_verified")),
    true,
  );
  assert.equal(
    isProminentReadinessRow(row("parser.tika", "document_parsing", "misconfigured")),
    true,
  );
  assert.equal(
    isProminentReadinessRow(row("catalog.stt", "catalog", "not_selected")),
    false,
  );
  assert.equal(
    isProminentReadinessRow(row("parser.mineru", "document_parsing", "available_disabled")),
    false,
  );
});

test("rows link to the page that owns them", () => {
  assert.equal(readinessRowHref("catalog.task"), "/settings#task-models");
  assert.equal(readinessRowHref("catalog.llm"), "/settings#llm");
  assert.equal(readinessRowHref("parser.mineru"), "/settings#knowledge");
  assert.equal(readinessRowHref("tool.videogen"), "/settings#tools");
  assert.equal(readinessRowHref("video.invidious"), "/settings#video-learning");
  assert.equal(
    readinessRowHref("runtime.coordination.redis"),
    "/settings#network",
  );
  assert.equal(readinessRowHref("knowledge.0"), "/knowledge-bases");
  assert.equal(readinessRowHref("visualizer.manim_video"), null);
});
