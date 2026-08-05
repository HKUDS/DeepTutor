import {
  consumeFeynmanHandoff,
  type FeynmanHandoff,
  type StorageLike,
} from "./feynman-learning-handoff";

/* ────────────────────────────────────────────────────────────────────────
 * Route-safe Feynman handoff consumption (UI-01).
 *
 * The Feynman workspace stashes a draft into a sessionStorage slot and
 * navigates to /home/{pathId}; the chat page consumes that slot exactly once
 * once its composer prefill bridge is published. The bridge is set on the
 * composer's mount effect, so a fresh /home page may not have it yet — the
 * original implementation retried with untracked `setTimeout` callbacks. If
 * /home/A started waiting and the user navigated to /home/B, A's late callback
 * could observe B's composer bridge, consume A's slot, select Mastery Path and
 * prefill A's draft into B.
 *
 * This module owns that retry lifecycle so it is testable in Node:
 *   - every scheduled retry is tracked and cancelled by the effect cleanup;
 *   - `start`/`cancel` bump a generation counter, so a superseded session
 *     becomes inert even if a timer somehow fires after navigation;
 *   - the callbacks may provide `isActive`, a route-session guard consulted
 *     before the slot is consumed and again before the draft is published.
 *     ChatPage creates ONE consumer per handoff effect — so every start binds
 *     the current handleSelectCapability/composer callbacks — and keeps a
 *     shared active-session marker in a layout-phase lifecycle tied to the
 *     route param. A retry left over from /home/A fails isActive(A) the moment
 *     /home/B commits: the window between B's commit and A's passive-effect
 *     cleanup is closed by that shared marker, not by the generation counter
 *     (which lives per consumer).
 *   - the rapid A -> B regression is proven in web/tests/feynman-handoff-consume.test.ts.
 * ──────────────────────────────────────────────────────────────────────── */

export interface FeynmanHandoffConsumeCallbacks {
  /** Whether the composer prefill bridge is available right now. */
  composerReady: () => boolean;
  /** Publish a consumed handoff into the real composer (select mastery_path first). */
  onHandoff: (handoff: FeynmanHandoff) => void;
  /**
   * Route-session guard. Consulted before the storage slot is consumed and
   * again before the handoff is published; returning `false` for the attempt's
   * path makes the attempt inert (no consumption, no publication, no further
   * retry). Reads a shared active-session marker that the host updates in a
   * layout-phase lifecycle tied to the route param, so a retry left over from a
   * previous route (A) becomes inert the moment the next route (B) commits —
   * before A's passive-effect cleanup can even cancel it — closing the window
   * that a per-effect consumer generation counter cannot see.
   */
  isActive?: (pathId: string) => boolean;
}

export interface FeynmanHandoffConsumeConfig {
  /** Retry cap while waiting for the composer bridge. */
  maxAttempts?: number;
  /** Delay between retry attempts. */
  retryDelayMs?: number;
  /** Clock source so TTL checks are deterministic in tests. */
  now?: () => number;
  /** Scheduler so tests can drive time manually (defaults to setTimeout). */
  schedule?: (fn: () => void, delay: number) => unknown;
  /** Cancels a scheduled retry (defaults to clearTimeout). */
  cancelSchedule?: (handle: unknown) => void;
}

/** Observability handle for one `start()` — lets a test assert a superseded
 *  session never consumed or published. */
export interface FeynmanHandoffConsumeSession {
  readonly pathId: string;
  readonly sessionToken: string;
  readonly consumed: boolean;
  readonly cancelled: boolean;
}

export interface FeynmanHandoffConsumer {
  /**
   * Begin consuming the handoff for `pathId`. Starting a new session
   * supersedes any previous in-flight session: its pending retry is cancelled
   * and its callbacks become inert.
   */
  start(pathId: string, sessionToken?: string): FeynmanHandoffConsumeSession;
  /** Cancel any pending retry and invalidate the current session. */
  cancel(): void;
}

/** Mutable internal view of a session handle (the public shape is readonly). */
interface MutableSession {
  pathId: string;
  sessionToken: string;
  consumed: boolean;
  cancelled: boolean;
}

/**
 * Create a route-safe handoff consumer bound to one storage instance.
 *
 * The consumer is deliberately small: it only knows how to wait for the
 * composer bridge and publish a valid handoff exactly once. Session routing
 * (which path is active) stays in the effect; the generation counter here is
 * what makes a superseded session unable to observe a later composer.
 */
export function createFeynmanHandoffConsumer(
  storage: StorageLike,
  callbacks: FeynmanHandoffConsumeCallbacks,
  config: FeynmanHandoffConsumeConfig = {},
): FeynmanHandoffConsumer {
  const maxAttempts = config.maxAttempts ?? 50;
  const retryDelayMs = config.retryDelayMs ?? 50;
  const now = config.now ?? (() => Date.now());
  const schedule =
    config.schedule ?? ((fn: () => void, delay: number) => setTimeout(fn, delay));
  const cancelSchedule =
    config.cancelSchedule ??
    ((handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>));

  // Generation counter: every `start` bumps it, so any retry scheduled by a
  // previous session sees its generation mismatch on the next tick and stops.
  let generation = 0;
  let pendingHandle: unknown = null;
  let currentSession: MutableSession | null = null;

  const clearPending = () => {
    if (pendingHandle !== null) {
      cancelSchedule(pendingHandle);
      pendingHandle = null;
    }
  };

  const start = (pathId: string, sessionToken?: string): FeynmanHandoffConsumeSession => {
    const token = sessionToken ?? pathId;
    const myGeneration = ++generation;
    clearPending();
    const session: MutableSession = {
      pathId,
      sessionToken: token,
      consumed: false,
      cancelled: false,
    };
    currentSession = session;
    let attempts = 0;

    const attempt = () => {
      // Three guards keep a superseded session inert:
      //  1. a newer `start` (or `cancel`) bumped the generation;
      //  2. this session was explicitly cancelled;
      //  3. the host's shared active-session marker moved on (a route change
      //     has rendered the next session). The generation counter cannot see
      //     that window on its own — `start(B)` has not run yet — so the
      //     attempt re-checks ownership before doing anything at all.
      if (myGeneration !== generation) return;
      if (session.cancelled) return;
      if (callbacks.isActive && !callbacks.isActive(session.pathId)) return;

      if (callbacks.composerReady()) {
        // Re-verify immediately before touching storage: the composer bridge
        // may have only just been published by the *next* session's commit,
        // which is exactly the cross-instance window this guard exists for.
        if (callbacks.isActive && !callbacks.isActive(session.pathId)) return;
        const handoff = consumeFeynmanHandoff(storage, pathId, now());
        if (!handoff) return; // no valid handoff — slot was removed by consume
        // Re-verify immediately before publication. Synchronous in practice,
        // but keeps the "belongs to the active session" check at the exact
        // publication boundary as well.
        if (callbacks.isActive && !callbacks.isActive(handoff.pathId)) return;
        session.consumed = true;
        clearPending();
        callbacks.onHandoff(handoff);
        return;
      }

      if (attempts < maxAttempts) {
        attempts += 1;
        pendingHandle = schedule(attempt, retryDelayMs);
      }
    };

    attempt();
    return session;
  };

  const cancel = () => {
    generation += 1; // invalidate the current session immediately
    clearPending();
    if (currentSession) {
      currentSession.cancelled = true;
      currentSession = null;
    }
  };

  return { start, cancel };
}
