/**
 * What a mastery conversation is doing right now — the client's half of
 * ``deeptutor/capabilities/mastery/mode.py``.
 *
 * Three modes, and the conversation moves between them: the outline mode
 * designs the map, study works it forward, review re-tests what is already
 * mastered. The tutor switches with `mastery_mode`; the learner switches by
 * pressing one of the three above the transcript.
 *
 * It is not a label. The server refuses a tool that does not belong to the
 * current mode, so this is what the conversation can actually do — which is
 * why the UI shows all three and marks the live one, rather than naming the
 * current one and leaving the others to be guessed at.
 */

export const MASTERY_MODES = ["outline", "study", "review"] as const;

export type MasteryMode = (typeof MASTERY_MODES)[number];

/** Mirrors the server: an unknown mode is shown as the ordinary study mode. */
export const DEFAULT_MASTERY_MODE: MasteryMode = "study";

export function normalizeMasteryMode(value: unknown): MasteryMode {
  const candidate = String(value ?? "")
    .trim()
    .toLowerCase();
  return (MASTERY_MODES as readonly string[]).includes(candidate)
    ? (candidate as MasteryMode)
    : DEFAULT_MASTERY_MODE;
}

/** The i18n keys each mode is named and explained by, in one place. */
/**
 * The i18n keys each mode is named by.
 *
 * Namespaced rather than the bare words: "Review" already exists elsewhere in
 * the product meaning *proofread*, and reusing it rendered this control as
 * 「审阅」 — the right translation of a different word.
 */
export const MASTERY_MODE_LABELS: Record<MasteryMode, string> = {
  outline: "masteryMode.outline",
  study: "masteryMode.study",
  review: "masteryMode.review",
};

/**
 * The route that opens a *new* conversation on a goal in this mode.
 *
 * One function so the entry points cannot disagree: creating a goal lands on
 * its outline, the sessions panel opens study conversations, and the review
 * card opens review ones. A route only ever sets the *starting* mode — an
 * existing conversation carries the mode it is in.
 */
export function masterySessionRoute(
  pathId: string,
  mode: MasteryMode,
  courseId = "",
): string {
  const params = new URLSearchParams();
  if (mode !== DEFAULT_MASTERY_MODE) params.set("mode", mode);
  if (courseId) params.set("course", courseId);
  const query = params.toString();
  return `/mastery/${encodeURIComponent(pathId)}/sessions${query ? `?${query}` : ""}`;
}

/**
 * Where a hand-off leaves the opening message for the conversation it opens.
 *
 * Separate from the ordinary pending-prompt slot because the intent differs:
 * that one *types* a line into the composer for the learner to read and send,
 * while this one is a message they have already sent by pressing the button
 * that brought them here. Pressing "design the outline with the tutor" is the
 * request; arriving at an empty screen and being asked to phrase it again
 * would be the product forgetting what it was just told.
 */
export const MASTERY_OPENING_SCOPE = "mastery_opening";

/**
 * The message a hand-off sends on the learner's behalf when it opens a
 * conversation in this mode, or "" for a mode that opens with nothing.
 *
 * Pressing a button *is* the request. An outline conversation opened from
 * "design the outline with the tutor" starts by asking for exactly that; a
 * review opened from a due-items card starts by naming the items. A study
 * conversation opens with nothing, because "start learning" does not say what
 * to start with — the screen offers three ways in instead.
 *
 * A mode the learner switches into by hand also sends nothing: they are
 * already in the middle of a conversation, and the tutor has the context.
 */
export function masteryOpeningMessage(
  mode: MasteryMode,
  translate: (key: string, vars?: Record<string, unknown>) => string,
  options: { dueTitles?: string[] } = {},
): string {
  if (mode === "outline") {
    return translate(
      "Use the materials I chose and design the outline for this goal with me.",
    );
  }
  if (mode === "review") {
    const due = (options.dueTitles ?? []).filter(Boolean);
    return due.length
      ? translate("Let's review what is due today: {{items}}.", {
          items: due.join(translate("source list separator")),
        })
      : translate("Let's review what I have already learned.");
  }
  return "";
}
