"use client";

import { browserStorage } from "@/shared/storage";

import dynamic from "next/dynamic";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
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
import {
  type MessageAttachment,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMasteryStudySession } from "@/hooks/useMasteryStudySession";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import { useResearchOutlineContinuation } from "@/hooks/useResearchOutlineContinuation";
import {
  fetchMasteryAskHint,
  setMasterySessionMode as setMasterySessionMode_api,
  type MasteryTopic,
} from "@/lib/learning-api";
import { notify } from "@/lib/notifications";
import { consumePendingPrompt } from "@/lib/pending-prompt";
import { buildChatOutline, scrollToChatTurn } from "@/lib/chat-outline";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";
import {
  MASTERY_OPENING_SCOPE,
  masteryOpeningMessage,
  masterySessionRoute,
  type MasteryMode,
} from "@/lib/mastery-mode";
import { workspaceActionNeedsConfiguration } from "@/lib/workspace-mode";

import { ActivityHeader } from "@/components/activity";

import { ModeSwitch } from "./ModeSwitch";
import { topicDisplayName, type Translate } from "./format";
import { LevelUpCelebration } from "./LevelUpCelebration";
import { MasteryComposer } from "./MasteryComposer";
import { ProgressRing } from "./ProgressRing";
import { StudyOutline } from "./StudyOutline";

const OUTLINE_STORAGE_KEY = "dt.mastery.outline";

/**
 * How each kind of session presents itself, and what it opens with.
 *
 * ``autoOpen`` is the message the screen sends on the learner's behalf. Only
 * the outline session has one, and it has one for a reason: arriving there is
 * not a choice the learner made from a menu — they pressed "design the outline
 * with the tutor" and were moved to a screen that, left alone, would sit empty
 * waiting for them to work out what to type. The work is already agreed; the
 * session should be doing it.
 */
const MODE_PRESENTATION: Record<
  MasteryMode,
  {
    /** One line under the header: what this mode is and is not. */
    noteKey: string;
    /** The empty conversation's heading and the line under it. */
    emptyTitleKey: string;
    emptyBodyKey: string;
  }
> = {
  outline: {
    noteKey: "Nothing is being taught yet — this mode agrees on what you will learn.",
    emptyTitleKey: "Design your outline",
    emptyBodyKey:
      "The tutor reads the materials you chose, asks what you already know, and proposes a route you can change.",
  },
  study: {
    noteKey: "",
    // Study's heading is the waypoint itself; these are only its body and
    // are never read for the title.
    emptyTitleKey: "",
    emptyBodyKey:
      "Your tutor adapts to your answers. Begin with a quick check, an intuitive explanation, or a challenge.",
  },
  review: {
    noteKey:
      "This mode re-tests what you have already learned. It will not teach anything new.",
    emptyTitleKey: "Go back over what you know",
    emptyBodyKey:
      "Review re-tests what you have already mastered. Due items come first, but you can revisit anything.",
  },
};

const SaveToNotebookModal = dynamic(
  () => import("@/components/notebook/SaveToNotebookModal"),
  { ssr: false },
);

/** Ways in, per mode. What "start" means is not the same in all three. */
const STARTERS: Record<
  MasteryMode,
  readonly { icon: typeof Compass; key: string }[]
> = {
  outline: [
    { icon: Compass, key: "Draft an outline from the materials I chose" },
    { icon: Sparkles, key: "Ask me a few things first, then propose an outline" },
    { icon: Flag, key: "I want to talk about how far I need to get" },
  ],
  study: [
    { icon: Compass, key: "Start with a quick check of what I already know" },
    { icon: Sparkles, key: "Teach me from intuition and one concrete example" },
    { icon: Flag, key: "Give me a challenging question right away" },
  ],
  review: [
    { icon: Compass, key: "Review what is due today" },
    { icon: Sparkles, key: "Go back over what I found hardest" },
    { icon: Flag, key: "Test me on everything I have mastered" },
  ],
};

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
  requestedMode = "study",
}: {
  pathId: string;
  routeSessionId?: string;
  courseId?: string;
  /** What a conversation opened here is for; ignored for an existing one. */
  requestedMode?: MasteryMode;
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
    loadMessageTrace,
    releaseMessageTrace,
    setMasterySessionMode,
  } = useChatStateAdapter();
  const confirmResearchOutline = useResearchOutlineContinuation();
  const {
    topic,
    topicError,
    knowledgeBases,
    sessionError,
    sessionLoading,
    sessionMode,
  } = useMasteryStudySession(
    pathId,
    routeSessionId,
    courseId,
    requestedMode,
  );
  const hasMessages = state.messages.length > 0;
  const prefillInputRef = useRef<((text: string) => void) | null>(null);
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
        return false;
      sendMessage(content);
      return true;
    },
    [sendMessage, sessionError, sessionLoading, state.isStreaming],
  );

  // Answering a question card starts the next turn: posing the question ended
  // the one that asked. Gated exactly like the composer, because a path admits
  // one live turn at a time — submitting into a running one is refused by the
  // backend, and returning ``false`` here reopens the card instead of showing
  // the learner that refusal.
  const answerMasteryQuestion = useCallback(
    (answer: { questionId: string; text: string }) => {
      const text = answer.text.trim();
      if (!text || state.isStreaming || sessionLoading || sessionError) {
        return false;
      }
      sendMessage(text, undefined, undefined, undefined, undefined, {
        masteryAnswer: { question_id: answer.questionId, text },
      });
      shouldAutoScrollRef.current = true;
      return true;
    },
    [
      sendMessage,
      sessionError,
      sessionLoading,
      shouldAutoScrollRef,
      state.isStreaming,
    ],
  );

  // Declining a question is a turn too: the engine holds one open question per
  // path, so a question left open is the one the tutor poses again next round.
  const skipMasteryQuestion = useCallback(
    (questionId: string) => {
      if (!questionId || state.isStreaming || sessionLoading || sessionError) {
        return false;
      }
      sendMessage(
        t("Let's skip this question."),
        undefined,
        undefined,
        undefined,
        undefined,
        { masterySkip: { question_id: questionId } },
      );
      shouldAutoScrollRef.current = true;
      return true;
    },
    [
      sendMessage,
      sessionError,
      sessionLoading,
      shouldAutoScrollRef,
      state.isStreaming,
      t,
    ],
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

  // A conversation that opens with nothing to say says the thing it was
  // opened to say.
  //
  // Derived from the mode rather than handed across the navigation. The
  // hand-off channel that used to carry it reads *destructively*, so a send
  // refused for any reason (a turn still settling, a session still resolving)
  // consumed the message and left the screen insisting work was under way
  // forever — the same dead end twice, in two different places. There is no
  // channel to lose now: an empty outline conversation always knows what it
  // is for. The hand-off is still read, but only to *enrich* the opening (the
  // review card names what is due), never to supply it.
  const openingSentRef = useRef("");
  useEffect(() => {
    if (!topic || hasMessages || sessionLoading || sessionError) return;
    if (state.isStreaming || openingSentRef.current === pathId) return;
    const opening =
      consumePendingPrompt(MASTERY_OPENING_SCOPE).trim() ||
      masteryOpeningMessage(sessionMode, t as Translate);
    // A study conversation opens with nothing on purpose: "start learning"
    // does not say what to start with, so the screen offers ways in instead.
    if (!opening) return;
    // Latch on the send, never before it: ``submit`` refuses silently while a
    // turn is live or the session is still resolving, and the next render
    // tries again.
    if (submit(opening)) openingSentRef.current = pathId;
  }, [
    hasMessages,
    pathId,
    sessionError,
    sessionLoading,
    sessionMode,
    state.isStreaming,
    submit,
    t,
    topic,
  ]);

  // The learner pressing one of the three modes above the transcript. The same
  // move the tutor makes with ``mastery_mode``, through the same admission
  // rule — so a refusal reads the same whoever asked for it.
  const [modeBusy, setModeBusy] = useState(false);
  const changeMode = useCallback(
    (next: MasteryMode) => {
      const sessionId = state.sessionId;
      if (!sessionId) {
        // Nothing has been said yet, so there is no conversation to record it
        // on. Keeping it locally is enough: the first turn carries it.
        setMasterySessionMode(next);
        return;
      }
      setModeBusy(true);
      void setMasterySessionMode_api(pathId, sessionId, next)
        .then(() => setMasterySessionMode(next))
        .catch((reason: unknown) => {
          notify(
            reason instanceof Error
              ? reason.message
              : t("The mode could not be changed"),
            { tone: "error" },
          );
        })
        .finally(() => setModeBusy(false));
    },
    [pathId, setMasterySessionMode, state.sessionId, t],
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
          {sessionMode === "study" ? (
            <span className="hidden min-w-0 truncate text-[12.5px] text-[var(--muted-foreground)] sm:inline">
              {waypoint.name}
            </span>
          ) : null}
        </div>

        {/* All three modes, with the live one marked. The mode decides which
            tools the tutor may use, so it is the answer to "why can't it just
            fix that for me" — and that question can only be asked by someone
            who can see the other two exist. */}
        <ModeSwitch
          mode={sessionMode}
          onSelect={changeMode}
          disabled={state.isStreaming || modeBusy || sessionLoading}
          className="hidden shrink-0 sm:flex"
        />

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
                {/* What this sitting is not. It stays visible for the whole
                    conversation rather than only on the empty state: the
                    question "have we started learning yet?" is asked by
                    someone scrolled halfway down, not by someone looking at a
                    blank screen. */}
                {MODE_PRESENTATION[sessionMode].noteKey && (
                  <p className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--secondary)] px-3.5 py-2.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
                    {t(MODE_PRESENTATION[sessionMode].noteKey)}
                  </p>
                )}
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
                  // Reached only when nothing was sent for the learner — a
                  // study conversation, or an opening the send refused. It
                  // therefore has to offer a way in rather than describing
                  // work that is not happening: a screen that claims the tutor
                  // is reading while nothing runs is the one state this
                  // surface must never reach, and it reached it twice.
                  <div className="mx-auto flex min-h-[54vh] max-w-2xl flex-col items-center justify-center text-center">
                    <div className="text-[12px] text-[var(--muted-foreground)]">
                      {sessionMode === "study" ? t("Next up") : t("Start here")}
                    </div>
                    <h2 className="mt-1.5 font-serif text-[20px] font-semibold tracking-[-0.01em] text-[var(--foreground)]">
                      {sessionMode === "study"
                        ? waypoint.name
                        : t(MODE_PRESENTATION[sessionMode].emptyTitleKey)}
                    </h2>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted-foreground)]">
                      {t(MODE_PRESENTATION[sessionMode].emptyBodyKey)}
                    </p>
                    <div className="mt-7 grid w-full gap-2 sm:grid-cols-3">
                      {STARTERS[sessionMode].map((starter) => {
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
                    {sessionMode === "outline" && total > 0 && (
                      // The outline exists, so this sitting has produced what
                      // it was opened for. Learning happens in a different
                      // kind of session, and nothing on this screen would
                      // otherwise tell the learner that — they would keep
                      // typing here and wonder why they were never taught.
                      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--primary)]/25 bg-[var(--primary)]/[0.06] px-4 py-3">
                        <div className="min-w-0">
                          <p className="text-[13px] font-medium text-[var(--foreground)]">
                            {t("Your outline is ready — {{count}} knowledge points", {
                              count: total,
                            })}
                          </p>
                          <p className="mt-0.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
                            {t(
                              "Keep refining it here, or open a learning session to start working through it.",
                            )}
                          </p>
                        </div>
                        <Link
                          href={masterySessionRoute(pathId, "study", courseId)}
                          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[13px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
                        >
                          {t("Start learning")}
                          <ArrowRight className="h-3.5 w-3.5" />
                        </Link>
                      </div>
                    )}
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
                      onAnswerMasteryQuestion={answerMasteryQuestion}
                      onSkipMasteryQuestion={skipMasteryQuestion}
                      onPreviewAttachment={handlePreviewMessageAttachment}
                      onConfirmOutline={confirmResearchOutline}
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
