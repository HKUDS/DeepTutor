"use client";

/**
 * FollowupChatComposer — the main chat composer, routing its sends into
 * ``QuizFollowupController`` instead of the unified chat context, so the
 * follow-up tab's composer surface (look, controls, @space popup, KB
 * picker, attachments, LLM selector, picker dialogs) matches the main chat
 * composer exactly.
 *
 * The composer machinery itself lives in ``StandaloneComposer``; this file
 * only holds what is specific to a quiz follow-up: the capability label,
 * the follow-up ``config``, and the answer images that ride along with the
 * very first send.
 */

import { memo, useCallback, useMemo } from "react";
import { MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";

import StandaloneComposer, {
  type StandaloneComposerSubmission,
} from "@/components/chat/home/StandaloneComposer";
import {
  type FollowupThreadState,
  type QuizFollowupTabContext,
  useFollowupThread,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import type { ComposerResourceCatalog } from "@/hooks/useComposerResources";
import { hasPendingAskUser } from "@/lib/ask-user-state";
import { buildQuizFollowupConfig } from "@/lib/quiz-types";
import { quoteAttachment } from "@/lib/quote-attachments";
import SideChatResponderMenu from "@/components/chat/home/SideChatResponderMenu";
import { sideChatTurnConfig, type SideChatResponder } from "@/lib/side-chat";

// Single-capability list — the follow-up tab is locked to "chat".
const FOLLOWUP_CAPABILITIES = [
  {
    value: "",
    label: "Chat",
    description: "Flexible conversation with any tool",
    icon: MessageSquare,
    allowedTools: [],
  },
];

/** One prompt per thing the thread is pinned to. A side chat names who will
 *  read it, since that is the one thing that changes what to write. */
export function followupPlaceholder(
  context: QuizFollowupTabContext,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const side = context.sideChat;
  if (!side) {
    return t("Ask anything about this question, your answer, or the AI judgment.");
  }
  return side.responder.kind === "dito"
    ? t("Ask Dito…")
    : t("Ask {{name}}…", { name: side.responder.name });
}

interface FollowupChatComposerProps {
  context: QuizFollowupTabContext;
  /** The conversation's skills and connectors; each thread picks its own. */
  resourceCatalog?: ComposerResourceCatalog;
  /** Connected agents a side chat can be handed to. */
  agents?: { name: string; kind?: string }[];
  /** Hand a side chat to someone else; absent, who answers is fixed. */
  onResponderChange?: (responder: SideChatResponder) => void;
}

function FollowupChatComposerImpl({
  context,
  resourceCatalog,
  agents = [],
  onResponderChange,
}: FollowupChatComposerProps) {
  const { t } = useTranslation();
  const controller = useQuizFollowupController();
  const thread = useFollowupThread(context.questionKey);

  const isFirstSend = !thread.sessionId && thread.messages.length === 0;

  // A turn paused on an ask_user card is still "streaming", but typing an
  // answer is exactly how it moves forward — the composer stays live.
  const awaitingUserReply = hasPendingAskUser(
    thread.messages[thread.messages.length - 1]?.events,
  );

  const handleSubmit = useCallback(
    (submission: StandaloneComposerSubmission) => {
      // A turn paused on a question: what the user typed is their answer,
      // not a new message. See page.tsx's handleSend for the same routing.
      if (awaitingUserReply) {
        if (submission.content.trim()) {
          controller.submitAskUserReply(context.questionKey, {
            text: submission.content,
          });
        }
        return;
      }
      if (thread.isStreaming) return;

      // The learner's own answer images belong to the question, not to the
      // composer — they ride along once, on the send that opens the thread.
      const answerImageAttachments = isFirstSend
        ? context.answerImages
            .map((image) => {
              if (image.base64) {
                return {
                  type: "image",
                  base64: image.base64,
                  filename: image.filename,
                  mime_type: image.mime,
                } as const;
              }
              if (image.url) {
                return {
                  type: "image",
                  url: image.url,
                  filename: image.filename,
                  mime_type: image.mime,
                } as const;
              }
              return null;
            })
            .filter(
              (entry): entry is NonNullable<typeof entry> => entry !== null,
            )
        : [];

      const baseConfig = context.sideChat
        ? sideChatTurnConfig(context.sideChat)
        : buildQuizFollowupConfig(
            context.question,
            context.userAnswer,
            context.isCorrect,
            context.parentQuizSessionId,
            {
              userAnswerImageFilenames: context.answerImages.map(
                (image) => image.filename,
              ),
              aiJudgment: context.aiJudgment,
            },
          );

      // Memory references ride on ``config`` — same convention as the
      // main chat sendMessage path.
      const config: Record<string, unknown> = { ...baseConfig };
      if (submission.memoryReferences.length > 0) {
        config.memory_references = submission.memoryReferences;
      }

      controller.sendMessage({
        questionKey: context.questionKey,
        content: submission.content,
        attachments: [...answerImageAttachments, ...submission.attachments],
        config,
        language: context.language,
        knowledgeBases: submission.knowledgeBases,
        notebookReferences: submission.notebookReferences,
        historyReferences: submission.historyReferences,
        bookReferences: submission.bookReferences,
        questionNotebookReferences: submission.questionNotebookReferences,
        persona: submission.persona ?? undefined,
        llmSelection: submission.llmSelection,
        skills: thread.resourceSelection.skills,
        mcp: thread.resourceSelection.mcp,
      });
    },
    [
      awaitingUserReply,
      context,
      controller,
      isFirstSend,
      thread.isStreaming,
      thread.resourceSelection,
    ],
  );

  const setResourceSelection = useCallback(
    (resourceSelection: FollowupThreadState["resourceSelection"]) =>
      controller.updateThread(context.questionKey, (prev) => ({
        ...prev,
        resourceSelection,
      })),
    [context.questionKey, controller],
  );

  const handleCancelStreaming = useCallback(() => {
    controller.cancelTurn(context.questionKey);
  }, [context.questionKey, controller]);

  const seedAttachments = useMemo(() => {
    const quote = context.seedQuote ? quoteAttachment(context.seedQuote.text) : null;
    return context.seedQuote && quote
      ? { id: context.seedQuote.id, attachments: [quote] }
      : null;
  }, [context.seedQuote]);

  const hasMessages = useMemo(
    () => thread.messages.some((m) => m.role !== "system"),
    [thread.messages],
  );

  return (
    <StandaloneComposer
      capabilities={FOLLOWUP_CAPABILITIES}
      hasMessages={hasMessages}
      isStreaming={thread.isStreaming}
      awaitingUserReply={awaitingUserReply}
      onSubmit={handleSubmit}
      onCancelStreaming={handleCancelStreaming}
      inputPlaceholder={followupPlaceholder(context, t)}
      seedAttachments={seedAttachments}
      // A pane's composer: one line tall, lists opening upward, and no mode
      // picker for a thread that only ever chats.
      docked
      showCapabilityChip={false}
      // In a side chat, who answers is the side chat — its own menu says so.
      partnerControls={!context.sideChat}
      trayEnd={
        context.sideChat && onResponderChange ? (
          <SideChatResponderMenu
            value={context.sideChat.responder}
            onChange={onResponderChange}
            agents={agents}
            aboutConversation={Boolean(context.sideChat.parentSessionId)}
          />
        ) : undefined
      }
      resourceCatalog={resourceCatalog}
      resourceSelection={thread.resourceSelection}
      onResourceSelectionChange={setResourceSelection}
    />
  );
}

const FollowupChatComposer = memo(FollowupChatComposerImpl);
export default FollowupChatComposer;

export type { FollowupChatComposerProps };
