import assert from "node:assert/strict";
import {createRequire} from "node:module";
import {join} from "node:path";
import {test} from "node:test";
import {evaluateJavaScript} from "../../../deeptutor/services/sandbox/javascript.mjs";
const require = createRequire(join(process.env.DEEPTUTOR_REMOTION_RUNTIME, "package.json"));
const {getQuickJS} = require("quickjs-emscripten");
const vm = await getQuickJS();
const run = (source, options) => evaluateJavaScript(vm, source, options);

test("returns only strings, including async results", async () => {
  assert.equal(await run('"同步"'), "同步");
  assert.equal(await run('(async () => {await Promise.resolve(); return "async"})()'), "async");
  await assert.rejects(run('({host: "object"})'), /must return a string/);
  await assert.rejects(run('new Promise(() => {})'), /did not settle/);
});

test("no environment, filesystem, networking, workers or process APIs", async () => {
  process.env.DT_SANDBOX_TEST_SECRET = "dummy-host-secret";
  try {
    for (const name of ["process", "require", "fetch", "WebSocket", "XMLHttpRequest", "Worker", "Deno", "Bun", "std", "os", "WebAssembly"]) {
      assert.equal(await run(`typeof globalThis[${JSON.stringify(name)}]`), "undefined", name);
    }
    assert.equal(await run('Function("return typeof process")()'), "undefined");
    assert.equal(await run('({}).constructor.constructor("return typeof process")()'), "undefined");
    assert.equal(await run('eval("typeof process")'), "undefined");
    await assert.rejects(run('import("node:fs")'), /module|load/i);
  } finally { delete process.env.DT_SANDBOX_TEST_SECRET; }
});

test("guest prototype changes never reach the host or the next evaluation", async () => {
  assert.equal(await run('Object.prototype.polluted = "guest"; "done"'), "done");
  assert.equal(({}).polluted, undefined);
  assert.equal(await run('typeof ({}).polluted'), "undefined");
});

test("limits synchronous loops, async loops, allocation and output", async () => {
  for (const source of ['while(true) {}', '(async () => {while(true) await Promise.resolve()})()']) {
    await assert.rejects(run(source, {timeoutMs: 100}), /interrupt|timed out/);
  }
  await assert.rejects(run('const a=[]; while(true) a.push(new Uint8Array(1024*1024))', {
    memoryLimitBytes: 8 * 1024 * 1024, timeoutMs: 2000,
  }), /memory|alloc|null/i);
  await assert.rejects(run('"x".repeat(1001)', {maxOutputChars: 1000}), /output limit/);
  assert.equal(await run('"still usable"'), "still usable");
});

test("reports synchronous and async guest exceptions", async () => {
  await assert.rejects(run('throw new Error("sync failure")'), /sync failure/);
  await assert.rejects(run('(async () => {throw new Error("async failure")})()'), /async failure/);
});
