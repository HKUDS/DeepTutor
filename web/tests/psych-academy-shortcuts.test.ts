import test from "node:test";
import assert from "node:assert/strict";

import {
  psychAcademyDedicatedRoute,
  psychAcademyPageHref,
  PSYCH_ACADEMY_SHORTCUTS,
} from "../lib/psych-academy-shortcuts";

test("psychAcademyDedicatedRoute maps plugin capabilities to workspace pages", () => {
  assert.equal(psychAcademyDedicatedRoute("counsel"), "/counsel");
  assert.equal(psychAcademyDedicatedRoute("counsel_sim"), "/sim");
  assert.equal(psychAcademyDedicatedRoute("distill"), "/distill");
  assert.equal(psychAcademyDedicatedRoute("mastery_path"), null);
  assert.equal(psychAcademyDedicatedRoute(null), null);
});

test("psychAcademyPageHref returns dedicated routes", () => {
  assert.equal(psychAcademyPageHref("train"), "/train");
  assert.equal(psychAcademyPageHref("counsel"), "/counsel");
});

test("PSYCH_ACADEMY_SHORTCUTS lists five academy surfaces", () => {
  assert.deepEqual(
    PSYCH_ACADEMY_SHORTCUTS.map((s) => s.id),
    ["counsel", "sim", "distill", "train", "intake"],
  );
});
