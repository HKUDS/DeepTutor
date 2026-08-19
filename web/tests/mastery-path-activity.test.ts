import test from "node:test";
import assert from "node:assert/strict";

import {
  EMPTY_FEED,
  latestRevision,
  mergeEventBatch,
  type ActivityFeed,
} from "../hooks/useMasteryPathActivity";
import type { MasteryEvent } from "../lib/learning-api";

function event(revision: number, eventType = "attempt.recorded"): MasteryEvent {
  return {
    id: revision,
    revision,
    event_type: eventType,
    payload: {},
    session_id: "",
    turn_id: "",
    created_at: revision,
  };
}

function feed(pathId: string, revisions: number[]): ActivityFeed {
  return {
    pathId,
    events: revisions.map((r) => event(r)),
    revision: Math.max(0, ...revisions),
  };
}

test("an incremental batch appends and advances the cursor", () => {
  const merged = mergeEventBatch(feed("p1", [1, 2]), "p1", 2, [
    event(3),
    event(4),
  ]);
  assert.deepEqual(
    merged.events.map((e) => e.revision),
    [1, 2, 3, 4],
  );
  assert.equal(merged.revision, 4);
});

test("a read from revision 0 replaces, so a forced refresh cannot double the feed", () => {
  const merged = mergeEventBatch(feed("p1", [1, 2, 3]), "p1", 0, [
    event(1),
    event(2),
    event(3),
  ]);
  assert.deepEqual(
    merged.events.map((e) => e.revision),
    [1, 2, 3],
  );
});

test("an empty batch leaves the feed untouched", () => {
  const before = feed("p1", [1, 2]);
  assert.equal(mergeEventBatch(before, "p1", 2, []), before);
  assert.equal(mergeEventBatch(EMPTY_FEED, "p1", 0, []), EMPTY_FEED);
});

test("a batch for another path never mixes into the previous path's history", () => {
  const merged = mergeEventBatch(feed("p1", [1, 2, 3]), "p2", 0, [event(1)]);
  assert.equal(merged.pathId, "p2");
  assert.deepEqual(
    merged.events.map((e) => e.revision),
    [1],
  );
});

test("the cursor never moves backwards past what was already requested", () => {
  assert.equal(latestRevision(7, []), 7);
  assert.equal(latestRevision(7, [event(9), event(8)]), 9);
});
