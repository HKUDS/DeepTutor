import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

function webRoot(): string {
  let dir = __dirname;
  for (let i = 0; i < 8; i += 1) {
    if (fs.existsSync(path.join(dir, "package.json"))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error("could not locate web root");
}

test("planning messages render inside the media context providers", () => {
  const source = fs.readFileSync(
    path.join(webRoot(), "app", "(utility)", "mastery", "planning", "[planId]", "layout.tsx"),
    "utf8",
  );
  assert.match(source, /<ReadingProvider>/);
  assert.match(source, /<WatchingProvider>/);
});

test("planning draft preserves course scope and attaches the created path", () => {
  const source = fs.readFileSync(
    path.join(webRoot(), "app", "(utility)", "mastery", "planning", "[planId]", "draft", "page.tsx"),
    "utf8",
  );
  assert.match(source, /useCourseScope\(\)/);
  assert.match(source, /scope\?\.attach\("mastery_path", topic\.path_id, input\.name\.trim\(\)\)/);
  assert.match(source, /learningPlanRoute\(planId, \{ courseId: scope\?\.id \}\)/);
});
