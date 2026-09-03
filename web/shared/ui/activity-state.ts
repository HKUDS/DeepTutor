/**
 * Where a single piece of work stands.
 *
 * Lives in `shared/` rather than beside the activity components because the
 * pure logic that *computes* these states (`lib/book-activity.ts`, and
 * whatever follows it) must not import from `components/` — so the four
 * states are the contract between the two layers, and there is exactly one
 * copy of it.
 */
export type ActivityState =
  /** In flight right now. */
  | "running"
  /** Blocked on the reader (an `ask_user` card, a confirmation). */
  | "awaiting"
  /** Finished badly. */
  | "error"
  /** Finished, or never started. */
  | "done";
