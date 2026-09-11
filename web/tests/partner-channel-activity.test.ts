import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = readFileSync(
  path.resolve(process.cwd(), "components/partners/PartnerChat.tsx"),
  "utf8",
);

test("partner chat restores only the active conversation", () => {
  assert.match(
    source,
    /getPartnerHistory\(partnerId, \{ sessionKey, limit: 60 \}\)/,
  );
});

test("partner chat renders external user echoes and live trace events", () => {
  assert.match(source, /if \(data\.external && data\.activity_id\)/);
  assert.match(source, /data\.type === "user_echo"/);
  assert.match(source, /data\.type === "stream_event" && data\.event/);
  assert.match(source, /externalDrafts\.map/);
  assert.match(
    source,
    /<AssistantActivity[\s\S]*events=\{externalDraft\.events\}/,
  );
});

test("history activity ids prevent replayed channel turns from duplicating", () => {
  assert.match(source, /m\.metadata\?\.activity_id/);
  assert.match(
    source,
    /msg\.activityId === activityId && msg\.role === "user"/,
  );
  assert.match(
    source,
    /msg\.activityId === activityId && msg\.role === "assistant"/,
  );
});
