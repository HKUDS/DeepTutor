"use client";

import { useCallback } from "react";

import {
  type MessageRequestSnapshot,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import type { OutlineItem } from "@/lib/research-types";

/** Resume Deep Research after its editable outline, on any chat surface. */
export function useResearchOutlineContinuation() {
  const { sendMessage } = useChatStateAdapter();
  return useCallback(
    (
      outline: OutlineItem[],
      topic: string,
      originalConfig?: Record<string, unknown> | null,
      originalSnapshot?: MessageRequestSnapshot | null,
    ) => {
      const config: Record<string, unknown> = {
        ...(originalConfig ?? {}),
        confirmed_outline: outline,
      };
      const requestSnapshotOverride = originalSnapshot
        ? {
            ...originalSnapshot,
            content: topic,
            capability: "deep_research",
            config,
          }
        : undefined;
      sendMessage(
        topic,
        originalSnapshot?.attachments ?? [],
        config,
        originalSnapshot?.notebookReferences,
        originalSnapshot?.historyReferences,
        {
          displayUserMessage: false,
          persistUserMessage: false,
          requestSnapshotOverride,
          bookReferences: originalSnapshot?.bookReferences,
        },
        originalSnapshot?.questionNotebookReferences,
        originalSnapshot?.persona,
        originalSnapshot?.memoryReferences,
      );
    },
    [sendMessage],
  );
}
