"use client";

import { browserStorage } from "@/shared/storage";

import dynamic from "next/dynamic";
import Link from "next/link";
import {
  ArrowLeft,
  BookmarkPlus,
  Compass,
  Flag,
  Loader2,
  Map as MapIcon,
  MessageCircle,
  PanelRight,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatMessageList } from "@/features/chat/messages";
import { ChatViewerBridges } from "@/components/chat/home/ChatViewerBridges";
import { buildSessionActivity } from "@/components/chat/home/SessionActivityPanel";
import { TurnNavigator } from "@/components/chat/home/TurnNavigator";
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/SessionViewerPanel";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMasteryStudySession } from "@/hooks/useMasteryStudySession";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import { useResearchOutlineContinuation } from "@/hooks/useResearchOutlineContinuation";
import { fetchMasteryAskHint, type MasteryTopic } from "@/lib/learning-api";
import { consumePendingPrompt } from "@/lib/pending-prompt";
import { buildChatOutline, scrollToChatTurn } from "@/lib/chat-outline";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";
import { workspaceActionNeedsConfiguration } from "@/lib/workspace-mode";

import { topicDisplayName, type Translate } from "./format";
import { LevelUpCelebration } from "./LevelUpCelebration";
import { MasteryComposer } from "./MasteryComposer";
import { ProgressRing } from "./ProgressRing";
import { StudyOutline } from "./StudyOutline";

const OUTLINE_STORAGE_KEY = "dt.mastery.outline";

const SaveToNotebookModal = dynamic(
  () => import("@/components/notebook/SaveToNotebookModal"),
  { ssr: false },
);

const STARTERS = [
  { icon: Compass, key: "Start with a quick check of what I already know" },
  { icon: Sparkles, key: "Teach me from intuition and one concrete example" },
  { icon: Flag, key: "Give me a challenging question right away" },
] as const;

/**
 * Where the tutor is. The id matters as much as the name: the outline
 * highlights by id, so two knowledge points that happen to share a name
 * can no longer both light up.
 */
function currentWaypoint(topic: MasteryTopic, fallback: string, t: Translate) {
  if (topic.next.knowledge_point_name) {
    return {
      id: topic.next.knowledge_point_id,
      name: topic.next.knowledge_point_name,
    };
  }
  for (const region of topic.map.modules) {
    const point = region.knowledge_points.find(
      (item) => item.status !== "mastered",
    );
    if (point) return { id: point.id, name: point.name };
  }
  return {
    id: "",
    name: topic.map.complete ? t("All complete") : fallback,
  };
}

export function MasteryStudy({
  pathId,
  routeSessionId,
  courseId = "",
}: {
  pathId: string;
  routeSessionId?: string;
  courseId?: string;
}) {
  const { t } = useTranslation();
  const {
    state,
    sendMessage,
    submitUserReply,
    regenerateLastMessage,
    deleteTurn,
    editMessage,
    switchBranch,
  } = useChatStateAdapter();
  const confirmResearchOutline = useResearchOutlineContinuation();
  const { topic, topicError, knowledgeBases, sessionError, sessionLoading } =
    useMasteryStudySession(pathId, routeSessionId, courseId);
  const hasMessages = state.messages.length > 0;
  const prefillInputRef = useRef<((text: string) => void) | null>(null);
  const viewerPanelRef = useRef<SessionViewerPanelHandle | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const sessionActivity = buildSessionActivity(state.messages);
  /* ── Transcript scrolling ────────────────────────────────────────────
     Was a bare `scrollIntoView` keyed on message count — no notion of the
     user having scrolled away, so it yanked the view back to the bottom
     on every delta regardless. See ReadingCompanion for the same wiring. */
  const { ref: composerBoxRef, height: composerHeight } =
    useMeasuredHeight<HTMLDivElement>();
  const lastMessage = state.messages[state.messages.length - 1];
  const {
    containerRef: messagesContainerRef,
    endRef: messagesEndRef,
    shouldAutoScrollRef,
    scrollToBottom,
    handleScroll: handleMessagesScroll,
  } = useChatAutoScroll({
    hasMessages,
    isStreaming: state.isStreaming,
    composerHeight,
    messageCount: state.messages.length,
    lastMessageContent: lastMessage?.content,
    lastEventCount: lastMessage?.events?.length,
  });
  const chatOutline = useMemo(
    () => buildChatOutline(state.messages, state.selectedBranches),
    [state.messages, state.selectedBranches],
  );
  const jumpToTurn = useCallback(
    (key: string) => {
      if (
        scrollToChatTurn(messagesContainerRef.current, key, {
          topOffset: 56,
          flash: true,
        })
      ) {
        shouldAutoScrollRef.current = false;
      }
    },
    [messagesContainerRef, shouldAutoScrollRef],
  );
  const resumeFollowingLatest = useCallback(() => {
    shouldAutoScrollRef.current = true;
    scrollToBottom("instant");
  }, [scrollToBottom, shouldAutoScrollRef]);

  const notebookFallbackTitle = topic
    ? topicDisplayName(topic, t)
    : t("Mastery Path");
  const { modalMessages: notebookSaveMessages, payload: notebookSavePayload } =
    useMemo(
      () =>
        buildConversationNotebookSave(state.messages, {
          source: "mastery_path",
          fallbackTitle: notebookFallbackTitle,
          activeCapability: state.activeCapability,
          language: state.language,
          sessionId: state.sessionId,
        }),
      [
        notebookFallbackTitle,
        state.activeCapability,
        state.language,
        state.messages,
        state.sessionId,
      ],
    );
  // A new turn is the clearest possible "show me the answer" — re-arm the
  // pin even if a previous turn's browsing had released it.
  useEffect(() => {
    if (!state.isStreaming) return;
    shouldAutoScrollRef.current = true;
    const container = messagesContainerRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messagesContainerRef, shouldAutoScrollRef, state.isStreaming]);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  // Reading a conversation and consulting the map are different moments, so
  // the rail is dismissible — and the choice sticks, since a learner who
  // wants the width wants it on every session, not just this one.
  const [outlineOpen, setOutlineOpen] = useState(true);
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOutlineOpen(
        browserStorage.readRaw("local", OUTLINE_STORAGE_KEY) !== "0",
      );
    } catch {
      // Private mode / blocked storage: the default (open) stands.
    }
  }, []);
  const toggleOutline = useCallback(() => {
    setOutlineOpen((open) => {
      const next = !open;
      try {
        browserStorage.writeRaw("local", OUTLINE_STORAGE_KEY, next ? "1" : "0");
      } catch {
        // Preference is best-effort; the session still honours the toggle.
      }
      return next;
    });
  }, []);

  // A Course Study hand-off may have written the opening line before sending
  // the learner here. Consumed once, so a refresh does not retype it — but
  // held until the composer exists: on the first render this screen is still
  // waiting on the topic and has nothing to type into.
  useEffect(() => {
    const pending = consumePendingPrompt("mastery_path");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (pending) setPendingPrompt(pending);
  }, []);

  useEffect(() => {
    if (!pendingPrompt || !prefillInputRef.current) return;
    prefillInputRef.current(pendingPrompt);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPendingPrompt(null);
  }, [pendingPrompt, topic, sessionError, sessionLoading]);

  // A question worth asking here, written by the task model. Fetched when the
  // turn settles rather than as it streams: what is worth asking next depends
  // on what the tutor just finished saying. The composer is fully usable
  // meanwhile — this only ever replaces a placeholder, so a slow or failed
  // call costs nothing but the offer.
  const [askHint, setAskHint] = useState("");
  useEffect(() => {
    if (state.isStreaming || sessionLoading || sessionError) return;
    let cancelled = false;
    void fetchMasteryAskHint(pathId, state.sessionId ?? "")
      .then((hint) => {
        if (!cancelled) setAskHint(hint);
      })
      .catch(() => {
        // Keep whatever is showing; the static placeholder is a fine floor.
      });
    return () => {
      cancelled = true;
    };
  }, [
    pathId,
    sessionError,
    sessionLoading,
    state.isStreaming,
    state.messages.length,
    state.sessionId,
  ]);

  // A point crossing into "mastered" is the one real payoff this screen
  // offers, and the backend does not emit a "just mastered" event to key
  // off — every mastery write lands as the same generic revision bump.
  // Diffing status transitions on each refetch catches it regardless of
  // *why* the map changed: the tutor's grade tool, a learner's own
  // override, a stale poll finally catching up.
  const priorPointStatusRef = useRef<Map<string, string> | null>(null);
  const celebrationCounterRef = useRef(0);
  const [celebration, setCelebration] = useState<{
    key: number;
    pointId: string;
  } | null>(null);
  useEffect(() => {
    if (!topic) return;
    const nextStatus = new Map<string, string>();
    for (const region of topic.map.modules) {
      for (const point of region.knowledge_points) {
        nextStatus.set(point.id, point.status);
      }
    }
    const priorStatus = priorPointStatusRef.current;
    priorPointStatusRef.current = nextStatus;
    if (!priorStatus) return;
    for (const region of topic.map.modules) {
      for (const point of region.knowledge_points) {
        const before = priorStatus.get(point.id);
        if (before && before !== "mastered" && point.status === "mastered") {
          celebrationCounterRef.current += 1;
          setCelebration({
            key: celebrationCounterRef.current,
            pointId: point.id,
          });
          return;
        }
      }
    }
  }, [topic]);

  const submit = useCallback(
    (value: string) => {
      const content = value.trim();
      if (!content || state.isStreaming || sessionLoading || sessionError)
        return;
      sendMessage(content);
    },
    [sendMessage, sessionError, sessionLoading, state.isStreaming],
  );

  const startFromPrompt = useCallback(
    (prompt: string) => {
      if (workspaceActionNeedsConfiguration(state.activeCapability)) {
        prefillInputRef.current?.(prompt);
        return;
      }
      submit(prompt);
    },
    [state.activeCapability, submit],
  );

  const copyAssistantMessage = useCallback(async (content: string) => {
    if (content.trim()) await navigator.clipboard.writeText(content);
  }, []);

  if (!topic && !topicError) {
    return (
      <div className="mastery-shell flex h-full items-center justify-center text-[var(--muted-foreground)]">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (!topic) {
    return (
      <div className="mastery-shell flex h-full flex-col items-center justify-center px-6 text-center">
        <MapIcon className="h-10 w-10 text-[var(--muted-foreground)] opacity-40" />
        <h1 className="mt-4 text-lg font-semibold">
          {t("This learning map could not be found")}
        </h1>
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">
          {topicError}
        </p>
        <Link
          href="/mastery"
          className="mt-5 text-sm font-medium text-[var(--primary)] hover:underline"
        >
          {t("Back to topics")}
        </Link>
      </div>
    );
  }

  const displayName = topicDisplayName(topic, t);
  const waypoint = currentWaypoint(topic, displayName, t);
  const completed = topic.map.counts.mastered;
  const total = topic.map.counts.total;

  return (
    <main className="mastery-shell flex h-full min-h-0 flex-col overflow-hidden">
      {/* One line, not two: the topic and the waypoint the tutor is on read
          as a single "where am I" statement, and the ring + count are one
          unit rather than a ring on the left and its own number on the
          right saying the same thing twice. */}
      <header className="flex h-[56px] shrink-0 items-center gap-1 border-b border-[var(--border)] bg-[var(--background)]/95 px-3 backdrop-blur sm:px-4">
        <Link
          href={`/mastery/${encodeURIComponent(pathId)}`}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
          title={t("Learning topics")}
          aria-label={t("Learning topics")}
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>

        <div className="ml-1.5 flex min-w-0 flex-1 items-baseline gap-2">
          <h1 className="shrink-0 truncate text-[14.5px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
            {displayName}
          </h1>
          <span
            aria-hidden="true"
            className="hidden shrink-0 text-[var(--muted-foreground)]/40 sm:inline"
          >
            /
          </span>
          <span className="hidden min-w-0 truncate text-[12.5px] text-[var(--muted-foreground)] sm:inline">
            {waypoint.name}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-1.5 pl-2">
          <button
            type="button"
            onClick={() => setShowSaveModal(true)}
            disabled={!notebookSavePayload}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
            title={t("Save to Notebook")}
            aria-label={t("Save to Notebook")}
          >
            <BookmarkPlus className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setViewerOpen((open) => !open)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
            aria-label={t("Activity")}
            aria-pressed={viewerOpen}
          >
            <PanelRight className="h-4 w-4" />
          </button>
          <ProgressRing
            value={total ? completed / total : 0}
            size={18}
            stroke={2}
            showLabel={false}
          />
          <span className="text-[12px] tabular-nums text-[var(--muted-foreground)]">
            {completed}/{total}
          </span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside
          className={`hidden shrink-0 overflow-y-auto border-r border-[var(--border)] bg-[var(--card)]/30 transition-[width] duration-200 xl:block ${
            outlineOpen ? "w-[252px] px-5 py-5" : "w-9"
          }`}
        >
          <StudyOutline
            topic={topic}
            currentPointId={waypoint.id}
            justMasteredId={celebration?.pointId ?? null}
            collapsed={!outlineOpen}
            onToggleCollapsed={toggleOutline}
          />
        </aside>

        <section className="flex min-w-0 flex-1 flex-col bg-[var(--background)]">
          <div className="relative min-h-0 flex-1">
            <div
              ref={messagesContainerRef}
              // Opts this scrollport into the global `overflow-anchor: none`
              // rule; without it the browser's own scroll anchoring fights
              // the pin every time a code block or KaTeX span reflows.
              data-chat-scroll-root="true"
              onScroll={() => {
                const container = messagesContainerRef.current;
                if (!container) return;
                const distanceFromBottom =
                  container.scrollHeight -
                  container.scrollTop -
                  container.clientHeight;
                // Arm-only while streaming: position alone should never
                // RELEASE the pin mid-turn (a gesture already does that,
                // unconditionally, inside the hook) — only ever confirm the
                // user scrolled back down to resume following.
                if (distanceFromBottom < 80) {
                  shouldAutoScrollRef.current = true;
                } else if (!state.isStreaming) {
                  handleMessagesScroll();
                }
              }}
              className="h-full overflow-y-auto [scrollbar-gutter:stable]"
            >
              <div
                data-chat-column="true"
                className="mx-auto w-full max-w-[900px] px-4 pb-8 pt-7 sm:px-7"
              >
                {sessionLoading ? (
                  <div className="flex min-h-[45vh] flex-col items-center justify-center text-sm text-[var(--muted-foreground)]">
                    <Loader2 className="mb-3 h-5 w-5 animate-spin" />
                    {t("Reopening this session…")}
                  </div>
                ) : sessionError ? (
                  <div className="mx-auto mt-20 max-w-md rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center">
                    <MessageCircle className="mx-auto h-8 w-8 text-red-500/60" />
                    <h2 className="mt-3 text-sm font-semibold">
                      {t("The session did not open")}
                    </h2>
                    <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">
                      {sessionError}
                    </p>
                    <Link
                      href={`/mastery/${encodeURIComponent(pathId)}/sessions`}
                      className="mt-4 inline-flex rounded-xl bg-[var(--primary)] px-3 py-2 text-xs font-medium text-[var(--primary-foreground)]"
                    >
                      {t("Start a new session")}
                    </Link>
                  </div>
                ) : !hasMessages ? (
                  <div className="mx-auto flex min-h-[54vh] max-w-2xl flex-col items-center justify-center text-center">
                    <div className="text-[12px] text-[var(--muted-foreground)]">
                      {t("Next up")}
                    </div>
                    <h2 className="mt-1.5 font-serif text-[20px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
                      {waypoint.name}
                    </h2>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted-foreground)]">
                      {t(
                        "Your tutor adapts to your answers. Begin with a quick check, an intuitive explanation, or a challenge.",
                      )}
                    </p>
                    <div className="mt-7 grid w-full gap-2 sm:grid-cols-3">
                      {STARTERS.map((starter) => {
                        const Icon = starter.icon;
                        const label = t(starter.key);
                        return (
                          <button
                            key={starter.key}
                            type="button"
                            onClick={() => startFromPrompt(label)}
                            disabled={state.isStreaming || sessionLoading}
                            className="group rounded-lg border border-[var(--border)] bg-[var(--card)] p-4 text-left transition hover:-translate-y-0.5 hover:border-[var(--primary)]/35 disabled:opacity-50"
                          >
                            <Icon className="h-4 w-4 text-[var(--primary)]" />
                            <span className="mt-3 block text-xs font-medium leading-5 text-[var(--foreground)]">
                              {label}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-9">
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
                      availableKbNames={new Set(knowledgeBases)}
                      showModeBadge={false}
                    />
                  </div>
                )}
                <div ref={messagesEndRef} className="h-px" />
              </div>
            </div>
            <TurnNavigator
              entries={chatOutline}
              scrollRootRef={messagesContainerRef}
              onJump={jumpToTurn}
              onJumpToBottom={resumeFollowingLatest}
            />
          </div>

          {!sessionError && (
            <div
              ref={composerBoxRef}
              className="shrink-0 bg-[var(--background)]"
            >
              <MasteryComposer
                placeholder={t("Ask your tutor about “{{waypoint}}”…", {
                  waypoint: waypoint.name,
                })}
                askHint={askHint}
                disabled={sessionLoading}
                prefillInputRef={prefillInputRef}
              />
            </div>
          )}
        </section>
      </div>

      {celebration && (
        <LevelUpCelebration
          key={celebration.key}
          onDone={() => setCelebration(null)}
        />
      )}
      <SaveToNotebookModal
        open={showSaveModal}
        payload={notebookSavePayload}
        messages={notebookSaveMessages}
        onClose={() => setShowSaveModal(false)}
      />
      <SessionViewerPanel
        ref={viewerPanelRef}
        open={viewerOpen}
        sessionId={state.sessionId}
        activity={sessionActivity}
        onClose={() => setViewerOpen(false)}
        onAutoOpen={() => setViewerOpen(true)}
      />
      <ChatViewerBridges viewerPanelRef={viewerPanelRef} />
    </main>
  );
}
