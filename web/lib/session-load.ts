/**
 * When a session fetch ends without a session, what the user should see.
 *
 * Three different things abort a load and only one of them is a failure, so
 * the decision is worth stating on its own: a newer load and the user's ✕ both
 * own the state that replaces this one, while a timeout owns nothing and has
 * to surface, or the overlay spins forever with no way out.
 */

/** How long to wait for a session fetch before calling it failed. */
export const SESSION_LOAD_TIMEOUT_MS = 30_000;

export interface LoadOutcome {
  /** The load's AbortSignal fired. */
  aborted: boolean;
  /** …and it fired because the wait ran out, not because a caller cancelled. */
  timedOut: boolean;
  /** A copy of this session was already painted from memory. */
  cached: boolean;
}

/**
 * True when the failure must be shown as a terminal, retryable state.
 *
 * A background revalidate keeps the cached transcript on screen — replacing a
 * readable conversation with an error because a refresh failed would be a
 * regression, not a fix.
 */
export function shouldSurfaceLoadFailure({
  aborted,
  timedOut,
  cached,
}: LoadOutcome): boolean {
  if (cached) return false;
  if (aborted && !timedOut) return false;
  return true;
}
