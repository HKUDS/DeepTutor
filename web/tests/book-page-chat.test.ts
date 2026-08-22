import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = readFileSync(
  path.resolve(
    process.cwd(),
    "app/(workspace)/book/components/BookChatPanel.tsx",
  ),
  "utf8",
);

test("resolving the first Page Chat session preserves its active socket", () => {
  const effectStart = source.indexOf("let cancelled = false;");
  const sameSessionGuard = source.indexOf(
    "initialSessionId === sessionIdRef.current",
    effectStart,
  );
  const disconnect = source.indexOf(
    "clientRef.current?.disconnect();",
    effectStart,
  );

  assert.notEqual(effectStart, -1);
  assert.notEqual(sameSessionGuard, -1);
  assert.notEqual(disconnect, -1);
  assert.ok(
    sameSessionGuard < disconnect,
    "the newly persisted session id must be ignored before resetting the live turn",
  );
});
