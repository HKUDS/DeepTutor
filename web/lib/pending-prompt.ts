/**
 * Hand a starting message from one surface to another's composer.
 *
 * Two callers today. The Settings hub's "let DeepTutor configure this" button
 * navigates to chat with the request already typed, so the user reads and sends
 * it rather than arriving at an empty box wondering what to say. Course Study's
 * hand-off cards do the same across the learning surfaces: the assistant
 * decides what is worth doing next, and the destination opens with that opening
 * line ready.
 *
 * sessionStorage rather than a query parameter on purpose — the chat route is
 * a catch-all segment, and reading search params there would pull the whole
 * page into a client-side bailout for what is a one-shot hand-off. It is also
 * consumed exactly once: a refresh must not retype a message the user already
 * sent or deliberately cleared.
 *
 * Scoped per destination because the slots are not interchangeable. A prompt
 * written for a mastery path would be nonsense in the reader, so a hand-off the
 * learner declined must not leak into whichever surface they open next.
 */
import { browserStorage } from "@/shared/storage";

const PENDING_PROMPT_KEY = "deeptutor.pendingPrompt";

function keyFor(scope: string): string {
  const clean = scope.trim();
  return clean ? `${PENDING_PROMPT_KEY}.${clean}` : PENDING_PROMPT_KEY;
}

export function setPendingPrompt(text: string, scope = ""): void {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw("session", keyFor(scope), text);
  } catch {
    // Private-mode browsers reject sessionStorage; the user still lands on the
    // destination, just with an empty composer.
  }
}

export function consumePendingPrompt(scope = ""): string {
  if (typeof window === "undefined") return "";
  try {
    const key = keyFor(scope);
    const value = browserStorage.readRaw("session", key);
    if (value) browserStorage.removeRaw("session", key);
    return value ?? "";
  } catch {
    return "";
  }
}
