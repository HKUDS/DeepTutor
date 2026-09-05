import assert from "node:assert/strict";
import test from "node:test";

import { learningPlanDraftRoute, learningPlanNewRoute, learningPlanRoute, shouldGenerateLearningPlanDraft } from "../lib/mastery-planning-route";

test("a successful new discussion forces draft regeneration despite stale ready state", () => {
  assert.equal(learningPlanDraftRoute("plan/a b", { regenerate: true }), "/mastery/planning/plan%2Fa%20b/draft?regenerate=1");
  assert.equal(shouldGenerateLearningPlanDraft("draft_ready", true), true);
});

test("the route-draft page reuses a ready draft when no new discussion occurred", () => {
  assert.equal(learningPlanDraftRoute("plan/a b"), "/mastery/planning/plan%2Fa%20b/draft");
  assert.equal(shouldGenerateLearningPlanDraft("draft_ready", false), false);
  assert.equal(shouldGenerateLearningPlanDraft("discussing", false), true);
  assert.equal(shouldGenerateLearningPlanDraft("settled", false), true);
});

test("planning navigation retains course scope through draft, back, and regeneration", () => {
  assert.equal(learningPlanNewRoute("course/a b"), "/mastery/new?course=course%2Fa+b");
  assert.equal(learningPlanRoute("plan/a b", { courseId: "course/a b" }), "/mastery/planning/plan%2Fa%20b?course=course%2Fa+b");
  assert.equal(learningPlanDraftRoute("plan/a b", { courseId: "course/a b" }), "/mastery/planning/plan%2Fa%20b/draft?course=course%2Fa+b");
  assert.equal(learningPlanDraftRoute("plan/a b", { courseId: "course/a b", regenerate: true }), "/mastery/planning/plan%2Fa%20b/draft?course=course%2Fa+b&regenerate=1");
});
