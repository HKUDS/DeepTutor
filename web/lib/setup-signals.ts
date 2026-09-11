import type { StreamEvent } from "@/features/chat/model/protocol";
import { toolResultMetadata } from "@/lib/tool-event";

/**
 * Reading the setup capability's signals off a turn's event stream.
 *
 * Kept as pure functions, apart from the components that render them, for the
 * same reason `lib/ask-user-state.ts` is: the interesting logic is which events
 * count and how they are deduplicated, and that deserves tests that do not need
 * a DOM.
 *
 * Mirrors the metadata written by `deeptutor/capabilities/setup/tools.py`.
 */

/** Hand-off card shown when a step needs a credential the assistant must not touch. */
export interface SetupCredentialData {
  service: string;
  label: string;
  settingsPath: string;
  reason: string;
}

function toolMetadataOf(event: StreamEvent): Record<string, unknown> | null {
  if (event.type !== "tool_result") return null;
  return toolResultMetadata(event.metadata);
}

/**
 * The most recent credential hand-off in this message, if any.
 *
 * `settingsPath` is required to be an in-app settings route: it is rendered as
 * a navigation target, and constraining it here means a malformed or hostile
 * value cannot turn the card into an open redirect.
 */
export function extractSetupCredential(
  events: StreamEvent[] | undefined,
): SetupCredentialData | null {
  if (!events || events.length === 0) return null;
  let latest: SetupCredentialData | null = null;
  for (const event of events) {
    const toolMetadata = toolMetadataOf(event);
    if (!toolMetadata) continue;
    const raw = toolMetadata.setup_credential;
    if (!raw || typeof raw !== "object") continue;
    const payload = raw as Record<string, unknown>;
    const settingsPath = String(payload.settings_path ?? "").trim();
    if (!settingsPath.startsWith("/settings")) continue;
    latest = {
      service: String(payload.service ?? ""),
      label: String(payload.label ?? ""),
      settingsPath,
      reason: String(payload.reason ?? ""),
    };
  }
  return latest;
}

/**
 * Stable ids for every `setup_applied` signal across a conversation.
 *
 * One id per tool call, so a caller can honour each exactly once: replayed
 * history and ordinary re-renders must not keep re-applying a preference the
 * user may have changed by hand since. Falls back to key+seq when the transport
 * did not carry a tool call id, which still distinguishes separate writes.
 */
export function collectAppliedSettingIds(
  messages: ReadonlyArray<{ events?: StreamEvent[] }> | undefined,
): string[] {
  if (!messages || messages.length === 0) return [];
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const message of messages) {
    for (const event of message.events ?? []) {
      const toolMetadata = toolMetadataOf(event);
      if (!toolMetadata) continue;
      const applied = toolMetadata.setup_applied;
      if (!applied || typeof applied !== "object") continue;
      const meta = (event.metadata ?? {}) as Record<string, unknown>;
      const callId =
        (event as { tool_call_id?: string }).tool_call_id ??
        (typeof meta.tool_call_id === "string" ? meta.tool_call_id : "");
      const key = String((applied as Record<string, unknown>).key ?? "");
      const id = callId || (key ? `${key}:${event.seq ?? ""}` : "");
      if (!id || seen.has(id)) continue;
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}
