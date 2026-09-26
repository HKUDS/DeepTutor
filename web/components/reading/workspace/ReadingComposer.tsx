"use client";

/**
 * The reading companion's composer — the same one the main chat page and
 * mastery study use, wired through the unified chat context.
 *
 * A reading conversation is a chat session like any other, so it gets the
 * whole composer: attachments, the knowledge-base picker (with real scope
 * activation, not a reading-local facsimile), the model selector, dictation.
 * The one thing specific to this surface is grounding: when the learner has
 * a passage selected, the pending viewport/quote has to reach the backend
 * before the message does, exactly like the retired bespoke textarea did.
 */

import { useCallback } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import StandaloneComposer, {
  type StandaloneComposerSubmission,
} from "@/components/chat/home/StandaloneComposer";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { useWorkspaceChatActions } from "@/hooks/useWorkspaceChatActions";
import {
  hasPendingAskUser,
  REPLY_SENT_AS_NEW_MESSAGE,
} from "@/lib/ask-user-state";
import { notify } from "@/lib/notifications";
import { setReadingViewport } from "@/lib/reading-turn-state";

export function ReadingComposer({
  placeholder,
  placeholderCompletion,
  selection,
  onSent,
  onRemoveSelection,
  linkedSessionIds,
  prefillInputRef,
}: {
  placeholder: string;
  /** Offered question the composer lets the learner take with Tab. */
  placeholderCompletion?: string;
  selection: { quote: string; locator: number } | null;
  /** Clears the pending selection once the message is on its way. */
  onSent: () => void;
  /** The learner dropped the quoted passage before sending. */
  onRemoveSelection: () => void;
  /** Reading-specific "reference these other reading conversations" links. */
  linkedSessionIds: string[];
  /** Lets the reader pane drop a quoted selection's focus into the box. */
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
  const { capabilities, activeCapabilityValue, selectCapability } =
    useWorkspaceChatActions();
  const { t } = useTranslation();

  const awaitingUserReply = hasPendingAskUser(
    state.messages[state.messages.length - 1]?.events,
  );

  const handleSubmit = useCallback(
    (submission: StandaloneComposerSubmission) => {
      const sendAsNewMessage = () => {
        if (selection) {
          setReadingViewport({
            locator: selection.locator,
            selection: selection.quote,
          });
        }
        // The composer's own "@ reference an earlier session" picker and this
        // surface's persistent linked-conversations list share one wire slot;
        // union them rather than letting either silently win.
        const historyReferences = Array.from(
          new Set([...linkedSessionIds, ...submission.historyReferences]),
        );
        sendMessage(
          submission.content,
          submission.attachments,
          // How many times the companion may consult the selected agent this
          // turn. Absent when no agent is picked, which is the ordinary case.
          submission.subagentBudget
            ? {
                ...(submission.config ?? {}),
                subagent_consult_budget: submission.subagentBudget,
              }
            : submission.config,
          submission.notebookReferences,
          historyReferences,
          { bookReferences: submission.bookReferences },
          submission.questionNotebookReferences,
          submission.persona ?? undefined,
          submission.memoryReferences,
        );
        onSent();
        window.setTimeout(() => setReadingViewport({ selection: "" }), 0);
      };

      // A turn paused on a question: what the reader typed is their answer,
      // not a new message. See ChatWorkspace's handleSend for the same routing
      // — including the fall-through on a refusal, which is what keeps a dead
      // question from swallowing the text they just wrote.
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
    [
      awaitingUserReply,
      linkedSessionIds,
      onSent,
      selection,
      sendMessage,
      submitUserReply,
      t,
    ],
  );

  return (
    <StandaloneComposer
      capabilities={capabilities}
      activeCapValue={activeCapabilityValue}
      onSelectCapability={selectCapability}
      showCapabilityChip
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
      inputPlaceholder={placeholder}
      inputPlaceholderCompletion={placeholderCompletion}
      inputHeader={
        selection ? (
          <QuotedPassage
            quote={selection.quote}
            onRemove={onRemoveSelection}
          />
        ) : null
      }
      prefillInputRef={prefillInputRef}
    />
  );
}

/**
 * The passage the next message is about, inside the box it will be sent from.
 *
 * Drawn the way the sent bubble draws it (a rule and the words, no card), so
 * the quote looks the same before and after it goes.
 */
function QuotedPassage({
  quote,
  onRemove,
}: {
  quote: string;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-1.5 px-4 pt-3">
      <p className="line-clamp-2 min-w-0 flex-1 border-l-2 border-[color-mix(in_srgb,var(--primary)_45%,transparent)] pl-2.5 text-[12.5px] leading-relaxed text-[var(--muted-foreground)]">
        {quote}
      </p>
      <button
        type="button"
        aria-label={t("Remove quoted passage")}
        title={t("Remove quoted passage")}
        onClick={onRemove}
        className="-mr-1 inline-flex size-6 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
      >
        <X size={12} />
      </button>
    </div>
  );
}
