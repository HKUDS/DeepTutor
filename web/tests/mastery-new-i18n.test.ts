import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

function findWebRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i++) {
    if (fs.existsSync(path.join(dir, "locales", "en", "app.json"))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate web root");
}

const WEB = findWebRoot();
const PAGE = path.join(WEB, "app", "(utility)", "mastery", "new", "page.tsx");
const EN = JSON.parse(fs.readFileSync(path.join(WEB, "locales", "en", "app.json"), "utf8"));
const ZH = JSON.parse(fs.readFileSync(path.join(WEB, "locales", "zh", "app.json"), "utf8"));
const ACTIVITY_KEYS = ["Reading", "Practice", "Projects", "Discussion", "Assessment"];

function pageKeys(): string[] {
  const source = fs.readFileSync(PAGE, "utf8");
  const keys = new Set<string>(ACTIVITY_KEYS);
  for (const match of source.matchAll(/\bt\(\s*["']((?:[^"'\\]|\\.)+)["']/g)) {
    keys.add(match[1]);
  }
  return [...keys];
}

test("mastery creation page has locale entries for every literal t() key", () => {
  const missing = pageKeys().filter((key) => !(key in EN) || !(key in ZH));
  assert.deepEqual(missing, []);
});

test("mastery creation page does not fall back to English in Chinese", () => {
  const echoed = pageKeys().filter(
    (key) => key.length > 3 && !key.includes("{{") && ZH[key] === key,
  );
  assert.deepEqual(echoed, []);
});
