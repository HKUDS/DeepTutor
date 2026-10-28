/**
 * A side chat: a conversation opened next to the main one, about it, that
 * never writes back into it.
 *
 * Who answers is the side chat's own choice, made when it is opened — Dito by
 * default, or a partner, a connected agent, or a partner group. Dito reads the
 * whole parent conversation; a partner or an agent answers in its own session
 * with whatever the learner sends (a quoted passage rides along as an
 * attachment); a group is convened by Dito, which reads the conversation and
 * brings the group's discussion back.
 */

import type { SessionPreferences } from "@/lib/session-api";

export type SideChatResponder =
  | { kind: "dito" }
  | { kind: "partner"; id: string; name: string }
  | { kind: "subagent"; id: string; name: string }
  | { kind: "partner_group"; id: string; name: string };

export const DITO: SideChatResponder = { kind: "dito" };

export interface SideChatContext {
  /** The conversation it is about; null when opened beside a draft, where
   *  there is nothing to read yet and the side chat simply stands alone. */
  parentSessionId: string | null;
  /** The tip of the branch the learner was looking at; null before a reply. */
  leafMessageId: number | null;
  /** Shown on the side chat's context card; never sent. */
  parentTitle?: string;
  responder: SideChatResponder;
}

export function sameResponder(
  a: SideChatResponder,
  b: SideChatResponder,
): boolean {
  return (
    a.kind === b.kind &&
    (a.kind === "dito" || a.id === (b as { id: string }).id)
  );
}

/** The ``answer_by`` value a partner or an agent answers through. */
function answerBy(responder: SideChatResponder): string | null {
  if (responder.kind === "partner") return `partner:${responder.id}`;
  if (responder.kind === "subagent") return `subagent:${responder.id}`;
  return null;
}

/** The turn fields that make a send a side-chat turn for ``context``. */
export function sideChatTurnConfig(
  context: SideChatContext,
): Record<string, unknown> {
  const { responder } = context;
  return {
    ...(context.parentSessionId
      ? {
          selection_tutor_context: {
            parent_session_id: context.parentSessionId,
            source_message_id: context.leafMessageId,
          },
        }
      : {}),
    answer_by: answerBy(responder) ?? "",
    ...(responder.kind === "partner_group"
      ? { partner_discussion_group_id: responder.id }
      : {}),
  };
}

/** Who answered a side chat before, read back from its stored preferences.
 *  Names fill in from the live rosters; the id is enough to keep answering. */
export function responderFromPreferences(
  preferences: SessionPreferences | undefined,
): SideChatResponder {
  const groupId = preferences?.side_chat_group_id?.trim();
  if (groupId) return { kind: "partner_group", id: groupId, name: groupId };
  const [kind, ...rest] = String(preferences?.answer_by ?? "").split(":");
  const id = rest.join(":").trim();
  if (id && kind === "partner") return { kind: "partner", id, name: id };
  if (id && kind === "subagent") return { kind: "subagent", id, name: id };
  return DITO;
}

/** A fresh side chat each time one is started; its thread is found again by
 *  session id once the backend assigns one. */
export function sideChatKey(parentSessionId: string | null): string {
  return `side-chat:${parentSessionId ?? "new"}:${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}
