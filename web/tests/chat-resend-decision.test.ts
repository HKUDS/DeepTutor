import assert from "node:assert/strict";
import test from "node:test";

import { decideFailedTurnReplay, isFailedTurnVisible } from "../lib/chat-resend";

test("an earlier completed turn does not discard an unsaved failed attempt", () => {
  const previous = { id: 1, role: "user" as const, parentMessageId: null };
  const lastUser = { id: -3, parentMessageId: 2, requestSnapshot: { content: "retry me" } };
  assert.deepEqual(
    decideFailedTurnReplay(
      [previous, { id: 2 }, lastUser, { id: -4 }],
      lastUser,
      { status: "completed", messages: [
        { id: 1, role: "user", content: "old" },
        { id: 2, role: "assistant", content: "done" },
      ] },
    ),
    { kind: "resend" },
  );
});

test("PocketBase string ids are already persisted, so old rows are not mistaken for this turn", () => {
  const lastUser = { id: -3, parentMessageId: "assistant_old", requestSnapshot: { content: "retry me" } };
  assert.deepEqual(
    decideFailedTurnReplay(
      [{ id: "user_old" }, { id: "assistant_old" }, lastUser, { id: -4 }],
      lastUser,
      { status: "completed", messages: [
        { id: "user_old", role: "user", content: "old" },
        { id: "assistant_old", role: "assistant", content: "done" },
      ] },
    ),
    { kind: "resend" },
  );
});

test("a failed user persisted during socket loss is reconciled before regenerate", () => {
  const lastUser = { id: -3, parentMessageId: "assistant_old", requestSnapshot: { content: "retry me" } };
  assert.deepEqual(
    decideFailedTurnReplay(
      [{ id: "assistant_old" }, lastUser, { id: -4 }],
      lastUser,
      { status: "failed", messages: [
        { id: "assistant_old", role: "assistant", content: "done" },
        { id: "user_new", role: "user", content: "retry me", parent_message_id: "assistant_old" },
      ] },
    ),
    { kind: "reconcile_regenerate", userId: "user_new" },
  );
});

test("resend is unavailable when the failed tail is hidden by branch selection", () => {
  const root = { id: 1, role: "user" as const, parentMessageId: null };
  const older = { id: 2, role: "assistant" as const, parentMessageId: 1 };
  const newer = { id: 3, role: "assistant" as const, parentMessageId: 1 };
  assert.equal(isFailedTurnVisible([root, older, newer], { "1": 2 }, "failed", false), false);
  assert.equal(isFailedTurnVisible([root, older, newer], { "1": 3 }, "failed", false), true);
});
