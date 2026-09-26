import { buildVisiblePath, type BranchMessage } from "./message-branches";

type MessageId = number | string;

interface ChatBranchMessage extends BranchMessage {
  role: "user" | "assistant" | "system";
  /** Set when this submission never reached the server (#1594): the turn
   *  left no assistant row, so the unsent user row is the retry handle. */
  failedSubmission?: boolean;
  /** A quota fallback kept the text but not enough context for safe resend. */
  failedSubmissionNeedsReview?: boolean;
}

/** A failed turn can be retried only while its tail is on the visible branch:
 *  either the failed assistant reply, or a user row flagged as never sent. */
export function isFailedTurnVisible<T extends ChatBranchMessage>(
  messages: T[],
  selectedBranches: Record<string, number>,
  status: string,
  isStreaming: boolean,
): boolean {
  if (isStreaming || (status !== "failed" && status !== "rejected")) return false;
  const tail = messages[messages.length - 1];
  if (tail?.role === "assistant") {
    return buildVisiblePath(messages, selectedBranches).messages.at(-1) === tail;
  }
  if (tail?.role === "user" && tail.failedSubmission && !tail.failedSubmissionNeedsReview) {
    return buildVisiblePath(messages, selectedBranches).messages.at(-1) === tail;
  }
  return false;
}

interface LocalMessage {
  id?: MessageId;
  parentMessageId?: MessageId | null;
}

interface RemoteMessage {
  id: MessageId;
  role: "user" | "assistant" | "system";
  content: string;
  parent_message_id?: MessageId | null;
}

interface RemoteSession {
  status?: string | null;
  active_turns?: readonly unknown[];
  messages?: readonly RemoteMessage[];
}

type ReplayDecision =
  | { kind: "refresh" }
  | { kind: "regenerate" }
  | { kind: "reconcile_regenerate"; userId: MessageId }
  | { kind: "resend" };

function isPersistedId(id: unknown): id is MessageId {
  return (typeof id === "number" && id > 0) ||
    (typeof id === "string" && id.length > 0);
}

function sameParent(left: MessageId | null | undefined, right: MessageId | null | undefined): boolean {
  return left == null ? right == null : right != null && String(left) === String(right);
}

/** Distinguish this failed turn from an earlier completed turn in the session. */
export function decideFailedTurnReplay(
  localMessages: readonly LocalMessage[],
  lastUser: LocalMessage & { requestSnapshot: { content: string } },
  remote: RemoteSession,
): ReplayDecision {
  if (remote.active_turns?.length) return { kind: "refresh" };
  const knownIds = new Set(
    localMessages.filter((message) => isPersistedId(message.id)).map((message) => String(message.id)),
  );
  const newRows = (remote.messages ?? []).filter(
    (message) => message.role !== "system" && !knownIds.has(String(message.id)),
  );

  if (isPersistedId(lastUser.id)) {
    return newRows.length > 0 || remote.status === "completed"
      ? { kind: "refresh" }
      : { kind: "regenerate" };
  }

  const persistedUser = [...newRows].reverse().find((message) => message.role === "user");
  if (persistedUser) {
    return ["failed", "rejected", "cancelled"].includes(remote.status ?? "") &&
      persistedUser.content === lastUser.requestSnapshot.content &&
      sameParent(persistedUser.parent_message_id, lastUser.parentMessageId)
      ? { kind: "reconcile_regenerate", userId: persistedUser.id }
      : { kind: "refresh" };
  }
  return newRows.length > 0 ? { kind: "refresh" } : { kind: "resend" };
}
