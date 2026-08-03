import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = readFileSync(
  path.resolve(process.cwd(), "lib/book-api.ts"),
  "utf8",
);

test("long-running Book operations use the streaming WebSocket transport", () => {
  // These operations routinely outlive the Next.js HTTP proxy's idle window.
  // Keeping this contract explicit prevents a future refactor from restoring
  // the false-failure pattern where REST disconnects while the backend keeps
  // generating the spine or page.
  assert.doesNotMatch(source, /\/books\/confirm-proposal/);
  assert.doesNotMatch(source, /\/books\/compile-page/);

  assert.match(source, /type:\s*"confirm_proposal"/);
  assert.match(source, /"confirm_proposal_result"/);
  assert.match(source, /type:\s*"compile_page"/);
  assert.match(source, /"compile_page_result"/);
});
