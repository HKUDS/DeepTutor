"use client";

import TaskPanelSection from "@/components/tasks/TaskPanelSection";

import { browserStorage } from "@/shared/storage";

/**
 * SessionViewerPanel — full right-side sidebar with browser-style tabs:
 * file previews, web pages, a Markdown note, quiz follow-ups, side chats
 * (with Dito, a partner, an agent or a partner group), GeoGebra boards and
 * subagent runs.
 *
 * - Tabs across the top of the panel; each closeable. The "+" launcher
 *   (``ViewerLauncher``) names everything the panel can hold.
 * - Tabs belong to their conversation: switching away stashes them, coming
 *   back restores them, and a draft keeps its tabs when its first turn makes
 *   it a session.
 * - File tabs use the same lazy previewer set as FilePreviewDrawer.
 * - Web tabs render an iframe of the URL. Cross-origin frames may refuse
 *   to load — we expose an "Open in browser" affordance so the user can
 *   always fall back. The user's network ultimately decides what loads.
 * - Imperative API via ref (``SessionViewerPanelHandle``).
 */

import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import dynamic from "next/dynamic";
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  Bot,
  Compass,
  Download,
  ExternalLink,
  Globe,
  Loader2,
  MessageSquarePlus,
  MessagesSquare,
  NotebookPen,
  Paperclip,
  Plus,
  UserRound,
  UsersRound,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  previewKindFor,
  resolveSourceUrl,
  type FilePreviewSource,
} from "@/components/chat/preview/previewerFor";
import {
  ActivityBody,
  type SessionActivity,
} from "@/components/chat/home/SessionActivityPanel";
import ViewerLauncher, {
  type LauncherClosedTab,
  type LauncherThread,
} from "@/components/chat/home/ViewerLauncher";
import type { ComposerResourceCatalog } from "@/hooks/useComposerResources";
import ResponderFace from "@/components/chat/home/ResponderFace";
import QuizFollowupTabBody from "@/components/quiz/QuizFollowupTabBody";
import ConsultationTabBody from "@/components/chat/home/ConsultationTabBody";
import {
  type QuizFollowupTabContext,
  useOptionalQuizFollowupController,
} from "@/context/QuizFollowupContext";
import type { GeogebraTabPayload } from "@/context/GeogebraTabContext";
import { apiUrl } from "@/lib/api";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import type { StreamEvent } from "@/features/chat/model/protocol";
import Tooltip from "@/shared/ui/Tooltip";
import { normalizeSelectedText } from "@/lib/selection-text";
import {
  DITO,
  responderFromPreferences,
  sameResponder,
  sideChatKey,
  type SideChatResponder,
} from "@/lib/side-chat";
import { usePartnerRoster } from "@/hooks/usePartnerRoster";
import { usePartnerGroups } from "@/hooks/usePartnerGroups";
import { listSessionThreads, type SessionSummary } from "@/lib/session-api";
import { subscribeSessionChanges } from "@/lib/session-events";
import { isPlaceholderSessionTitle } from "@/lib/session-title";
import { SHORTCUTS } from "@/lib/shortcuts";

const PdfPreview = dynamic(
  () => import("@/components/chat/preview/previewers/PdfPreview"),
);
const ImagePreview = dynamic(
  () => import("@/components/chat/preview/previewers/ImagePreview"),
);
const VideoPreview = dynamic(
  () => import("@/components/chat/preview/previewers/VideoPreview"),
);
const SvgPreview = dynamic(
  () => import("@/components/chat/preview/previewers/SvgPreview"),
);
const MarkdownPreview = dynamic(
  () => import("@/components/chat/preview/previewers/MarkdownPreview"),
);
const TextPreview = dynamic(
  () => import("@/components/chat/preview/previewers/TextPreview"),
);
const DocxPreview = dynamic(
  () => import("@/components/chat/preview/previewers/DocxPreview"),
);
const XlsxPreview = dynamic(
  () => import("@/components/chat/preview/previewers/XlsxPreview"),
);
const OfficePdfPreview = dynamic(
  () => import("@/components/chat/preview/previewers/OfficePdfPreview"),
);
const OfficeTextPreview = dynamic(
  () => import("@/components/chat/preview/previewers/OfficeTextPreview"),
);
const FallbackPreview = dynamic(
  () => import("@/components/chat/preview/previewers/FallbackPreview"),
);
const ChatMarkdownNoteTabBody = dynamic(
  () => import("@/components/chat/home/ChatMarkdownNoteTab"),
  { ssr: false },
);
const Geogebra = dynamic(() => import("@/components/Geogebra"), {
  ssr: false,
});

/* Resizable width — the panel overlays from the right and the chat shell
   reserves space for it via the ``--viewer-width`` CSS var (see globals.css).
   Both read the same var so the squeeze and the panel edge stay locked
   together while dragging. */
const VIEWER_WIDTH_VAR = "--viewer-width";
const VIEWER_WIDTH_KEY = "dt:viewer-width";
const VIEWER_WIDTH_DEFAULT = 520;
const VIEWER_WIDTH_MIN = 400;
const VIEWER_WIDTH_MAX = 960;

function clampViewerWidth(px: number): number {
  // Hard floor/ceiling, plus a soft ceiling that always leaves the chat
  // column ~30% of the viewport so the panel can't swallow the conversation.
  const ceiling =
    typeof window !== "undefined"
      ? Math.max(
          VIEWER_WIDTH_MIN,
          Math.min(VIEWER_WIDTH_MAX, window.innerWidth * 0.7),
        )
      : VIEWER_WIDTH_MAX;
  return Math.round(Math.max(VIEWER_WIDTH_MIN, Math.min(px, ceiling)));
}

function readStoredViewerWidth(): number {
  if (typeof window === "undefined") return VIEWER_WIDTH_DEFAULT;
  const raw = browserStorage.readRaw("local", VIEWER_WIDTH_KEY);
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed)
    ? clampViewerWidth(parsed)
    : VIEWER_WIDTH_DEFAULT;
}

/* ------------------------------------------------------------------ */
/*  Tab types                                                          */
/* ------------------------------------------------------------------ */

type ViewerTab =
  | { kind: "file"; id: string; label: string; source: FilePreviewSource }
  | { kind: "web"; id: string; label: string; url: string }
  | { kind: "markdown-note"; id: string; label: string }
  | {
      kind: "quiz-followup";
      id: string;
      label: string;
      context: QuizFollowupTabContext;
    }
  | {
      kind: "side-chat";
      id: string;
      label: string;
      context: QuizFollowupTabContext;
    }
  | {
      kind: "geogebra";
      id: string;
      label: string;
      script: string;
      /** A blank board the learner draws on, with GeoGebra's own tools. */
      editable?: boolean;
    }
  | { kind: "new"; id: string; label: string }
  | {
      kind: "subagent";
      id: string;
      label: string;
      callId: string;
      events: StreamEvent[];
    };

export interface SessionViewerPanelHandle {
  openFileTab(a: MessageAttachment): void;
  openWebTab(url: string): void;
  /** Opens the session-scoped inline Markdown editor tab. */
  openMarkdownNoteTab(): void;
  /** Opens (or focuses) the follow-up chat tab for a quiz question. */
  openQuizFollowupTab(context: QuizFollowupTabContext): void;
  /**
   * Opens a side chat about this conversation — with Dito unless another
   * responder is named. A ``quote`` lands in its composer as an attachment:
   * an open side chat with the same responder takes it, so asking about a
   * second passage continues the same thread.
   */
  openSideChatTab(options?: SideChatOpenOptions): void;
  /** Opens (or focuses) an interactive GeoGebra applet tab. */
  openGeogebraTab(payload: GeogebraTabPayload): void;
  /** Opens (first time) or live-updates a connected subagent's run tab. */
  openSubagentTab(callId: string, label: string, events: StreamEvent[], focus?: boolean): void;
  /** Opens the panel and switches to the Activity home (where the
   *  capability-config card lives). */
  focusActivityHome(): void;
}

export interface SideChatOpenOptions {
  responder?: SideChatResponder;
  quote?: string;
}

/** What a side chat opened from the viewer is about. */
export interface ViewerConversation {
  title: string;
  /** The last persisted message on the branch on screen; null before one. */
  leafMessageId: number | null;
  language: string;
}

export interface SessionViewerPanelProps {
  open: boolean;
  sessionId: string | null;
  /** The conversation whose tabs are showing (a draft has a key before it
   *  has a session id). Falls back to ``sessionId``. */
  sessionKey?: string;
  /** The key this conversation had before the server bound it — a draft
   *  whose first turn just made it a session. Its tabs carry over. */
  reboundFromKey?: string | null;
  /** Grounding for a side chat; absent before the conversation has a reply. */
  conversation?: ViewerConversation | null;
  /** Store scope for reading this conversation's side chats. */
  workspaceId?: string | null;
  onClose: () => void;
  onAutoOpen: () => void;
  /** Aggregated session activity, shown on the Activity home view. */
  activity: SessionActivity;
  /** Optional capability-config card appended below the activity sections. */
  configSection?: ReactNode;
  taskDraftIds?: string[];
  onTaskDraftChange?: (ids: string[]) => void;
  /** The conversation's skills and connectors, for side chats to narrow to. */
  resourceCatalog?: ComposerResourceCatalog;
  /** Connected agents a side chat can be handed to. */
  agents?: { name: string; kind?: string }[];
}

const NO_AGENTS: { name: string; kind?: string }[] = [];

function fileTabIdFor(a: MessageAttachment, fallback: number): string {
  return `file:${a.id ?? a.filename ?? `idx-${fallback}`}`;
}

function webTabIdFor(url: string): string {
  return `web:${url}`;
}

const markdownNoteTabId = "markdown-note";

/** One launcher tab at a time — a second "+" focuses it instead of piling
 *  up blank tabs. */
const newTabId = "new-tab";

function quizFollowupTabIdFor(questionKey: string): string {
  return `quiz-followup:${questionKey}`;
}

function sideChatTabIdFor(questionKey: string): string {
  return `side-chat:${questionKey}`;
}

const RESPONDER_ICONS: Record<SideChatResponder["kind"], LucideIcon> = {
  dito: MessagesSquare,
  partner: UserRound,
  subagent: Bot,
  partner_group: UsersRound,
};

function geogebraTabIdFor(payloadId: string): string {
  return `geogebra:${payloadId}`;
}

function subagentTabIdFor(callId: string): string {
  return `subagent:${callId}`;
}

/** One icon per kind of tab, shared by the tab bar and the launcher. */
function tabIcon(tab: ViewerTab): LucideIcon {
  switch (tab.kind) {
    case "web":
      return Globe;
    case "markdown-note":
      return NotebookPen;
    case "side-chat":
      return RESPONDER_ICONS[tab.context.sideChat?.responder.kind ?? "dito"];
    case "quiz-followup":
      return MessageSquarePlus;
    case "geogebra":
      return Compass;
    case "subagent":
      return Bot;
    case "new":
      return Plus;
    default:
      return Paperclip;
  }
}

interface StashedTabs {
  tabs: ViewerTab[];
  activeTabId: string | null;
  closedTabs: ViewerTab[];
}

/** Conversations whose tabs are kept for when the learner comes back. */
const STASHED_CONVERSATIONS = 12;
/** Closed tabs offered back on the launcher, newest first. */
const RECENTLY_CLOSED_LIMIT = 4;

function hostnameFor(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 32);
  }
}

function attachmentToPreviewSource(a: MessageAttachment): FilePreviewSource {
  return {
    filename: a.filename || "",
    mimeType: a.mime_type,
    type: a.type,
    url: a.url,
    base64: a.base64,
    extractedText: a.extracted_text,
    id: a.id,
  };
}

/* ------------------------------------------------------------------ */
/*  Panel                                                              */
/* ------------------------------------------------------------------ */

function SessionViewerPanelInner(
  {
    open,
    sessionId,
    sessionKey,
    reboundFromKey = null,
    conversation = null,
    workspaceId = null,
    onClose,
    onAutoOpen,
    activity,
    configSection,
    taskDraftIds,
    onTaskDraftChange,
    resourceCatalog,
    agents = NO_AGENTS,
  }: SessionViewerPanelProps,
  ref: React.Ref<SessionViewerPanelHandle>,
) {
  const { t } = useTranslation();
  const followups = useOptionalQuizFollowupController();
  const [tabs, setTabs] = useState<ViewerTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [closedTabs, setClosedTabs] = useState<ViewerTab[]>([]);

  // Drag-to-resize width. The width is NOT React state — the panel reads it
  // from the ``--viewer-width`` CSS var (so does the chat shell's squeeze),
  // and the drag writes that var directly. This keeps the inline style a
  // constant string (no SSR/client hydration mismatch) and means a drag
  // re-styles one DOM node per frame instead of re-rendering the whole panel
  // every pointer move — the difference between janky and buttery.
  const widthRef = useRef(VIEWER_WIDTH_DEFAULT);
  useEffect(() => {
    // Restore the persisted width after mount (kept out of the initial render
    // so server and client agree on the fallback width).
    widthRef.current = readStoredViewerWidth();
    document.documentElement.style.setProperty(
      VIEWER_WIDTH_VAR,
      `${widthRef.current}px`,
    );
  }, []);

  const startResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    document.documentElement.dataset.viewerResizing = "true";
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    // The panel's right edge sits ``--viewer-inset`` in from the window edge.
    const inset =
      parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue(
          "--viewer-inset",
        ),
      ) || 0;
    let rafId = 0;
    let pendingX = e.clientX;
    const apply = () => {
      rafId = 0;
      const w = clampViewerWidth(window.innerWidth - inset - pendingX);
      widthRef.current = w;
      document.documentElement.style.setProperty(VIEWER_WIDTH_VAR, `${w}px`);
    };
    const onMove = (ev: PointerEvent) => {
      // Coalesce to one var write per frame — pointermove can fire faster
      // than the display refreshes.
      pendingX = ev.clientX;
      if (!rafId) rafId = requestAnimationFrame(apply);
    };
    const onUp = () => {
      if (rafId) cancelAnimationFrame(rafId);
      delete document.documentElement.dataset.viewerResizing;
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      browserStorage.writeRaw(
        "local",
        VIEWER_WIDTH_KEY,
        String(widthRef.current),
      );
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }, []);

  // Tabs belong to the conversation that opened them. Leaving one stashes its
  // tabs and coming back restores them. A draft whose first turn just bound
  // it to a session is the same conversation under a new key: it keeps them.
  const tabsKey = sessionKey ?? sessionId ?? "draft";
  const [stash, setStash] = useState<ReadonlyMap<string, StashedTabs>>(
    () => new Map(),
  );
  const [trackedKey, setTrackedKey] = useState(tabsKey);
  if (trackedKey !== tabsKey) {
    setTrackedKey(tabsKey);
    if (reboundFromKey !== trackedKey) {
      const restored = stash.get(tabsKey);
      // Re-inserted so a Map's insertion order stays oldest-first.
      const next = new Map(stash);
      next.delete(trackedKey);
      next.delete(tabsKey);
      next.set(trackedKey, { tabs, activeTabId, closedTabs });
      for (const key of next.keys()) {
        if (next.size <= STASHED_CONVERSATIONS) break;
        next.delete(key);
      }
      setStash(next);
      setTabs(restored?.tabs ?? []);
      setActiveTabId(restored?.activeTabId ?? null);
      setClosedTabs(restored?.closedTabs ?? []);
    }
  }

  const openFileTab = useCallback(
    (a: MessageAttachment) => {
      setTabs((prev) => {
        const id = fileTabIdFor(a, prev.length);
        const existingIdx = prev.findIndex((tab) => tab.id === id);
        if (existingIdx >= 0) {
          setActiveTabId(id);
          return prev;
        }
        const label = a.filename || "Attachment";
        const next: ViewerTab = {
          kind: "file",
          id,
          label,
          source: attachmentToPreviewSource(a),
        };
        setActiveTabId(id);
        return [...prev, next];
      });
      onAutoOpen();
    },
    [onAutoOpen],
  );

  const openWebTab = useCallback(
    (url: string) => {
      setTabs((prev) => {
        const id = webTabIdFor(url);
        const existingIdx = prev.findIndex((tab) => tab.id === id);
        if (existingIdx >= 0) {
          setActiveTabId(id);
          return prev;
        }
        const next: ViewerTab = {
          kind: "web",
          id,
          label: hostnameFor(url),
          url,
        };
        setActiveTabId(id);
        return [...prev, next];
      });
      onAutoOpen();
    },
    [onAutoOpen],
  );

  const openNewTab = useCallback(() => {
    setTabs((prev) =>
      prev.some((tab) => tab.id === newTabId)
        ? prev
        : [...prev, { kind: "new", id: newTabId, label: t("New tab") }],
    );
    setActiveTabId(newTabId);
  }, [t]);

  /** The launcher tab becomes whatever it opens, browser-style: drop it,
   *  then open (or focus) the target, which lands where it stood. */
  const openFromNewTab = useCallback((openTarget: () => void) => {
    setTabs((prev) => prev.filter((tab) => tab.id !== newTabId));
    openTarget();
  }, []);

  const openMarkdownNoteTab = useCallback(() => {
    setTabs((prev) => {
      const existingIdx = prev.findIndex((tab) => tab.id === markdownNoteTabId);
      if (existingIdx >= 0) {
        setActiveTabId(markdownNoteTabId);
        return prev;
      }
      const next: ViewerTab = {
        kind: "markdown-note",
        id: markdownNoteTabId,
        label: t("Markdown note"),
      };
      setActiveTabId(markdownNoteTabId);
      return [...prev, next];
    });
    onAutoOpen();
  }, [onAutoOpen, t]);

  const openQuizFollowupTab = useCallback(
    (context: QuizFollowupTabContext) => {
      setTabs((prev) => {
        const id = quizFollowupTabIdFor(context.questionKey);
        const existingIdx = prev.findIndex((tab) => tab.id === id);
        // When the tab already exists, refresh its pinned context (answer
        // text, judgment, etc.) since the learner may have updated it
        // since the tab was first opened.
        if (existingIdx >= 0) {
          const refreshed: ViewerTab = {
            kind: "quiz-followup",
            id,
            label: context.tabLabel,
            context,
          };
          const next = [...prev];
          next[existingIdx] = refreshed;
          setActiveTabId(id);
          return next;
        }
        const next: ViewerTab = {
          kind: "quiz-followup",
          id,
          label: context.tabLabel,
          context,
        };
        setActiveTabId(id);
        return [...prev, next];
      });
      onAutoOpen();
    },
    [onAutoOpen],
  );

  // Names for a responder known only by id (a thread reopened from the
  // server); the shared rosters fill them in once loaded.
  const { partners } = usePartnerRoster(open);
  const { groups } = usePartnerGroups(open);
  const named = useCallback(
    (responder: SideChatResponder): SideChatResponder => {
      if (responder.kind === "partner") {
        const partner = partners.find((p) => p.partner_id === responder.id);
        return partner ? { ...responder, name: partner.name } : responder;
      }
      if (responder.kind === "partner_group") {
        const group = groups.find((g) => g.group_id === responder.id);
        return group ? { ...responder, name: group.name } : responder;
      }
      return responder;
    },
    [groups, partners],
  );
  const responderLabel = useCallback(
    (responder: SideChatResponder) => (responder.kind === "dito" ? "Dito" : responder.name),
    [],
  );

  /** Open (or focus) one side chat. */
  const putSideChatTab = useCallback(
    (
      questionKey: string,
      responder: SideChatResponder,
      language: string,
      followupSessionId: string | null = null,
      seedQuote?: { id: number; text: string },
    ) => {
      const id = sideChatTabIdFor(questionKey);
      const label = responderLabel(responder);
      const context: QuizFollowupTabContext = {
        questionKey,
        question: {
          question_id: questionKey,
          question: "",
          question_type: "concept",
          correct_answer: "",
          explanation: "",
        },
        userAnswer: "",
        isCorrect: null,
        answerImages: [],
        aiJudgment: "",
        parentQuizSessionId: null,
        notebookEntryId: null,
        followupSessionId,
        language,
        tabLabel: label,
        sideChat: {
          parentSessionId: sessionId ?? null,
          leafMessageId: conversation?.leafMessageId ?? null,
          parentTitle: conversation?.title,
          responder,
        },
        ...(seedQuote ? { seedQuote } : {}),
      };
      setTabs((prev) => {
        const tab: ViewerTab = { kind: "side-chat", id, label, context };
        const existingIdx = prev.findIndex((open) => open.id === id);
        if (existingIdx < 0) return [...prev, tab];
        const next = [...prev];
        next[existingIdx] = tab;
        return next;
      });
      setActiveTabId(id);
      onAutoOpen();
    },
    [conversation, onAutoOpen, responderLabel, sessionId],
  );

  const seedCounter = useRef(0);
  const openSideChatTab = useCallback(
    ({ responder = DITO, quote }: SideChatOpenOptions = {}) => {
      const text = quote ? normalizeSelectedText(quote) : "";
      const seedQuote = text ? { id: ++seedCounter.current, text } : undefined;
      const sideChats = tabs.filter(
        (tab): tab is Extract<ViewerTab, { kind: "side-chat" }> =>
          tab.kind === "side-chat" &&
          Boolean(tab.context.sideChat) &&
          sameResponder(tab.context.sideChat!.responder, responder),
      );
      // A quote joins the side chat already talking to this responder (the
      // one on screen first); opening one bare reuses only a blank one.
      const target = text
        ? (sideChats.find((tab) => tab.id === activeTabId) ?? sideChats.at(-1))
        : sideChats.find(
            (tab) =>
              !tab.context.followupSessionId &&
              (followups?.getThread(tab.context.questionKey).messages.length ?? 0) === 0,
          );
      if (target) {
        if (seedQuote) {
          setTabs((prev) =>
            prev.map((tab) =>
              tab.id === target.id && tab.kind === "side-chat"
                ? { ...tab, context: { ...tab.context, seedQuote } }
                : tab,
            ),
          );
        }
        setActiveTabId(target.id);
        onAutoOpen();
        return;
      }
      putSideChatTab(
        sideChatKey(sessionId ?? null),
        responder,
        conversation?.language ?? "en",
        null,
        seedQuote,
      );
    },
    [activeTabId, conversation, followups, onAutoOpen, putSideChatTab, sessionId, tabs],
  );

  /** Hand a side chat to someone else: the tab keeps its thread, takes the
   *  new name, and the next message goes to them. */
  const setSideChatResponder = useCallback(
    (tabId: string, responder: SideChatResponder) => {
      setTabs((prev) =>
        prev.map((tab) =>
          tab.id === tabId && tab.kind === "side-chat" && tab.context.sideChat
            ? {
                ...tab,
                label: responderLabel(responder),
                context: {
                  ...tab.context,
                  tabLabel: responderLabel(responder),
                  sideChat: { ...tab.context.sideChat, responder },
                },
              }
            : tab,
        ),
      );
    },
    [responderLabel],
  );

  /** Bring back an earlier side chat, its history read from the server. A
   *  thread still live in this page keeps its key, so its in-flight state
   *  survives. */
  const openSideChatThread = useCallback(
    (thread: SessionSummary) => {
      if (!sessionId) return;
      const prefs = thread.preferences ?? {};
      const live = followups
        ? Object.entries(followups.getAllThreads()).find(
            ([, state]) => state.sessionId === thread.session_id,
          )?.[0]
        : undefined;
      putSideChatTab(
        live ?? `thread:${thread.session_id}`,
        named(responderFromPreferences(prefs)),
        conversation?.language ?? prefs.language ?? "en",
        thread.session_id,
      );
    },
    [conversation, followups, named, putSideChatTab, sessionId],
  );

  const openGeogebraBoard = useCallback(() => {
    const id = geogebraTabIdFor(`board-${Date.now().toString(36)}`);
    setTabs((prev) => [
      ...prev,
      { kind: "geogebra", id, label: t("GeoGebra board"), script: "", editable: true },
    ]);
    setActiveTabId(id);
    onAutoOpen();
  }, [onAutoOpen, t]);

  const openGeogebraTab = useCallback(
    (payload: GeogebraTabPayload) => {
      setTabs((prev) => {
        const id = geogebraTabIdFor(payload.id);
        const existingIdx = prev.findIndex((tab) => tab.id === id);
        if (existingIdx >= 0) {
          // Refresh the script in case the assistant produced an updated
          // version under the same payload id (e.g. a refined figure).
          const refreshed: ViewerTab = {
            kind: "geogebra",
            id,
            label: payload.title || "GeoGebra",
            script: payload.script,
          };
          const next = [...prev];
          next[existingIdx] = refreshed;
          setActiveTabId(id);
          return next;
        }
        const next: ViewerTab = {
          kind: "geogebra",
          id,
          label: payload.title || "GeoGebra",
          script: payload.script,
        };
        setActiveTabId(id);
        return [...prev, next];
      });
      onAutoOpen();
    },
    [onAutoOpen],
  );

  // A connected subagent's run streams into its own tab. The first call (when
  // the consult starts) reveals + focuses the tab; later calls only refresh its
  // events, so live streaming never yanks the user off whatever they're viewing.
  const subagentSeenRef = useRef<Set<string>>(new Set());
  const openSubagentTab = useCallback(
    (callId: string, label: string, events: StreamEvent[], focus = false) => {
      const id = subagentTabIdFor(callId);
      const isNew = !subagentSeenRef.current.has(callId);
      subagentSeenRef.current.add(callId);
      setTabs((prev) => {
        const existingIdx = prev.findIndex((tab) => tab.id === id);
        const tab: ViewerTab = { kind: "subagent", id, label, callId, events };
        if (existingIdx >= 0) {
          const next = [...prev];
          next[existingIdx] = tab;
          return next;
        }
        return [...prev, tab];
      });
      if (isNew || focus) {
        setActiveTabId(id);
        onAutoOpen();
      }
    },
    [onAutoOpen],
  );

  // Open the panel and return to the Activity home (where the
  // capability-config card surfaces). Used by the send-gate.
  const focusActivityHome = useCallback(() => {
    setActiveTabId(null);
    onAutoOpen();
  }, [onAutoOpen]);

  useImperativeHandle(
    ref,
    () => ({
      openFileTab,
      openWebTab,
      openMarkdownNoteTab,
      openQuizFollowupTab,
      openSideChatTab,
      openGeogebraTab,
      openSubagentTab,
      focusActivityHome,
    }),
    [
      openFileTab,
      openWebTab,
      openMarkdownNoteTab,
      openQuizFollowupTab,
      openSideChatTab,
      openGeogebraTab,
      openSubagentTab,
      focusActivityHome,
    ],
  );

  const closeTab = useCallback(
    (id: string) => {
      setTabs((prev) => {
        const idx = prev.findIndex((tab) => tab.id === id);
        if (idx === -1) return prev;
        const closed = prev[idx];
        if (closed.kind !== "new") {
          setClosedTabs((recent) =>
            [closed, ...recent.filter((tab) => tab.id !== id)].slice(
              0,
              RECENTLY_CLOSED_LIMIT,
            ),
          );
        }
        const next = prev.filter((tab) => tab.id !== id);
        if (activeTabId === id) {
          // Fall back to the previous tab, or to the Activity home when none
          // remain — the panel stays open since the home is always useful.
          setActiveTabId(
            next.length === 0
              ? null
              : (next[Math.max(0, idx - 1)] ?? next[0]).id,
          );
        }
        return next;
      });
    },
    [activeTabId],
  );

  const reopenClosedTab = useCallback(
    (id: string) => {
      const closed = closedTabs.find((tab) => tab.id === id);
      if (!closed) return;
      setClosedTabs((recent) => recent.filter((tab) => tab.id !== id));
      setTabs((prev) =>
        prev.some((tab) => tab.id === id)
          ? prev.filter((tab) => tab.id !== newTabId)
          : [...prev.filter((tab) => tab.id !== newTabId), closed],
      );
      setActiveTabId(id);
    },
    [closedTabs],
  );

  // This conversation's side chats, read when the launcher opens —
  // new threads appear between two openings, never while one is on screen.
  const launcherOpen = tabs.some((tab) => tab.id === newTabId) && activeTabId === newTabId;
  const [threads, setThreads] = useState<{ sessionId: string; rows: SessionSummary[] }>({
    sessionId: "",
    rows: [],
  });
  const [threadsRevision, setThreadsRevision] = useState(0);
  useEffect(() => subscribeSessionChanges(() => setThreadsRevision((n) => n + 1)), []);
  useEffect(() => {
    if (!launcherOpen || !sessionId) return;
    const controller = new AbortController();
    listSessionThreads(sessionId, workspaceId ?? undefined, controller.signal)
      .then((rows) => setThreads({ sessionId, rows }))
      .catch(() => {
        /* the launcher simply omits threads it cannot read */
      });
    return () => controller.abort();
  }, [launcherOpen, sessionId, threadsRevision, workspaceId]);

  const openThreadSessionIds = new Set(
    tabs.flatMap((tab) =>
      tab.kind === "side-chat"
        ? [
            followups?.getThread(tab.context.questionKey).sessionId ??
              tab.context.followupSessionId,
          ].filter((value): value is string => Boolean(value))
        : [],
    ),
  );
  const threadRows = threads.sessionId === sessionId ? threads.rows : [];
  const launcherThreads: LauncherThread[] = threadRows
    .filter((row) => !openThreadSessionIds.has(row.session_id))
    .slice(0, 6)
    .map((row) => {
      const responder = named(responderFromPreferences(row.preferences));
      return {
        id: row.session_id,
        title: isPlaceholderSessionTitle(row.title) ? t("Side chat") : row.title,
        detail: t("With {{name}}", { name: responderLabel(responder) }),
        icon: RESPONDER_ICONS[responder.kind],
        updatedAt: row.updated_at,
      };
    });
  const threadIds = new Set(threadRows.map((row) => row.session_id));
  const launcherClosedTabs: LauncherClosedTab[] = closedTabs
    .filter((tab) => !tabs.some((open) => open.id === tab.id))
    // A thread the server already lists is offered there, with its history.
    .filter(
      (tab) =>
        tab.kind !== "side-chat" ||
        !threadIds.has(
          followups?.getThread(tab.context.questionKey).sessionId ??
            tab.context.followupSessionId ??
            "",
        ),
    )
    .map((tab) => ({ id: tab.id, label: tab.label, icon: tabIcon(tab) }));

  // ESC closes the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // The panel is lazy: it usually mounts *because* it was just opened, so its
  // first render is already open and would pop in with no slide. Hold one
  // closed frame after mount so the transition has a start state to run from.
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => setEntered(true));
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, []);

  // The viewer is visible whenever it's open — even with no tabs. The
  // tabs.length === 0 case renders a "Landing" page where the user can
  // paste a URL or pick a local file to open as the first tab.
  const visible = open && entered;
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? null;

  const openLocalFile = useCallback(
    (file: File) => {
      const url = URL.createObjectURL(file);
      openFileTab({
        type: file.type.startsWith("image/") ? "image" : "file",
        filename: file.name,
        mime_type: file.type,
        url,
      });
    },
    [openFileTab],
  );

  /* Below the drawer breakpoint the panel is a full-screen sheet, not a side
     panel: there is no chat column left to sit beside, and VIEWER_WIDTH_MIN is
     wider than the phone it would overlay. That override lives in CSS
     (`max-md:!w-full`) rather than `useDevice()` so it is right on the first
     paint and follows an orientation change for free — the var-driven width
     and its drag handle stay desktop-only machinery. The slide, the inset
     sheet shape, and the shadow live in `.dt-viewer-panel` (globals.css),
     sharing one curve with the chat column's squeeze. */
  return (
    <div
      role="dialog"
      aria-hidden={!visible}
      data-open={visible ? "true" : "false"}
      className="dt-viewer-panel fixed right-0 top-0 z-[30] flex h-dvh flex-col bg-[var(--card)] max-md:!w-full md:max-w-[92vw]"
      style={{
        // Constant string (not a state value) so SSR and the first client
        // render agree; the real width lives in the var, updated imperatively.
        width: `var(${VIEWER_WIDTH_VAR}, ${VIEWER_WIDTH_DEFAULT}px)`,
        willChange: "transform",
      }}
    >
      {/* Left-edge resize handle. A narrow invisible hit-area whose grip pill
          shows on hover — drag left/right to set the panel width. */}
      <div
        onPointerDown={startResize}
        role="separator"
        aria-orientation="vertical"
        aria-label={t("Resize viewer")}
        className="group/resize absolute inset-y-0 left-0 z-10 w-2 cursor-col-resize max-md:hidden"
      >
        <span className="absolute left-[3px] top-1/2 h-10 w-[3px] -translate-y-1/2 rounded-full bg-transparent transition-colors group-hover/resize:bg-[color-mix(in_srgb,var(--muted-foreground)_35%,transparent)]" />
      </div>
      <TabBar
        tabs={tabs}
        activeTabId={activeTabId}
        homeActive={activeTab === null}
        onSelectHome={() => setActiveTabId(null)}
        onSelect={setActiveTabId}
        onCloseTab={closeTab}
        onNewTab={openNewTab}
        onClosePanel={onClose}
        agents={agents}
        actions={
          activeTab?.kind === "file" ? (
            <FileTabActions source={activeTab.source} />
          ) : null
        }
      />
      <div className="relative min-h-0 flex-1 overflow-hidden bg-[var(--card)]">
        {activeTab?.kind === "file" ? (
          <FileTabBody source={activeTab.source} />
        ) : activeTab?.kind === "web" ? (
          <WebTabBody key={activeTab.url} url={activeTab.url} />
        ) : activeTab?.kind === "markdown-note" ? (
          <ChatMarkdownNoteTabBody
            key={`${activeTab.id}:${sessionId ?? "pending"}`}
            sessionId={sessionId}
          />
        ) : activeTab?.kind === "quiz-followup" ? (
          <QuizFollowupTabBody
            key={activeTab.context.questionKey}
            context={activeTab.context}
            resourceCatalog={resourceCatalog}
          />
        ) : activeTab?.kind === "side-chat" ? (
          <QuizFollowupTabBody
            key={activeTab.context.questionKey}
            context={activeTab.context}
            resourceCatalog={resourceCatalog}
            agents={agents}
            onResponderChange={(responder) =>
              setSideChatResponder(activeTab.id, responder)
            }
          />
        ) : activeTab?.kind === "geogebra" ? (
          <GeogebraTabBody
            key={activeTab.id}
            script={activeTab.script}
            editable={activeTab.editable}
          />
        ) : activeTab?.kind === "new" ? (
          <ViewerLauncher
            onOpenUrl={(url) => openFromNewTab(() => openWebTab(url))}
            onOpenLocalFile={(file) => openFromNewTab(() => openLocalFile(file))}
            onOpenMarkdownNote={() => openFromNewTab(openMarkdownNoteTab)}
            onOpenGeogebraBoard={() => openFromNewTab(openGeogebraBoard)}
            // Always open: beside a draft it is a conversation of its own.
            onOpenSideChat={(responder) =>
              openFromNewTab(() => openSideChatTab({ responder }))
            }
            sideChatAboutConversation={Boolean(sessionId && conversation)}
            sideChatAgents={agents}
            sideChatShortcut={SHORTCUTS.sideChat}
            threads={launcherThreads}
            onOpenThread={(id) => {
              const row = threadRows.find((thread) => thread.session_id === id);
              if (row) openFromNewTab(() => openSideChatThread(row));
            }}
            closedTabs={launcherClosedTabs}
            onReopenTab={reopenClosedTab}
          />
        ) : activeTab?.kind === "subagent" ? (
          <ConsultationTabBody
            key={activeTab.id}
            tabEvents={activeTab.events}
            sessionId={sessionId}
          />
        ) : (
          <ActivityHome
            sessionId={sessionId}
            taskDraftIds={taskDraftIds}
            onTaskDraftChange={onTaskDraftChange}
            activity={activity}
            open={visible}
            configSection={configSection}
            onOpenAttachment={openFileTab}
            onClose={onClose}
          />
        )}
      </div>
    </div>
  );
}

const SessionViewerPanel = memo(forwardRef(SessionViewerPanelInner));
export default SessionViewerPanel;

/* ------------------------------------------------------------------ */
/*  Tab bar                                                            */
/* ------------------------------------------------------------------ */

/**
 * Pill tab bar. No band behind it and no browser-tab chrome: the header is
 * the panel's own surface, the focused tab is a soft filled pill and the
 * rest are quiet text that tint on hover. The Activity home is always first
 * and never closeable; a tab's close button stays visible on the focused tab
 * and appears on hover for the others.
 */
const TAB_PILL =
  "inline-flex h-7 shrink-0 items-center rounded-lg text-[12.5px] font-medium transition-colors";
const TAB_ACTIVE =
  "bg-[color-mix(in_srgb,var(--muted)_85%,transparent)] text-[var(--foreground)]";
const TAB_IDLE =
  "text-[var(--muted-foreground)] hover:bg-[color-mix(in_srgb,var(--muted)_55%,transparent)] hover:text-[var(--foreground)]";
const TAB_FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--ring)]";
const HEADER_ICON = `inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] hover:text-[var(--foreground)] disabled:pointer-events-none disabled:opacity-40 ${TAB_FOCUS}`;

function TabBar({
  tabs,
  activeTabId,
  homeActive,
  onSelectHome,
  onSelect,
  onCloseTab,
  onNewTab,
  onClosePanel,
  agents,
  actions,
}: {
  tabs: ViewerTab[];
  /** Connected agents, so an agent's side chat wears its own glyph. */
  agents: { name: string; kind?: string }[];
  activeTabId: string | null;
  homeActive: boolean;
  onSelectHome: () => void;
  onSelect: (id: string) => void;
  onCloseTab: (id: string) => void;
  onNewTab: () => void;
  onClosePanel: () => void;
  /** The focused tab's own actions (download, open in browser), kept in the
   *  header so they don't cost the content a row of their own. */
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex h-12 shrink-0 items-center gap-1 pl-2.5 pr-2">
      <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <button
          type="button"
          onClick={onSelectHome}
          aria-pressed={homeActive}
          className={`${TAB_PILL} ${TAB_FOCUS} gap-1.5 px-2.5 ${homeActive ? TAB_ACTIVE : TAB_IDLE}`}
        >
          <Activity size={13} strokeWidth={1.8} className="shrink-0" />
          <span>{t("Activity")}</span>
        </button>
        {tabs.map((tab) => {
          const active = tab.id === activeTabId;
          const Icon = tabIcon(tab);
          return (
            <div
              key={tab.id}
              className={`group ${TAB_PILL} max-w-[190px] ${active ? TAB_ACTIVE : TAB_IDLE}`}
            >
              <button
                type="button"
                onClick={() => onSelect(tab.id)}
                aria-pressed={active}
                aria-label={tab.label}
                className={`inline-flex h-full min-w-0 flex-1 items-center gap-1.5 rounded-lg pl-2.5 pr-1 text-left ${TAB_FOCUS}`}
              >
                {/* A side chat wears the face of whoever answers it. */}
                {tab.kind === "side-chat" && tab.context.sideChat ? (
                  <ResponderFace
                    responder={tab.context.sideChat.responder}
                    agents={agents}
                    size={13}
                  />
                ) : (
                  <Icon size={13} strokeWidth={1.8} className="shrink-0" />
                )}
                <span className="truncate">{tab.label}</span>
              </button>
              <Tooltip label={t("Close tab")} side="bottom">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCloseTab(tab.id);
                  }}
                  className={`mr-1 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] transition-[opacity,background-color,color] hover:bg-[color-mix(in_srgb,var(--foreground)_8%,transparent)] hover:text-[var(--foreground)] focus-visible:opacity-100 ${TAB_FOCUS} ${
                    active ? "opacity-70" : "opacity-0 group-hover:opacity-70"
                  }`}
                  aria-label={t("Close tab")}
                >
                  <X size={12} strokeWidth={2} />
                </button>
              </Tooltip>
            </div>
          );
        })}
      </div>
      {actions ? (
        <>
          {actions}
          <span
            aria-hidden="true"
            className="mx-1 h-4 w-px shrink-0 bg-[color-mix(in_srgb,var(--border)_85%,transparent)]"
          />
        </>
      ) : null}
      <Tooltip label={t("New tab")} side="bottom">
        <button
          type="button"
          onClick={onNewTab}
          className={HEADER_ICON}
          aria-label={t("New tab")}
        >
          <Plus size={16} strokeWidth={1.8} />
        </button>
      </Tooltip>
      <Tooltip label={t("Close viewer")} side="bottom">
        <button
          type="button"
          onClick={onClosePanel}
          className={HEADER_ICON}
          aria-label={t("Close viewer")}
        >
          <X size={15} strokeWidth={1.8} />
        </button>
      </Tooltip>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Activity home — the panel's default view (no tab focused)          */
/* ------------------------------------------------------------------ */

/**
 * The Activity landing: what this conversation has done — tasks, tools, KBs,
 * Space refs, files (see ``ActivityBody``). Opening something new lives on
 * the "+" launcher alone. Clicking a file opens it as a tab in this panel.
 */
function ActivityHome({
  sessionId,
  taskDraftIds,
  onTaskDraftChange,
  activity,
  open,
  configSection,
  onOpenAttachment,
  onClose,
}: {
  sessionId: string | null;
  taskDraftIds?: string[];
  onTaskDraftChange?: (ids: string[]) => void;
  activity: SessionActivity;
  open: boolean;
  configSection?: ReactNode;
  onOpenAttachment: (a: MessageAttachment) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="h-full space-y-5 overflow-y-auto px-3 pb-8 pt-1 sm:px-3.5">
      <div className="sticky top-0 z-10 -mx-3 flex justify-start border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--card)_94%,transparent)] px-3 py-2 backdrop-blur-sm sm:-mx-3.5 sm:px-3.5">
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-9 items-center gap-2 rounded-lg px-2.5 text-sm font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          aria-label={t("Back to conversation")}
        >
          <ArrowLeft size={16} strokeWidth={1.8} />
          <span>{t("Back to conversation")}</span>
        </button>
      </div>
      <TaskPanelSection
        sessionId={sessionId}
        draftTaskIds={taskDraftIds}
        onDraftChange={onTaskDraftChange}
      />
      <ActivityBody
        activity={activity}
        open={open}
        onOpenAttachment={onOpenAttachment}
        configSection={configSection}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  File tab body                                                      */
/* ------------------------------------------------------------------ */

/** Where a file tab's bytes can be fetched: the served URL, or a data URL
 *  for a pending (un-sent) base64 attachment so download / open-in-browser
 *  still work before it is uploaded. */
function fileUrlFor(source: FilePreviewSource): string | null {
  const previewUrl = resolveSourceUrl(source, apiUrl);
  if (previewUrl) return previewUrl;
  if (source.base64) {
    const mime = source.mimeType || "application/octet-stream";
    return `data:${mime};base64,${source.base64}`;
  }
  return null;
}

/** Download + open-in-browser for the focused file tab, shown in the tab
 *  bar. The tab already names the file, so these are bare icons. */
function FileTabActions({ source }: { source: FilePreviewSource }) {
  const { t } = useTranslation();
  const fileUrl = useMemo(() => fileUrlFor(source), [source]);
  const filename = source.filename || t("Attachment");
  return (
    <>
      {fileUrl ? (
        <Tooltip label={t("Download")} side="bottom">
          <a
            href={fileUrl}
            download={filename}
            className={HEADER_ICON}
            aria-label={t("Download")}
          >
            <Download size={15} strokeWidth={1.8} />
          </a>
        </Tooltip>
      ) : null}
      <Tooltip label={t("Open in browser")} side="bottom">
        <button
          type="button"
          onClick={() => {
            if (fileUrl) window.open(fileUrl, "_blank", "noopener,noreferrer");
          }}
          disabled={!fileUrl}
          className={HEADER_ICON}
          aria-label={t("Open in browser")}
        >
          <ExternalLink size={14} strokeWidth={1.8} />
        </button>
      </Tooltip>
    </>
  );
}

function FileTabBody({ source }: { source: FilePreviewSource }) {
  const previewUrl = useMemo(() => resolveSourceUrl(source, apiUrl), [source]);
  const kind = previewKindFor(source);
  return (
    <div className="relative h-full overflow-hidden">
      <PreviewBody source={source} previewUrl={previewUrl} kind={kind} />
    </div>
  );
}

const PreviewBody = memo(function PreviewBody({
  source,
  previewUrl,
  kind,
}: {
  source: FilePreviewSource;
  previewUrl: string | null;
  kind: ReturnType<typeof previewKindFor> | null;
}) {
  const filename = source.filename;

  if (kind === "office-text") {
    const fallback = (
      <OfficeTextPreview
        filename={filename}
        extractedText={source.extractedText}
        url={previewUrl}
      />
    );
    if (previewUrl) {
      return (
        <OfficePdfPreview url={previewUrl} filename={filename} fallback={fallback} />
      );
    }
    return fallback;
  }

  if (!previewUrl) {
    return <FallbackPreview filename={filename} url={null} reason="legacy" />;
  }

  switch (kind) {
    case "pdf":
      return <PdfPreview url={previewUrl} filename={filename} />;
    case "docx":
      return (
        <OfficePdfPreview
          url={previewUrl}
          filename={filename}
          fallback={<DocxPreview url={previewUrl} />}
        />
      );
    case "xlsx":
      return (
        <OfficePdfPreview
          url={previewUrl}
          filename={filename}
          fallback={<XlsxPreview url={previewUrl} />}
        />
      );
    case "image":
      return <ImagePreview url={previewUrl} filename={filename} />;
    case "video":
      return <VideoPreview url={previewUrl} filename={filename} />;
    case "svg":
      return <SvgPreview url={previewUrl} filename={filename} />;
    case "markdown":
      return (
        <div className="h-full overflow-y-auto">
          <MarkdownPreview url={previewUrl} />
        </div>
      );
    case "code":
    case "text":
      return (
        <div className="h-full overflow-y-auto">
          <TextPreview url={previewUrl} filename={filename} />
        </div>
      );
    case "fallback":
    default:
      return <FallbackPreview filename={filename} url={previewUrl} />;
  }
});

/* ------------------------------------------------------------------ */
/*  Web tab body — iframe with safety fallback                         */
/* ------------------------------------------------------------------ */

/**
 * Web preview tab. Many sites set `X-Frame-Options: DENY` or a CSP
 * `frame-ancestors` directive that flat-out refuses iframe embedding — a
 * browser-enforced anti-clickjacking measure we can't bypass from the
 * frontend. We can't *detect* the failure reliably either (cross-origin
 * iframes are opaque to JS), so we lean on UX honesty:
 *
 *  • A persistent info banner at the top tells the user upfront that some
 *    sites won't load, and exposes "Open in browser" as a big primary
 *    action right next to it.
 *  • A loading spinner is overlaid until either `onLoad` fires or a soft
 *    timeout (4.5 s) elapses. After the timeout we switch the banner copy
 *    to a more explicit "site likely refused embedding" warning so the
 *    user knows the spinner isn't a real load-in-progress.
 */
function WebTabBody({ url }: { url: string }) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const host = hostnameFor(url);

  const openInBrowser = useCallback(() => {
    window.open(url, "_blank", "noopener,noreferrer");
  }, [url]);

  useEffect(() => {
    const timer = window.setTimeout(() => setTimedOut(true), 4500);
    return () => window.clearTimeout(timer);
  }, []);

  const blocked = timedOut && !loaded;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-[color-mix(in_srgb,var(--border)_40%,transparent)] bg-[var(--card)] px-4 py-2.5">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[color-mix(in_srgb,var(--muted)_55%,transparent)]">
          <Globe
            size={14}
            strokeWidth={1.7}
            className="text-[var(--muted-foreground)]"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-semibold text-[var(--foreground)]">
            {host}
          </div>
          <div className="truncate text-[10px] text-[var(--muted-foreground)]">
            {url}
          </div>
        </div>
        <button
          type="button"
          onClick={openInBrowser}
          className={`inline-flex shrink-0 items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold transition-colors ${
            blocked
              ? "bg-[var(--primary)] text-[var(--primary-foreground)] hover:bg-[color-mix(in_srgb,var(--primary)_90%,transparent)]"
              : "border border-[color-mix(in_srgb,var(--border)_55%,transparent)] text-[var(--muted-foreground)] hover:border-[color-mix(in_srgb,var(--primary)_35%,transparent)] hover:text-[var(--primary)]"
          }`}
        >
          <ExternalLink size={11} strokeWidth={1.9} />
          {t("Open in browser")}
        </button>
      </div>

      {/* Persistent info banner — explains the iframe limitation. Swaps to
          a louder warning once we suspect the site has refused to embed. */}
      <div
        className={`flex shrink-0 items-start gap-2 border-b border-[color-mix(in_srgb,var(--border)_30%,transparent)] px-4 py-2 text-[11px] leading-snug ${
          blocked
            ? "bg-[color-mix(in_srgb,var(--primary)_8%,var(--card))] text-[var(--foreground)]"
            : "bg-[color-mix(in_srgb,var(--muted)_45%,var(--card))] text-[var(--muted-foreground)]"
        }`}
      >
        <AlertCircle
          size={12}
          strokeWidth={1.9}
          className={`mt-[1px] shrink-0 ${
            blocked ? "text-[var(--primary)]" : "text-[var(--muted-foreground)]"
          }`}
        />
        <span>
          {blocked
            ? t(
                "This site looks like it refused to embed (its security headers block iframes). Use “Open in browser” to view it in a real tab.",
              )
            : t(
                "Many sites refuse to embed for security reasons. If the page below stays blank, use “Open in browser”.",
              )}
        </span>
      </div>

      <div className="relative flex-1 overflow-hidden bg-[var(--background)]">
        <iframe
          key={url}
          src={url}
          title={host}
          onLoad={() => setLoaded(true)}
          className="h-full w-full border-0"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          referrerPolicy="no-referrer"
        />
        {!loaded && !timedOut ? (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 bg-[color-mix(in_srgb,var(--card)_70%,transparent)] text-[12px] text-[var(--muted-foreground)] backdrop-blur-sm">
            <Loader2
              size={18}
              strokeWidth={1.7}
              className="animate-spin text-[color-mix(in_srgb,var(--primary)_80%,transparent)]"
            />
            <span>{t("Loading {{host}}…", { host })}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Geogebra tab body                                                  */
/* ------------------------------------------------------------------ */

/**
 * Renders an interactive GeoGebra applet for a ggbscript payload. The
 * heavy lifting (deployggb.js load + applet mount + evalCommand loop)
 * lives in the shared ``Geogebra`` component; this body just gives it
 * the right size and chrome inside the tab.
 */
/** The applet is sized once, to the tab as it opens: GeoGebra rebuilds (and
 *  loses the learner's drawing) whenever its size props change. */
function GeogebraTabBody({
  script,
  editable = false,
}: {
  script: string;
  editable?: boolean;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(
    null,
  );
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    setSize({
      width: Math.max(320, Math.floor(frame.clientWidth) - 24),
      height: Math.max(360, Math.floor(frame.clientHeight) - 24),
    });
  }, []);
  return (
    <div ref={frameRef} className="h-full w-full overflow-auto bg-[var(--card)] p-3">
      {size ? (
        <Geogebra
          script={script}
          editable={editable}
          width={size.width}
          height={size.height}
          className="m-0 border-0 bg-transparent"
        />
      ) : null}
    </div>
  );
}
