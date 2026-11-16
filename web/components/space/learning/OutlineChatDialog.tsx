"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Sparkles, X } from "lucide-react";

import { browserStorage } from "@/shared/storage";
import { copyText } from "@/lib/clipboard";
import { resolveMasterySession } from "@/lib/learning-api";
import { MASTERY_WORKSPACE_MODE } from "@/lib/workspace-mode";
import { MASTERY_CAPABILITY_VALUE } from "@/features/capabilities/presentation";
import {
  ChatStateAdapterProvider,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { ChatMessageList } from "@/features/chat/messages";
import StandaloneComposer, {
  type StandaloneComposerSubmission,
} from "@/components/chat/home/StandaloneComposer";
import { hasPendingAskUser, REPLY_SENT_AS_NEW_MESSAGE } from "@/lib/ask-user-state";
import { notify } from "@/lib/notifications";
import { STUDY_COMPOSER_WIDTH } from "./MasteryComposer";

const SESSION_STORAGE_KEY = "dt.mastery.outline.session";

/** Remember the outline conversation so the next open resumes it directly. */
function rememberOutlineSession(pathId: string, sessionId: string): void {
  const stored = browserStorage.readRaw("local", SESSION_STORAGE_KEY);
  let map: Record<string, string> = {};
  try {
    map = JSON.parse(stored || "{}");
  } catch {
    /* ignore malformed storage */
  }
  map[pathId] = sessionId;
  browserStorage.writeRaw("local", SESSION_STORAGE_KEY, JSON.stringify(map));
}

/** The outline conversation this path opened last, or "" when none is known. */
function storedOutlineSession(pathId: string): string {
  const stored = browserStorage.readRaw("local", SESSION_STORAGE_KEY);
  try {
    const map = JSON.parse(stored || "{}") as Record<string, string>;
    return typeof map[pathId] === "string" ? map[pathId] : "";
  } catch {
    return "";
  }
}

/**
 * The outline conversation, opened in a modal on the session screen.
 *
 * It is the *same* chat surface the rest of the app uses — ``ChatStateAdapter``
 * for the turn runtime and ``ChatMessageList`` for the transcript — so the tool
 * trace, streaming typewriter, failure retry and every card render exactly as
 * they do in chat. The earlier bespoke mini-chat could not show any of that:
 * it rendered ``AssistantResponse`` alone, which draws the reply text and
 * nothing about how the tutor produced it.
 *
 * The adapter is a *nested* provider, so opening the outline here never
 * disturbs the study conversation behind the modal.
 */
export function OutlineChatDialog({
  pathId,
  onClose,
}: {
  pathId: string;
  onClose: () => void;
}) {
  return (
    <ChatStateAdapterProvider>
      <OutlineChatBody pathId={pathId} onClose={onClose} />
    </ChatStateAdapterProvider>
  );
}

function OutlineChatBody({
  pathId,
  onClose,
}: {
  pathId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const {
    state,
    loadSession,
    configureSession,
    sendMessage,
    submitUserReply,
    cancelStreamingTurn,
    regenerateLastMessage,
    resendLastMessage,
    deleteTurn,
    discardFailedSubmission,
    retryFailedSubmission,
    editMessage,
    switchBranch,
    loadMessageTrace,
    releaseMessageTrace,
    setKBs,
    setLLMSelection,
  } = useChatStateAdapter();

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // Resolve (create/reuse) the outline session, then load it into this adapter.
  // The transcript is the shared one; this dialog only owns the shell.
  //
  // The conversation this path opened last is reused directly — that is one
  // round-trip instead of two — and a stale id (deleted in another tab) falls
  // back to resolving a fresh one.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    const configure = (sessionId: string) =>
      configureSession(
        {
          workspaceMode: MASTERY_WORKSPACE_MODE,
          capability: MASTERY_CAPABILITY_VALUE,
          masteryPathId: pathId,
          masterySessionMode: "outline",
        },
        sessionId,
      );
    void (async () => {
      try {
        const known = storedOutlineSession(pathId);
        if (known) {
          try {
            await loadSession(known);
            if (cancelled) return;
            configure(known);
            return;
          } catch {
            /* stale id — resolve a fresh session below */
          }
        }
        const placed = await resolveMasterySession(pathId, "outline");
        if (cancelled) return;
        rememberOutlineSession(pathId, placed.session_id);
        await loadSession(placed.session_id);
        if (cancelled) return;
        // The server stores these on the session; restating them keeps the
        // composer and the turn payload pinned to the outline conversation.
        configure(placed.session_id);
      } catch {
        if (!cancelled) setLoadError(t("Could not load the outline conversation."));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [configureSession, loadSession, pathId, t]);

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller) scroller.scrollTop = scroller.scrollHeight;
  }, [state.messages]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, [loading]);

  const copyAssistantMessage = useCallback(
    (content: string) => copyText(content),
    [],
  );

  const awaitingUserReply = hasPendingAskUser(
    state.messages[state.messages.length - 1]?.events,
  );

  const handleSubmit = useCallback(
    (submission: StandaloneComposerSubmission) => {
      const text = submission.content.trim();
      if (!text && !submission.attachments?.length) return;
      const sendAsNewMessage = () =>
        sendMessage(
          submission.content,
          submission.attachments,
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
      // A turn paused on an ask_user card: what the learner typed is their
      // answer, not a new message. Same routing as the study composer.
      if (awaitingUserReply && text) {
        void submitUserReply({ text })
          .then((sent) => {
            if (sent) return;
            notify(t(REPLY_SENT_AS_NEW_MESSAGE));
            sendAsNewMessage();
          })
          .catch(() => sendAsNewMessage());
        return;
      }
      sendAsNewMessage();
    },
    [awaitingUserReply, sendMessage, submitUserReply, t],
  );

  function handleDialogKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="outline-chat-title"
      tabIndex={-1}
      onKeyDown={handleDialogKeyDown}
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-3 backdrop-blur-sm sm:p-6"
    >
      <div className="flex h-full w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)] shadow-2xl">
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--card)] px-4 py-3">
          <h2
            id="outline-chat-title"
            className="text-sm font-semibold text-[var(--foreground)]"
          >
            {t("Outline chat")}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Transcript — the shared message list, so the tool trace and every
            card render exactly as they do in chat. */}
        <div
          ref={scrollerRef}
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain bg-[var(--background)] px-4 py-4 sm:px-6"
        >
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-[var(--muted-foreground)]" />
            </div>
          ) : loadError ? (
            <div className="flex h-full min-h-48 items-center justify-center px-6 text-center text-sm text-[var(--destructive)]">
              {loadError}
            </div>
          ) : state.messages.length === 0 ? (
            <div className="flex h-full min-h-48 flex-col items-center justify-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--primary)]/10">
                <Sparkles className="h-5 w-5 text-[var(--primary)]" />
              </div>
              <h3 className="text-base font-semibold text-[var(--foreground)]">
                {t("Outline chat")}
              </h3>
              <p className="max-w-sm text-sm leading-6 text-[var(--muted-foreground)]">
                {t(
                  "Describe how you want to change the outline, and the tutor will help you adjust it.",
                )}
              </p>
            </div>
          ) : (
            <ChatMessageList
              messages={state.messages}
              isStreaming={state.isStreaming}
              sessionId={state.sessionId}
              language={state.language}
              onCopyAssistantMessage={copyAssistantMessage}
              onRegenerateMessage={() => regenerateLastMessage()}
              canResendLastTurn={state.lastTurnFailed}
              onResendLastTurn={resendLastMessage}
              onDeleteTurn={deleteTurn}
              onDiscardFailedSubmission={discardFailedSubmission}
              onRetryFailedSubmission={retryFailedSubmission}
              selectedBranches={state.selectedBranches}
              onEditMessage={editMessage}
              onSwitchBranch={switchBranch}
              onSubmitUserReply={submitUserReply}
              onLoadMessageTrace={(messageId) =>
                state.sessionId
                  ? loadMessageTrace(state.sessionId, messageId)
                  : Promise.resolve()
              }
              onReleaseMessageTrace={(messageId) => {
                if (state.sessionId) {
                  releaseMessageTrace(state.sessionId, messageId);
                }
              }}
              showModeBadge={false}
            />
          )}
        </div>

        <StandaloneComposer
          showCapabilityChip={false}
          hasMessages={state.messages.length > 0}
          maxWidthClass={STUDY_COMPOSER_WIDTH}
          maxInputHeight={128}
          isStreaming={state.isStreaming}
          awaitingUserReply={awaitingUserReply}
          selectedKnowledgeBases={state.knowledgeBases}
          onKnowledgeBasesChange={setKBs}
          llmSelection={state.llmSelection}
          onLLMSelectionChange={setLLMSelection}
          onSubmit={handleSubmit}
          onCancelStreaming={cancelStreamingTurn}
          inputPlaceholder={
            loading ? "" : t("Describe what to change in the outline\u2026")
          }
        />
      </div>
    </div>
  );
}
