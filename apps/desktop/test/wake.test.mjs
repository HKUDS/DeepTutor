import test from 'node:test';
import assert from 'node:assert/strict';
import {
  WAKE_EVENTS,
  WAKE_GRACE_MS,
  createWakeGrace,
  onWake,
  recoverAfterWake,
} from '../src/wake.mjs';

/** A controllable clock, so the grace window is testable without waiting. */
function clock(start = 1_000_000) {
  let value = start;
  return { now: () => value, advance: ms => { value += ms; } };
}

// ── Wake grace: a probe failure right after waking is not a dead core ───────

test('a miss right after waking is tolerated', () => {
  const time = clock();
  const grace = createWakeGrace({ now: time.now });
  grace.mark();
  assert.equal(grace.shouldTolerate(), true);
});

test('the grace expires, so a genuinely dead core is still noticed', () => {
  // The whole point: tolerating forever would hide a real failure.
  const time = clock();
  const grace = createWakeGrace({ now: time.now, graceMs: 30_000 });
  grace.mark();
  time.advance(29_999);
  assert.equal(grace.shouldTolerate(), true);
  time.advance(2);
  assert.equal(grace.shouldTolerate(), false);
});

test('nothing is tolerated before any wake', () => {
  const time = clock();
  const grace = createWakeGrace({ now: time.now });
  assert.equal(grace.shouldTolerate(), false);
});

test('a second wake restarts the window', () => {
  const time = clock();
  const grace = createWakeGrace({ now: time.now, graceMs: 30_000 });
  grace.mark();
  time.advance(25_000);
  grace.mark();
  time.advance(20_000);
  // 45s after the first wake, but only 20s after the second.
  assert.equal(grace.shouldTolerate(), true);
});

test('the default grace outlasts the health monitor failure window', () => {
  // The monitor runs every 10s and fails after 3 misses: 30s of tolerance
  // covers exactly that window, so a wake cannot trip the breaker by itself.
  assert.ok(WAKE_GRACE_MS >= 30_000, `grace ${WAKE_GRACE_MS}ms is shorter than 3 probes`);
});

// ── Recovering the window and its view ────────────────────────────────────

function fakeWindow({ minimized = false, destroyed = false } = {}) {
  const calls = [];
  return {
    calls,
    isDestroyed: () => destroyed,
    isMinimized: () => minimized,
    restore: () => calls.push('restore'),
  };
}

test('a wake lays the content out and repaints it', () => {
  // A view that was on screen when the display slept comes back unpainted.
  const window = fakeWindow();
  const calls = [];
  const result = recoverAfterWake({
    window,
    view: { webContents: { isDestroyed: () => false } },
    layout: () => calls.push('layout'),
    invalidate: () => calls.push('invalidate'),
  });

  assert.equal(result, 'recovered');
  assert.deepEqual(calls, ['layout', 'invalidate']);
});

test('a wake restores a window that slept minimized', () => {
  const window = fakeWindow({ minimized: true });
  recoverAfterWake({ window, view: null, layout: () => {}, invalidate: () => {} });
  assert.deepEqual(window.calls, ['restore']);
});

test('a wake with no window yet does nothing and says so', () => {
  // Real state during startup; worth distinguishing from a failed recovery.
  const calls = [];
  assert.equal(
    recoverAfterWake({ window: null, view: null, layout: () => calls.push('layout') }),
    'no-window',
  );
  assert.deepEqual(calls, [], 'layout must not run without a window');
});

test('a destroyed window is not touched', () => {
  const window = fakeWindow({ destroyed: true });
  const calls = [];
  assert.equal(
    recoverAfterWake({ window, view: null, layout: () => calls.push('layout') }),
    'no-window',
  );
  assert.deepEqual(calls, []);
});

test('a missing invalidate hook still lays out', () => {
  // Not every Electron version exposes invalidate; recovery must not depend on it.
  const window = fakeWindow();
  const calls = [];
  const result = recoverAfterWake({
    window,
    view: { webContents: { isDestroyed: () => false } },
    layout: () => calls.push('layout'),
    invalidate: undefined,
  });
  assert.equal(result, 'recovered');
  assert.deepEqual(calls, ['layout']);
});

test('content that was destroyed is reported after the window is fixed', () => {
  // The window is still repaired (it may be showing an error page), but the
  // caller learns the view needs recreating rather than repainting.
  const window = fakeWindow();
  const calls = [];
  const result = recoverAfterWake({
    window,
    view: { webContents: { isDestroyed: () => true } },
    layout: () => calls.push('layout'),
    invalidate: () => calls.push('invalidate'),
  });
  assert.equal(result, 'no-content');
  assert.deepEqual(calls, ['layout']);
});

// ── Subscribing ───────────────────────────────────────────────────────────

test('both resume and unlock-screen count as a wake', () => {
  const listeners = {};
  const powerMonitor = { on: (event, handler) => { (listeners[event] ??= []).push(handler); } };
  let calls = 0;
  onWake(powerMonitor, () => { calls += 1; });

  assert.deepEqual([...WAKE_EVENTS].sort(), ['resume', 'unlock-screen']);
  for (const event of WAKE_EVENTS) for (const handler of listeners[event] ?? []) handler();
  assert.equal(calls, WAKE_EVENTS.length);
});

test('a missing power monitor is not an error', () => {
  // Headless or partially mocked environments must not crash the shell.
  assert.doesNotThrow(() => onWake(undefined, () => {}));
});
