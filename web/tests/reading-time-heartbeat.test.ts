import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

import {
  isReadingActive,
  ReadingTimeAccumulator,
  READING_TIME_BEAT_INTERVAL_MS,
  READING_TIME_IDLE_GRACE_MS,
} from "@/lib/reading-time";
import {
  saveReadingTime,
  sendReadingTimeBeacon,
} from "@/lib/reading-api";

function source(file: string): string {
  return readFileSync(path.resolve(process.cwd(), file), "utf8");
}

test("the heartbeat cadence and idle grace match the #1988 contract", () => {
  assert.equal(READING_TIME_BEAT_INTERVAL_MS, 30_000);
  // The credited grace past the last interaction is one heartbeat, so idle
  // time can never inflate a day beyond that tolerance.
  assert.equal(READING_TIME_IDLE_GRACE_MS, READING_TIME_BEAT_INTERVAL_MS);
});

test("activity requires visibility, focus and recent input — or playback", () => {
  const base = { visible: true, focused: true, playing: false, lastInputAt: 100_000 };
  assert.equal(isReadingActive(base, 130_000), true);
  // Beyond the idle grace the clock stops, even though the tab is visible.
  assert.equal(isReadingActive(base, 130_001), false);
  // Read-aloud / playback keeps it running without input.
  assert.equal(isReadingActive({ ...base, playing: true, lastInputAt: null }, 999_999), true);
  // A hidden tab or an unfocused window never counts.
  assert.equal(isReadingActive({ ...base, visible: false }, 130_000), false);
  assert.equal(isReadingActive({ ...base, focused: false }, 130_000), false);
});

test("two active minutes, then idle and hidden, credit about two minutes", () => {
  let state = { visible: true, focused: true, playing: false, lastInputAt: 0 };
  const accumulator = new ReadingTimeAccumulator(() => state);

  // 120 ticks of active reading (learner keeps interacting).
  for (let seconds = 0; seconds < 120; seconds += 1) {
    state = { ...state, lastInputAt: seconds * 1000 };
    accumulator.tick(seconds * 1000);
  }
  // 90 s idle: the clock runs at most one heartbeat past the last input.
  for (let seconds = 120; seconds < 210; seconds += 1) {
    accumulator.tick(seconds * 1000);
  }
  // 30 s hidden tab.
  state = { ...state, visible: false };
  for (let seconds = 210; seconds < 240; seconds += 1) {
    accumulator.tick(seconds * 1000);
  }
  // About two minutes: 120 active seconds plus at most the 30 s grace.
  const claimed = accumulator.takeBeat();
  assert.ok(claimed >= 120 && claimed <= 150, `claimed ${claimed}`);
  assert.equal(accumulator.pending, 0);
});

test("a beat claims exactly what accumulated since the previous beat", () => {
  const state = { visible: true, focused: true, playing: false, lastInputAt: 0 };
  const accumulator = new ReadingTimeAccumulator(() => state);
  for (let seconds = 0; seconds < 30; seconds += 1) {
    state.lastInputAt = seconds * 1000;
    accumulator.tick(seconds * 1000);
  }
  assert.equal(accumulator.takeBeat(), 30);
  for (let seconds = 30; seconds < 45; seconds += 1) {
    state.lastInputAt = seconds * 1000;
    accumulator.tick(seconds * 1000);
  }
  assert.equal(accumulator.takeBeat(), 15);
  assert.equal(accumulator.takeBeat(), 0);
});

// ---- source contract: the Reader actually wires the heartbeat ------------

test("ReaderPane and MediaReadingStage mount the reading-time heartbeat", () => {
  const pane = source("components/reading/ReaderPane.tsx");
  const media = source("components/reading/workspace/MediaReadingStage.tsx");
  const heartbeat = source("components/reading/ReadingTimeHeartbeat.tsx");
  const hook = source("components/reading/use-reading-time.ts");
  for (const [name, file] of [
    ["ReaderPane", pane],
    ["MediaReadingStage", media],
  ] as const) {
    assert.match(file, /<ReadingTimeHeartbeat/, `${name} mounts the heartbeat`);
    assert.match(file, /dynamic\(/, `${name} keeps the heartbeat out of the route's first load`);
  }
  assert.match(heartbeat, /useReadingTimeHeartbeat\(props\)/);
  // Document reading counts read-aloud; media counts playback ticks.
  assert.match(pane, /playing=\{\(\) => Boolean\(readingActions\?\.speaking\)\}/);
  assert.match(media, /playing=\{\(\) => Date\.now\(\) - lastMediaTimeAtRef\.current < 2500\}/);
  // The final beat survives page unload via sendBeacon, timers are cleared.
  assert.match(hook, /sendReadingTimeBeacon/);
  assert.match(hook, /pagehide/);
  assert.match(hook, /window\.clearInterval\(tickTimer\)/);
  assert.match(hook, /window\.clearInterval\(beatTimer\)/);
  // The API surface the hook posts to exists and carries the timezone.
  const api = source("lib/reading-api.ts");
  assert.match(api, /\/reading-time/);
  assert.match(api, /active_seconds/);
  assert.equal(typeof saveReadingTime, "function");
  assert.equal(typeof sendReadingTimeBeacon, "function");
});
