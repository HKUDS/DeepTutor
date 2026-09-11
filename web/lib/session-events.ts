// Lightweight client-side event bus for conversation-list mutations.
//
// The sidebar's session list is fetched once when the shell mounts, but a
// conversation can be archived, restored or deleted from a route that has
// nothing to do with the sidebar — Settings › Archive being the case that
// forced this: a restore that leaves the sidebar unchanged reads as a restore
// that did not happen. Same shape as `co-writer-events` and for the same
// reason: the sidebar lives at the shell level, the mutations do not.

const EVENT_NAME = "sessions:changed";

type Listener = () => void;

function getTarget(): EventTarget | null {
  if (typeof window === "undefined") return null;
  return window;
}

/** Tell every mounted session list to refetch. */
export function notifySessionsChanged(): void {
  getTarget()?.dispatchEvent(new Event(EVENT_NAME));
}

export function subscribeSessionChanges(listener: Listener): () => void {
  const target = getTarget();
  if (!target) return () => {};
  target.addEventListener(EVENT_NAME, listener);
  return () => target.removeEventListener(EVENT_NAME, listener);
}
