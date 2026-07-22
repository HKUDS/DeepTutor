import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// Resolve <web>/locales by walking up from the compiled test location
// (dist/node-tests/tests/*.js) until we find the locales directory.
function findLocalesRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, "locales");
    if (fs.existsSync(path.join(candidate, "en"))) return candidate;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate locales/ directory from " + __dirname);
}

function listJsonFiles(dir: string): string[] {
  const out: string[] = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...listJsonFiles(full));
    else if (ent.isFile() && ent.name.endsWith(".json")) out.push(full);
  }
  return out;
}

// A "namespace key" is a dotted identifier such as `settingsTour.appearance.title`
// (lowercase camelCase segments, no whitespace). These are code-side keys whose
// value must be real translated copy — never the key itself. Plain-English keys
// like "Back" or proper nouns like "Chart.js" do not match (the latter starts
// uppercase), so they are correctly excluded.
const NAMESPACE_KEY = /^[a-z][A-Za-z0-9]*(\.[A-Za-z0-9]+)+$/;

const localesRoot = findLocalesRoot();
const enRoot = path.join(localesRoot, "en");

for (const file of listJsonFiles(enRoot)) {
  const rel = path.relative(localesRoot, file).replaceAll("\\", "/");
  test(`en locale ${rel} has no untranslated placeholder values`, () => {
    const json = JSON.parse(fs.readFileSync(file, "utf8")) as Record<
      string,
      unknown
    >;
    const placeholders: string[] = [];
    for (const [key, value] of Object.entries(json)) {
      if (NAMESPACE_KEY.test(key) && value === key) placeholders.push(key);
    }
    assert.deepEqual(
      placeholders,
      [],
      `Found namespace keys whose value equals the key (untranslated placeholders): ${placeholders.join(", ")}`,
    );
  });
}
