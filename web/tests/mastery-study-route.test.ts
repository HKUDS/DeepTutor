import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import {
  isMasteryDraftSessionReady,
  isReviewAvailable,
  isRoutedStudySessionReady,
  modeSwitchTarget,
} from "../lib/mastery-study-route";

const base = {
  guard: {
    routeKey: "topic-a:new",
    previousSessionId: "session-old",
  },
  routeKey: "topic-a:new",
  masteryPathId: "topic-a",
  pathId: "topic-a",
};

test("a stale previous session cannot bounce a new-study route backwards", () => {
  assert.equal(
    isMasteryDraftSessionReady({ ...base, sessionId: "session-old" }),
    false,
  );
});

test("the backend-bound draft session is promoted into the route", () => {
  assert.equal(
    isMasteryDraftSessionReady({ ...base, sessionId: "session-new" }),
    true,
  );
});

test("a route or topic switch invalidates an older draft guard", () => {
  assert.equal(
    isMasteryDraftSessionReady({
      ...base,
      routeKey: "topic-b:new",
      sessionId: "session-new",
    }),
    false,
  );
  assert.equal(
    isMasteryDraftSessionReady({
      ...base,
      masteryPathId: "topic-b",
      sessionId: "session-new",
    }),
    false,
  );
});

test("an unbound draft stays on the sessionless study route", () => {
  assert.equal(isMasteryDraftSessionReady({ ...base, sessionId: null }), false);
});

test("a previous knowledge point's conversation is not ready on the new route", () => {
  assert.equal(
    isRoutedStudySessionReady({
      routeSessionId: "session-kp0",
      adapterSessionId: "session-memory",
      sessionLoading: true,
    }),
    false,
  );
  assert.equal(
    isRoutedStudySessionReady({
      routeSessionId: "session-kp0",
      adapterSessionId: "session-memory",
      sessionLoading: false,
    }),
    false,
  );
});

test("the routed knowledge point's conversation is ready once the adapter matches", () => {
  assert.equal(
    isRoutedStudySessionReady({
      routeSessionId: "session-kp0",
      adapterSessionId: "session-kp0",
      sessionLoading: false,
    }),
    true,
  );
});

const placed = [
  { id: "kp0", status: "mastered" },
  { id: "kp1", status: "learning" },
  { id: "kp2", status: "new" },
];

const placedModules = [{ knowledge_points: placed }];

test("switching to study keeps the mastered point being read", () => {
  // Reading kp0's review and pressing "学习" must open kp0's study history,
  // not the frontier. Filtering study by "not mastered" moved the learner to
  // kp1 and showed that conversation's transcript instead.
  assert.equal(modeSwitchTarget(placed, "kp0", "kp1"), "kp0");
});

test("switching to review keeps an unmastered point", () => {
  // Every point has its own study and review transcript, so pressing "复习"
  // on kp1 must open kp1's review, not some mastered point's. Re-picking by
  // mastery status moved the learner to kp0 and showed kp0's review instead.
  assert.equal(modeSwitchTarget(placed, "kp1", "kp1"), "kp1");
});

test("review keeps the bound point when it is already mastered", () => {
  assert.equal(modeSwitchTarget(placed, "kp0", "kp1"), "kp0");
});

test("study falls back to the frontier when no point is bound", () => {
  assert.equal(modeSwitchTarget(placed, "", "kp1"), "kp1");
});

test("a point that left the outline keeps the conversation bound to it", () => {
  // The transcript is still open; jumping to a different point because the
  // outline no longer lists this one would swap the conversation under the
  // learner without them asking for it.
  assert.equal(modeSwitchTarget(placed, "removed", "kp1"), "removed");
});

test("review is offered once the point on screen is mastered", () => {
  assert.equal(
    isReviewAvailable({ modules: placedModules, pointId: "kp0", sessionMode: "study" }),
    true,
  );
});

test("review is not offered while the point on screen is still being learned", () => {
  // The tutor refuses to examine an unmastered objective, so a review button
  // here would open a conversation the engine will not conduct.
  assert.equal(
    isReviewAvailable({ modules: placedModules, pointId: "kp1", sessionMode: "study" }),
    false,
  );
});

test("a live review conversation keeps the control regardless of status", () => {
  // Older review sessions were created before this rule existed; the learner
  // must still be able to see which mode they are in and leave it.
  assert.equal(
    isReviewAvailable({ modules: placedModules, pointId: "kp1", sessionMode: "review" }),
    true,
  );
});

test("an unplaced conversation offers no review", () => {
  assert.equal(
    isReviewAvailable({ modules: placedModules, pointId: "", sessionMode: "study" }),
    false,
  );
});

test("a point missing from the outline offers no review", () => {
  assert.equal(
    isReviewAvailable({ modules: placedModules, pointId: "gone", sessionMode: "study" }),
    false,
  );
});

test("legacy /mastery/.../study URLs permanently redirect to /sessions", async () => {
  const nextConfig = require(path.resolve(process.cwd(), "next.config.js")) as {
    redirects?: () => Promise<
      Array<{ source: string; destination: string; statusCode: number }>
    >;
  };
  assert.equal(typeof nextConfig.redirects, "function");
  const redirects = await nextConfig.redirects!();
  assert.deepEqual(
    redirects.filter((entry) => entry.source.includes("/study")),
    [
      {
        source: "/mastery/:pathId/study",
        destination: "/learning/mastery/:pathId/sessions",
        statusCode: 301,
      },
      {
        source: "/mastery/:pathId/study/:sessionId",
        destination: "/learning/mastery/:pathId/sessions/:sessionId",
        statusCode: 301,
      },
    ],
  );
});
