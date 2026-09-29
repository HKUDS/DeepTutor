import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

test("ChatStateAdapter implements resendLastMessage preserving snapshot", () => {
  const adapter = source("features/chat/ChatStateAdapter.tsx");
  assert.match(adapter, /resendLastMessage/);
  assert.match(adapter, /requestSnapshotOverride/);
  assert.match(adapter, /displayUserMessage: false/);
  assert.match(adapter, /POP_LAST_ASSISTANT/);
});

test("ChatMessageList renders Resend only for failed last assistant turn", () => {
  const list = source("features/chat/messages/ChatMessageList.tsx");
  assert.match(list, /canResendLastTurn/);
  assert.match(list, /onResendLastTurn/);
  assert.match(list, /showResend/);
  assert.match(list, /Resend/);
});

test("ChatWorkspace wires resend props to ChatMessageList", () => {
  const workspace = source("features/chat/components/ChatWorkspace.tsx");
  assert.match(workspace, /resendLastMessage/);
  assert.match(workspace, /canResendLastTurn=\{state\.lastTurnFailed\}/);
  assert.match(workspace, /onResendLastTurn=\{handleResendMessage\}/);
});

test("Resend translations exist in en and zh", () => {
  const en = JSON.parse(source("locales/en/app.json"));
  const zh = JSON.parse(source("locales/zh/app.json"));
  assert.equal(en.Resend, "Resend");
  assert.equal(zh.Resend, "重新发送");
});

test("failed submissions stay visibly unsent and recoverable (#1594)", () => {
  const adapter = source("features/chat/ChatStateAdapter.tsx");
  assert.match(adapter, /storeFailedSubmission/);
  assert.match(adapter, /readFailedSubmission/);
  assert.match(adapter, /clearFailedSubmission/);
  assert.match(adapter, /submissionFailed: true/);
  const list = source("features/chat/messages/ChatMessageList.tsx");
  assert.match(list, /failedSubmission/);
  assert.match(list, /data-unsent="true"/);
  assert.match(list, /Not sent/);
  const workspace = source("features/chat/components/ChatWorkspace.tsx");
  assert.match(workspace, /state\.submissionFailed/);
  assert.match(workspace, /data-submission-error="true"/);
  const en = JSON.parse(source("locales/en/app.json"));
  const zh = JSON.parse(source("locales/zh/app.json"));
  assert.equal(en["Not sent"], "Not sent");
  assert.equal(zh["Not sent"], "未发送");
});
