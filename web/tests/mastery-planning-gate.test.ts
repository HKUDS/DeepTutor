import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const masteryPagePath = path.join(
  process.cwd(),
  "app",
  "(utility)",
  "mastery",
  "page.tsx",
);
const newMasteryPagePath = path.join(
  process.cwd(),
  "app",
  "(utility)",
  "mastery",
  "new",
  "page.tsx",
);

test("mastery entry uses the legacy wizard until experimental planning is enabled", () => {
  const source = fs.readFileSync(masteryPagePath, "utf8");

  assert.match(source, /const \{ experimentalMasteryPlanning \} = useAppShell\(\)/);
  assert.match(source, /if \(experimentalMasteryPlanning\) router\.push\("\/mastery\/new"\)/);
  assert.match(source, /\{wizardOpen && !experimentalMasteryPlanning && \(/);
  assert.match(source, /<CreateTopicWizard/);
});

test("new mastery planning page returns to the legacy entry when the gate is disabled", () => {
  const source = fs.readFileSync(newMasteryPagePath, "utf8");

  assert.match(
    source,
    /if \(experimentalMasteryPlanningReady && !experimentalMasteryPlanning\) \{\s*router\.replace\("\/mastery"\);/,
  );
  assert.match(
    source,
    /if \(experimentalMasteryPlanningReady && !experimentalMasteryPlanning\) return null;/,
  );
});
