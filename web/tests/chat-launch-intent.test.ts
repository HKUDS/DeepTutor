import test from "node:test";
import assert from "node:assert/strict";

import {
  newMasteryPathChatUrl,
  readChatLaunchIntent,
} from "../lib/chat-launch-intent";

test("continuing a mastery path opens a fresh associated chat", () => {
  assert.equal(
    newMasteryPathChatUrl("calculus/path 1"),
    "/home?capability=mastery_path&mastery_path_id=calculus%2Fpath+1",
  );
});

test("the mastery continue URL round-trips into a launch intent", () => {
  const url = newMasteryPathChatUrl("calculus/path 1");
  const intent = readChatLaunchIntent(url.slice(url.indexOf("?")));
  assert.equal(intent.capability, "mastery_path");
  assert.equal(intent.masteryPathId, "calculus/path 1");
  assert.deepEqual(intent.tools, []);
});

test("an absent capability stays unspecified, an empty one means plain chat", () => {
  assert.equal(readChatLaunchIntent("?tool=web_search").capability, null);
  assert.equal(readChatLaunchIntent("?capability=").capability, "");
});

test("tools are collected verbatim for the caller to validate", () => {
  assert.deepEqual(
    readChatLaunchIntent("?tool=web_search&tool=+reason+").tools,
    ["web_search", "reason"],
  );
});

test("a blank mastery path id is dropped rather than bound", () => {
  assert.equal(readChatLaunchIntent("?mastery_path_id=%20%20").masteryPathId, null);
  assert.deepEqual(readChatLaunchIntent(""), {
    capability: null,
    tools: [],
    masteryPathId: null,
  });
});
