import test from "node:test";
import assert from "node:assert/strict";
import {
  SESSION_LOAD_TIMEOUT_MS,
  shouldSurfaceLoadFailure,
} from "../lib/session-load";

// Issue #912: a session fetch that never settled left the overlay spinning
// with no way out but abandoning the conversation, and one that failed
// replaced the URL with /home — dropping the session id, so a transient
// error read as "my history is gone". Both must end in a retryable state.

test("a plain failure on a cold open surfaces", () => {
  assert.equal(
    shouldSurfaceLoadFailure({
      aborted: false,
      timedOut: false,
      cached: false,
    }),
    true,
  );
});

test("a timeout surfaces even though it aborted the request itself", () => {
  assert.equal(
    shouldSurfaceLoadFailure({ aborted: true, timedOut: true, cached: false }),
    true,
  );
});

test("an abort that is not a timeout belongs to whoever cancelled it", () => {
  // The user's ✕ and a newer load both set the state that replaces this one;
  // reporting a failure here would overwrite it.
  assert.equal(
    shouldSurfaceLoadFailure({ aborted: true, timedOut: false, cached: false }),
    false,
  );
});

test("a failed background revalidate keeps the cached transcript on screen", () => {
  for (const outcome of [
    { aborted: false, timedOut: false, cached: true },
    { aborted: true, timedOut: true, cached: true },
  ]) {
    assert.equal(shouldSurfaceLoadFailure(outcome), false);
  }
});

test("the wait is bounded", () => {
  assert.ok(SESSION_LOAD_TIMEOUT_MS > 0 && SESSION_LOAD_TIMEOUT_MS <= 60_000);
});
