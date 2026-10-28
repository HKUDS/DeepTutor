/**
 * Hand a starting message from one surface to another's composer.
 *
 * Settings opens chat with a configuration request ready to read and send.
 * Mastery hand-off cards prefill the opening line in a study conversation.
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
