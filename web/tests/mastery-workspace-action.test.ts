import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  CHAT_CAPABILITIES,
  MASTERY_CAPABILITY_VALUE,
  VISIBLE_CHAT_CAPABILITIES,
  WORKSPACE_CHAT_CAPABILITIES,
  mergeCapabilityPresentations,
} from "../features/capabilities/presentation";

const capability = (value: string) =>
  CHAT_CAPABILITIES.find((entry) => entry.value === value);

test("the study screen runs the tutor loop, not chat", () => {
  // The screen used to open on "Chat", which reached the tutor anyway through
  // the workspace flag. The visible label named the wrong loop, and picking
  // "Mastery Path" from the same menu was a second route to one place.
  assert.equal(MASTERY_CAPABILITY_VALUE, "mastery_path");
  assert.ok(capability(MASTERY_CAPABILITY_VALUE));
});

test("entering a course does not take a tool away from the learner", () => {
  const chat = capability("");
  const mastery = capability(MASTERY_CAPABILITY_VALUE);

  assert.ok(chat && mastery);
  assert.deepEqual(
    [...mastery.allowedTools].sort(),
    [...chat.allowedTools].sort(),
  );
});

test("the tutor loop is reached by being in the workspace, never picked from a menu", () => {
  // Home offers actions to run on the current conversation; the tutor is not
  // one of them, it is where the Mastery screen already is. Reading's action
  // menu excludes it for the same reason.
  for (const list of [VISIBLE_CHAT_CAPABILITIES, WORKSPACE_CHAT_CAPABILITIES]) {
    assert.ok(
      !list.some((entry) => entry.value === MASTERY_CAPABILITY_VALUE),
      "mastery_path must not appear in an action menu",
    );
  }
});

test("the catalog still resolves the tutor loop when the backend offers it", () => {
  // Excluded from the menus above, but the pinned workspace looks it up by id
  // and needs its real presentation (icon, label, tool list) — not the
  // "unknown extension" fallback.
  const [resolved] = mergeCapabilityPresentations([
    {
      id: MASTERY_CAPABILITY_VALUE,
      kind: "capability",
      available: true,
      manifest: null,
      configSchema: null,
    },
  ]);

  assert.equal(resolved.value, MASTERY_CAPABILITY_VALUE);
  assert.ok(resolved.allowedTools.includes("web_search"));
  assert.ok(resolved.allowedTools.length > 2);
});

test("the mastery composer pins its action and renders no action menu", () => {
  const source = fs.readFileSync(
    path.join(process.cwd(), "components/space/learning/MasteryComposer.tsx"),
    "utf8",
  );

  assert.match(source, /pinnedCapability: MASTERY_CAPABILITY_VALUE/);
  assert.match(source, /showCapabilityChip=\{false\}/);
  // The pin has to also be on the session configuration, or every
  // configuration pass would reset the capability to chat.
  const sessionHook = fs.readFileSync(
    path.join(process.cwd(), "hooks/useMasteryStudySession.ts"),
    "utf8",
  );
  assert.match(sessionHook, /capability: MASTERY_CAPABILITY_VALUE/);
});
