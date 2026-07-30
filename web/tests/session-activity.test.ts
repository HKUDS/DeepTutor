import test from "node:test";
import assert from "node:assert/strict";
import {
  artifactDiskPath,
  buildSessionActivity,
} from "../lib/session-activity";
import type {
  MessageItem,
  MessageRequestSnapshot,
} from "../context/UnifiedChatContext";
import type { StreamEvent } from "../lib/unified-ws";

/** A StreamEvent with only the fields the fold reads set explicitly. */
function event(
  type: string,
  metadata: Record<string, unknown> = {},
): StreamEvent {
  return {
    type: type as StreamEvent["type"],
    source: "",
    stage: "",
    content: "",
    metadata,
    timestamp: 0,
  };
}

/** A request snapshot with only the fields the fold reads set explicitly. */
function snapshot(
  fields: Partial<MessageRequestSnapshot> = {},
): MessageRequestSnapshot {
  return {
    content: "",
    enabledTools: [],
    knowledgeBases: [],
    language: "en",
    ...fields,
  };
}

function messages(...items: Partial<MessageItem>[]): MessageItem[] {
  return items.map(
    (item, idx) =>
      ({
        id: idx + 1,
        role: idx % 2 === 0 ? "user" : "assistant",
        content: "",
        ...item,
      }) as MessageItem,
  );
}

const UPLOAD = {
  type: "document",
  filename: "syllabus.pdf",
  id: "att-1",
  url: "/api/attachments/att-1/syllabus.pdf",
};

const ARTIFACT = {
  type: "document",
  filename: "summary.pptx",
  generated: true,
  size_bytes: 24_576,
  url: "/api/outputs/workspace/chat/chat/turn_1/exec/summary.pptx",
};

/* ------------------------------------------------------------------ */
/*  uploads vs generated files                                         */
/* ------------------------------------------------------------------ */

test("splits generated files out of user uploads", () => {
  const activity = buildSessionActivity(
    messages(
      { role: "user", attachments: [UPLOAD] },
      { role: "assistant", attachments: [ARTIFACT] },
    ),
  );

  assert.equal(activity.attachments.length, 1);
  assert.equal(activity.attachments[0].attachment.filename, "syllabus.pdf");
  assert.equal(activity.artifacts.length, 1);
  assert.equal(activity.artifacts[0].attachment.filename, "summary.pptx");
});

test("keeps the originating message index on both lists", () => {
  const activity = buildSessionActivity(
    messages(
      { role: "user", attachments: [UPLOAD] },
      { role: "assistant", attachments: [ARTIFACT] },
    ),
  );

  assert.equal(activity.attachments[0].messageIndex, 0);
  assert.equal(activity.artifacts[0].messageIndex, 1);
});

test("collects generated files across every turn in order", () => {
  const second = { ...ARTIFACT, filename: "chart.png", type: "image" };
  const activity = buildSessionActivity(
    messages(
      { role: "user" },
      { role: "assistant", attachments: [ARTIFACT] },
      { role: "user" },
      { role: "assistant", attachments: [second] },
    ),
  );

  assert.deepEqual(
    activity.artifacts.map((a) => a.attachment.filename),
    ["summary.pptx", "chart.png"],
  );
});

test("a session with only generated files is not empty", () => {
  // Regression guard: isEmpty ignoring artifacts would render the empty-state
  // card over a session that did produce something.
  const activity = buildSessionActivity(
    messages({ role: "assistant", attachments: [ARTIFACT] }),
  );

  assert.equal(activity.isEmpty, false);
  assert.equal(activity.attachments.length, 0);
});

test("a session with nothing at all is empty", () => {
  const activity = buildSessionActivity(messages({ role: "user" }));

  assert.equal(activity.isEmpty, true);
  assert.equal(activity.artifacts.length, 0);
});

/* ------------------------------------------------------------------ */
/*  tools / knowledge bases                                            */
/* ------------------------------------------------------------------ */

test("counts tool calls and orders them by frequency", () => {
  const activity = buildSessionActivity(
    messages({
      role: "assistant",
      events: [
        event("tool_call", { tool: "rag" }),
        event("tool_call", { tool: "exec" }),
        event("tool_call", { tool: "rag" }),
        event("content"),
      ],
    }),
  );

  assert.deepEqual(activity.tools, [
    { name: "rag", count: 2 },
    { name: "exec", count: 1 },
  ]);
});

test("dedupes knowledge bases across turns", () => {
  const activity = buildSessionActivity(
    messages(
      { role: "user", requestSnapshot: snapshot({ knowledgeBases: ["KB"] }) },
      { role: "user", requestSnapshot: snapshot({ knowledgeBases: ["KB"] }) },
    ),
  );

  assert.deepEqual(activity.knowledgeBases, ["KB"]);
});

/* ------------------------------------------------------------------ */
/*  artifactDiskPath                                                   */
/* ------------------------------------------------------------------ */

test("derives the data-root-relative path from an outputs URL", () => {
  assert.equal(
    artifactDiskPath(ARTIFACT.url),
    "workspace/chat/chat/turn_1/exec/summary.pptx",
  );
});

test("decodes percent-escaped segments", () => {
  assert.equal(
    artifactDiskPath(
      "/api/outputs/workspace/chat/chat/t/exec/%E6%8A%A5%E5%91%8A.pptx",
    ),
    "workspace/chat/chat/t/exec/报告.pptx",
  );
});

test("falls back to the raw form on a malformed escape", () => {
  assert.equal(artifactDiskPath("/api/outputs/bad%zz.pptx"), "bad%zz.pptx");
});

test("returns null for uploads and for missing URLs", () => {
  assert.equal(artifactDiskPath(UPLOAD.url), null);
  assert.equal(artifactDiskPath(undefined), null);
  assert.equal(artifactDiskPath(""), null);
});
