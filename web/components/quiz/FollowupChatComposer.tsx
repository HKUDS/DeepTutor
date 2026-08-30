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
  type QuizFollowupTabContext,
  useFollowupThread,
  useQuizFollowupController,
} from "@/context/QuizFollowupContext";
import { hasPendingAskUser } from "@/lib/ask-user-state";
import { buildQuizFollowupConfig } from "@/lib/quiz-types";
import { buildSelectionTutorConfig } from "@/lib/selection-tutor";

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

interface FollowupChatComposerProps {
  context: QuizFollowupTabContext;
}

function FollowupChatComposerImpl({ context }: FollowupChatComposerProps) {
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

      const baseConfig = context.tutorSelection
        ? buildSelectionTutorConfig(context.tutorSelection)
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
      });
    },
    [awaitingUserReply, context, controller, isFirstSend, thread.isStreaming],
  );

  const handleCancelStreaming = useCallback(() => {
    // The follow-up runner is owned by the controller; we don't expose
    // a hard cancel from the public surface. Treat this as a no-op for
    // now — the user can refresh or close the tab to recover.
  }, []);

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
      inputPlaceholder={t(
        "Ask anything about this question, your answer, or the AI judgment.",
      )}
    />
  );
}

const FollowupChatComposer = memo(FollowupChatComposerImpl);
export default FollowupChatComposer;

export type { FollowupChatComposerProps };
