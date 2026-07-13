import type { StreamEvent } from "./unified-ws";

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
  const meta = asRecord(event.metadata);
  const toolMetadata = asRecord(meta?.tool_metadata);
  return asRecord(toolMetadata?.ask_user) ?? asRecord(meta?.ask_user);
}

function askUserToolCallId(event: StreamEvent): string {
  const meta = asRecord(event.metadata);
  return typeof meta?.tool_call_id === "string" ? meta.tool_call_id.trim() : "";
}

/**
 * Returns true when a stream contains an ask_user card that has not yet
 * emitted the matching ask_user_resolved progress event.
 */
export function hasPendingAskUser(
  events: StreamEvent[] | undefined,
  turnId?: string | null,
): boolean {
  const pending = new Set<string>();
  let anonymousCount = 0;

  for (const event of events ?? []) {
    if (!eventBelongsToTurn(event, turnId)) continue;
    const meta = asRecord(event.metadata);

    if (event.type === "tool_result" && askUserPayloadFrom(event)) {
      const toolCallId = askUserToolCallId(event);
      pending.add(toolCallId ? `id:${toolCallId}` : `anon:${anonymousCount++}`);
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

  return pending.size > 0;
}

export function hasPendingAskUserInMessages(
  messages: MessageWithEvents[],
  turnId?: string | null,
): boolean {
  return messages.some((message) => hasPendingAskUser(message.events, turnId));
}
