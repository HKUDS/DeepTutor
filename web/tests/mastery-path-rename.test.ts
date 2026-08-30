import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

function source(file: string): string {
  return readFileSync(path.resolve(process.cwd(), file), "utf8");
}

/**
 * Renaming a path was implemented, then lost when the topic detail page was
 * rewritten — the component survived with no importer, so nothing failed. A
 * reachability check is the only kind of test that would have caught it.
 */
test("a learner can rename a path from the topic detail page", () => {
  const page = source("app/(utility)/mastery/[pathId]/page.tsx");
  const title = source("components/space/learning/PathTitle.tsx");

  assert.match(page, /import \{ PathTitle \}/);
  assert.match(page, /<PathTitle/);
  assert.match(page, /renameProgress\(pathId, name\)/);
  // The write must land in local state: this page otherwise rediscovers
  // changes through the activity feed a poll interval later.
  assert.match(page, /setTopic\(\(previous\) =>[\s\S]*?name: saved\.name/);
  assert.match(title, /storedName/);
});

test("the rename editor opens with the stored name, not a derived label", () => {
  const title = source("components/space/learning/PathTitle.tsx");

  // Seeding the field with the derived display label would let "save" pin
  // that placeholder as the real name and cost the path its fallback.
  assert.match(title, /useState\(storedName\)/);
  assert.doesNotMatch(title, /useState\(displayName\)/);
  // Blur must not commit — that turns "clicked elsewhere" into a rename.
  assert.match(
    title,
    /onBlur=\{\(\) => \{\s*if \(draft\.trim\(\) === storedName\.trim\(\)\) setEditing\(false\);/,
  );
});
