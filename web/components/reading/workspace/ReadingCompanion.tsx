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
  Download,
  Link2,
  ListOrdered,
  PanelRight,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatMessageList } from "@/features/chat/messages";
import { buildSessionActivity } from "@/components/chat/home/SessionActivityPanel";
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/SessionViewerPanel";
import { ChatViewerBridges } from "@/components/chat/home/ChatViewerBridges";
import {
  type MessageAttachment,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import { useResearchOutlineContinuation } from "@/hooks/useResearchOutlineContinuation";
import { buildChatOutline, scrollToChatTurn } from "@/lib/chat-outline";
import { downloadChatMarkdown } from "@/lib/chat-export";
import { copyText } from "@/lib/clipboard";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";
import { setReadingViewport } from "@/lib/reading-turn-state";
import {
  fetchReadingAskHint,
  type ReadingConversation,
  type ReadingLibraryMaterial,
} from "@/lib/reading-workspace-api";
import { READER_ASK_EVENT } from "@/components/reading/ReaderPane";
import {
  focusReadingComposer,
  useReadingActions,
  type ReadingActionCard,
} from "@/components/reading/reading-actions-context";
import { ReadingActionCards } from "./ReadingActionCards";
import { ReadingComposer } from "./ReadingComposer";
import { CompanionWelcome } from "./WorkspaceChrome";
import {
  useWorkspaceMenuSection,
  type WorkspaceMenuItem,
} from "@/components/reading/workspace-menu-context";

const SaveToNotebookModal = dynamic(
  () => import("@/components/notebook/SaveToNotebookModal"),
  { ssr: false },
);

const COMPOSER_FADE =
  "linear-gradient(to bottom, #000 calc(100% - 32px), transparent)";

export function ReadingCompanion({
  workspaceId,
  material,
  activeConversation,
  linkedSessionIds,
  activeLocator,
  selection,
  onClearSelection,
  onOpenLinker,
  prefillInputRef,
}: {
  workspaceId: string;
  /** The material currently open in the reader, if any. */
  material: ReadingLibraryMaterial | null;
  activeConversation: ReadingConversation | null;
  /** Conversations pinned as extra context for every turn. */
  linkedSessionIds: string[];
  /** Where the reader is, used to write a placeholder about this page. */
  activeLocator: number;
  selection: { quote: string; locator: number } | null;
  onClearSelection: () => void;
  onOpenLinker: () => void;
  prefillInputRef: React.MutableRefObject<((text: string) => void) | null>;
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

  const readingActions = useReadingActions();
  const [turnsOpen, setTurnsOpen] = useState(false);
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

  const closeTurns = useCallback(() => setTurnsOpen(false), []);

  // The list closes on a click-away catcher; Escape has to be wired
  // separately, or a keyboard user who opened it has no way back out.
  useEffect(() => {
    if (!turnsOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeTurns();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeTurns, turnsOpen]);

  // "Ask a follow-up" on a card: the passage it answered becomes the quoted
  // context of the next question, exactly as "Ask about this" does from the
  // document. A card with no passage (a quiz on the page) just focuses the box.
  const followUpCard = useCallback(
    (card: ReadingActionCard) => {
      if (card.quote) {
        window.dispatchEvent(
          new CustomEvent(READER_ASK_EVENT, {
            detail: { quote: card.quote, locator: card.locator },
          }),
        );
        return;
      }
      focusReadingComposer();
    },
    [],
  );
  const hasCards = Boolean(readingActions?.cards.length);

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

  const hasMessages = messageCount > 0;

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

  const downloadMarkdown = useCallback(() => {
    if (!state.messages.length) return;
    downloadChatMarkdown(state.messages, {
      title:
        activeConversation?.title ||
        material?.title ||
        t("Reading conversation"),
    });
  }, [activeConversation?.title, material?.title, state.messages, t]);

  // Handed to the workspace's single ⋯. Only the question list stays here: it
  // is a long, scrolling list, and it belongs over the conversation it jumps
  // through rather than under the top bar's corner.
  const menuItems = useMemo<WorkspaceMenuItem[]>(() => {
    const items: WorkspaceMenuItem[] = [
      {
        key: "save",
        icon: BookmarkPlus,
        label: t("Save to Notebook"),
        disabled: !chatSavePayload,
        onSelect: () => setShowSaveModal(true),
      },
      {
        key: "markdown",
        icon: Download,
        label: t("Download Markdown"),
        disabled: !hasMessages,
        onSelect: downloadMarkdown,
      },
      {
        key: "activity",
        icon: PanelRight,
        label: t("Activity"),
        onSelect: () => setViewerOpen(true),
      },
      {
        key: "link",
        icon: Link2,
        label: t("Link earlier reading conversations"),
        // A link is stored on the conversation, so there has to be one.
        hint: !activeConversation
          ? t("Send a message first, then link earlier reading conversations")
          : linkedSessionIds.length
            ? t("Using {{count}} linked conversations as context", {
                count: linkedSessionIds.length,
              })
            : undefined,
        disabled: !activeConversation,
        onSelect: onOpenLinker,
      },
    ];
    if (chatOutline.length > 1) {
      items.push({
        key: "turns",
        icon: ListOrdered,
        label: t("Jump to a question"),
        onSelect: () => setTurnsOpen(true),
      });
    }
    return items;
  }, [
    activeConversation,
    chatOutline.length,
    chatSavePayload,
    downloadMarkdown,
    hasMessages,
    linkedSessionIds.length,
    onOpenLinker,
    t,
  ]);
  useWorkspaceMenuSection("conversation", menuItems);

  const copyAssistantMessage = useCallback(
    (content: string) => copyText(content),
    [],
  );

  return (
    <aside className="absolute inset-y-0 right-0 z-30 flex w-[min(420px,100%)] min-h-0 min-w-0 flex-col bg-[var(--card)] shadow-[-18px_0_42px_rgba(0,0,0,.12)] dark:bg-[var(--background)] xl:static xl:w-auto xl:shadow-none">
      {/* No header of its own: the workspace bar above already names this
          column, and its actions live there (new conversation, quiz) or in
          the workspace ⋯ (save, export, link). The question list is the one
          thing that still opens here, over the conversation it jumps through. */}
      {turnsOpen && (
        <div className="relative z-50 h-0">
          <div className="fixed inset-0" onClick={closeTurns} />
          <div className="absolute right-2 top-2 w-60 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-1.5 text-[12px] shadow-[0_20px_50px_rgba(0,0,0,.18)] dark:border-[var(--border)] dark:bg-[var(--popover)]">
            <p className="flex w-full items-center gap-1.5 px-2.5 py-2 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
              <ListOrdered size={11} />
              {t("Jump to a question")}
            </p>
            <div className="max-h-64 overflow-y-auto">
              {chatOutline.map((entry) => (
                <button
                  key={entry.key}
                  type="button"
                  onClick={() => {
                    closeTurns();
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
          </div>
        </div>
      )}

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
        // No rule above the composer: the last lines fade out instead, so the
        // composer floats over the conversation as it does on /chat. The
        // bottom padding keeps that fade over empty space, not the last line.
        className="min-h-0 flex-1 overflow-y-auto px-4 pb-10 pt-4 [scrollbar-gutter:stable]"
        style={{
          WebkitMaskImage: COMPOSER_FADE,
          maskImage: COMPOSER_FADE,
        }}
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
        ) : hasCards ? null : (
          <CompanionWelcome hasMaterial={Boolean(material)} />
        )}
        <ReadingActionCards
          sessionId={state.sessionId}
          onFollowUp={followUpCard}
        />
        <div ref={messagesEndRef} className="h-px" />
      </div>

      <div
        ref={composerBoxRef}
        data-reading-composer=""
        className="shrink-0 pt-1"
      >
        {!!linkedSessionIds.length && (
          <div className="mx-4 mb-2 flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
            <Link2 size={11} />
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
          onRemoveSelection={() => {
            onClearSelection();
            setReadingViewport({ selection: "" });
          }}
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
