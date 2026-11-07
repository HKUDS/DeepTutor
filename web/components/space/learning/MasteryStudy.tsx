"use client";

import { scopedUrl } from "@/lib/workspace-scope";
import { MASTERY_HOME, masterySessionRoute as openPlacedSession, masterySessionsRoute, masteryTopicRoute, withKnowledgePoint } from "@/lib/learning-routes";

import { browserStorage } from "@/shared/storage";
import Tooltip from "@/shared/ui/Tooltip";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
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

import {
  latestPendingAskUser,
  type AskUserCardData,
} from "@/components/chat/home/AskUserOptions";
import { pendingProseDecision } from "@/lib/outline-decision";
import { ChatMessageList } from "@/features/chat/messages";
import FollowupChipsRow from "@/features/chat/messages/FollowupChipsRow";
import MasteryQuestionCard from "@/components/chat/home/MasteryQuestionCard";
import {
  ComposerChoiceDock,
  OutlineDecisionDialog,
} from "@/components/space/learning/OutlineDecisionDialog";
import { OutlineChatDialog } from "@/components/space/learning/OutlineChatDialog";
import { latestOpenMasteryQuestion } from "@/lib/mastery-question";
import { localizedRejectionReason } from "@/lib/submission-rejection";
import { ChatViewerBridges } from "@/components/chat/home/ChatViewerBridges";
import { buildSessionActivity } from "@/components/chat/home/SessionActivityPanel";
import { TurnNavigator } from "@/components/chat/home/TurnNavigator";
import SessionViewerPanel, {
  type SessionViewerPanelHandle,
} from "@/components/chat/home/LazySessionViewerPanel";
import {
  type MessageAttachment,
  useChatStateAdapter,
} from "@/features/chat/ChatStateAdapter";
import { useChatAutoScroll } from "@/hooks/useChatAutoScroll";
import { useMasteryOpening } from "@/hooks/useMasteryOpening";
import { useMasteryStudySession } from "@/hooks/useMasteryStudySession";
import { useMeasuredHeight } from "@/hooks/useMeasuredHeight";
import { useResearchOutlineContinuation } from "@/hooks/useResearchOutlineContinuation";
import {
  commitOutlineAddition,
  fetchMasteryAskHint,
  resolveMasterySession,
  rollPointLectureDraft,
  type MasteryTopic,
} from "@/lib/learning-api";
import { isReviewAvailable, isRoutedStudySessionReady, modeSwitchTarget } from "@/lib/mastery-study-route";
import { lectureRevisionOnMessage } from "@/lib/lecture-preview";
import {
  modeHandoffFingerprint,
  outlinePreviewOnMessage,
  shouldFollowModeHandoff,
} from "@/lib/outline-preview";
import { getSession } from "@/lib/session-api";
import { notify } from "@/lib/notifications";
import { copyText } from "@/lib/clipboard";
import { consumePendingPrompt } from "@/lib/pending-prompt";
import { buildChatOutline, scrollToChatTurn } from "@/lib/chat-outline";
import { buildConversationNotebookSave } from "@/lib/conversation-notebook-save";
import { type MasteryMode } from "@/lib/mastery-mode";
import { workspaceActionNeedsConfiguration } from "@/lib/workspace-mode";

import { ActivityHeader } from "@/components/activity";

import { LectureDraftCard } from "./LectureDraftCard";
import { LectureReaderPane } from "./LectureReaderPane";
import { LectureRevisionCard } from "./LectureRevisionCard";
import { ReadingPanelSeparator } from "@/components/reading/workspace/ReadingPanelSeparator";
import { ModeSwitch } from "./ModeSwitch";
import { viewedKnowledgePoint } from "./viewed-point";
import { MasteryPathCrumb } from "@/components/layout/instance-crumbs";
import { PageBarSlot, usePageBarOffers } from "@/components/layout/PageChrome";
import { topicDisplayName, type Translate } from "./format";
import { LevelUpCelebration } from "./LevelUpCelebration";
import { MasteryComposer, STUDY_COMPOSER_WIDTH } from "./MasteryComposer";
import { ProgressRing } from "./ProgressRing";
import { StudyOutline } from "./StudyOutline";
import { useMasteryLectureLayout } from "./useMasteryLectureLayout";
import { usePointLectureReady } from "./usePointLectureReady";

const OUTLINE_STORAGE_KEY = "dt.mastery.outline";

/**
 * Next-step actions that mean "go learn this knowledge point". A path whose
 * frontier is one of these offers the point itself; ``answer_pending`` and
 * ``review`` are not unfinished learning and must not become a "next point".
 */
const NEXT_STUDY_ACTIONS = new Set(["teach", "probe", "practice", "assess"]);

/**
 * How each kind of session presents itself.
 *
 * The outline is the one mode with two jobs under one name. Opened on a goal
 * that has no outline it is a *drafting* sitting; opened on a goal that has
 * one — which is what 修改大纲 does — it is an *editing* sitting, and every
 * line on the screen has to say which. Telling someone who came to change one
 * knowledge point to "design your outline" invites a rebuild of a map they
 * already agreed to, and offering "draft an outline from the materials I
 * chose" as a way in offers exactly that.
 */
const MODE_PRESENTATION: Record<
  MasteryMode,
  {
    /** One line under the header: what this mode is and is not. */
    noteKey: string;
    /** The empty conversation's heading and the line under it. */
    emptyTitleKey: string;
    emptyBodyKey: string;
    /** The same two, for an outline that already exists and is being edited. */
    reviseTitleKey?: string;
    reviseBodyKey?: string;
    reviseNoteKey?: string;
  }
> = {
  outline: {
    noteKey: "Nothing is being taught yet — this mode agrees on what you will learn.",
    emptyTitleKey: "Design your outline",
    emptyBodyKey:
      "The tutor reads the materials you chose, asks what you already know, and proposes a route you can change.",
    reviseTitleKey: "Change your outline",
    reviseBodyKey:
      "Say what should be different — a point to add, one that is too hard, the order of two modules. The tutor revises the map and keeps the rest.",
    reviseNoteKey:
      "This session changes the outline. Nothing here is taught or tested.",
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
 * Ways into an outline that already exists.
 *
 * None of the drafting starters belong here: "draft an outline" over a map the
 * learner has been studying is a request to start over. These name the edits
 * people actually make — a point that is wrong, one that is missing, an order
 * that stops making sense — and each is a one-tap way to say so.
 */
const OUTLINE_REVISION_STARTERS: readonly {
  icon: typeof Compass;
  key: string;
}[] = [
  { icon: Compass, key: "Change what one knowledge point covers" },
  { icon: Sparkles, key: "Add a knowledge point I am missing" },
  { icon: Flag, key: "Reorder the modules on this outline" },
];

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

function OutlineAdditionButton({
  modules,
  defaultModuleId,
  onConfirm,
}: {
  modules: { id: string; name: string }[];
  defaultModuleId: string;
  onConfirm: (moduleId: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [moduleId, setModuleId] = useState(defaultModuleId);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  if (done) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <select
        value={moduleId}
        onChange={(event) => setModuleId(event.target.value)}
        className="h-8 rounded-lg border border-[var(--input)] bg-[var(--card)] px-2 text-[12px]"
        aria-label={t("Module {{n}}", { n: "" })}
      >
        {modules.map((module, index) => (
          <option key={module.id} value={module.id}>
            {t("Module {{n}}", { n: index + 1 })} {module.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={busy || !moduleId}
        onClick={() => {
          setBusy(true);
          void onConfirm(moduleId)
            .then(() => setDone(true))
            .catch((reason: unknown) => {
              notify(
                reason instanceof Error ? reason.message : t("Update failed"),
                { tone: "error" },
              );
            })
            .finally(() => setBusy(false));
        }}
        className="h-8 rounded-lg border border-[var(--border)] px-2.5 text-[12px] font-medium hover:bg-[var(--muted)] disabled:opacity-40"
      >
        {busy ? t("Saving...") : t("Add as an outline knowledge point")}
      </button>
    </div>
  );
}

export function MasteryStudy({
  pathId,
  routeSessionId,
  requestedMode = "study",
  hintedPointId = "",
}: {
  pathId: string;
  routeSessionId?: string;
  /** What a conversation opened here is for; ignored for an existing one. */
  requestedMode?: MasteryMode;
  /** Point this navigation opened, used until the session preference arrives. */
  hintedPointId?: string;
}) {
  const { t } = useTranslation();
  const router = useRouter();
  const [boundPointId, setBoundPointId] = useState<string | null>(
    hintedPointId.trim() || null,
  );
  const handedOffRef = useRef("");
  const handoffBaselineRef = useRef("");
  useEffect(() => {
    handedOffRef.current = "";
    handoffBaselineRef.current = "";
  }, [routeSessionId]);
  const {
    state,
    sendMessage,
    submitUserReply,
    regenerateLastMessage,
    resendLastMessage,
    deleteTurn,
    discardFailedSubmission,
    retryFailedSubmission,
    editMessage,
    switchBranch,
    loadMessageTrace,
    releaseMessageTrace,
  } = useChatStateAdapter();
  const confirmResearchOutline = useResearchOutlineContinuation();
  const {
    topic,
    topicError,
    knowledgeBases,
    sessionError,
    sessionLoading,
    sessionMode,
    refreshTopic,
  } = useMasteryStudySession(
    pathId,
    routeSessionId,
    requestedMode,
  );
  const sessionReady = isRoutedStudySessionReady({
    routeSessionId,
    adapterSessionId: state.sessionId,
    sessionLoading,
  });
  const hasMessages = state.messages.length > 0;
  const outlineDecision = useMemo(
    () =>
      sessionReady
        ? latestPendingAskUser(state.messages, {
            streaming: state.isStreaming,
          })
        : null,
    [sessionReady, state.messages, state.isStreaming],
  );
  const proseDecision = useMemo(() => {
    if (!sessionReady || outlineDecision || state.isStreaming) return null;
    return pendingProseDecision(state.messages);
  }, [outlineDecision, sessionReady, state.isStreaming, state.messages]);
  const openQuestion = useMemo(
    () =>
      sessionReady ? latestOpenMasteryQuestion(state.messages) : null,
    [sessionReady, state.messages],
  );
  const proseDecisionCard = useMemo<AskUserCardData | null>(() => {
    if (!proseDecision) return null;
    return {
      payload: {
        intro: null,
        questions: [
          {
            id: "outline-decision",
            prompt: proseDecision.prompt,
            header: null,
            multi_select: false,
            options: proseDecision.options.map((label) => ({
              label,
              description: null,
            })),
            allow_free_text: true,
            placeholder: null,
          },
        ],
      },
      answers: null,
      resolved: false,
    };
  }, [proseDecision]);
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
  // The study composer lists KB sources by label, but the stored request
  // snapshot keeps the qualified ref — resolve it so sent-message reference
  // chips read the same way.
  const kbDisplayNames = useMemo(
    () =>
      Object.fromEntries(
        (topic?.sources ?? [])
          .filter(
            (source) =>
              source.kind === "knowledge_base" && source.source_id && source.label,
          )
          .map((source) => [source.source_id as string, source.label]),
      ),
    [topic],
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

  // A Mastery hand-off may have written the opening line before sending
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
  const hintSessionRef = useRef(state.sessionId ?? "");
  useEffect(() => {
    if (state.isStreaming || sessionLoading || sessionError) return;
    const sessionId = state.sessionId ?? "";
    // A hint written for another point's conversation must not stay in the
    // box while this one is still fetching its own question.
    if (hintSessionRef.current !== sessionId) {
      hintSessionRef.current = sessionId;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setAskHint("");
    }
    let cancelled = false;
    void fetchMasteryAskHint(pathId, sessionId)
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
    (answer: { questionId: string; text: string; answers?: Array<{ questionId: string; text: string }> }) => {
      const text = answer.text.trim();
      if (!text || state.isStreaming || sessionLoading || sessionError) {
        return false;
      }
      sendMessage(text, undefined, undefined, undefined, undefined, {
        masteryAnswer: {
          question_id: answer.questionId,
          text,
          ...(answer.answers ? { answers: Object.fromEntries(answer.answers.map((item) => [item.questionId, item.text])) } : {}),
        },
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

  useMasteryOpening({
    pathId,
    topicReady: Boolean(topic),
    hasMessages,
    hasOutline: (topic?.map.counts.total ?? 0) > 0,
    sessionLoading,
    sessionError,
    sessionMode,
    isStreaming: state.isStreaming,
    submit,
  });

  // The learner pressing one of the three modes above the transcript. The same
  // move the tutor makes with ``mastery_mode``, through the same admission
  // rule — so a refusal reads the same whoever asked for it.
  const [modeBusy, setModeBusy] = useState(false);
  // The outline chat runs in a modal on this screen instead of navigating to
  // the outline session page: the learner is mid-way through a lesson and the
  // outline edit is a different sitting that must not overwrite it.
  const [outlineDialogOpen, setOutlineDialogOpen] = useState(false);
  // Navigation itself, without the busy flag: an effect that advances the
  // learner to the next point has no button to disable, and setting state in
  // an effect body is a cascading render the learner pays for.
  //
  // Every phase is a conversation of its own: the outline sits on the path,
  // study and review on a knowledge point. Switching phase therefore means
  // opening that conversation, never restyling the one on screen — an outline
  // edit is a different sitting from the lesson, and must not overwrite it.
  const navigateToPlaced = useCallback(
    (mode: MasteryMode, pointId = "") => {
      if (mode !== "outline" && !pointId) return Promise.resolve();
      // The point being left, when this is a departure and a study session to
      // save it from. The same rule the tutor's ``mastery_mode`` applies: a
      // draft nobody pressed the button on is still better saved than lost,
      // and it is what review is about to show. Switching study -> review on
      // one point is not a departure, so nothing is confirmed for it. Nor is
      // stepping into the outline conversation: the learner is going to look
      // at the map, not to close the lecture they were reading.
      const leaving =
        mode !== "review" || !pointId || pointId === boundPointId
          ? ""
          : (boundPointId ?? "");
      return resolveMasterySession(pathId, mode, pointId, leaving).then((placed) => {
        if (placed.session_id && placed.session_id !== state.sessionId) {
          router.push(
            withKnowledgePoint(
              openPlacedSession(pathId, placed.session_id),
              placed.knowledge_point_id,
            ),
          );
        }
      });
    },
    [boundPointId, pathId, router, state.sessionId],
  );
  const openPlaced = useCallback(
    (mode: MasteryMode, pointId = "") => {
      if (mode !== "outline" && !pointId) return;
      setModeBusy(true);
      void navigateToPlaced(mode, pointId)
        .catch((reason: unknown) => {
          notify(
            reason instanceof Error ? reason.message : t("The mode could not be changed"),
            { tone: "error" },
          );
        })
        .finally(() => setModeBusy(false));
    },
    [navigateToPlaced, t],
  );
  const changeMode = useCallback(
    (next: MasteryMode) => {
      if (next === "outline") {
        // The outline is a modal on this screen, not another conversation —
        // the same move as the "Outline chat" control above the composer.
        setOutlineDialogOpen(true);
        return;
      }
      if (!topic || boundPointId === null) return;
      const points = topic.map.modules.flatMap((module) => module.knowledge_points);
      // The mode switch never moves the learner to another point: each point
      // has its own study and review transcript, and the outline is what
      // changes which point those transcripts belong to.
      const pointId =
        modeSwitchTarget(points, boundPointId, topic.next.knowledge_point_id) ||
        currentWaypoint(topic, topicDisplayName(topic, t), t).id;
      openPlaced(next, pointId);
    },
    [boundPointId, openPlaced, t, topic],
  );

  useEffect(() => {
    const sessionId = state.sessionId;
    // The chat adapter can still be holding the previous conversation while
    // this route's session is reopening. Reading that one would place the
    // outline on the wrong knowledge point.
    if (!sessionId || (routeSessionId && sessionId !== routeSessionId)) return;
    const hint = hintedPointId.trim();
    let cancelled = false;
    void getSession(sessionId)
      .then((detail) => {
        if (cancelled) return;
        const pointId = detail.preferences?.mastery_knowledge_point_id;
        setBoundPointId(typeof pointId === "string" ? pointId : "");
      })
      .catch(() => {
        if (!cancelled) setBoundPointId(hint || null);
      });
    return () => {
      cancelled = true;
    };
  }, [hintedPointId, routeSessionId, state.sessionId]);

  useEffect(() => {
    // Cached transcripts still carry the last mastery_mode jump. Following
    // that on open sends the learner back to a different knowledge point.
    if (!sessionReady || state.isStreaming) return;
    const found = modeHandoffFingerprint(state.messages, state.sessionId);
    if (!handoffBaselineRef.current) {
      handoffBaselineRef.current = found.fingerprint;
      return;
    }
    if (
      !shouldFollowModeHandoff({
        ...found,
        sessionId: state.sessionId,
        baselineFingerprint: handoffBaselineRef.current,
      }) ||
      found.target === handedOffRef.current
    ) {
      return;
    }
    handedOffRef.current = found.target;
    handoffBaselineRef.current = found.fingerprint;
    router.push(openPlacedSession(pathId, found.target));
  }, [pathId, router, sessionReady, state.isStreaming, state.messages, state.sessionId]);

  const copyAssistantMessage = useCallback(
    (content: string) => copyText(content),
    [],
  );
  const locationInBar = usePageBarOffers("instance");

  // Hooks have to run before the loading and not-found returns below, so the
  // layout and the lecture cards are set up unconditionally and merely render
  // nothing until a topic exists.
  const topicModules = useMemo<MasteryTopic["map"]["modules"]>(
    () => topic?.map.modules ?? [],
    [topic],
  );
  const viewedPoint = topic
    ? viewedKnowledgePoint(topicModules, boundPointId, sessionMode, currentWaypoint(topic, "", t))
    : null;
  // The review screen is the lecture beside the conversation about it. The
  // layout only applies there: study is one column of teaching, and an empty
  // lecture pane next to it would be a promise the screen cannot keep.
  const lecturePoint = viewedPoint?.id || boundPointId || "";
  const { gridAttach: lectureGridAttach, ...lectureLayout } = useMasteryLectureLayout({
    enabled: sessionMode === "review" && Boolean(lecturePoint),
  });
  const reviewSplit = lectureLayout.split;

  // The panes read the lecture independently, so a card applied in the chat
  // has to tell the reader pane to refetch. A counter is the smallest thing
  // that does that without lifting the whole lecture into this component.
  const [lectureEpoch, setLectureEpoch] = useState(0);
  const handleLectureConfirmed = useCallback(() => setLectureEpoch((value) => value + 1), []);

  // Confirming the section's lecture from study closes the loop: the section is
  // done and its lecture is settled, so the learner lands on the review — the
  // lecture beside the re-test — which is where the cue to start the next
  // section lives.
  const handleStudyLectureConfirmed = useCallback(() => {
    handleLectureConfirmed();
    if (viewedPoint) openPlaced("review", viewedPoint.id);
  }, [handleLectureConfirmed, openPlaced, viewedPoint]);

  // The study draft is rolled after the assistant message is persisted, so it
  // lands slightly after the stream ends. Bumping once per settled turn makes
  // the card re-read the draft instead of waiting for a reload.
  const [turnEpoch, setTurnEpoch] = useState(0);
  const wasStreamingRef = useRef(false);
  useEffect(() => {
    if (state.isStreaming) {
      wasStreamingRef.current = true;
      return;
    }
    if (!wasStreamingRef.current) return;
    wasStreamingRef.current = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTurnEpoch((value) => value + 1);
  }, [state.isStreaming]);

  // Review is the lecture beside the re-test, so the control waits for the
  // lecture the runtime writes just after the turn that masters the point.
  // Re-read when a turn settles or a lecture is rewritten in the pane.
  const lectureForReview = usePointLectureReady(pathId, lecturePoint, lectureEpoch + turnEpoch);
  const hasLectureForReview = Boolean(lectureForReview && lectureForReview.status !== "none");

  const orderedStudyPoints = useMemo(
    () => topicModules.flatMap((module) => module.knowledge_points),
    [topicModules],
  );
  const viewedPointStatus = viewedPoint
    ? orderedStudyPoints.find((point) => point.id === viewedPoint.id)?.status
    : undefined;

  // The next point the learner has left to learn, after the one on screen.
  // Offered on the review page once the section is confirmed — the review page
  // is where a finished section lands, so the "keep going" cue belongs there.
  // The path's own frontier wins when there is unfinished work, so this button
  // and the topic page's "continue" never name different knowledge points.
  const nextPointAfterCurrent = useMemo(() => {
    if (!viewedPoint || viewedPointStatus !== "mastered") return null;
    const frontier = topic?.next;
    if (
      frontier &&
      NEXT_STUDY_ACTIONS.has(frontier.action) &&
      frontier.knowledge_point_id &&
      frontier.knowledge_point_id !== viewedPoint.id
    ) {
      return { id: frontier.knowledge_point_id, name: frontier.knowledge_point_name };
    }
    const currentIndex = orderedStudyPoints.findIndex((point) => point.id === viewedPoint.id);
    if (currentIndex < 0) return null;
    const next = orderedStudyPoints
      .slice(currentIndex + 1)
      .find((point) => point.status !== "mastered");
    return next ? { id: next.id, name: next.name } : null;
  }, [orderedStudyPoints, topic, viewedPoint, viewedPointStatus]);

  // A finished point should never be left without its lecture. The runtime
  // rolls one after the teaching turn, but an interrupted turn (or a failure)
  // leaves nothing, and then the button above has nothing to wait for. Ask for
  // it once, after the ready-hook's retries have had their chance.
  const lectureRollAttemptedRef = useRef("");
  useEffect(() => {
    if (sessionMode !== "study" || !viewedPoint) return;
    if (viewedPointStatus !== "mastered") return;
    if (lectureForReview === null || lectureForReview.status !== "none") return;
    if (lectureRollAttemptedRef.current === viewedPoint.id) return;
    lectureRollAttemptedRef.current = viewedPoint.id;
    void rollPointLectureDraft(pathId, viewedPoint.id)
      .then(() => setLectureEpoch((value) => value + 1))
      .catch(() => {
        // Best-effort: the review pane's force-rewrite can retry.
      });
  }, [lectureForReview, pathId, sessionMode, viewedPoint, viewedPointStatus]);

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
          href={scopedUrl(MASTERY_HOME)}
          className="mt-5 text-sm font-medium text-[var(--primary)] hover:underline"
        >
          {t("Back to topics")}
        </Link>
      </div>
    );
  }

  const displayName = topicDisplayName(topic, t);
  const waypoint = currentWaypoint(topic, displayName, t);
  // The crumb names the point this conversation is *on*, not the frontier the
  // path is heading to. The two differ while a finished point is still open,
  // and showing the frontier there told the learner they were somewhere else.
  // ``viewedPoint`` is the placed point, and falls back to the frontier only
  // when the conversation has no placement at all.
  const onScreenPointName = viewedPoint?.name || waypoint.name;
  const completed = topic.map.counts.mastered;
  const total = topic.map.counts.total;
  // The outline sitting says which of its two jobs it is doing. "Nothing is
  // being taught yet" is true of a first draft and wrong for an edit, and the
  // learner reaching this screen from 修改大纲 is doing the second.
  const editingOutline = sessionMode === "outline" && total > 0;
  const modeNote = editingOutline
    ? t(MODE_PRESENTATION.outline.reviseNoteKey ?? "")
    : MODE_PRESENTATION[sessionMode].noteKey
      ? t(MODE_PRESENTATION[sessionMode].noteKey)
      : "";
  const reviewAvailable = isReviewAvailable({
    modules: topicModules,
    pointId: lecturePoint,
    sessionMode,
    hasLecture: hasLectureForReview,
  });
  // Review is offered only once the point on screen is mastered — before that
  // there is nothing to consolidate, and the tutor refuses to examine it. The
  // outline and study tabs stay together either way: a lone "study" tab is not
  // a choice, so the pair remains even before a review is possible.
  const visibleModes: readonly MasteryMode[] = reviewAvailable
    ? ["outline", "study", "review"]
    : ["outline", "study"];

  return (
    <main className="mastery-shell flex h-full min-h-0 flex-col overflow-hidden">
      {/* One line, not two: the topic and the waypoint the tutor is on read
          as a single "where am I" statement, and the ring + count are one
          unit rather than a ring on the left and its own number on the
          right saying the same thing twice. */}
      {/* 「精通之路 / the path / the waypoint」 and the session's controls go
          up into the page bar; without one this row keeps them, with its own
          way back to the path. */}
      <header className="dt-study-head flex h-[56px] shrink-0 items-center gap-1 bg-[var(--background)] px-3 sm:px-4">
        {locationInBar ? (
          <PageBarSlot name="instance">
            <MasteryPathCrumb id={pathId} label={displayName} bare />
            {sessionMode !== "outline" ? (
              <>
                <span aria-hidden className="dt-crumb-sep">
                  /
                </span>
                <span className="dt-crumb-tail">{onScreenPointName}</span>
              </>
            ) : null}
          </PageBarSlot>
        ) : (
          <>
            <Tooltip label={t("Learning topics")} side="bottom">
              <Link
                href={masteryTopicRoute(pathId)}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)]"
                aria-label={t("Learning topics")}
              >
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Tooltip>

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
              {sessionMode !== "outline" ? (
                <span className="hidden min-w-0 truncate text-[12.5px] text-[var(--muted-foreground)] sm:inline">
                  {onScreenPointName}
                </span>
              ) : null}
            </div>
          </>
        )}

        {/* The modes this conversation can switch between, with the live one
            marked. The mode decides which tools the tutor may use, so it is the
            answer to "why can't it just fix that for me" — and that question
            can only be asked by someone who can see the other modes exist.
            Review appears only once the point on screen is mastered. */}
        <PageBarSlot name="actions" className="contents">
        <ModeSwitch
          mode={sessionMode}
          modes={visibleModes}
          onSelect={changeMode}
          disabled={state.isStreaming || modeBusy || sessionLoading}
          className="hidden shrink-0 sm:flex"
        />

        <div className="flex shrink-0 items-center gap-1.5 pl-2">
          <Tooltip label={t("Save to Notebook")}>
            <button
              type="button"
              onClick={() => setShowSaveModal(true)}
              disabled={!notebookSavePayload}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/60 hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
              aria-label={t("Save to Notebook")}
            >
              <BookmarkPlus className="h-4 w-4" />
            </button>
          </Tooltip>
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
        </PageBarSlot>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside
          className={`hidden shrink-0 overflow-y-auto transition-[width] duration-200 xl:block ${
            outlineOpen ? "w-[252px] px-5 py-5" : "w-9"
          }`}
        >          <StudyOutline
            topic={topic}
            currentPointId={viewedPoint?.id ?? ""}
            nextPointId={topic.next.knowledge_point_id}
            justMasteredId={celebration?.pointId ?? null}
            collapsed={!outlineOpen}
            onToggleCollapsed={toggleOutline}
            onSelectPoint={(pointId) => {
              // A mastered objective opens its review conversation — study
              // has nothing left to work on there. Anything else opens study:
              // review re-tests proven work, so an unmastered point has no
              // review conversation worth opening.
              const mastered = topic.map.modules.some((module) =>
                module.knowledge_points.some(
                  (point) => point.id === pointId && point.status === "mastered",
                ),
              );
              openPlaced(mastered ? "review" : "study", pointId);
            }}
          />
        </aside>

        <div
          ref={lectureGridAttach}
          style={reviewSplit ? lectureLayout.gridStyle : undefined}
          // Grid only while the lecture actually sits beside the chat. In
          // study — and in review when the lecture is collapsed or stacked —
          // this stays a plain flex column so the conversation keeps the full
          // width it has everywhere else.
          //
          // `flex-1` stays on in both cases. Turning it into `flex-none`
          // while splitting made the grid's own width indefinite, so the
          // `1fr` chat track resolved to its max-content width and the whole
          // container grew past its parent — the right edge of the
          // conversation was clipped off-screen instead of sharing the row.
          className={`flex min-h-0 min-w-0 flex-1 flex-col ${
            reviewSplit ? "xl:grid" : ""
          }`}
        >
          {reviewSplit ? (
            <>
              <LectureReaderPane
                key={`split-${lectureEpoch}`}
                pathId={pathId}
                knowledgePointId={lecturePoint}
                onLectureConfirmed={handleLectureConfirmed}
                onCollapse={lectureLayout.toggle}
              />
              <ReadingPanelSeparator
                label={t("Resize lecture")}
                width={lectureLayout.lectureWidth}
                min={lectureLayout.lectureMin}
                max={lectureLayout.lectureMax}
                direction={1}
                onResize={lectureLayout.resize}
              />
            </>
          ) : sessionMode === "review" && lecturePoint && !lectureLayout.collapsed ? (
            // Too narrow for two columns. Stacked, collapsible: review still
            // has its lecture, without stealing the width the conversation
            // needs or silently hiding the thing the learner came to read.
            <div className="h-[42%] min-h-[200px] shrink-0 border-b border-[var(--border)] xl:hidden">
              <LectureReaderPane
                key={`stack-${lectureEpoch}`}
                pathId={pathId}
                knowledgePointId={lecturePoint}
                onLectureConfirmed={handleLectureConfirmed}
                onCollapse={lectureLayout.toggle}
              />
            </div>
          ) : null}
        <section className="relative flex min-w-0 flex-1 flex-col bg-[var(--background)]">
          <div className="relative min-h-0 flex-1 basis-0">
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
                    blank screen.

                    The outline's own line needs the same care for the opposite
                    reason: an outline that already exists is being *edited*
                    here, and telling its author "nothing is being taught yet"
                    describes a first draft they are not writing. */}
                {modeNote && (
                  <p className="mb-6 rounded-lg border border-[var(--border)] bg-[var(--secondary)] px-3.5 py-2.5 text-[12px] leading-5 text-[var(--muted-foreground)]">
                    {modeNote}
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
                      href={masterySessionsRoute(pathId)}
                      className="mt-4 inline-flex rounded-xl bg-[var(--primary)] px-3 py-2 text-xs font-medium text-[var(--primary-foreground)]"
                    >
                      {t("Start a new session")}
                    </Link>
                  </div>
                ) : !hasMessages ? (                  // Reached only when nothing was sent for the learner — a
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
                        ? viewedPoint?.name || displayName
                        : t(
                            (total > 0 &&
                              MODE_PRESENTATION[sessionMode].reviseTitleKey) ||
                              MODE_PRESENTATION[sessionMode].emptyTitleKey,
                          )}
                    </h2>
                    <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted-foreground)]">
                      {t(
                        (total > 0 &&
                          MODE_PRESENTATION[sessionMode].reviseBodyKey) ||
                          MODE_PRESENTATION[sessionMode].emptyBodyKey,
                      )}
                    </p>
                    <div className="mt-7 grid w-full gap-2 sm:grid-cols-3">
                      {(
                        sessionMode === "outline" && total > 0
                          ? OUTLINE_REVISION_STARTERS
                          : STARTERS[sessionMode]
                      ).map((starter) => {
                        const Icon = starter.icon;
                        const label = t(starter.key);
                        return (
                          <button
                            key={starter.key}
                            type="button"
                            onClick={() => {
                              const pointName = viewedPoint?.name.trim() ?? "";
                              startFromPrompt(
                                pointName
                                  ? t(
                                      "{{prompt}} This conversation's knowledge point is {{name}}.",
                                      { prompt: label, name: pointName },
                                    )
                                  : label,
                              );
                            }}
                            disabled={state.isStreaming || sessionLoading}
                            className="group rounded-[14px] bg-[rgb(var(--dt-ink,55_53_47)/0.03)] p-4 text-left transition hover:-translate-y-0.5 hover:bg-[rgb(var(--dt-ink,55_53_47)/0.055)] disabled:opacity-50"
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
                        <button
                          type="button"
                          onClick={() => {
                            const pointId =
                              topic.next.knowledge_point_id ||
                              topic.map.modules[0]?.knowledge_points[0]?.id ||
                              "";
                            // Study is its own conversation per knowledge
                            // point; landing on "the next one" means opening
                            // that conversation, not a fresh draft.
                            if (pointId) openPlaced("study", pointId);
                          }}
                          disabled={
                            modeBusy ||
                            !(
                              topic.next.knowledge_point_id ||
                              topic.map.modules[0]?.knowledge_points[0]?.id
                            )
                          }
                          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[13px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90 disabled:opacity-40"
                        >
                          {t("Start learning")}
                          <ArrowRight className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                    <ChatMessageList
                      messages={state.messages}
                      isStreaming={state.isStreaming}
                      sessionId={state.sessionId}
                      language={state.language}
                      onCopyAssistantMessage={copyAssistantMessage}
                      onRegenerateMessage={regenerateLastMessage}
                      canResendLastTurn={state.lastTurnFailed}
                      onResendLastTurn={resendLastMessage}
                      onDeleteTurn={deleteTurn}
                      onDiscardFailedSubmission={discardFailedSubmission}
                      onRetryFailedSubmission={retryFailedSubmission}
                      selectedBranches={state.selectedBranches}
                      onEditMessage={editMessage}
                      onSwitchBranch={switchBranch}
                      onSubmitUserReply={submitUserReply}
                      onAnswerMasteryQuestion={answerMasteryQuestion}
                      onSkipMasteryQuestion={skipMasteryQuestion}
                      onChallengeMasteryQuestion={(questionId) => {
                        if (state.isStreaming || sessionLoading || sessionError) return false;
                        sendMessage(t('Please review assessment {{questionId}} against its original source evidence. If it is unsupported, invalidate it and recompute learning state. Do not grant mastery merely because I challenged it.', { questionId }));
                        return true;
                      }}
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
                      kbDisplayNames={kbDisplayNames}
                      showModeBadge={false}
                      deferPendingAskUser
                      deferPendingMasteryQuestion
                      outlineAddition={
                        sessionMode === "outline" || !state.sessionId
                          ? undefined
                          : (message) => {
                              const preview = outlinePreviewOnMessage(message.events);
                              if (!preview || !topic) return null;
                              const moduleId =
                                topic.map.modules.find((module) =>
                                  module.knowledge_points.some(
                                    (point) => point.id === viewedPoint?.id,
                                  ),
                                )?.id || topic.map.modules[0]?.id || "";
                              if (!moduleId) return null;
                              return (
                                <OutlineAdditionButton
                                  modules={topic.map.modules.map((module) => ({
                                    id: module.id,
                                    name: module.name,
                                  }))}
                                  defaultModuleId={moduleId}
                                  onConfirm={async (chosen) => {
                                    await commitOutlineAddition(pathId, {
                                      preview_id: preview.previewId,
                                      session_id: state.sessionId || "",
                                      module_id: chosen,
                                    });
                                    notify(t("Added to the outline"));
                                  }}
                                />
                              );
                            }
                      }
                      lectureRevision={
                        sessionMode === "outline" || !state.sessionId
                          ? undefined
                          : (message) => {
                              const preview = lectureRevisionOnMessage(message.events);
                              if (!preview) return null;
                              return (
                                <LectureRevisionCard
                                  key={preview.previewId}
                                  preview={preview}
                                  pathId={pathId}
                                  knowledgePointId={
                                    lecturePoint || (viewedPoint?.id ?? "")
                                  }
                                  onApplied={handleLectureConfirmed}
                                />
                              );
                            }
                      }
                    />
                    <FollowupChipsRow
                      sessionId={state.sessionId}
                      isStreaming={state.isStreaming}
                      turnKey={state.messages.length}
                      enabled={
                        sessionMode !== "outline" &&
                        !openQuestion &&
                        lastMessage?.role === "assistant"
                      }
                      onFollowup={sendMessage}
                    />
                    {sessionMode === "study" &&
                    lecturePoint &&
                    viewedPointStatus === "mastered" ? (
                      // The lecture is the section's product, so its card waits
                      // for the section to be done. The runtime keeps rolling
                      // the draft as teaching happens, but showing it mid-way
                      // reads as "this section is finished" when it is not.
                      // Once mastered, the card is already there to confirm.
                      <LectureDraftCard
                        key={`draft-${lecturePoint}`}
                        pathId={pathId}
                        knowledgePointId={lecturePoint}
                        sessionId={state.sessionId ?? ""}
                        pointName={viewedPoint?.name ?? ""}
                        refreshToken={lectureEpoch + turnEpoch}
                        onConfirmed={handleStudyLectureConfirmed}
                      />
                    ) : null}
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
              className={`flex min-h-0 shrink-0 flex-col bg-[var(--background)] px-3 pb-2 sm:px-4 ${
                openQuestion || outlineDecision || proseDecisionCard
                  ? ""
                  : "max-h-[min(42vh,400px)] overflow-y-auto overscroll-contain"
              }`}
            >
              <div className={`mx-auto w-full shrink-0 px-6 ${STUDY_COMPOSER_WIDTH}`}>
                {sessionMode === "review" && nextPointAfterCurrent ? (
                  // A finished section lands on review; from there, starting
                  // the next section is the learner's move, not an automatic
                  // jump.
                  <div className="mb-2">
                    <button
                      type="button"
                      onClick={() => openPlaced("study", nextPointAfterCurrent.id)}
                      disabled={modeBusy}
                      className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
                    >
                      {t("Next knowledge point")}
                      <span className="min-w-0 truncate opacity-80">
                        · {nextPointAfterCurrent.name}
                      </span>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0" />
                    </button>
                  </div>
                ) : null}
                {(sessionMode === "outline" || lecturePoint) && (
                  <div className="mb-2 flex gap-1.5">
                    {sessionMode === "outline" ? (
                    // The outline sitting is where the map is designed, so the
                    // way back to it is a way into learning: the first point
                    // that still has something left to work on.
                    <button
                      type="button"
                      onClick={() => {
                        const pointId =
                          currentWaypoint(topic, displayName, t).id ||
                          topic.map.modules[0]?.knowledge_points[0]?.id ||
                          "";
                        if (pointId) openPlaced("study", pointId);
                      }}
                      disabled={total === 0 || modeBusy}
                      className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-[12px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-40"
                    >
                      {t("Start learning")}
                    </button>
                  ) : null}
                  {sessionMode === "review" && lecturePoint && !reviewSplit ? (
                    // Below the split threshold there is no room for two
                    // columns, so the lecture becomes something the learner
                    // opens rather than something they see.
                    <button
                      type="button"
                      onClick={lectureLayout.toggle}
                      className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-[12px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)]"
                    >
                      {t("Lecture")}
                    </button>
                  ) : null}
                  {sessionMode !== "outline" && lecturePoint ? (
                    // The lecture is the tutor's account of the point; in study
                    // it is the lesson the conversation is building. Writing the
                    // learner's own beside it is the whole point of a
                    // self-explanation, so it opens a blank page in the session
                    // viewer, where it can also be discussed with Dito.
                    <button
                      type="button"
                      onClick={() => viewerPanelRef.current?.openMarkdownNoteTab()}
                      className="rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-[12px] font-medium text-[var(--foreground)] hover:bg-[var(--muted)]"
                    >
                      {t("Write it myself")}
                    </button>
                  ) : null}
                  </div>
                )}
              </div>
              {openQuestion || outlineDecision || proseDecisionCard ? (
                <div className="min-h-0 shrink">
              {openQuestion ? (
                <ComposerChoiceDock
                  testId="mastery-answer-dock"
                  summary={
                    openQuestion.options.length >= 2
                      ? t("{{count}} options need your choice", {
                          count: openQuestion.options.length,
                        })
                      : t("A question needs your answer")
                  }
                  confirmLabel={
                    openQuestion.options.length >= 2
                      ? t("Review the options")
                      : t("Answer this question")
                  }
                >
                  <div className="px-3.5 py-2">
                    <MasteryQuestionCard
                      question={openQuestion}
                      grade={null}
                      answered={false}
                      submittedAnswer=""
                      onSubmit={({ text, answers }) =>
                        answerMasteryQuestion({
                          questionId: openQuestion.questionId,
                          text: String(text ?? ""),
                          ...(openQuestion.questionType === "group"
                            ? { answers }
                            : {}),
                        })
                      }
                      onSkip={skipMasteryQuestion}
                      onChallenge={(questionId) => {
                        if (state.isStreaming || sessionLoading || sessionError) {
                          return false;
                        }
                        sendMessage(
                          t(
                            "Please review assessment {{questionId}} against its original source evidence. If it is unsupported, invalidate it and recompute learning state. Do not grant mastery merely because I challenged it.",
                            { questionId },
                          ),
                        );
                        return true;
                      }}
                    />
                  </div>
                </ComposerChoiceDock>
              ) : outlineDecision ? (
                <OutlineDecisionDialog
                  data={outlineDecision}
                  onSubmit={submitUserReply}
                />
              ) : proseDecisionCard ? (
                <OutlineDecisionDialog
                  data={proseDecisionCard}
                  onSubmit={(payload) => {
                    const text = (
                      payload.answers
                        ?.map((answer) => answer.text.trim())
                        .filter(Boolean)
                        .join("\n") ||
                      payload.text ||
                      ""
                    ).trim();
                    void sendMessage(text || t("Skip this choice and continue."));
                    return true;
                  }}
                />
              ) : null}
                </div>
              ) : null}
              <div className="shrink-0">
              {/* The refusal banner lives here too, not only on the chat page:
                  study and review send through the same runtime, so they hit
                  the same admission refusals — and without this the learner
                  saw a bare "Not sent" badge and no reason at all. */}
              {state.submissionFailed ? (
                <div
                  role="alert"
                  data-submission-error="true"
                  className={`mx-auto w-full px-6 pb-1 ${STUDY_COMPOSER_WIDTH}`}
                >
                  <div className="flex w-full items-center gap-2 rounded-xl border border-[var(--destructive)]/30 bg-[var(--destructive)]/5 px-3 py-2">
                    <AlertCircle
                      className="h-4 w-4 shrink-0 text-[var(--destructive)]"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 text-[12px] leading-[1.5] text-[var(--foreground)]">
                      {state.submissionRejectionReason
                        ? localizedRejectionReason(
                            state.submissionRejectionReason,
                            t,
                          )
                        : state.submissionNotSaved
                          ? t(
                              "This unsent message could not be saved in your browser. Copy it before leaving this page.",
                            )
                          : state.submissionNeedsReview
                            ? t(
                                "Message text was saved, but its attachments or settings could not be restored. Copy it and send again.",
                              )
                            : t(
                                "Couldn't reach the server. Please check your connection and retry.",
                              )}
                    </span>
                  </div>
                </div>
              ) : null}
              <MasteryComposer
                placeholder={
                  sessionMode === "outline"
                    ? // The outline sitting has no waypoint to name: it is
                      // about the map itself. Before there is a map the line
                      // is the goal; after it, the change they want.
                      editingOutline
                      ? t("Describe what to change in the outline…")
                      : t("Say what you want to be able to do…")
                    : t("Ask your tutor about “{{waypoint}}”…", {
                        waypoint: viewedPoint?.name || displayName,
                      })
                }
                askHint={
                  // The hint is written for the waypoint in view, and the
                  // outline sitting has none. Leaving it on replaced this
                  // screen's own placeholder with a question about a
                  // knowledge point the sitting cannot teach.
                  sessionMode === "outline" ? "" : askHint
                }
                disabled={sessionLoading}
                prefillInputRef={prefillInputRef}
              />
              </div>
            </div>
          )}
        </section>
        </div>
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
      {outlineDialogOpen && (
        <OutlineChatDialog
          pathId={pathId}
          onClose={() => {
            setOutlineDialogOpen(false);
            // An outline edit may have rewritten the map while the learner
            // was in the dialog; re-read the topic so the rail and waypoint
            // reflect what the tutor just agreed to.
            refreshTopic();
          }}
        />
      )}
    </main>
  );
}
