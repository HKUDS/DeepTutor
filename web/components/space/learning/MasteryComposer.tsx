"use client";

/**
 * The study screen's composer — the same one the main chat page uses,
 * sending through the unified chat context.
 *
 * A mastery session is a chat session, so the learner gets the whole
 * composer: attachments, `@`-space references, the knowledge picker, the
 * model selector, dictation. Two of those controls are session-scoped
 * rather than per-turn — the knowledge bases in play and the pinned model —
 * so both are driven straight off the session state instead of a second
 * copy inside the composer.
 *
 * What it does NOT get is the action menu. This screen runs one loop — the
 * tutor — and it used to open on "Chat" instead, which reached the same tutor
 * by a different route (the workspace flag made a chat turn mount the mastery
 * tools). Two entrances to one place, with the visible label naming the wrong
 * one. The action is now the screen itself.
 */

import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import StandaloneComposer, {
  type StandaloneComposerSubmission,
} from "@/components/chat/home/StandaloneComposer";
import { MASTERY_CAPABILITY_VALUE } from "@/features/capabilities/presentation";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { useContextBudget } from "@/hooks/useContextBudget";
import { useWorkspaceChatActions } from "@/hooks/useWorkspaceChatActions";
import {
  hasPendingAskUser,
  REPLY_SENT_AS_NEW_MESSAGE,
} from "@/lib/ask-user-state";
import { notify } from "@/lib/notifications";

export function MasteryComposer({
  placeholder,
  askHint,
  disabled,
  prefillInputRef,
}: {
  placeholder: string;
  /** A question the tutor suggests asking here; Tab takes it. "" for none. */
  askHint?: string;
  /** The session is still opening — nothing can be sent yet. */
  disabled?: boolean;
  /** Lets the screen drop a handed-off opening line into the textarea. */
  prefillInputRef?: React.MutableRefObject<((text: string) => void) | null>;
}) {
  const {
    state,
    sendMessage,
    submitUserReply,
    cancelStreamingTurn,
    setKBs,
    setLLMSelection,
    setPersonaSelection,
  } = useChatStateAdapter();
  // Pins the turn to the tutor loop; returns no capabilities to offer.
  useWorkspaceChatActions({ pinnedCapability: MASTERY_CAPABILITY_VALUE });
  const contextBudget = useContextBudget(state.messages);
  const { t } = useTranslation();

  // A turn paused on an ask_user card is still "streaming", but typing an
  // answer is exactly how it moves forward — the composer stays live.
  //
  // A question card is NOT that: posing one ends the turn, so what the learner
  // types next is a new message — an answer they would rather write out, or a
  // question about the material. Routing it as a same-turn reply sent it into
  // a turn that was already over, and every message after a question came back
  // "this question is no longer active" until they reloaded.
  const awaitingUserReply = hasPendingAskUser(
    state.messages[state.messages.length - 1]?.events,
  );

  const handleSubmit = useCallback(
    (submission: StandaloneComposerSubmission) => {
      if (disabled) return;
      const sendAsNewMessage = () =>
        sendMessage(
          submission.content,
          submission.attachments,
          // How many times the tutor may consult the selected agent this turn.
          // Absent when no agent is picked, which is the ordinary case.
          submission.subagentBudget
            ? {
                ...(submission.config ?? {}),
                subagent_consult_budget: submission.subagentBudget,
              }
            : submission.config,
          submission.notebookReferences,
          submission.historyReferences,
          { bookReferences: submission.bookReferences },
          submission.questionNotebookReferences,
          submission.persona ?? undefined,
          submission.memoryReferences,
        );

      // A turn paused on a question: what the learner typed is their answer,
      // not a new message. See ChatWorkspace's handleSend for the same routing
      // — including the fall-through, which is the part that matters: the
      // composer has already cleared the box, so stopping on a refusal
      // discarded what they wrote.
      if (awaitingUserReply && submission.content.trim()) {
        void submitUserReply({ text: submission.content }).then((sent) => {
          if (sent) return;
          notify(t(REPLY_SENT_AS_NEW_MESSAGE));
          sendAsNewMessage();
        });
        return;
      }
      sendAsNewMessage();
    },
    [awaitingUserReply, disabled, sendMessage, submitUserReply, t],
  );

  return (
    <StandaloneComposer
      showCapabilityChip={false}
      hasMessages={state.messages.length > 0}
      isStreaming={state.isStreaming}
      awaitingUserReply={awaitingUserReply}
      selectedKnowledgeBases={state.knowledgeBases}
      onKnowledgeBasesChange={setKBs}
      llmSelection={state.llmSelection}
      onLLMSelectionChange={setLLMSelection}
      personaSelection={state.personaSelection}
      onPersonaSelectionChange={setPersonaSelection}
      onSubmit={handleSubmit}
      onCancelStreaming={cancelStreamingTurn}
      // The suggested question *is* the placeholder once there is one: naming
      // the waypoint a third time says nothing the header has not, whereas the
      // question shows the learner a way in.
      inputPlaceholder={askHint || placeholder}
      inputPlaceholderCompletion={askHint}
      prefillInputRef={prefillInputRef}
      // A tutoring transcript fills a window faster than a chat one — a topic's
      // materials, the map, and the whole history of questions all ride along —
      // so the reading belongs here at least as much as on the chat page.
      contextBudget={contextBudget}
    />
  );
}
