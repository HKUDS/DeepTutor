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
 */

import { useCallback } from "react";

import StandaloneComposer, {
  type StandaloneComposerSubmission,
} from "@/components/chat/home/StandaloneComposer";
import { useUnifiedChat } from "@/context/UnifiedChatContext";
import { hasPendingAskUser } from "@/lib/ask-user-state";

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
  } = useUnifiedChat();

  // A turn paused on an ask_user card is still "streaming", but typing an
  // answer is exactly how it moves forward — the composer stays live.
  const awaitingUserReply = hasPendingAskUser(
    state.messages[state.messages.length - 1]?.events,
  );

  const handleSubmit = useCallback(
    (submission: StandaloneComposerSubmission) => {
      if (disabled) return;
      // A turn paused on a question: what the user typed is their answer,
      // not a new message. See page.tsx's handleSend for the same routing.
      if (awaitingUserReply) {
        if (submission.content.trim()) {
          submitUserReply({ text: submission.content });
        }
        return;
      }
      sendMessage(
        submission.content,
        submission.attachments,
        // How many times the tutor may consult the selected agent this turn.
        // Absent when no agent is picked, which is the ordinary case.
        submission.subagentBudget
          ? { subagent_consult_budget: submission.subagentBudget }
          : undefined,
        submission.notebookReferences,
        submission.historyReferences,
        { bookReferences: submission.bookReferences },
        submission.questionNotebookReferences,
        submission.persona ?? undefined,
        submission.memoryReferences,
      );
    },
    [awaitingUserReply, disabled, sendMessage, submitUserReply],
  );

  return (
    <StandaloneComposer
      // No capability chip: this screen only ever runs the mastery tutor and
      // says so in its own header, so a picker that cannot pick is noise.
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
    />
  );
}
