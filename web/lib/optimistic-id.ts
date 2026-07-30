/**
 * Client-minted ids for optimistic (not-yet-persisted) chat rows.
 *
 * Optimistic rows carry a NEGATIVE id until the turn's ``done`` event reports
 * the persisted ones; ``lib/message-branches`` relies on that sign (a more
 * negative id ranks as the newer sibling) and ``lib/turn-reconcile`` keys its
 * optimistic→persisted remap by it.
 *
 * Keying by id is why plain ``-Date.now()`` was not enough: the user row and
 * the assistant placeholder are dispatched back-to-back (``ADD_USER_MSG``
 * then ``STREAM_START``), so they routinely landed in the same millisecond
 * and shared one id. The remap then collapsed both rows onto a single
 * persisted id, which pinned the next turn's ``parent_message_id`` to the
 * previous USER message and dropped the assistant reply out of the visible
 * path until a session reload (issue #698).
 *
 * So: keep the timestamp shape, but never return the same value twice —
 * every call is strictly smaller than the last.
 */

let lastOptimisticId = 0;

export function nextOptimisticId(): number {
  const stamp = -Date.now();
  lastOptimisticId = stamp < lastOptimisticId ? stamp : lastOptimisticId - 1;
  return lastOptimisticId;
}
