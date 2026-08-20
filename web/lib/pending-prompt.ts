/**
 * Hand a starting message from one page to the chat composer on another.
 *
 * Used by the Settings hub's "let DeepTutor configure this" entry point: the
 * button navigates to chat and the composer opens with the request already
 * typed, so the user reads and sends it rather than arriving at an empty box
 * wondering what to say.
 *
 * sessionStorage rather than a query parameter on purpose — the chat route is
 * a catch-all segment, and reading search params there would pull the whole
 * page into a client-side bailout for what is a one-shot hand-off. It is also
 * consumed exactly once: a refresh must not retype a message the user already
 * sent or deliberately cleared.
 */
const PENDING_PROMPT_KEY = "deeptutor.pendingPrompt";

export function setPendingPrompt(text: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(PENDING_PROMPT_KEY, text);
  } catch {
    // Private-mode browsers reject sessionStorage; the user still lands on
    // chat, just with an empty composer.
  }
}

export function consumePendingPrompt(): string {
  if (typeof window === "undefined") return "";
  try {
    const value = window.sessionStorage.getItem(PENDING_PROMPT_KEY);
    if (value) window.sessionStorage.removeItem(PENDING_PROMPT_KEY);
    return value ?? "";
  } catch {
    return "";
  }
}
