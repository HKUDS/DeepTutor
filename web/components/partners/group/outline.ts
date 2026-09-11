/**
 * Rail model for a Group discussion.
 *
 * The product-chat rail answers "where did I ask that?". A Group has a second
 * kind of turn — an approved Partner-to-Partner question — and the point of
 * putting it on the same rail is rhythm: at a glance you can see where you
 * drove the conversation and where the Partners took it between themselves.
 * Those ticks are toned differently rather than merged into the user's, so
 * the two never get confused.
 */

import { plainTextPreview, type ChatOutlineEntry } from "@/lib/chat-outline";

import type { Round } from "./useGroupSession";

/** Longest title in the set defines the full-width tick. */
function normalise(entries: ChatOutlineEntry[]): ChatOutlineEntry[] {
  const longest = entries.reduce(
    (max, entry) => Math.max(max, entry.title.length),
    1,
  );
  return entries.map((entry) => ({
    ...entry,
    weight: Math.min(1, entry.title.length / longest),
  }));
}

/** First seat that actually produced prose, as the hover preview's answer. */
function firstReply(round: Round, skip: number): string {
  for (let index = skip; index < round.seats.length; index += 1) {
    const seat = round.seats[index];
    const body = seat.message?.content ?? seat.streamed;
    const preview = plainTextPreview(body, 160);
    if (preview) return preview;
  }
  return "";
}

export function buildGroupOutline(rounds: Round[]): ChatOutlineEntry[] {
  const entries: ChatOutlineEntry[] = [];

  rounds.forEach((round, index) => {
    if (round.followup) {
      // The question is the round's own first seat; the answer follows it.
      const question = round.seats[0]?.message;
      const title = plainTextPreview(question?.content ?? "", 160);
      if (!title) return;
      const invocation = round.seats.find((seat) => seat.message?.invocation)
        ?.message?.invocation;
      const badge =
        invocation && invocation.requester_partner_name
          ? `${invocation.requester_partner_name} → ${invocation.target_partner_name}`
          : question?.author_name || "";
      entries.push({
        key: round.turnId,
        index,
        ordinal: entries.length + 1,
        title,
        reply: firstReply(round, 1),
        weight: 0,
        tone: "peer",
        badge,
      });
      return;
    }

    const title = plainTextPreview(round.user?.content ?? "", 160);
    if (!title) return;
    entries.push({
      key: round.turnId,
      index,
      ordinal: entries.length + 1,
      title,
      reply: firstReply(round, 0),
      weight: 0,
      tone: "user",
    });
  });

  return normalise(entries);
}
