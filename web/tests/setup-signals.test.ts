import test from "node:test";
import assert from "node:assert/strict";

import {
  collectAppliedSettingIds,
  extractSetupCredential,
} from "../lib/setup-signals";
import type { StreamEvent } from "../lib/unified-ws";

function toolResult(
  toolMetadata: Record<string, unknown>,
  extra: Partial<StreamEvent> = {},
): StreamEvent {
  return {
    type: "tool_result",
    source: "test",
    stage: "loop",
    content: "",
    metadata: { tool_metadata: toolMetadata },
    session_id: "session-1",
    turn_id: "turn-1",
    seq: 1,
    timestamp: 0,
    ...extra,
  } as StreamEvent;
}

test("extractSetupCredential reads the hand-off payload", () => {
  const data = extractSetupCredential([
    toolResult({
      setup_credential: {
        service: "llm",
        label: "chat model provider",
        settings_path: "/settings/llm",
        reason: "需要 API key",
      },
    }),
  ]);
  assert.deepEqual(data, {
    service: "llm",
    label: "chat model provider",
    settingsPath: "/settings/llm",
    reason: "需要 API key",
  });
});

test("extractSetupCredential keeps the most recent hand-off", () => {
  const data = extractSetupCredential([
    toolResult({ setup_credential: { settings_path: "/settings/llm" } }),
    toolResult({ setup_credential: { settings_path: "/settings/search" } }),
  ]);
  assert.equal(data?.settingsPath, "/settings/search");
});

test("extractSetupCredential refuses a path outside settings", () => {
  // The path is navigated to, so anything that is not an in-app settings route
  // would make the card an open redirect.
  for (const path of [
    "https://evil.example.com",
    "//evil.example.com",
    "/home",
    "",
  ]) {
    assert.equal(
      extractSetupCredential([
        toolResult({ setup_credential: { settings_path: path } }),
      ]),
      null,
      `should reject ${path}`,
    );
  }
});

test("extractSetupCredential ignores unrelated tool results", () => {
  assert.equal(
    extractSetupCredential([
      toolResult({ ask_user: { questions: [] } }),
      toolResult({ setup_inspect: { settings: [] } }),
    ]),
    null,
  );
  assert.equal(extractSetupCredential([]), null);
  assert.equal(extractSetupCredential(undefined), null);
});

test("collectAppliedSettingIds returns one id per applied change", () => {
  const ids = collectAppliedSettingIds([
    {
      events: [
        toolResult({ setup_applied: { key: "interface.language" } }, {
          tool_call_id: "call-1",
        } as Partial<StreamEvent>),
        toolResult({ setup_applied: { key: "interface.theme" } }, {
          tool_call_id: "call-2",
        } as Partial<StreamEvent>),
      ],
    },
  ]);
  assert.deepEqual(ids, ["call-1", "call-2"]);
});

test("collectAppliedSettingIds deduplicates a replayed tool call", () => {
  // History replay re-delivers the same event; honouring it twice would
  // overwrite a preference the user has since changed by hand.
  const event = toolResult({ setup_applied: { key: "interface.theme" } }, {
    tool_call_id: "call-1",
  } as Partial<StreamEvent>);
  const ids = collectAppliedSettingIds([
    { events: [event] },
    { events: [event] },
  ]);
  assert.deepEqual(ids, ["call-1"]);
});

test("collectAppliedSettingIds falls back to key and seq without a call id", () => {
  const ids = collectAppliedSettingIds([
    {
      events: [
        toolResult({ setup_applied: { key: "interface.theme" } }, { seq: 7 }),
        toolResult({ setup_applied: { key: "interface.theme" } }, { seq: 9 }),
      ],
    },
  ]);
  assert.deepEqual(ids, ["interface.theme:7", "interface.theme:9"]);
});

test("collectAppliedSettingIds ignores turns that changed nothing", () => {
  assert.deepEqual(
    collectAppliedSettingIds([
      { events: [toolResult({ setup_inspect: { settings: [] } })] },
      { events: [] },
      {},
    ]),
    [],
  );
  assert.deepEqual(collectAppliedSettingIds(undefined), []);
});
