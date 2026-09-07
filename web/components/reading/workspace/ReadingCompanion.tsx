"use client";

/**
 * The reading companion — the chat panel beside the open material.
 *
 * It is a chat surface first and a reading feature second, so everything a
 * conversation needs is imported from the main chat page's own components
 * rather than reimplemented at 380 px: `ChatMessageList` renders the
 * transcript, `useChatAutoScroll` pins it while a reply streams,
 * `ReadingComposer` wraps the same composer /chat uses, `SessionViewerPanel`
 * is the same activity drawer, and the transcript outline comes from the same
 * `buildChatOutline`. When those change on /chat, they change here.
 *
 * What is genuinely local to reading is the small part that is left: which
 * material is open, the passage the learner has selected, the conversations
 * linked as context, and a placeholder written against the page in view.
 *
 * It lives in its own file because the workspace shell around it is a view,
 * and a `test:node` rule holds that shell under 900 lines — the panel had
 * grown to a third of it.
 */

import dynamic from "next/dynamic";
import {
  BookmarkPlus,
  ChevronDown,
  ChevronLeft,
  Download,
  Highlighter,
  History,
  Link2,
  ListOrdered,
  MoreHorizontal,
  PanelRight,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatMessageList } from "@/features/chat/messages";
import { buildSessionActivity } from "@/components/chat/home/SessionActivityPanel";
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/SessionViewerPanel";
import { ChatViewerBridges } from "@/components/chat/home/ChatViewerBridges";
import Tooltip from "@/components/common/Tooltip";
import {
  type MessageAttachment,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import { useResearchOutlineContinuation } from "@/hooks/useResearchOutlineContinuation";
import { buildChatOutline, scrollToChatTurn } from "@/lib/chat-outline";
import { downloadChatMarkdown } from "@/lib/chat-export";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";
import { setReadingViewport } from "@/lib/reading-turn-state";
import { workspaceActionNeedsConfiguration } from "@/lib/workspace-mode";
import {
  fetchReadingAskHint,
  fetchReadingOpeners,
  type ReadingConversation,
  type ReadingLibraryMaterial,
} from "@/lib/reading-workspace-api";
import { ConversationMenu } from "./dialogs";
import { ReadingComposer } from "./ReadingComposer";
import { CompanionWelcome, MenuItem } from "./WorkspaceChrome";

const SaveToNotebookModal = dynamic(
  () => import("@/components/notebook/SaveToNotebookModal"),
  { ssr: false },
);

/** Which face the header's overflow menu is showing. */
type MenuView = "actions" | "turns";

export function ReadingCompanion({
  workspaceId,
  material,
  conversations,
  activeConversation,
  linkedSessionIds,
  activeLocator,
  selection,
  onClearSelection,
  onOpenLinker,
  onSelectConversation,
  onNewConversation,
  onRenameConversation,
  onDeleteConversation,
  onQuickPrompt,
  prefillInputRef,
  onClose,
}: {
  workspaceId: string;
  /** The material currently open in the reader, if any. */
  material: ReadingLibraryMaterial | null;
  conversations: ReadingConversation[];
  activeConversation: ReadingConversation | null;
  /** Conversations pinned as extra context for every turn. */
  linkedSessionIds: string[];
  /** Where the reader is, used to write a placeholder about this page. */
  activeLocator: number;
  selection: { quote: string; locator: number } | null;
  onClearSelection: () => void;
  onOpenLinker: () => void;
  onSelectConversation: (sessionId: string) => void | Promise<void>;
  onNewConversation: () => void;
  onRenameConversation: (conversation: ReadingConversation) => void;
  onDeleteConversation: (conversation: ReadingConversation) => void;
  /** Send a guided one-click prompt without touching the composer's text. */
  onQuickPrompt: (prompt: string) => void;
  prefillInputRef: React.MutableRefObject<((text: string) => void) | null>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const {
    state,
    submitUserReply,
    regenerateLastMessage,
    deleteTurn,
    editMessage,
    switchBranch,
    loadMessageTrace,
    releaseMessageTrace,
  } = useChatStateAdapter();
  const confirmResearchOutline = useResearchOutlineContinuation();

  const [showSessions, setShowSessions] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuView, setMenuView] = useState<MenuView>("actions");
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const viewerPanelRef = useRef<SessionViewerPanelHandle | null>(null);

  // Attachment cards were rendered without a click handler here, so a
  // generated file or image in the transcript simply did nothing when
  // clicked. The viewer panel below is already mounted; this opens the
  // attachment in it, the same way chat does.
  const handlePreviewMessageAttachment = useCallback(
    (attachment: MessageAttachment) => {
      viewerPanelRef.current?.openFileTab(attachment);
    },
    [],
  );

  const closeMenu = useCallback(() => {
    setMenuOpen(false);
    setMenuView("actions");
  }, []);

  const handleWelcomeAction = useCallback(
    (prompt: string) => {
      if (workspaceActionNeedsConfiguration(state.activeCapability)) {
        prefillInputRef.current?.(prompt);
        return;
      }
      onQuickPrompt(prompt);
    },
    [onQuickPrompt, prefillInputRef, state.activeCapability],
  );

  /* ── Transcript scrolling ────────────────────────────────────────────
     The pin-to-bottom hook /chat uses. The companion used to be a bare
     `overflow-y-auto`, so a streaming reply grew below the fold while the
     viewport sat still and the answer looked like it had stopped. */
  const { ref: composerBoxRef, height: composerHeight } =
    useMeasuredHeight<HTMLDivElement>();
  const lastMessage = state.messages[state.messages.length - 1];
  const {
    containerRef: messagesContainerRef,
    endRef: messagesEndRef,
    shouldAutoScrollRef,
    handleScroll: handleMessagesScroll,
  } = useChatAutoScroll({
    hasMessages: state.messages.length > 0,
    isStreaming: state.isStreaming,
    composerHeight,
    messageCount: state.messages.length,
    lastMessageContent: lastMessage?.content,
    lastEventCount: lastMessage?.events?.length,
  });

  // Binding a session id mid-answer changes the URL from `/reading/<ws>` to
  // `/reading/<ws>/sessions/<id>`, which remounts this panel: the new instance
  // inherits a turn that is already streaming, but its scrollport starts at
  // the top, so the reply the learner just asked for renders below the fold.
  // Arming the pin at the start of every turn is right on its own terms too —
  // asking a question is the clearest possible "show me the answer".
  useEffect(() => {
    if (!state.isStreaming) return;
    shouldAutoScrollRef.current = true;
    const container = messagesContainerRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messagesContainerRef, shouldAutoScrollRef, state.isStreaming]);

  /* ── Going back through a long conversation ──────────────────────────
     Same model as /chat's turn rail, different presentation: that rail
     needs a 52 px gutter it will never get in a 380 px panel, so the
     questions are listed in the header menu instead. */
  const chatOutline = useMemo(
    () => buildChatOutline(state.messages, state.selectedBranches),
    [state.messages, state.selectedBranches],
  );

  const jumpToTurn = useCallback(
    (key: string) => {
      const container = messagesContainerRef.current;
      if (scrollToChatTurn(container, key, { topOffset: 12 })) {
        // Release the pin, or the next streamed delta snaps the reader back.
        shouldAutoScrollRef.current = false;
      }
    },
    [messagesContainerRef, shouldAutoScrollRef],
  );

  /* ── The line above the composer ─────────────────────────────────────
     Written by the task model against this material, this page and the
     last exchange — a question the learner could ask, never an answer.
     Empty means "keep the static placeholder", which is also what every
     failure produces, so nothing on screen ever waits for this. */
  const [askHint, setAskHint] = useState("");
  const messageCount = state.messages.length;
  useEffect(() => {
    if (!workspaceId) return;
    const controller = new AbortController();
    let cancelled = false;
    void fetchReadingAskHint(
      workspaceId,
      {
        sessionId: state.sessionId || "",
        locator: activeLocator,
        selection: selection?.quote || "",
      },
      { signal: controller.signal },
    ).then((hint) => {
      if (!cancelled) setAskHint(hint);
    });
    return () => {
      cancelled = true;
      controller.abort();
    };
    // Re-asked when the conversation moves or the reader does: those are
    // exactly the moments a different question becomes worth offering.
  }, [
    activeLocator,
    messageCount,
    selection?.quote,
    state.sessionId,
    workspaceId,
  ]);

  /* ── What an empty conversation offers ───────────────────────────────
     Only fetched while there is nothing to show, and only re-fetched when
     the material or the page changes: these open a conversation, they do
     not follow one. */
  const [openers, setOpeners] = useState<string[]>([]);
  const hasMessages = messageCount > 0;
  useEffect(() => {
    if (!workspaceId || hasMessages) return;
    const controller = new AbortController();
    let cancelled = false;
    void fetchReadingOpeners(workspaceId, activeLocator, {
      signal: controller.signal,
    }).then((lines) => {
      if (!cancelled) setOpeners(lines);
    });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [activeLocator, hasMessages, workspaceId]);

  /* ── Session-level actions, the same three /chat puts in its header ── */
  const { modalMessages: chatSaveMessages, payload: chatSavePayload } =
    useMemo(
      () =>
        buildConversationNotebookSave(state.messages, {
          source: "immersive_reading",
          fallbackTitle: material?.title || "Reading conversation",
          activeCapability: state.activeCapability,
          language: state.language,
          sessionId: state.sessionId,
        }),
      [
        material?.title,
        state.activeCapability,
        state.language,
        state.messages,
        state.sessionId,
      ],
    );

  const sessionActivity = useMemo(
    () => buildSessionActivity(state.messages),
    [state.messages],
  );

  const copyAssistantMessage = useCallback(async (content: string) => {
    await navigator.clipboard.writeText(content);
  }, []);

  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex w-[min(420px,100%)] min-h-0 min-w-0 flex-col bg-[var(--card)] shadow-[-18px_0_42px_rgba(0,0,0,.12)] dark:bg-[var(--background)] xl:static xl:w-auto xl:shadow-none">
      <div className="relative flex h-11 shrink-0 items-center gap-2.5 border-b border-[var(--border)] px-4 dark:border-[var(--border)]">
        <div className="min-w-0 flex-1">
          <p className="font-serif text-[13px] font-semibold leading-tight text-[var(--foreground)]">
            {t("Reading companion")}
          </p>
          {/* A material's own title, not a label: upper-casing it would
              rewrite a book name and destroy a CJK one. */}
          <p className="truncate text-[10.5px] text-[var(--muted-foreground)]">
            {material?.title || t("Grounded in your materials")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Tooltip
            label={
              activeConversation
                ? t("Link earlier reading conversations")
                : t(
                    "Send a message first, then link earlier reading conversations",
                  )
            }
          >
            <button
              type="button"
              onClick={onOpenLinker}
              disabled={!activeConversation}
              aria-label={t("Link earlier reading conversations")}
              className={`relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-90 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent ${
                linkedSessionIds.length
                  ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
              }`}
            >
              <Link2 size={14} strokeWidth={1.7} />
              {linkedSessionIds.length > 0 && (
                <span className="absolute right-0.5 top-0.5 flex size-[13px] items-center justify-center rounded-full bg-[var(--primary)] text-[8px] font-semibold leading-none text-[var(--primary-foreground)]">
                  {linkedSessionIds.length}
                </span>
              )}
            </button>
          </Tooltip>
          <Tooltip label={t("Reading conversations")} suppressed={showSessions}>
            <button
              type="button"
              onClick={() => setShowSessions((current) => !current)}
              aria-label={t("Reading conversations")}
              aria-expanded={showSessions}
              className={`inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[10px] font-medium transition-[background-color,color,transform] duration-150 active:scale-95 ${
                showSessions
                  ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
              }`}
            >
              <History size={13} strokeWidth={1.7} />
              <ChevronDown
                size={10}
                className={`transition-transform duration-150 ${showSessions ? "rotate-180" : ""}`}
              />
            </button>
          </Tooltip>
          <Tooltip label={t("Conversation actions")} suppressed={menuOpen}>
            <button
              type="button"
              onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}
              aria-label={t("Conversation actions")}
              aria-expanded={menuOpen}
              className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-[background-color,color,transform] duration-150 active:scale-90 ${
                menuOpen
                  ? "bg-[var(--primary)]/10 text-[var(--primary)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)]"
              }`}
            >
              <MoreHorizontal size={14} strokeWidth={1.7} />
            </button>
          </Tooltip>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-[background-color,color,transform] duration-150 hover:bg-[var(--muted)]/55 hover:text-[var(--foreground)] active:scale-90 xl:hidden"
          aria-label={t("Close reading companion")}
        >
          <X size={14} strokeWidth={1.7} />
        </button>

        {menuOpen && (
          <>
            {/* Click-away is a full-viewport catcher rather than a blur
                handler: the items are buttons, and blur fires before their
                click lands. */}
            <div className="fixed inset-0 z-40" onClick={closeMenu} />
            <div className="absolute right-2 top-10 z-50 w-60 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-1.5 text-[11px] shadow-[0_20px_50px_rgba(0,0,0,.18)] dark:border-[var(--border)] dark:bg-[var(--popover)]">
              {menuView === "actions" ? (
                <>
                  <MenuItem
                    icon={BookmarkPlus}
                    label={t("Save to Notebook")}
                    onClick={() => {
                      closeMenu();
                      if (chatSavePayload) setShowSaveModal(true);
                    }}
                  />
                  <MenuItem
                    icon={Download}
                    label={t("Download Markdown")}
                    onClick={() => {
                      closeMenu();
                      if (!state.messages.length) return;
                      downloadChatMarkdown(state.messages, {
                        title:
                          activeConversation?.title ||
                          material?.title ||
                          t("Reading conversation"),
                      });
                    }}
                  />
                  <MenuItem
                    icon={PanelRight}
                    label={t("Activity")}
                    onClick={() => {
                      closeMenu();
                      setViewerOpen(true);
                    }}
                  />
                  {chatOutline.length > 1 && (
                    <MenuItem
                      icon={ListOrdered}
                      label={t("Jump to a question")}
                      onClick={() => setMenuView("turns")}
                    />
                  )}
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => setMenuView("actions")}
                    className="flex w-full items-center gap-1.5 rounded-md px-2.5 py-2 text-left text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
                  >
                    <ChevronLeft size={11} />
                    {t("Jump to a question")}
                  </button>
                  <div className="max-h-64 overflow-y-auto">
                    {chatOutline.map((entry) => (
                      <button
                        key={entry.key}
                        type="button"
                        onClick={() => {
                          closeMenu();
                          jumpToTurn(entry.key);
                        }}
                        className="flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left transition hover:bg-[var(--muted)]"
                      >
                        <span className="mt-[1px] shrink-0 text-[9px] tabular-nums text-[var(--muted-foreground)]">
                          {entry.ordinal}
                        </span>
                        <span className="line-clamp-2 min-w-0 flex-1 text-[10.5px] leading-relaxed text-[var(--foreground)]">
                          {entry.title}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </>
        )}

        {showSessions && (
          <ConversationMenu
            conversations={conversations}
            activeSessionId={state.sessionId}
            onSelect={async (sessionId) => {
              setShowSessions(false);
              await onSelectConversation(sessionId);
            }}
            onNew={() => {
              setShowSessions(false);
              onNewConversation();
            }}
            onRename={(row) => {
              setShowSessions(false);
              onRenameConversation(row);
            }}
            onDelete={(row) => {
              setShowSessions(false);
              onDeleteConversation(row);
            }}
          />
        )}
      </div>

      <div
        ref={messagesContainerRef}
        // Opts this scrollport into the global `overflow-anchor: none` rule;
        // without it the browser's own scroll anchoring fights the pin every
        // time a code block or KaTeX span reflows.
        data-chat-scroll-root="true"
        onScroll={() => {
          const container = messagesContainerRef.current;
          if (!container) return;
          const distanceFromBottom =
            container.scrollHeight -
            container.scrollTop -
            container.clientHeight;
          // Arm-only while streaming: the exported handler decides "did the
          // user move?" by distance-from-bottom alone, a fine proxy in a
          // 960px column but not in this 380px one — a single paragraph
          // reflowing mid-answer can clear 80px with no user intent at all,
          // and using that to RELEASE the pin mid-turn used to kill it
          // halfway through a reply. Confirming the user scrolled back near
          // the bottom is safe either way, though — that's a real "let me
          // keep following" signal regardless of column width — so only that
          // direction runs unconditionally; releasing on distance alone
          // waits for the turn to finish (a gesture already releases it
          // instantly and unconditionally, inside the hook itself).
          if (distanceFromBottom < 80) {
            shouldAutoScrollRef.current = true;
          } else if (!state.isStreaming) {
            handleMessagesScroll();
          }
        }}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4 [scrollbar-gutter:stable]"
      >
        {state.messages.length ? (
          <ChatMessageList
            messages={state.messages}
            isStreaming={state.isStreaming}
            sessionId={state.sessionId}
            language={state.language}
            onCopyAssistantMessage={copyAssistantMessage}
            onRegenerateMessage={regenerateLastMessage}
            onDeleteTurn={deleteTurn}
            selectedBranches={state.selectedBranches}
            onEditMessage={editMessage}
            onSwitchBranch={switchBranch}
            onSubmitUserReply={submitUserReply}
            onConfirmOutline={confirmResearchOutline}
            onPreviewAttachment={handlePreviewMessageAttachment}
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
        ) : (
          <CompanionWelcome
            title={material?.title ?? ""}
            onAction={handleWelcomeAction}
            suggestions={openers}
          />
        )}
        <div ref={messagesEndRef} className="h-px" />
      </div>

      <div
        ref={composerBoxRef}
        className="shrink-0 border-t border-[var(--border)] bg-[var(--card)] pt-3 dark:border-[var(--border)] dark:bg-[var(--secondary)]"
      >
        {selection && (
          <div className="mx-4 mb-2 flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-2.5 py-2 dark:border-[var(--border)] dark:bg-[var(--card)]">
            <Highlighter
              size={12}
              className="mt-0.5 shrink-0 text-[var(--primary)]"
            />
            <p className="line-clamp-2 min-w-0 flex-1 text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
              {selection.quote}
            </p>
            <button
              type="button"
              onClick={() => {
                onClearSelection();
                setReadingViewport({ selection: "" });
              }}
            >
              <X size={10} />
            </button>
          </div>
        )}
        {!!linkedSessionIds.length && (
          <div className="mx-4 mb-2 flex items-center gap-1.5 text-[10px] text-[var(--muted-foreground)]">
            <Link2 size={10} />
            {t("Using {{count}} linked conversations as context", {
              count: linkedSessionIds.length,
            })}
          </div>
        )}
        <ReadingComposer
          // The offered question *is* the placeholder, and Tab takes it. When
          // there is none, the static line stands.
          placeholder={askHint || t("Ask about this material…")}
          placeholderCompletion={askHint}
          selection={selection}
          onSent={onClearSelection}
          linkedSessionIds={linkedSessionIds}
          prefillInputRef={prefillInputRef}
        />
      </div>

      <SaveToNotebookModal
        open={showSaveModal}
        payload={chatSavePayload}
        messages={chatSaveMessages}
        onClose={() => setShowSaveModal(false)}
      />

      {/* Fixed right-hand drawer, the same component /chat opens. It overlays
          the companion rather than squeezing it: at this width a third column
          would leave nothing readable. */}
      <SessionViewerPanel
        ref={viewerPanelRef}
        open={viewerOpen}
        sessionId={state.sessionId}
        activity={sessionActivity}
        onClose={() => setViewerOpen(false)}
        onAutoOpen={() => setViewerOpen(true)}
      />
      <ChatViewerBridges viewerPanelRef={viewerPanelRef} />
    </aside>
  );
}
