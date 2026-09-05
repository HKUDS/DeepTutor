import assert from "node:assert/strict";
import test from "node:test";

import { createLearningPlan, fetchLearningPlan, generateLearningPlanRouteDraft, generateMasteryTopicDraftCompatible, isLearningPlanConflict, saveLearningPlanRouteDraft, sendLearningPlanMessage, settleLearningPlan } from "../lib/learning-api";

test("structured mastery draft client posts the complete nullable plan payload", async () => {
  const original = globalThis.fetch;
  let request: { url: string; method?: string; body?: string } | undefined;
  globalThis.fetch = async (input, init) => {
    request = { url: String(input), method: init?.method, body: init?.body as string | undefined };
    return Response.json({ description: "d", modules: [] });
  };
  try {
    await generateMasteryTopicDraftCompatible({
      name: "Algebra",
      goal: "Solve equations",
      sources: [],
      topic: { name: "Algebra", purpose: "Solve equations" },
      learner_context: { current_level: null, known_topics: null, skipped_topics: null },
      learning_preferences: null,
      time_constraints: null,
      milestones: null,
    });
    assert.ok(request?.url.endsWith("/api/mastery-paths/topics/draft"));
    assert.equal(request?.method, "POST");
    const body = JSON.parse(request!.body ?? "{}") as Record<string, unknown>;
    assert.deepEqual(body.time_constraints, null);
    assert.deepEqual(body.milestones, null);
    assert.deepEqual(body.topic, { name: "Algebra", purpose: "Solve equations" });
  } finally {
    globalThis.fetch = original;
  }
});

test("learning plan client uses the planning API paths and payloads", async () => {
  const original = globalThis.fetch;
  const requests: Array<{ url: string; method?: string; body?: string }> = [];
  globalThis.fetch = async (input, init) => { requests.push({ url: String(input), method: init?.method, body: init?.body as string | undefined }); return Response.json({ plan_id: "p", state: "discussing", input: {}, brief: {}, messages: [] }); };
  try {
    const input = { name: "A", goal: "B", sources: [], topic: { name: "A", purpose: "B" } };
    await createLearningPlan(input); await fetchLearningPlan("p/x"); await sendLearningPlanMessage("p/x", "hello"); await settleLearningPlan("p/x", input); await generateLearningPlanRouteDraft("p/x"); await generateLearningPlanRouteDraft("p/x", { force: true }); await saveLearningPlanRouteDraft("p/x", { description: "edited", modules: [] });
    assert.deepEqual(requests.map((r) => [r.method || "GET", r.url]), [
      ["POST", "/api/mastery-paths/learning-plans"], ["GET", "/api/mastery-paths/learning-plans/p%2Fx"], ["POST", "/api/mastery-paths/learning-plans/p%2Fx/planning-session/messages"], ["POST", "/api/mastery-paths/learning-plans/p%2Fx/settle"], ["POST", "/api/mastery-paths/learning-plans/p%2Fx/route-draft"], ["POST", "/api/mastery-paths/learning-plans/p%2Fx/route-draft?force=true"], ["PUT", "/api/mastery-paths/learning-plans/p%2Fx/route-draft"],
    ]);
    assert.equal(JSON.parse(requests[2].body || "{}").content, "hello");
    assert.equal(JSON.parse(requests[6].body || "{}").description, "edited");
  } finally { globalThis.fetch = original; }
});

test("learning plan client maps 409 conflicts to a stable code without hiding other failures", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Learning plan is busy; retry after the current operation" }), { status: 409, headers: { "Content-Type": "application/json" } });
  try {
    await assert.rejects(sendLearningPlanMessage("p", "hello"), (error: unknown) => isLearningPlanConflict(error));
  } finally {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "not found" }), { status: 404, headers: { "Content-Type": "application/json" } });
  }
  try {
    await assert.rejects(fetchLearningPlan("p"), /Failed to load learning plan \(404\): not found/);
  } finally {
    globalThis.fetch = original;
  }
});
