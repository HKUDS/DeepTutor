import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

test("workspace owns one runtime and Reading does not nest another", () => {
  assert.match(source("app/(workspace)/layout.tsx"), /ChatRuntimeProvider/);
  assert.doesNotMatch(
    source("app/(workspace)/reading/layout.tsx"),
    /ChatRuntimeProvider|ChatStateAdapterProvider/,
  );
});

test("Mastery study receives its own runtime outside the workspace group", () => {
  assert.match(
    source("app/(utility)/mastery/[pathId]/sessions/layout.tsx"),
    /ChatRuntimeProvider/,
  );
});

test("the runtime provider mounts one live state owner", () => {
  const provider = source("features/chat/ChatRuntimeProvider.tsx");
  assert.match(provider, /ChatStateAdapterProvider/);
  assert.doesNotMatch(provider, /createChatStore|ChatActions|ChatStoreProvider/);
  assert.match(provider, /cannot be nested/);
});
