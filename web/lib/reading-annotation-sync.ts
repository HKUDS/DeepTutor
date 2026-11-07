"use client";

import { browserStorage } from "@/shared/storage";

/**
 * Tell the other tabs that a document's marks changed.
 *
 * The reader keeps its annotations in memory, loaded when a material is
 * opened. Two tabs on the same document therefore each hold their own copy:
 * a mark saved in one is invisible in the other until it reloads, and worse,
 * a note edited in the second tab is written from the first tab's stale copy
 * of the others. A storage event is the cheapest way to close that gap —
 * the shared storage layer already broadcasts across tabs, and the app already listens
 * for it elsewhere.
 *
 * The payload is a counter, not the marks themselves: the receiving tab
 * re-reads through the normal API, so it gets whatever the server actually
 * holds rather than a copy that could have been overtaken by a third tab.
 */

const ANNOTATIONS_REVISION_KEY = "dt.reader.annotationsRevision";

/**
 * Monotonic counter, so two writes never carry the same payload.
 *
 * A storage write only fires a `storage` event when the value actually
 * changes. Two saves inside one millisecond would serialise to identical JSON,
 * the second write would be silent, and the other tab would miss that change.
 */
let revisionSeq = 0;

/**
 * Per-tab identity, so two tabs can never write the same payload.
 *
 * `seq` alone is a per-tab counter: two tabs both start at 1, and if they write
 * in the same millisecond the serialised payloads are byte-identical —
 * `setItem` sees an unchanged value, no `storage` event fires, and the second
 * tab's change is lost without a trace.
 */
const TAB_ID =
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);

/** Announce that this tab changed the marks on `materialId`. */
export function publishAnnotationsChange(materialId: string): void {
  if (typeof window === "undefined") return;
  revisionSeq += 1;
  try {
    browserStorage.writeRaw(
      "local",
      ANNOTATIONS_REVISION_KEY,
      JSON.stringify({ materialId, at: Date.now(), seq: revisionSeq, tab: TAB_ID }),
    );
  } catch {
    // Storage can be denied (private mode, a restricted iframe). Cross-tab
    // sync is a convenience; losing it must not break saving.
  }
}

/**
 * Run `listener` when *another* tab reports a change to `materialId`.
 *
 * Returns an unsubscribe function. Storage events do not fire in the tab that
 * wrote them, so this never reacts to the local tab's own writes.
 */
export function subscribeToAnnotationsChange(
  materialId: string | null,
  listener: () => void,
): () => void {
  if (typeof window === "undefined" || !materialId) return () => undefined;
  const onStorage = (event: StorageEvent) => {
    if (event.key !== ANNOTATIONS_REVISION_KEY || !event.newValue) return;
    // The shared subscriber checks this too; without it a write to
    // sessionStorage under the same key would look like a change here.
    if (event.storageArea && event.storageArea !== window.localStorage) return;
    try {
      const payload = JSON.parse(event.newValue) as { materialId?: string };
      if (payload.materialId === materialId) listener();
    } catch {
      // A malformed payload is not worth a notice; the next real write fixes it.
    }
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}
