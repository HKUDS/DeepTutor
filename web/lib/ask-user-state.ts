import type { StreamEvent } from "@/features/chat/model/protocol";
import {
  MASTERY_QUESTION_KIND,
  readPosedQuestion,
} from "@/lib/mastery-question";
import { toolResultPayload } from "@/lib/tool-event";

/**
 * Shown when a reply could not be delivered — the turn that asked the
 * question is gone (most often a backend restart since it was posed).
 *
 * One string, three surfaces: the question card renders it inline, the
 * mastery and reading composers raise it as a toast. Keeping it here keeps
 * them saying the same thing, and keeps a single key in the locale files.
 */
export const REPLY_NOT_DELIVERED =
  "This question is no longer active, so your answer could not be sent. Send a new message to continue.";

/**
 * Shown when a composer's reply was refused and re-sent as a new message.
 *
 * The composers used to raise {@link REPLY_NOT_DELIVERED} instead and stop,
 * which discarded what the user had typed — while telling them to do the one
 * thing the composer was refusing to do. They now fall through to an ordinary
 * message, so the honest report is that the text went somewhere, just not to
 * the question.
 *
 * The card keeps {@link REPLY_NOT_DELIVERED}: its own Submit really has
 * nowhere to send an answer, and it has no composer to fall through to.
 */
export const REPLY_SENT_AS_NEW_MESSAGE =
  "That question is no longer waiting for an answer, so this was sent as a new message.";

type MessageWithEvents = {
  events?: StreamEvent[];
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function eventBelongsToTurn(
  event: StreamEvent,
  turnId?: string | null,
): boolean {
  if (!turnId) return true;
  return !event.turn_id || event.turn_id === turnId;
}

function askUserPayloadFrom(
  event: StreamEvent,
): Record<string, unknown> | null {
  return asRecord(toolResultPayload(event.metadata, "ask_user"));
}

/**
 * A mastery card posed before mastery questions got their own event key: it
 * arrived on the `ask_user` channel with a `kind` marker.
 *
 * It must not count as a live pause. `mastery_quiz` ends its turn and the
 * answer opens the next one (see `MasteryStudy`'s `answerMasteryQuestion`),
 * so no `ask_user_resolved` ever arrives for it — and treating one as a pause
 * left every composer permanently convinced the learner owed a same-turn
 * reply, routing their next message (a question about the material included)
 * into a `submit_user_reply` for a turn that had already finished. The backend
 * refused it, and the learner got "this question is no longer active".
 *
 * Cards posed now cannot reach this code at all: they are not `ask_user`
 * payloads.
 */
function isLegacyMasteryCard(payload: Record<string, unknown>): boolean {
  return payload.kind === MASTERY_QUESTION_KIND;
}

function askUserToolCallId(event: StreamEvent): string {
  const meta = asRecord(event.metadata);
  return typeof meta?.tool_call_id === "string" ? meta.tool_call_id.trim() : "";
}

function pendingCards(
  events: StreamEvent[] | undefined,
  turnId: string | null | undefined,
  includeMastery: boolean,
): number {
  const pending = new Set<string>();
  let anonymousCount = 0;

  for (const event of events ?? []) {
    if (!eventBelongsToTurn(event, turnId)) continue;
    const meta = asRecord(event.metadata);

    if (event.type === "tool_result") {
      const posed = readPosedQuestion(event);
      if (posed) {
        // A posed question waits on the learner, but not on this turn.
        if (includeMastery) pending.add(`mastery:${posed.questionId}`);
        continue;
      }
      const payload = askUserPayloadFrom(event);
      if (payload && (includeMastery || !isLegacyMasteryCard(payload))) {
        const toolCallId = askUserToolCallId(event);
        pending.add(
          toolCallId ? `id:${toolCallId}` : `anon:${anonymousCount++}`,
        );
      }
      continue;
    }

    if (event.type === "progress" && meta?.ask_user_resolved === true) {
      const resolvedId =
        typeof meta.ask_user_tool_call_id === "string"
          ? meta.ask_user_tool_call_id.trim()
          : "";
      if (resolvedId) {
        pending.delete(`id:${resolvedId}`);
      } else {
        pending.clear();
      }
    }
  }

  return pending.size;
}

/**
 * Returns true when a stream contains an ask_user card that has not yet
 * emitted the matching ask_user_resolved progress event.
 *
 * This is the *pause* question: is the turn parked, waiting for a reply that
 * belongs to it? Mastery cards are excluded — see `isLegacyMasteryCard`.
 */
export function hasPendingAskUser(
  events: StreamEvent[] | undefined,
  turnId?: string | null,
): boolean {
  return pendingCards(events, turnId, false) > 0;
}

export function hasPendingAskUserInMessages(
  messages: MessageWithEvents[],
  turnId?: string | null,
): boolean {
  return messages.some((message) => hasPendingAskUser(message.events, turnId));
}

/**
 * Returns true when *any* card is still waiting on the user — a paused
 * `ask_user` or a mastery question that ended its turn.
 *
 * For surfaces that only care that something on screen wants the user's
 * attention (keeping it scrolled into view), not for anything that decides
 * where their next message is sent.
 */
export function hasPendingUserCard(
  events: StreamEvent[] | undefined,
  turnId?: string | null,
): boolean {
  return pendingCards(events, turnId, true) > 0;
}
