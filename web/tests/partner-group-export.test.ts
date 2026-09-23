import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import { buildChatMarkdown } from "../lib/chat-export";
import { toPartnerGroupExportMessages } from "../lib/partner-group-export";
import type { PartnerGroupMessage } from "../lib/partner-groups-api";

function message(
  role: "user" | "partner",
  content: string,
  authorName = "",
  kind = "message",
): PartnerGroupMessage {
  return {
    event_id: `${role}-${content}`,
    turn_id: "turn-1",
    session_key: "group-session",
    role,
    content,
    author_id: role === "user" ? "user" : authorName.toLowerCase(),
    author_name: authorName,
    created_at: "2026-09-23T00:00:00Z",
    mentions: [],
    error: false,
    kind,
    events: [],
    invocation_id: "",
    invocation: null,
  };
}

test("group export preserves transcript order and Partner attribution", () => {
  const messages = toPartnerGroupExportMessages([
    message("user", "Compare both approaches."),
    message("partner", "The first favors recall.", "Ada"),
    message("partner", "The second favors precision.", "Turing"),
  ]);

  assert.deepEqual(
    messages.map(({ role, content, speaker }) => ({ role, content, speaker })),
    [
      { role: "user", content: "Compare both approaches.", speaker: undefined },
      {
        role: "assistant",
        content: "The first favors recall.",
        speaker: "Ada",
      },
      {
        role: "assistant",
        content: "The second favors precision.",
        speaker: "Turing",
      },
    ],
  );

  const markdown = buildChatMarkdown(messages, {
    title: "Research panel — Retrieval",
    exportedAt: new Date("2026-09-23T08:00:00Z"),
  });
  assert.match(markdown, /^# Research panel — Retrieval/);
  assert.match(markdown, /_Exported: 2026-09-23T08:00:00\.000Z_/);
  assert.match(markdown, /## User\n\nCompare both approaches\./);
  assert.match(markdown, /## Ada\n\nThe first favors recall\./);
  assert.match(markdown, /## Turing\n\nThe second favors precision\./);
  assert.ok(markdown.indexOf("## Ada") < markdown.indexOf("## Turing"));
});

test("group export keeps untrusted speaker names on one heading line", () => {
  const [exported] = toPartnerGroupExportMessages([
    message("partner", "Still one message.", "Ada\n## Forged"),
  ]);
  const markdown = buildChatMarkdown([exported], {
    exportedAt: new Date("2026-09-23T08:00:00Z"),
  });
  assert.match(markdown, /## Ada ## Forged\n\nStill one message\./);
  assert.doesNotMatch(markdown, /## Ada\n## Forged/);
});

test("group export omits persisted round metadata", () => {
  const messages = toPartnerGroupExportMessages([
    message("user", "Start a panel."),
    message("partner", "Cancelled", "", "round_stopped"),
  ]);

  assert.deepEqual(messages, [
    {
      role: "user",
      content: "Start a panel.",
      speaker: undefined,
    },
  ]);
});

test("group page exposes a disabled-until-ready Markdown download control", () => {
  const pageSource = readFileSync(
    path.resolve(
      process.cwd(),
      "app/(workspace)/partners/groups/[groupId]/page.tsx",
    ),
    "utf8",
  );
  const chatSource = readFileSync(
    path.resolve(
      process.cwd(),
      "components/partners/group/PartnerGroupChat.tsx",
    ),
    "utf8",
  );

  assert.match(pageSource, /downloadChatMarkdown\(exportMessages/);
  assert.match(pageSource, /disabled=\{!groupMessages\.length\}/);
  assert.match(pageSource, /onMessagesChange=\{setGroupMessages\}/);
  assert.match(
    chatSource,
    /onMessagesChange\?\.\(loading \? \[\] : messages\)/,
  );
});
