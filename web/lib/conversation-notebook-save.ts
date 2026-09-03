/** Build the shared notebook payload for transcript-based workspaces. */

import type { MessageItem } from "@/features/chat/ChatStateAdapter";

export interface ConversationNotebookSaveOptions {
  source: string;
  fallbackTitle: string;
  activeCapability: string | null;
  language: string;
  sessionId: string | null;
}

/**
 * Chat, Mastery Study, and Immersive Reading all save the same selectable
 * transcript record. Keep the payload contract here so restoring the action
 * on a workspace cannot create a subtly different notebook record (#1182).
 */
export function buildConversationNotebookSave(
  messages: MessageItem[],
  options: ConversationNotebookSaveOptions,
) {
  const modalMessages = messages.map((message) => ({
    role: message.role,
    content: message.content,
    capability: message.capability,
  }));
  if (!messages.length) return { modalMessages, payload: null };

  const title =
    messages
      .find((message) => message.role === "user")
      ?.content.trim()
      .slice(0, 80) || options.fallbackTitle;

  return {
    modalMessages,
    payload: {
      recordType: "chat" as const,
      title,
      // The modal rebuilds these from the learner's selected messages.
      userQuery: "",
      output: "",
      metadata: {
        source: options.source,
        capability: options.activeCapability || options.source,
        ui_language: options.language,
        session_id: options.sessionId,
        total_message_count: messages.length,
      },
    },
  };
}
