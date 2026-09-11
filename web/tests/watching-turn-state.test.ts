import assert from "node:assert/strict";
import test from "node:test";

import {
  resetWatchingTurnState,
  setWatchingMaterial,
  setWatchingViewport,
  watchingTurnFields,
} from "../lib/watching-turn-state";

test.beforeEach(resetWatchingTurnState);

test("sends material and viewport only for immersive watching", () => {
  setWatchingMaterial("0123456789abcdef");
  setWatchingViewport(42.5);
  assert.deepEqual(watchingTurnFields("immersive_watching"), {
    timed_media_id: "0123456789abcdef",
    timed_media_viewport: { time_seconds: 42.5 },
  });
  assert.deepEqual(watchingTurnFields("chat"), {});
  assert.deepEqual(watchingTurnFields("immersive_reading"), {});
});

test("closing material clears stale playback position", () => {
  setWatchingMaterial("0123456789abcdef");
  setWatchingViewport(42);
  setWatchingMaterial(null);
  assert.deepEqual(watchingTurnFields("immersive_watching"), {});
});
