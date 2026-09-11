import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const readWebFile = (...parts: string[]) =>
  readFileSync(path.join(process.cwd(), ...parts), "utf8");

test("runtime RAM and long-term memory use distinct Chinese labels", () => {
  const usage = readWebFile("components", "settings", "MemoryUsageItem.tsx");
  const zh = JSON.parse(readWebFile("locales", "zh", "app.json")) as Record<
    string,
    string
  >;

  assert.match(usage, /t\("System memory"\)/);
  assert.doesNotMatch(usage, /t\("Memory"\)/);
  assert.equal(zh["System memory"], "内存");
  assert.equal(zh.Memory, "记忆");
});
