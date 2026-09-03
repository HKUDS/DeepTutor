import assert from "node:assert/strict";
import test from "node:test";

import { isMasteryDraftSessionReady } from "../lib/mastery-study-route";

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
