import assert from "node:assert/strict";
import test from "node:test";
import { invidiousAccountResultMessage } from "../lib/invidious-account-result";

test("authorization failures give specific recovery steps without reflecting input", () => {
  assert.match(
    invidiousAccountResultMessage("authorization_expired")!,
    /start again/,
  );
  assert.match(
    invidiousAccountResultMessage("authorization_login_required")!,
    /DeepTutor login/,
  );
  assert.match(
    invidiousAccountResultMessage("authorization_unavailable")!,
    /instance/,
  );
  assert.match(invidiousAccountResultMessage("connected")!, /connected/);
  assert.equal(invidiousAccountResultMessage("token=secret"), null);
});
