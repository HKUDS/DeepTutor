import assert from "node:assert/strict";
import test from "node:test";

import { filterOutgoingAttachments } from "../features/chat/controllers/useChatAttachments";
import {
  capabilityLaunchIntent,
  pruneKnowledgeBases,
} from "../features/chat/controllers/useChatComposerController";
import { boundedReferences } from "../features/chat/controllers/useChatReferences";
import {
  routeSessionId,
  shouldRevalidateCachedSession,
} from "../features/chat/controllers/useChatRouteSession";

test("route/session selection and cached revalidation stay deterministic", () => {
  assert.equal(routeSessionId("session-1"), "session-1");
  assert.equal(routeSessionId(" "), null);
  assert.equal(
    shouldRevalidateCachedSession({
      routeSessionId: "session-1",
      selectedSessionId: "session-1",
      hasCachedMessages: true,
      isStreaming: false,
    }),
    true,
  );
  assert.equal(
    shouldRevalidateCachedSession({
      routeSessionId: "session-1",
      selectedSessionId: "session-1",
      hasCachedMessages: true,
      isStreaming: true,
    }),
    false,
  );
});

test("course launch intent and KB pruning do not mutate source values", () => {
  const selected = ["math", "missing", "math", "physics"];
  assert.deepEqual(
    pruneKnowledgeBases(selected, new Set(["math", "physics"])),
    ["math", "physics"],
  );
  assert.deepEqual(
    capabilityLaunchIntent({ capability: null, courseId: " course " }),
    {
      capability: "chat",
      tools: [],
      courseId: "course",
    },
  );
  assert.equal(selected.length, 4);
});

test("attachment and reference payloads are filtered and bounded before send", () => {
  assert.deepEqual(
    filterOutgoingAttachments(
      [
        { type: "document", filename: "ok.pdf", url: "/ok" },
        { type: "image", filename: "unsafe.svg", base64: "x" },
        { type: "document", filename: "missing.pdf" },
      ],
      5,
    ).map((item) => item.filename),
    ["ok.pdf"],
  );
  assert.deepEqual(
    boundedReferences({
      history: ["session-1", ""],
      notebooks: [{ notebook_id: "nb", record_ids: ["r"] }],
      books: [{ book_id: "", page_ids: ["p"] }],
      readings: [{ material_id: "m", revision: 0, locators: [1] }],
    }),
    {
      history: ["session-1"],
      notebooks: [{ notebook_id: "nb", record_ids: ["r"] }],
      books: [],
      readings: [],
    },
  );
});
