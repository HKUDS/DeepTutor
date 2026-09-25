import assert from "node:assert/strict";
import test from "node:test";

import { waitForReplyLanguageSave } from "../features/chat/controllers/reply-language-save";

test("a failed selector save keeps the draft and blocks sending in the old language", async () => {
  const restored: string[] = [];
  const send = async (pending: Promise<void> | null) => {
    if (!(await waitForReplyLanguageSave(pending, "Explain in French", (draft) => restored.push(draft)))) {
      return false;
    }
    return true;
  };

  assert.equal(await send(Promise.reject(new Error("Save failed"))), false);
  assert.deepEqual(restored, ["Explain in French"]);
  assert.equal(await send(Promise.resolve()), true);
  assert.equal(await send(null), true);
});
