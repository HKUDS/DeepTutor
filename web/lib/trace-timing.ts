/**
 * Turn-level timing for the chat status header.
 *
 * Each assistant turn used to surface a duration label on every
 * sub-trace ("Plan for 5s", "Round 3 · 8s", …). That made the
 * trace card noisy and made it hard to tell at a glance how long
 * the whole answer took. The current design hoists timing to the
 * single ``DeepTutor reasoning…`` status row at the top of the
 * answer: one number, ticking up while the turn is in flight and
 * frozen once the turn is done.
 *
 * The clock derives its bounds from the event stream so reconnects
 * keep the duration coherent — we never depend on a transient React
 * state that resets on remount.
 */

import type { StreamEvent } from "@/features/chat/model/protocol";

/**
 * Elapsed seconds for the turn the ``events`` belong to.
 *
 * Returns ``null`` when the stream has not produced any timestamped
 * event yet (e.g. the optimistic assistant placeholder before the
 * first server frame arrives).
 *
 * While ``isStreaming`` is true the upper bound floats to
 * ``nowSeconds`` so the label ticks up in real time; once streaming
 * ends the bound collapses to the latest event timestamp and the
 * duration freezes.
 *
 * ``bounds`` carries the turn's real span when the caller has it. A persisted
 * turn arrives as a *preview* — only its tool and terminal events survive —
 * and the events that mark where the turn began are never among them. Timing
 * the preview alone therefore starts the clock at the first tool call and
 * discards however long the model spent thinking beforehand. A round that
 * thinks and then answers in a single burst has its entire duration in that
 * discarded span, and rendered as ``0s``.
 */
export function getTurnDurationSeconds(
  events: StreamEvent[],
  nowSeconds: number,
  isStreaming: boolean,
  bounds?: { started_at?: number | null; ended_at?: number | null } | null,
): number | null {
  let min = Number.POSITIVE_INFINITY;
  let max = 0;
  for (const event of events) {
    const ts = event.timestamp;
    if (typeof ts !== "number") continue;
    if (ts < min) min = ts;
    if (ts > max) max = ts;
  }
  const startedAt = bounds?.started_at;
  if (typeof startedAt === "number" && startedAt < min) min = startedAt;
  const endedAt = bounds?.ended_at;
  if (typeof endedAt === "number" && endedAt > max) max = endedAt;
  if (!Number.isFinite(min)) return null;
  // Still live: keep ticking against the wall clock. The recorded end is only
  // authoritative once the turn has stopped producing events.
  const end = isStreaming ? Math.max(nowSeconds, max) : max;
  return Math.max(0, end - min);
}

/** Compact human-readable duration: ``"12s"``, ``"1m 4s"``, ``"1h 2m"``. */
export function formatTurnDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const remSeconds = total % 60;
  if (minutes < 60) {
    return remSeconds === 0 ? `${minutes}m` : `${minutes}m ${remSeconds}s`;
  }
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return remMinutes === 0 ? `${hours}h` : `${hours}h ${remMinutes}m`;
}
