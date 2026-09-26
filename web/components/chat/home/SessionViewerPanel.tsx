"use client";

import { browserStorage } from "@/shared/storage";

/**
 * SessionViewerPanel — full right-side sidebar with browser-style tabs that
 * can hold (a) attachment previews and (b) embedded web pages clicked from
 * assistant messages.
 *
 * - Tabs across the top of the panel; each closeable.
 * - File tabs use the same lazy previewer set as FilePreviewDrawer.
 * - Web tabs render an iframe of the URL. Cross-origin frames may refuse
 *   to load — we expose an "Open in browser" affordance so the user can
 *   always fall back. The user's network ultimately decides what loads.
 * - Imperative API via ref: openFileTab(att), openWebTab(url).
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
  ArrowRight,
  ChevronRight,
  Compass,
  Download,
  ExternalLink,
  FileUp,
  Globe,
  GraduationCap,
  Loader2,
  MessageSquarePlus,
  NotebookPen,
  Paperclip,
  Plus,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  previewKindFor,
  resolveSourceUrl,
  type FilePreviewSource,
} from "@/components/chat/preview/previewerFor";
import {
  ACTIVITY_LABEL,
  ACTIVITY_ROW_HOVER,
  ACTIVITY_TILE,
  ActivityBody,
  type SessionActivity,
} from "@/components/chat/home/SessionActivityPanel";
import QuizFollowupTabBody from "@/components/quiz/QuizFollowupTabBody";
import ConsultationTabBody from "@/components/chat/home/ConsultationTabBody";
import type { QuizFollowupTabContext } from "@/context/QuizFollowupContext";
import type { GeogebraTabPayload } from "@/context/GeogebraTabContext";
import { apiUrl } from "@/lib/api";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import type { StreamEvent } from "@/features/chat/model/protocol";
import {
  normalizeSelectedText,
  selectionTutorKey,
  type SelectionTutorContext,
} from "@/lib/selection-tutor";

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
      kind: "selection-tutor";
      id: string;
      label: string;
      context: QuizFollowupTabContext;
    }
  | {
      kind: "geogebra";
      id: string;
      label: string;
      script: string;
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
  /** Opens an independent Little Tutor thread grounded in selected chat text. */
  openSelectionTutorTab(
    selection: SelectionTutorContext,
    language: string,
  ): void;
  /** Opens (or focuses) an interactive GeoGebra applet tab. */
  openGeogebraTab(payload: GeogebraTabPayload): void;
  /** Opens (first time) or live-updates a connected subagent's run tab. */
  openSubagentTab(callId: string, label: string, events: StreamEvent[], focus?: boolean): void;
  /** Opens the panel and switches to the Activity home (where the
   *  capability-config card lives). */
  focusActivityHome(): void;
}

export interface SessionViewerPanelProps {
  open: boolean;
  sessionId: string | null;
  onClose: () => void;
  onAutoOpen: () => void;
  /** Aggregated session activity, shown on the Activity home view. */
  activity: SessionActivity;
  /** Optional capability-config card appended below the activity sections. */
  configSection?: ReactNode;
}

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

function selectionTutorTabIdFor(questionKey: string): string {
  return `selection-tutor:${questionKey}`;
}

function geogebraTabIdFor(payloadId: string): string {
  return `geogebra:${payloadId}`;
}

function subagentTabIdFor(callId: string): string {
  return `subagent:${callId}`;
}

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
    onClose,
    onAutoOpen,
    activity,
    configSection,
  }: SessionViewerPanelProps,
  ref: React.Ref<SessionViewerPanelHandle>,
) {
  const { t } = useTranslation();
  const [tabs, setTabs] = useState<ViewerTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);

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

  // Wipe tabs whenever the session changes — preview/web state belongs to
  // the conversation that triggered it.
  const [trackedSessionId, setTrackedSessionId] = useState<string | null>(
    sessionId,
  );
  if (trackedSessionId !== sessionId) {
    setTrackedSessionId(sessionId);
    setTabs([]);
    setActiveTabId(null);
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

  const openSelectionTutorTab = useCallback(
    (selection: SelectionTutorContext, language: string) => {
      const selectedText = normalizeSelectedText(selection.selectedText);
      if (!selectedText) return;
      const questionKey = selectionTutorKey(
        selectedText,
        sessionId,
        selection.sourceMessageId,
      );
      const id = selectionTutorTabIdFor(questionKey);
      const context: QuizFollowupTabContext = {
        questionKey,
        question: {
          question_id: questionKey,
          question: selectedText,
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
        followupSessionId: null,
        language,
        tabLabel: t("Little Tutor"),
        tutorSelection: {
          selectedText,
          parentSessionId: sessionId,
          sourceMessageId: selection.sourceMessageId,
          sourceMessageText: selection.sourceMessageText,
          sourceMessageRole: selection.sourceMessageRole,
        },
      };

      setTabs((prev) => {
        const existingIdx = prev.findIndex((tab) => tab.id === id);
        const tab: ViewerTab = {
          kind: "selection-tutor",
          id,
          label: t("Little Tutor"),
          context,
        };
        if (existingIdx >= 0) {
          const next = [...prev];
          next[existingIdx] = tab;
          setActiveTabId(id);
          return next;
        }
        setActiveTabId(id);
        return [...prev, tab];
      });
      onAutoOpen();
    },
    [onAutoOpen, sessionId, t],
  );

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
      openSelectionTutorTab,
      openGeogebraTab,
      openSubagentTab,
      focusActivityHome,
    }),
    [
      openFileTab,
      openWebTab,
      openMarkdownNoteTab,
      openQuizFollowupTab,
      openSelectionTutorTab,
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
          />
        ) : activeTab?.kind === "selection-tutor" ? (
          <QuizFollowupTabBody
            key={activeTab.context.questionKey}
            context={activeTab.context}
          />
        ) : activeTab?.kind === "geogebra" ? (
          <GeogebraTabBody key={activeTab.id} script={activeTab.script} />
        ) : activeTab?.kind === "new" ? (
          <div className="h-full overflow-y-auto px-3 pb-8 pt-1 sm:px-3.5">
            <ActivityOpener
              autoFocus
              onOpenWebTab={(url) => openFromNewTab(() => openWebTab(url))}
              onOpenLocalFile={(file) =>
                openFromNewTab(() => openLocalFile(file))
              }
              onOpenMarkdownNote={() => openFromNewTab(openMarkdownNoteTab)}
            />
          </div>
        ) : activeTab?.kind === "subagent" ? (
          <ConsultationTabBody
            key={activeTab.id}
            tabEvents={activeTab.events}
            sessionId={sessionId}
          />
        ) : (
          <ActivityHome
            activity={activity}
            open={visible}
            configSection={configSection}
            onOpenAttachment={openFileTab}
            onOpenWebTab={openWebTab}
            onOpenLocalFile={openLocalFile}
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
  actions,
}: {
  tabs: ViewerTab[];
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
          title={t("Activity")}
        >
          <Activity size={13} strokeWidth={1.8} className="shrink-0" />
          <span>{t("Activity")}</span>
        </button>
        {tabs.map((tab) => {
          const active = tab.id === activeTabId;
          const Icon =
            tab.kind === "web"
              ? Globe
              : tab.kind === "markdown-note"
                ? NotebookPen
                : tab.kind === "selection-tutor"
                  ? GraduationCap
                  : tab.kind === "quiz-followup"
                    ? MessageSquarePlus
                    : tab.kind === "geogebra"
                      ? Compass
                      : tab.kind === "new"
                        ? Plus
                        : Paperclip;
          return (
            <div
              key={tab.id}
              className={`group ${TAB_PILL} max-w-[190px] ${active ? TAB_ACTIVE : TAB_IDLE}`}
              title={tab.label}
            >
              <button
                type="button"
                onClick={() => onSelect(tab.id)}
                aria-pressed={active}
                className={`inline-flex h-full min-w-0 flex-1 items-center gap-1.5 rounded-lg pl-2.5 pr-1 text-left ${TAB_FOCUS}`}
              >
                <Icon size={13} strokeWidth={1.8} className="shrink-0" />
                <span className="truncate">{tab.label}</span>
              </button>
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
      <button
        type="button"
        onClick={onNewTab}
        className={HEADER_ICON}
        aria-label={t("New tab")}
        title={t("New tab")}
      >
        <Plus size={16} strokeWidth={1.8} />
      </button>
      <button
        type="button"
        onClick={onClosePanel}
        className={HEADER_ICON}
        aria-label={t("Close viewer")}
        title={t("Close viewer")}
      >
        <X size={15} strokeWidth={1.8} />
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Activity home — the panel's default view (no tab focused)          */
/* ------------------------------------------------------------------ */

/**
 * The merged Activity landing: the session-activity sections (tools, KBs,
 * Space refs, attachments — see ``ActivityBody``) plus a compact opener for
 * a URL or a local file. Clicking an attachment opens it as a file tab in
 * this same panel.
 */
function ActivityHome({
  activity,
  open,
  configSection,
  onOpenAttachment,
  onOpenWebTab,
  onOpenLocalFile,
}: {
  activity: SessionActivity;
  open: boolean;
  configSection?: ReactNode;
  onOpenAttachment: (a: MessageAttachment) => void;
  onOpenWebTab: (url: string) => void;
  onOpenLocalFile: (file: File) => void;
}) {
  return (
    <div className="h-full space-y-5 overflow-y-auto px-3 pb-8 pt-1 sm:px-3.5">
      <ActivityBody
        activity={activity}
        open={open}
        onOpenAttachment={onOpenAttachment}
        configSection={configSection}
      />
      <ActivityOpener
        onOpenWebTab={onOpenWebTab}
        onOpenLocalFile={onOpenLocalFile}
      />
    </div>
  );
}

// A URL is not translatable — and routed through t() its "https:" prefix
// reads as an i18next namespace separator and is eaten ("//example.com").
const URL_PLACEHOLDER = "https://example.com";

/** Two quiet action rows for opening a URL or local file as a viewer tab. */
function ActivityOpener({
  onOpenWebTab,
  onOpenLocalFile,
  onOpenMarkdownNote,
  autoFocus = false,
}: {
  onOpenWebTab: (url: string) => void;
  onOpenLocalFile: (file: File) => void;
  /** Offered on the "+" launcher tab; the Activity home has its own route to
   *  the note (the chat header's note button). */
  onOpenMarkdownNote?: () => void;
  autoFocus?: boolean;
}) {
  const { t } = useTranslation();
  const [urlInput, setUrlInput] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const submitUrl = useCallback(() => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
    const href = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    onOpenWebTab(href);
    setUrlInput("");
  }, [urlInput, onOpenWebTab]);

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onOpenLocalFile(file);
      e.target.value = "";
    },
    [onOpenLocalFile],
  );

  return (
    <section>
      <h2 className={ACTIVITY_LABEL}>{t("Open")}</h2>
      <div className={`${ACTIVITY_TILE} p-1`}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submitUrl();
          }}
          className={`flex min-h-10 items-center gap-2.5 rounded-lg px-2.5 transition-colors ${ACTIVITY_ROW_HOVER} focus-within:bg-[var(--card)] focus-within:shadow-[0_0_0_1px_color-mix(in_srgb,var(--ring)_55%,transparent)]`}
        >
          <Globe
            size={15}
            strokeWidth={1.7}
            aria-hidden="true"
            className="shrink-0 text-[var(--muted-foreground)]"
          />
          <input
            type="text"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            aria-label={t("Open URL")}
            placeholder={URL_PLACEHOLDER}
            autoFocus={autoFocus}
            className="min-w-0 flex-1 bg-transparent text-[12.5px] text-[var(--foreground)] outline-none placeholder:text-[color-mix(in_srgb,var(--muted-foreground)_75%,transparent)]"
          />
          <button
            type="submit"
            disabled={!urlInput.trim()}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)] transition-[opacity,background-color] hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:bg-transparent disabled:text-[var(--muted-foreground)] disabled:opacity-50"
            aria-label={t("Open URL")}
          >
            <ArrowRight size={13} strokeWidth={2} />
          </button>
        </form>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className={`group flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[12.5px] font-medium text-[var(--foreground)] transition-colors ${ACTIVITY_ROW_HOVER} focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--ring)]`}
        >
          <FileUp size={15} strokeWidth={1.7} aria-hidden="true" className="shrink-0 text-[var(--muted-foreground)]" />
          <span className="min-w-0 flex-1 truncate">{t("Open a local file")}</span>
          <ChevronRight size={14} strokeWidth={1.7} aria-hidden="true" className="shrink-0 text-[var(--muted-foreground)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
        </button>
        {onOpenMarkdownNote ? (
          <button
            type="button"
            onClick={onOpenMarkdownNote}
            className={`group flex min-h-10 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[12.5px] font-medium text-[var(--foreground)] transition-colors ${ACTIVITY_ROW_HOVER} focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[var(--ring)]`}
          >
            <NotebookPen size={15} strokeWidth={1.7} aria-hidden="true" className="shrink-0 text-[var(--muted-foreground)]" />
            <span className="min-w-0 flex-1 truncate">{t("Markdown note")}</span>
            <ChevronRight size={14} strokeWidth={1.7} aria-hidden="true" className="shrink-0 text-[var(--muted-foreground)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
          </button>
        ) : null}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleFileSelect}
        aria-hidden="true"
        tabIndex={-1}
      />
    </section>
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
        <a
          href={fileUrl}
          download={filename}
          className={HEADER_ICON}
          aria-label={t("Download")}
          title={t("Download")}
        >
          <Download size={15} strokeWidth={1.8} />
        </a>
      ) : null}
      <button
        type="button"
        onClick={() => {
          if (fileUrl) window.open(fileUrl, "_blank", "noopener,noreferrer");
        }}
        disabled={!fileUrl}
        className={HEADER_ICON}
        aria-label={t("Open in browser")}
        title={t("Open in browser")}
      >
        <ExternalLink size={14} strokeWidth={1.8} />
      </button>
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
function GeogebraTabBody({ script }: { script: string }) {
  return (
    <div className="h-full w-full overflow-auto bg-[var(--card)] p-3">
      <Geogebra
        script={script}
        width={560}
        height={520}
        className="m-0 border-0 bg-transparent"
      />
    </div>
  );
}
