import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { runInNewContext } from "node:vm";

function compact(source: string): { output: string; resources: unknown } {
  const loaderContext = { module: { exports: undefined as unknown } };
  runInNewContext(
    readFileSync(path.join(process.cwd(), "scripts/compact-locale-loader.cjs"), "utf8"),
    loaderContext,
  );
  const loader = loaderContext.module.exports as (source: string) => string;
  const output = loader.call({}, source);
  const context = { module: { exports: undefined as unknown } };
  runInNewContext(output, context);
  return { output, resources: JSON.parse(JSON.stringify(context.module.exports)) };
}

test("compact English resources preserve every translation and remove duplicate copy", () => {
  const source = readFileSync(path.join(process.cwd(), "locales/en/app.json"), "utf8");
  const result = compact(source);
  assert.deepEqual(result.resources, JSON.parse(source));
  assert.ok(result.output.length < JSON.stringify(JSON.parse(source)).length * 0.65);
});

test("compact resources preserve interpolation, escapes, empty values and special keys", () => {
  const source = '{"Hello {{name}}":"Hello {{name}}","key":"Translated", "quote\\\"":"quote\\\"", "empty":"", "__proto__":"safe", "constructor":"constructor"}';
  assert.deepEqual(compact(source).resources, JSON.parse(source));
});
