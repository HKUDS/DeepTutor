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

test("opening a trace does not move the number it was showing", () => {
  // A collapsed turn is timed from its preview plus the span recorded over
  // the whole stream; opening it swaps in every event the server holds. The
  // label has to survive that, so the recorded span must travel with the
  // fetched events — dropping it left the duration to be re-derived, and an
  // 11s turn read 12s the moment it was opened.
  const bounds = { started_at: 100, ended_at: 111.4 };
  const preview = [event("tool_call", 104), event("done", 111)];
  const full = [
    event("stage_start", 100.2),
    event("thinking", 101),
    event("tool_call", 104),
    event("thinking", 108),
    event("done", 111),
  ];

  const collapsed = getTurnDurationSeconds(preview, 0, false, bounds);
  const opened = getTurnDurationSeconds(full, 0, false, bounds);
  assert.equal(collapsed, opened);
  assert.equal(formatTurnDuration(collapsed ?? 0), "11s");
  assert.equal(formatTurnDuration(opened ?? 0), "11s");
});

test("losing the recorded span is what made the number move", () => {
  // Guards the reason rather than the symptom: with no bounds to anchor it,
  // the same two event sets disagree. This is the state the fetch used to
  // leave the message in.
  const preview = [event("tool_call", 104), event("done", 111)];
  const full = [event("stage_start", 100.2), event("done", 111)];
  assert.notEqual(
    getTurnDurationSeconds(preview, 0, false, null),
    getTurnDurationSeconds(full, 0, false, null),
  );
});
