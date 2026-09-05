import assert from "node:assert/strict";
import test from "node:test";
import { buildStructuredTopicDraftInput, structuredPlanIssues, type MasteryPathFormValues } from "../lib/mastery-path-form";

const base: MasteryPathFormValues = { name: "", goal: "", learningPurpose: null, customPurpose: "", level: null, knownTopics: "", skippedTopics: "", scopeMode: null, scopeInclude: "", scopeExclude: "", approach: null, granularity: null, rigor: null, activities: [], timeMode: null, weeklyHours: "", durationWeeks: "", deadline: "", sessionMinutes: "", milestonePreference: null, milestones: [] };

test("structured validation catches conditional requirements", () => {
  assert.deepEqual(structuredPlanIssues({ ...base, name: "x", goal: "y", scopeMode: "selected" }), ["scope_include"]);
  assert.deepEqual(structuredPlanIssues({ ...base, name: "x", goal: "y", timeMode: "weekly" }), ["weekly_hours"]);
  assert.deepEqual(structuredPlanIssues({ ...base, name: "x", goal: "y", learningPurpose: "custom" }), ["custom_purpose"]);
});

test("payload preserves nullable fields and only sends mode-compatible time values", () => {
  const payload = buildStructuredTopicDraftInput({ ...base, name: " Algebra ", goal: " Solve ", timeMode: null, sessionMinutes: "45", knownTopics: "vectors, matrices" }, []);
  assert.equal(payload.topic.name, "Algebra");
  assert.deepEqual(payload.learner_context, { current_level: null, known_topics: ["vectors", "matrices"], skipped_topics: null });
  assert.equal(payload.time_constraints?.session_duration_minutes, null);
});
