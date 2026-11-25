import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

test("workspace owns one runtime and Reading does not nest another", () => {
  assert.match(source("app/(shell)/layout.tsx"), /ChatRuntimeProvider/);
  assert.doesNotMatch(
    source("app/(shell)/(workspace)/layout.tsx"),
    /ChatRuntimeProvider|ChatStateAdapterProvider/,
  );
  assert.doesNotMatch(
    source("app/(shell)/(workspace)/learning/reading/layout.tsx"),
    /ChatRuntimeProvider|ChatStateAdapterProvider/,
  );
});

test("Mastery study inherits the workspace runtime without nesting", () => {
  assert.doesNotMatch(
    source("app/(shell)/(workspace)/learning/mastery/[pathId]/sessions/layout.tsx"),
    /ChatRuntimeProvider/,
  );
});

test("the runtime provider mounts one live state owner", () => {
  const provider = source("features/chat/ChatRuntimeProvider.tsx");
  assert.match(provider, /ChatStateAdapterProvider/);
  assert.doesNotMatch(provider, /createChatStore|ChatActions|ChatStoreProvider/);
  assert.match(provider, /cannot be nested/);
});
