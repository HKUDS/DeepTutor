/**
 * Waking from sleep is not the same as never having slept.
 *
 * A desktop shell that sleeps and wakes has to answer two questions: is the
 * window still painting, and is the core still alive? Neither is true by
 * default, and both fail the same way — a blank window with no explanation
 * (#2846).
 *
 * This module holds the decision logic, kept free of Electron imports so it can
 * be tested on any platform. The wiring lives in `main.mjs` and `runtime.mjs`.
 */

/**
 * How long after a wake to stop treating a failed health probe as fatal.
 *
 * Waking re-establishes the network stack asynchronously: the loopback socket the
 * backend listens on can refuse connections for a moment, and the health monitor
 * runs every 10 seconds and fails the core after 3 consecutive misses. Three
 * quick misses right after a wake therefore rebooted a core that was never
 * broken. 30 seconds covers that three-probe window with room to spare.
 */
export const WAKE_GRACE_MS = 30_000;

/**
 * Time source plus grace window, so a probe failure can be classified.
 *
 * `mark()` records a wake. `shouldTolerate()` then answers, for a moment in
 * time, whether a miss is still explained by that wake.
 */
export function createWakeGrace({ now = () => Date.now(), graceMs = WAKE_GRACE_MS } = {}) {
  let wokeAt = Number.NEGATIVE_INFINITY;
  return {
    mark() { wokeAt = now(); },
    /**
     * A miss counts toward the failure breaker unless it lands inside the grace
     * window opened by a wake.
     */
    shouldTolerate() { return now() - wokeAt < graceMs; },
    /** Exposed for tests and diagnostics. */
    get wokeAt() { return wokeAt; },
  };
}

/**
 * Bring the window and its content back after the machine wakes.
 *
 * A `WebContentsView` that was on screen when the display slept can come back
 * unpainted — the same symptom as an occluded window, reached by a different
 * path — and a window that went to sleep minimized comes back minimized, which
 * reads as "the app is gone".
 *
 * Returns what it did, rather than a bare boolean: "there was no window yet" is
 * a real state during startup and is worth distinguishing from "recovered".
 */
export function recoverAfterWake({ window, view, layout, invalidate } = {}) {
  if (!window || window.isDestroyed?.()) return 'no-window';
  if (window.isMinimized?.()) window.restore();
  if (typeof layout === 'function') layout();
  // The window itself is repaired either way; what differs is whether there is
  // still content to repaint. A destroyed view means it needs recreating, so
  // asking it to invalidate would be meaningless.
  if (view?.webContents?.isDestroyed?.()) return 'no-content';
  // Unchanged bounds give the compositor nothing to redo, so ask outright.
  // `invalidate` is not exposed by every Electron version, hence the check.
  if (typeof invalidate === 'function') invalidate();
  return 'recovered';
}

/**
 * Subscribe the shell to the events that mean "the machine just woke".
 *
 * Both are needed: `resume` fires after a real sleep, while `unlock-screen`
 * also covers the case where the session was locked without a full suspend on
 * platforms that report it that way. A handler may be called twice for one
 * wake; the work it does is idempotent.
 */
export const WAKE_EVENTS = ['resume', 'unlock-screen'];

export function onWake(powerMonitor, handler) {
  if (!powerMonitor) return;
  for (const event of WAKE_EVENTS) powerMonitor.on(event, handler);
}
