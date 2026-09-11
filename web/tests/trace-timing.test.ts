import assert from "node:assert/strict";
import test from "node:test";

import type { StreamEvent } from "../features/chat/model/protocol";
import {
  formatTurnDuration,
  getTurnDurationSeconds,
} from "../lib/trace-timing";

const event = (type: string, timestamp: number): StreamEvent =>
  ({ type, timestamp }) as unknown as StreamEvent;

test("a live turn ticks against the wall clock", () => {
  const events = [event("stage_start", 100), event("tool_call", 104)];

  assert.equal(getTurnDurationSeconds(events, 112, true), 12);
});

test("a settled turn freezes on its last event", () => {
  const events = [event("stage_start", 100), event("done", 117)];

  assert.equal(getTurnDurationSeconds(events, 999, false), 17);
});

test("a previewed turn is timed by its recorded span, not by what survived", () => {
  // What a persisted mastery turn actually looks like: it thought for 5.7s,
  // then emitted its answer and its mastery_quiz call in one burst. The
  // preview keeps only the tool and terminal events — all inside that burst —
  // so timing them alone reports 0s for a turn the learner waited 6s for.
  const preview = [
    event("tool_call", 419.872),
    event("tool_result", 419.883),
    event("result", 419.895),
    event("done", 419.896),
  ];

  assert.equal(Math.round(getTurnDurationSeconds(preview, 0, false) ?? -1), 0);
  assert.equal(
    Math.round(
      getTurnDurationSeconds(preview, 0, false, {
        started_at: 414.146,
        ended_at: 419.896,
      }) ?? -1,
    ),
    6,
  );
});

test("recorded bounds only ever widen the span", () => {
  // A stale or narrower snapshot must not shrink a turn that the live events
  // already prove ran longer.
  const events = [event("stage_start", 100), event("done", 130)];

  assert.equal(
    getTurnDurationSeconds(events, 0, false, {
      started_at: 110,
      ended_at: 120,
    }),
    30,
  );
});

test("no timestamps anywhere still reports nothing rather than zero", () => {
  assert.equal(getTurnDurationSeconds([], 0, false), null);
  assert.equal(getTurnDurationSeconds([], 0, false, {}), null);
  assert.equal(
    getTurnDurationSeconds([], 0, false, { started_at: null, ended_at: null }),
    null,
  );
});

test("a span present only in the bounds is still a duration", () => {
  // The preview can be empty (a turn whose every event was compacted away)
  // while the server still knows how long it took.
  assert.equal(
    getTurnDurationSeconds([], 0, false, { started_at: 10, ended_at: 25 }),
    15,
  );
});

test("durations read as compact human time", () => {
  assert.equal(formatTurnDuration(0), "0s");
  assert.equal(formatTurnDuration(5.75), "6s");
  assert.equal(formatTurnDuration(64), "1m 4s");
  assert.equal(formatTurnDuration(3600), "1h");
});
