/**
 * Why the server refused a turn, in the learner's own language.
 *
 * `start_turn_rejected` is what a learner sees when admission says no, and the
 * server always pairs it with a reason: a mastery path another session is
 * still driving, a conversation asked for a topic it is not on, a workspace
 * that moved under it. Those are things the learner can act on. The banner
 * they used to get — "couldn't reach the server, check your connection" —
 * was for the opposite failure, a request that never arrived, and sent them to
 * troubleshoot the network while the real blocker sat in another tab.
 *
 * Only the codes worth translating live here. Anything else is shown as the
 * server wrote it: an unlocalised true sentence still beats a false one.
 */

export interface RejectionCopy {
  /** Matched against the start of the server's message. */
  prefix: string;
  /** English source string; the `t()` key. */
  key: string;
}

export const SUBMISSION_REJECTION_COPY: readonly RejectionCopy[] = [
  {
    prefix: "mastery_path_busy",
    key: "Another session is still working on this topic. Close it or let it finish, then send again.",
  },
  {
    prefix: "mastery_session_topic_mismatch",
    key: "This conversation belongs to a different topic. Open it from that topic and send again.",
  },
  {
    prefix: "The conversation workspace changed",
    key: "The conversation workspace changed. Reload the conversation to continue.",
  },
];

/** "" when nothing was refused; otherwise the reason, translated if known. */
export function localizedRejectionReason(
  reason: string,
  t: (key: string) => string,
): string {
  const text = reason.trim();
  if (!text) return "";
  const known = SUBMISSION_REJECTION_COPY.find((entry) =>
    text.startsWith(entry.prefix),
  );
  return known ? t(known.key) : text;
}
