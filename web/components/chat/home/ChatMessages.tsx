"use client";

import dynamic from "next/dynamic";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Bot,
  Brain,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Coins,
  Copy,
  AlertCircle,
  Database,
  Loader2,
  MessageSquare,
  Pencil,
  RefreshCcw,
  Square,
  UserRound,
  Volume2,
  X,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import AssistantResponse from "@/components/common/AssistantResponse";
import {
  InlineFileCardProvider,
  mergeGeneratedFiles,
} from "@/components/common/InlineFileCard";
import Tooltip from "@/components/common/Tooltip";
import type {
  MessageAttachment,
  MessageRequestSnapshot,
} from "@/context/UnifiedChatContext";
import { apiFetch, apiUrl } from "@/lib/api";
import { docIconFor } from "@/lib/doc-attachments";
import { useVoiceAutoplay } from "@/hooks/useVoiceAutoplay";
import { extractMathAnimatorResult } from "@/lib/math-animator-types";
import {
  extractQuizQuestions,
  extractStreamingQuizQuestions,
} from "@/lib/quiz-types";
import { extractVisualizeResult } from "@/lib/visualize-types";
import type { StreamEvent } from "@/lib/unified-ws";
import { hasVisibleMarkdownContent } from "@/lib/markdown-display";
import type { SelectedBookReference } from "@/lib/book-references";
import { buildVisiblePath, type SiblingInfo } from "@/lib/message-branches";
import type { SpaceMemoryFile } from "@/lib/space-items";
import {
  AskUserOptions,
  extractAskUserPayload,
  extractMessageSegments,
} from "./AskUserOptions";
import ContextReferenceTree, {
  type ContextTreeItem,
} from "./ContextReferenceTree";
import { AssistantActivity } from "./TracePanels";
import { agentGlyph } from "@/components/agents/agent-icons";
import { useConnectedAgentKinds } from "@/hooks/useConnectedAgentKinds";

const MathAnimatorViewer = dynamic(
  () => import("@/components/math-animator/MathAnimatorViewer"),
  { ssr: false },
);
const QuizViewer = dynamic(() => import("@/components/quiz/QuizViewer"), {
  ssr: false,
});
const ResearchOutlineEditor = dynamic(
  () => import("@/components/research/ResearchOutlineEditor"),
  { ssr: false },
);
const VisualizationViewer = dynamic(
  () => import("@/components/visualize/VisualizationViewer"),
  { ssr: false },
);

interface ChatMessageItem {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
  capability?: string;
  events?: StreamEvent[];
  attachments?: MessageAttachment[];
  requestSnapshot?: MessageRequestSnapshot;
  parentMessageId?: number | null;
}

interface NotebookReferenceGroup {
  notebookId: string;
  notebookName: string;
  count: number;
}

// Returns the i18n key (and a sensible fallback) for the capability badge
// shown above the user's message. Callers must run `t(...)` on the result.
function getModeBadgeLabel(capability?: string | null): string {
  if (!capability || capability === "chat") return "Chat";
  if (capability === "deep_solve") return "Deep Solve";
  if (capability === "deep_question") return "Quiz Generation";
  if (capability === "deep_research") return "Deep Research";
  if (capability === "math_animator") return "Math Animator";
  if (capability === "visualize") return "Visualize";
  if (capability === "mastery_path") return "Mastery Path";
  return capability;
}

function imageSrcForAttachment(attachment: MessageAttachment): string | null {
  if (attachment.url) {
    if (
      attachment.url.startsWith("http") ||
      attachment.url.startsWith("blob:") ||
      attachment.url.startsWith("data:")
    ) {
      return attachment.url;
    }
    return apiUrl(attachment.url);
  }

  const base64 = attachment.base64?.trim();
  if (!base64) return null;
  if (base64.startsWith("data:")) return base64;
  return `data:${attachment.mime_type || "image/png"};base64,${base64}`;
}

/** Format a byte count for a file card subtitle (e.g. "14 KB"). */
function formatFileSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

/** "DeepTutor_Introduction.pdf" → "DeepTutor Introduction" — the card title
 * reads like a document name; the extension already shows in the subtitle. */
function humanizeFilename(filename: string): string {
  const stem = filename.replace(/\.[A-Za-z0-9]{1,8}$/, "");
  return (
    stem
      .replace(/[_-]+/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim() || filename
  );
}

/**
 * Files the assistant produced this turn (exec/code/media artifacts),
 * rendered as openable cards under the message — click to open in the Viewer
 * side panel, same path as user uploads. Sources: persisted ``generated``
 * attachments on the message (durable) merged with artifacts from streamed
 * tool_result events (live, while the turn is still running), deduped by URL.
 */
function GeneratedFileCards({
  attachments,
  events,
  onOpen,
}: {
  attachments: MessageAttachment[];
  events?: StreamEvent[];
  onOpen?: (attachment: MessageAttachment) => void;
}) {
  const { t } = useTranslation();
  const files = useMemo(
    () => mergeGeneratedFiles(attachments, events),
    [attachments, events],
  );
  if (!files.length) return null;
  return (
    <div className="mt-3 flex flex-col gap-2">
      {files.map((a, i) => {
        const filename = a.filename || t("File");
        const key = a.id || a.url || `gen-${i}`;
        const mime = a.mime_type || "";
        const mediaSrc = imageSrcForAttachment(a);

        // Generated images / videos render inline (preview the moment they
        // arrive); everything else stays a compact openable file card.
        if (mime.startsWith("image/") && mediaSrc) {
          return (
            <button
              key={key}
              type="button"
              onClick={onOpen ? () => onOpen(a) : undefined}
              className="group block w-full max-w-[min(520px,90%)] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] text-left shadow-sm transition hover:border-[var(--border)]"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={mediaSrc}
                alt={filename}
                loading="lazy"
                className="block max-h-[360px] w-full bg-[var(--background)] object-contain"
              />
              <span className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="min-w-0 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                  {humanizeFilename(filename)}
                </span>
                <span className="shrink-0 text-[11px] text-[var(--muted-foreground)] transition group-hover:text-[var(--foreground)]">
                  {t("Open")}
                </span>
              </span>
            </button>
          );
        }

        if (mime.startsWith("video/") && mediaSrc) {
          return (
            <div
              key={key}
              className="w-full max-w-[min(520px,90%)] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-sm"
            >
              <video
                src={mediaSrc}
                controls
                preload="metadata"
                className="block max-h-[360px] w-full bg-black"
              />
              <button
                type="button"
                onClick={onOpen ? () => onOpen(a) : undefined}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition hover:bg-[var(--muted)]/30"
              >
                <span className="min-w-0 truncate text-[12.5px] font-medium text-[var(--foreground)]">
                  {humanizeFilename(filename)}
                </span>
                <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                  {t("Open")}
                </span>
              </button>
            </div>
          );
        }

        const spec = docIconFor(filename);
        const Icon = spec.Icon;
        const size = formatFileSize(a.size_bytes);
        return (
          <button
            key={key}
            type="button"
            onClick={onOpen ? () => onOpen(a) : undefined}
            className="group flex w-full max-w-[min(520px,90%)] items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 py-2.5 text-left shadow-sm transition hover:border-[var(--border)] hover:bg-[var(--muted)]/30"
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--background)]">
              <Icon className={`h-[18px] w-[18px] ${spec.tint}`} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium text-[var(--foreground)]">
                {humanizeFilename(filename)}
              </span>
              <span className="block text-[11px] text-[var(--muted-foreground)]">
                {spec.label}
                {size ? ` · ${size}` : ""}
              </span>
            </span>
            <span className="shrink-0 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--foreground)] transition group-hover:bg-[var(--muted)]/40">
              {t("Open")}
            </span>
          </button>
        );
      })}
    </div>
  );
}

const AssistantMessage = memo(function AssistantMessage({
  msg,
  isStreaming,
  outlineStatus,
  sessionId,
  language,
  onConfirmOutline,
  onSubmitUserReply,
  researchRequestSnapshot,
}: {
  msg: { content: string; capability?: string; events?: StreamEvent[] };
  isStreaming?: boolean;
  outlineStatus?: "editing" | "researching" | "done";
  sessionId?: string | null;
  language?: string;
  researchRequestSnapshot?: MessageRequestSnapshot | null;
  onConfirmOutline?: (
    outline: Array<{ title: string; overview: string }>,
    topic: string,
    researchConfig?: Record<string, unknown> | null,
    requestSnapshot?: MessageRequestSnapshot | null,
  ) => void;
  /**
   * Submit a reply for a turn that is paused on ``ask_user``. Wired
   * through from the page so the card's option-buttons / free-text
   * input can deliver the user's selection back to the backend over
   * the unified WebSocket. Triggers a same-turn resume (no new user
   * bubble). Accepts either a flat string (legacy single-question) or
   * a structured object with per-question ``answers`` (v2 path).
   */
  onSubmitUserReply?: (
    reply:
      | string
      | {
          text?: string;
          answers?: Array<{ questionId: string; text: string }>;
        },
  ) => void;
}) {
  const events = useMemo(() => msg.events ?? [], [msg.events]);
  const resultEvent = useMemo(
    () => msg.events?.find((event) => event.type === "result") ?? null,
    [msg.events],
  );

  const outlinePreview = useMemo(() => {
    if (msg.capability !== "deep_research" || !resultEvent) return null;
    const meta = resultEvent.metadata as Record<string, unknown> | undefined;
    if (!meta?.outline_preview) return null;
    return {
      sub_topics: (meta.sub_topics ?? []) as Array<{
        title: string;
        overview: string;
      }>,
      topic: String(meta.topic ?? ""),
      research_config: (meta.research_config ?? null) as Record<
        string,
        unknown
      > | null,
    };
  }, [msg.capability, resultEvent]);

  const quizQuestions = useMemo(() => {
    if (msg.capability !== "deep_question") return null;
    // Once the final result event lands, it's authoritative — it carries
    // the canonical summary.results[]. Until then, accumulate questions
    // from the live ``quiz_question_emitted`` content events so the
    // QuizViewer can render each card the moment it's generated.
    if (resultEvent) return extractQuizQuestions(resultEvent.metadata);
    return extractStreamingQuizQuestions(msg.events ?? []);
  }, [msg.capability, msg.events, resultEvent]);

  const mathAnimatorResult = useMemo(() => {
    if (msg.capability !== "math_animator" || !resultEvent) return null;
    return extractMathAnimatorResult(resultEvent.metadata);
  }, [msg.capability, resultEvent]);

  const visualizeResult = useMemo(() => {
    if (msg.capability !== "visualize" || !resultEvent) return null;
    return extractVisualizeResult(resultEvent.metadata);
  }, [msg.capability, resultEvent]);

  // Detect the ``ask_user`` terminator payload: when the assistant turn
  // ended via the ``ask_user`` tool, this is the question the user is
  // expected to answer next. Render option chips below the message.
  const askUserPayload = useMemo(
    () => extractAskUserPayload(msg.events),
    [msg.events],
  );

  // Interleaved segments for the default chat surface — text emitted
  // before the ask_user call renders above the card; text emitted by
  // the resumed iteration renders below it. Only walked when this
  // message will actually render through the default branch (the
  // research / quiz / animator / visualize branches have their own
  // layout and pin the card elsewhere).
  const useInlineAskUserSegments =
    !outlinePreview &&
    !mathAnimatorResult &&
    !visualizeResult &&
    !(quizQuestions && quizQuestions.length > 0);
  const messageSegments = useMemo(
    () => (useInlineAskUserSegments ? extractMessageSegments(msg.events) : []),
    [useInlineAskUserSegments, msg.events],
  );
  const hasInlineAskUser =
    useInlineAskUserSegments &&
    messageSegments.some((seg) => seg.kind === "ask_user");

  const researchInProgress =
    outlineStatus === "researching" || outlineStatus === "done";
  const showResearchBody =
    Boolean(outlinePreview) && researchInProgress && Boolean(msg.content);

  return (
    <>
      {/* Activity block pinned to the TOP: the status header
          ("DeepTutor Exploring… · 8s" → "DeepTutor responded. · 10s") with
          the exploring trace nested beneath it — expanded while DeepTutor is
          still working, collapsed once it settles into the final answer. */}
      <AssistantActivity
        events={events}
        isStreaming={isStreaming}
        content={msg.content}
        className="mb-3"
      />
      {outlinePreview && outlinePreview.sub_topics.length > 0 ? (
        <>
          {/* Layout for the merged research bubble:
                1. trace rows (above, via TraceFlow)
                2. ask_user Q&A summary (collapsible once research starts)
                3. Outline editor (auto-collapses once locked)
                4. Final report body (only after research is underway)
              The Q&A intentionally sits ABOVE the outline so the user
              sees the path that produced the outline before the outline
              itself. */}
          {askUserPayload ? (
            <AskUserOptions
              data={askUserPayload}
              onSubmit={(reply) => {
                if (!onSubmitUserReply) return;
                onSubmitUserReply(reply);
              }}
              collapsible={researchInProgress}
              defaultCollapsed={researchInProgress}
            />
          ) : null}
          <ResearchOutlineEditor
            outline={outlinePreview.sub_topics}
            topic={outlinePreview.topic}
            onConfirm={(items) =>
              onConfirmOutline?.(
                items,
                outlinePreview.topic,
                outlinePreview.research_config,
                researchRequestSnapshot,
              )
            }
            status={outlineStatus}
          />
          {showResearchBody ? (
            <AssistantResponse
              content={msg.content}
              isStreaming={isStreaming}
            />
          ) : null}
        </>
      ) : mathAnimatorResult ? (
        <MathAnimatorViewer result={mathAnimatorResult} />
      ) : visualizeResult ? (
        <VisualizationViewer result={visualizeResult} />
      ) : quizQuestions && quizQuestions.length > 0 ? (
        <>
          {/* The quiz preface (the "I researched X, now let me quiz you on Y"
              sentence the user watched stream in) rides along ABOVE the quiz
              card. Without this, the streamed text
              vanishes from the bubble the moment the first card appears
              because the branch above is mutually exclusive with
              <AssistantResponse>. The body is already free of the
              per-question markdown — the pipeline trims that out of
              ``msg.content`` since the QuizViewer renders the cards
              themselves. */}
          {msg.content ? (
            <AssistantResponse
              content={msg.content}
              isStreaming={isStreaming}
            />
          ) : null}
          <QuizViewer
            questions={quizQuestions}
            sessionId={sessionId}
            turnId={resultEvent?.turn_id ?? null}
            language={language}
          />
        </>
      ) : hasInlineAskUser ? (
        // Default chat surface with one or more ask_user calls: render
        // text and cards in the exact order they were streamed, so the
        // pre-ask_user narration sits above the card and the resumed
        // iteration's text sits below.
        messageSegments.map((seg) =>
          seg.kind === "text" ? (
            <AssistantResponse
              key={seg.key}
              content={seg.text}
              isStreaming={isStreaming}
            />
          ) : (
            <AskUserOptions
              key={seg.key}
              data={seg.data}
              onSubmit={(reply) => {
                if (!onSubmitUserReply) return;
                onSubmitUserReply(reply);
              }}
            />
          ),
        )
      ) : (
        <AssistantResponse content={msg.content} isStreaming={isStreaming} />
      )}
      {/* Non-default branches (quiz, math animator, visualize) keep
          ask_user below the body. The default branch inlines the card
          via ``messageSegments``; the research branch renders its own
          card above the outline editor — both skip this fallback. */}
      {!outlinePreview && !hasInlineAskUser && askUserPayload ? (
        <AskUserOptions
          data={askUserPayload}
          onSubmit={(reply) => {
            if (!onSubmitUserReply) return;
            onSubmitUserReply(reply);
          }}
        />
      ) : null}
    </>
  );
});

AssistantMessage.displayName = "AssistantMessage";

function CostFooter({
  cost,
  tokens,
  calls,
}: {
  cost: number;
  tokens: number;
  calls: number;
}) {
  const { t } = useTranslation();
  const formatCost = (usd: number) => {
    if (usd < 0.01) return `$${usd.toFixed(4)}`;
    return `$${usd.toFixed(2)}`;
  };
  const formatTokens = (n: number) => {
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(n);
  };
  return (
    <div className="flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]/70">
      <Coins size={11} strokeWidth={1.5} className="shrink-0" />
      <span>{formatCost(cost)}</span>
      <span className="opacity-50">·</span>
      <span>
        {formatTokens(tokens)} {t("tokens")}
      </span>
      <span className="opacity-50">·</span>
      <span>
        {calls} {t("calls")}
      </span>
    </div>
  );
}

// Claude-style icon-only message action: a quiet 15px glyph with the label
// in an instant tooltip, brightening on hover.
function RoughActionButton({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <Tooltip label={label} side="top">
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        className="inline-flex items-center justify-center rounded-md p-1 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-35"
      >
        <Icon size={15} strokeWidth={1.5} />
      </button>
    </Tooltip>
  );
}

function CopyActionButton({
  content,
  onCopy,
}: {
  content: string;
  onCopy: (content: string) => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleClick = useCallback(() => {
    void Promise.resolve(onCopy(content)).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 1600);
    });
  }, [content, onCopy]);

  return (
    <Tooltip label={copied ? t("Copied") : t("Copy")} side="top">
      <button
        type="button"
        onClick={handleClick}
        aria-live="polite"
        aria-label={copied ? t("Copied") : t("Copy")}
        className={`inline-flex items-center justify-center rounded-md p-1 transition-colors ${
          copied
            ? "text-[var(--primary)]"
            : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
        }`}
      >
        {copied ? (
          <Check size={15} strokeWidth={2} />
        ) : (
          <Copy size={15} strokeWidth={1.5} />
        )}
      </button>
    </Tooltip>
  );
}

// Speaker button: synthesizes the reply via the configured TTS provider and
// plays it. On the first manual play of a session it offers to auto-play the
// rest; `autoPlayFresh` triggers playback automatically for a reply that just
// finished generating when auto-play is on.
function PlayAudioButton({
  content,
  conversationKey,
  autoPlayFresh,
}: {
  content: string;
  conversationKey?: string;
  autoPlayFresh: boolean;
}) {
  const { t } = useTranslation();
  const {
    autoplayEnabled,
    enableForSession,
    markPrompted,
    shouldPromptOnFirstPlay,
  } = useVoiceAutoplay(conversationKey);
  const [state, setState] = useState<"idle" | "loading" | "playing">("idle");
  const [showPrompt, setShowPrompt] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const autoPlayedRef = useRef(false);

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
  }, []);

  const play = useCallback(async () => {
    setState("loading");
    try {
      const resp = await apiFetch(apiUrl("/api/v1/voice/tts"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: content }),
      });
      if (!resp.ok) {
        cleanup();
        setState("idle");
        return;
      }
      const blob = await resp.blob();
      cleanup();
      const url = URL.createObjectURL(blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        setState("idle");
        cleanup();
      };
      audio.onerror = () => {
        setState("idle");
        cleanup();
      };
      await audio.play();
      setState("playing");
    } catch {
      cleanup();
      setState("idle");
    }
  }, [cleanup, content]);

  const handleClick = useCallback(() => {
    if (state === "playing" || state === "loading") {
      cleanup();
      setState("idle");
      return;
    }
    const willPrompt = shouldPromptOnFirstPlay();
    void play();
    if (willPrompt) {
      markPrompted();
      setShowPrompt(true);
    }
  }, [cleanup, markPrompted, play, shouldPromptOnFirstPlay, state]);

  // Auto-play a freshly-generated reply when enabled, exactly once. Deferred
  // to a timer so synthesis (which sets state) starts off the effect body.
  useEffect(() => {
    if (!autoPlayFresh || !autoplayEnabled) return;
    if (autoPlayedRef.current) return;
    if (!content.trim()) return;
    autoPlayedRef.current = true;
    const id = window.setTimeout(() => void play(), 0);
    return () => window.clearTimeout(id);
  }, [autoPlayFresh, autoplayEnabled, content, play]);

  useEffect(() => cleanup, [cleanup]);

  return (
    <div className="relative inline-flex">
      <Tooltip
        label={state === "playing" ? t("Stop") : t("Play aloud")}
        side="top"
      >
        <button
          type="button"
          onClick={handleClick}
          aria-label={state === "playing" ? t("Stop") : t("Play aloud")}
          className={`inline-flex items-center justify-center rounded-md p-1 transition-colors ${
            state === "playing"
              ? "text-[var(--primary)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
          }`}
        >
          {state === "loading" ? (
            <Loader2 size={15} strokeWidth={1.8} className="animate-spin" />
          ) : state === "playing" ? (
            <Square size={13} strokeWidth={1.8} className="fill-current" />
          ) : (
            <Volume2 size={15} strokeWidth={1.5} />
          )}
        </button>
      </Tooltip>
      {showPrompt && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-60 rounded-lg border border-[var(--border)] bg-[var(--card)] p-3 shadow-lg">
          <p className="text-[12px] leading-relaxed text-[var(--foreground)]">
            {t("Auto-play replies in this conversation?")}
          </p>
          <div className="mt-2.5 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowPrompt(false)}
              className="rounded-md px-2.5 py-1 text-[11.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
            >
              {t("Not now")}
            </button>
            <button
              type="button"
              onClick={() => {
                enableForSession();
                setShowPrompt(false);
              }}
              className="rounded-md bg-[var(--primary)] px-2.5 py-1 text-[11.5px] font-medium text-[var(--primary-foreground)] hover:bg-[var(--primary)]/90"
            >
              {t("Turn on")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function BranchNavigator({
  info,
  onSwitch,
}: {
  info: SiblingInfo;
  onSwitch: (childId: number) => void;
}) {
  const { t } = useTranslation();
  const prevIdx = info.index - 2; // 0-based prev index
  const nextIdx = info.index; // 0-based next index
  const prevId = prevIdx >= 0 ? info.siblingIds[prevIdx] : null;
  const nextId =
    nextIdx < info.siblingIds.length ? info.siblingIds[nextIdx] : null;
  return (
    <div className="inline-flex items-center gap-0.5 text-[10.5px] text-[var(--muted-foreground)]">
      <button
        type="button"
        onClick={() => prevId !== null && onSwitch(prevId)}
        disabled={prevId === null}
        aria-label={t("Previous branch")}
        className="rounded p-0.5 transition-colors hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronLeft size={12} strokeWidth={1.8} />
      </button>
      <span className="select-none tabular-nums">
        {info.index} / {info.total}
      </span>
      <button
        type="button"
        onClick={() => nextId !== null && onSwitch(nextId)}
        disabled={nextId === null}
        aria-label={t("Next branch")}
        className="rounded p-0.5 transition-colors hover:text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronRight size={12} strokeWidth={1.8} />
      </button>
    </div>
  );
}

function DeleteTurnButton({ onDelete }: { onDelete: () => void }) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState(false);
  if (!confirm) {
    return (
      <RoughActionButton
        icon={Trash2}
        label={t("Delete")}
        onClick={() => setConfirm(true)}
      />
    );
  }
  return (
    <div className="inline-flex items-center gap-1.5 text-[11px]">
      <span className="text-[var(--muted-foreground)]">
        {t("Delete this turn?")}
      </span>
      <button
        type="button"
        onClick={() => {
          onDelete();
          setConfirm(false);
        }}
        className="rounded-md px-1.5 py-0.5 font-medium text-[var(--destructive)] hover:bg-[var(--destructive)]/10"
      >
        {t("Delete")}
      </button>
      <button
        type="button"
        onClick={() => setConfirm(false)}
        className="rounded-md px-1.5 py-0.5 font-medium text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
      >
        {t("Cancel")}
      </button>
    </div>
  );
}

const UserMessage = memo(function UserMessage({
  msg,
  index,
  onPreviewAttachment,
  onCopy,
  onEdit,
  editDisabled,
  siblingInfo,
  onSwitchBranch,
}: {
  msg: ChatMessageItem;
  index: number;
  onPreviewAttachment?: (attachment: MessageAttachment) => void;
  onCopy?: (content: string) => void | Promise<void>;
  onEdit?: (messageId: number, newContent: string) => void;
  editDisabled?: boolean;
  siblingInfo?: SiblingInfo;
  onSwitchBranch?: (parentMessageId: number | null, childId: number) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.content);
  // Connected subagents ride in knowledge_bases (same selection path) but are
  // agents, not KBs — this maps a selected name to its backend kind so the
  // reference chip can badge it with the agent's brand icon.
  const agentKinds = useConnectedAgentKinds();
  if (msg.content.startsWith("[Quiz Performance]")) return null;
  // ``msg.id`` can be a negative client-side sentinel for optimistic
  // (just-sent, not yet reconciled with the server) rows. We still allow
  // the Edit button to surface — ``editMessage`` in the context handles
  // the optimistic case by triggering a session reload to resolve the
  // real id before submitting the branch.
  const canEdit =
    Boolean(onEdit) && typeof msg.id === "number" && !editDisabled;
  const startEdit = () => {
    if (!canEdit) return;
    setDraft(msg.content);
    setEditing(true);
  };
  const cancelEdit = () => {
    setEditing(false);
    setDraft(msg.content);
  };
  const submitEdit = () => {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === msg.content) {
      cancelEdit();
      return;
    }
    if (typeof msg.id !== "number") return;
    onEdit?.(msg.id, trimmed);
    setEditing(false);
  };

  // Everything this turn carried — file attachments plus the request
  // snapshot's Space references — rendered as one collapsed tree under
  // the bubble (the sent-message mirror of the composer's tree).
  const snap = msg.requestSnapshot;
  const refTreeItems: ContextTreeItem[] = [
    ...(msg.attachments ?? []).map((a, ai): ContextTreeItem => {
      const filename = a.filename || t("Attachment");
      const spec = docIconFor(filename);
      const src = a.type === "image" ? imageSrcForAttachment(a) : null;
      return {
        key: `att-${ai}`,
        icon: spec.Icon,
        kind: spec.label,
        label: filename,
        thumbnailUrl: src ?? undefined,
        onClick: onPreviewAttachment ? () => onPreviewAttachment(a) : undefined,
      };
    }),
    ...(snap?.knowledgeBases ?? []).map((name): ContextTreeItem => {
      const agentKind = agentKinds[name];
      if (agentKind) {
        return {
          key: `agent-${name}`,
          // Brand SVG marks share the lucide call signature (size/strokeWidth/
          // className); cast bridges the structural-variance gap.
          icon: (agentGlyph(agentKind) ?? Bot) as unknown as LucideIcon,
          kind: t("Agent"),
          label: name,
        };
      }
      return {
        key: `kb-${name}`,
        icon: Database,
        kind: t("Knowledge"),
        label: name,
      };
    }),
    ...(snap?.bookReferences ?? []).map(
      (ref): ContextTreeItem => ({
        key: `book-${ref.book_id}`,
        icon: BookOpen,
        kind: t("Book"),
        label: `${ref.page_ids.length} ${t("chapters")}`,
      }),
    ),
    ...(snap?.notebookReferences ?? []).map(
      (ref): ContextTreeItem => ({
        key: `nb-${ref.notebook_id}`,
        icon: BookOpen,
        kind: t("Notebook"),
        label: `${ref.record_ids.length} ${t("records")}`,
      }),
    ),
    // Imported agent conversations are folded into the same history_references
    // payload but carry the `imported_` id prefix — split them back out so they
    // read as "My Agents" rather than "Chat History" (mirrors the composer).
    ...(snap?.historyReferences ?? [])
      .filter((sid) => !sid.startsWith("imported_"))
      .map(
        (sid): ContextTreeItem => ({
          key: `hist-${sid}`,
          icon: MessageSquare,
          kind: t("Chat History"),
          label: "",
        }),
      ),
    ...(snap?.historyReferences ?? [])
      .filter((sid) => sid.startsWith("imported_"))
      .map(
        (sid): ContextTreeItem => ({
          key: `agent-${sid}`,
          icon: Bot,
          kind: t("My Agents"),
          label: "",
        }),
      ),
    ...(snap?.questionNotebookReferences?.length
      ? [
          {
            key: "qb",
            icon: ClipboardList,
            kind: t("Question Bank"),
            label: `${snap.questionNotebookReferences.length} ${t("items")}`,
          } satisfies ContextTreeItem,
        ]
      : []),
    ...(snap?.persona
      ? [
          {
            key: "persona",
            icon: UserRound,
            kind: t("Persona"),
            label: snap.persona,
          } satisfies ContextTreeItem,
        ]
      : []),
    ...(snap?.memoryReferences ?? []).map(
      (file): ContextTreeItem => ({
        key: `mem-${file}`,
        icon: Brain,
        kind: t("Memory"),
        label: file === "summary" ? t("Summary") : t("Profile"),
      }),
    ),
  ];

  return (
    <div key={`${msg.role}-${index}`} className="group flex justify-end">
      <div className="flex max-w-[75%] flex-col items-end gap-1.5">
        <div className="flex justify-end pr-1">
          <span className="text-[10px] tracking-wide text-[var(--muted-foreground)]">
            {t(getModeBadgeLabel(msg.capability))}
          </span>
        </div>
        {editing ? (
          <div className="w-[min(620px,75vw)] rounded-2xl border border-[var(--primary)]/40 bg-[var(--secondary)] px-3 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] shadow-sm">
            <textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  cancelEdit();
                } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  submitEdit();
                }
              }}
              rows={Math.min(8, Math.max(2, draft.split("\n").length))}
              className="w-full resize-none border-0 bg-transparent text-[14px] leading-relaxed text-[var(--foreground)] outline-none focus:outline-none"
            />
            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="text-[10.5px] text-[var(--muted-foreground)]/80">
                {t("Use the arrows below to switch between branches.")}
              </span>
              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  onClick={cancelEdit}
                  className="rounded-md px-2 py-0.5 text-[11px] font-medium text-[var(--muted-foreground)] hover:bg-[var(--muted)]/40"
                >
                  {t("Cancel")}
                </button>
                <button
                  type="button"
                  onClick={submitEdit}
                  disabled={!draft.trim() || draft.trim() === msg.content}
                  className="rounded-md bg-[var(--primary)] px-2.5 py-0.5 text-[11px] font-medium text-[var(--primary-foreground)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {t("Send")}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl bg-[var(--secondary)] px-4 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] shadow-sm">
            <div className="whitespace-pre-wrap">{msg.content}</div>
          </div>
        )}
        {!editing && refTreeItems.length > 0 && (
          <div className="pr-1">
            <ContextReferenceTree
              items={refTreeItems}
              direction="down"
              align="right"
              summaryNoun={t("attachments")}
            />
          </div>
        )}
        {!editing && (onCopy || canEdit || siblingInfo) && msg.content && (
          <div className="flex h-7 items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
            {siblingInfo && siblingInfo.total > 1 && (
              <BranchNavigator
                info={siblingInfo}
                onSwitch={(childId) =>
                  onSwitchBranch?.(siblingInfo.parentId, childId)
                }
              />
            )}
            {onCopy && (
              <CopyActionButton content={msg.content} onCopy={onCopy} />
            )}
            {canEdit && (
              <RoughActionButton
                icon={Pencil}
                label={t("Edit")}
                onClick={startEdit}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
});

UserMessage.displayName = "UserMessage";

export const ChatMessageList = memo(function ChatMessageList({
  messages,
  isStreaming,
  sessionId,
  language,
  onCopyAssistantMessage,
  onRegenerateMessage,
  onConfirmOutline,
  onPreviewAttachment,
  onDeleteTurn,
  selectedBranches,
  onEditMessage,
  onSwitchBranch,
  onSubmitUserReply,
}: {
  messages: ChatMessageItem[];
  isStreaming: boolean;
  sessionId?: string | null;
  language?: string;
  onCopyAssistantMessage: (content: string) => void | Promise<void>;
  onRegenerateMessage: () => void;
  onConfirmOutline?: (
    outline: Array<{ title: string; overview: string }>,
    topic: string,
    researchConfig?: Record<string, unknown> | null,
    requestSnapshot?: MessageRequestSnapshot | null,
  ) => void;
  onPreviewAttachment?: (attachment: MessageAttachment) => void;
  onDeleteTurn?: (messageId: number) => void;
  /** Edit-branching: selected sibling at each branch point. */
  selectedBranches?: Record<string, number>;
  onEditMessage?: (messageId: number, newContent: string) => void;
  onSwitchBranch?: (parentMessageId: number | null, childId: number) => void;
  /**
   * Deliver an ``ask_user`` reply back to the backend so the agentic
   * loop resumes on the same turn. Forwarded into each
   * ``AssistantMessage`` so the card UI rendered alongside the paused
   * assistant bubble can submit selections / free-form text. Accepts
   * either a string (legacy) or a structured object with per-question
   * ``answers`` (v2).
   */
  onSubmitUserReply?: (
    reply:
      | string
      | {
          text?: string;
          answers?: Array<{ questionId: string; text: string }>;
        },
  ) => void;
}) {
  const { t } = useTranslation();
  // Visible path: when no branching has happened the result is identical
  // to the input. After an edit, sibling branches are filtered out so the
  // UI shows exactly one continuous thread, with arrow nav exposed on the
  // user message where branching diverges.
  const { messages: visibleMessages, siblingsByMessageId } = useMemo(
    () => buildVisiblePath(messages, selectedBranches),
    [messages, selectedBranches],
  );

  // Deep-research two-turn merge.
  //
  // The capability runs in two BE turns: turn-1 emits rephrase +
  // decompose + an outline-preview result; turn-2 (after the user
  // confirms the outline) emits the research blocks + the final
  // report. The user wants both turns to live in ONE assistant
  // bubble so the rephrase trace, the Q&A summary, the (collapsed)
  // outline editor, and the research / reporting traces are all
  // visually contiguous instead of split across two bubbles.
  //
  // For each parent (outline-preview) msg with a followup
  // deep_research msg, we synthesise a merged msg with:
  //
  // * events  — parent.events ++ followup.events (preserving order
  //   so TraceFlow's call_id grouping keeps working).
  // * content — followup.content (the report). The parent's
  //   rephrase preface is already represented inside the trace card,
  //   so concatenating again would duplicate it above the report.
  //
  // The followup is dropped from the visible row list so only the
  // merged bubble renders.
  const deepResearchMergeMap = useMemo(() => {
    const map = new Map<
      number,
      { mergedEvents: StreamEvent[]; mergedContent: string }
    >();
    const followupIndices = new Set<number>();
    for (let i = 0; i < visibleMessages.length; i++) {
      const msg = visibleMessages[i];
      if (msg.role !== "assistant" || msg.capability !== "deep_research")
        continue;
      const resultEv = msg.events?.find((e) => e.type === "result");
      const meta = resultEv?.metadata as Record<string, unknown> | undefined;
      if (!meta?.outline_preview) continue;
      const followupIdx = visibleMessages
        .slice(i + 1)
        .findIndex(
          (m) => m.role === "assistant" && m.capability === "deep_research",
        );
      if (followupIdx === -1) continue;
      const absoluteFollowupIdx = i + 1 + followupIdx;
      const followup = visibleMessages[absoluteFollowupIdx];
      const mergedEvents = [...(msg.events ?? []), ...(followup.events ?? [])];
      const mergedContent = followup.content || msg.content;
      map.set(i, { mergedEvents, mergedContent });
      followupIndices.add(absoluteFollowupIdx);
    }
    return { mergedByParent: map, followupIndices };
  }, [visibleMessages]);

  const outlineStatusByIndex = useMemo(() => {
    const map = new Map<number, "editing" | "researching" | "done">();
    for (let i = 0; i < visibleMessages.length; i++) {
      const msg = visibleMessages[i];
      if (msg.role !== "assistant" || msg.capability !== "deep_research")
        continue;
      const resultEv = msg.events?.find((e) => e.type === "result");
      const meta = resultEv?.metadata as Record<string, unknown> | undefined;
      if (!meta?.outline_preview) continue;
      const followup = visibleMessages
        .slice(i + 1)
        .find(
          (m) => m.role === "assistant" && m.capability === "deep_research",
        );
      if (followup) {
        const followupResult = followup.events?.find(
          (e) => e.type === "result",
        );
        map.set(i, followupResult ? "done" : "researching");
      } else {
        // The first deep_research turn only plans/rephrases/decomposes and
        // returns an outline preview. While that turn is still flushing
        // post-result events, the outline must already be editable; only the
        // hidden follow-up turn created by "Start Research" means research is
        // actually underway.
        map.set(i, "editing");
      }
    }
    return map;
  }, [visibleMessages]);

  const messageRows = useMemo(() => {
    // System messages are backend grounding (e.g. quiz follow-up context) and
    // must never be rendered as a chat bubble. Filter them out defensively in
    // addition to the hydration-time filter in UnifiedChatContext.
    return visibleMessages
      .map((msg, index) => ({ msg, originalIndex: index }))
      .filter(({ msg, originalIndex }) => {
        if (msg.role === "system") return false;
        // Drop deep_research followup msgs — their events were merged
        // into the parent (outline-preview) bubble.
        if (deepResearchMergeMap.followupIndices.has(originalIndex))
          return false;
        return true;
      })
      .map(({ msg, originalIndex }) => {
        // Splice in the merged event stream when this row owns a
        // deep_research two-turn pair.
        const merged = deepResearchMergeMap.mergedByParent.get(originalIndex);
        const effectiveMsg: ChatMessageItem = merged
          ? {
              ...msg,
              events: merged.mergedEvents,
              content: merged.mergedContent,
            }
          : msg;
        if (effectiveMsg.role === "user") {
          return {
            msg: effectiveMsg,
            originalIndex,
            pairedUserMessage: null as ChatMessageItem | null,
          };
        }
        const pairedUserMessage =
          [...visibleMessages.slice(0, originalIndex)]
            .reverse()
            .find((previous) => previous.role === "user") ?? null;
        return { msg: effectiveMsg, originalIndex, pairedUserMessage };
      });
  }, [visibleMessages, deepResearchMergeMap]);

  const lastRenderedAssistantIndex = useMemo(() => {
    for (let idx = messageRows.length - 1; idx >= 0; idx -= 1) {
      if (messageRows[idx].msg.role === "assistant")
        return messageRows[idx].originalIndex;
    }
    return -1;
  }, [messageRows]);

  // Auto-play (when enabled) must fire only for a reply that JUST finished
  // generating — never when loading history. We capture the last-assistant
  // index at the moment streaming flips off; the matching speaker button
  // plays once. Switching sessions clears the marker. Uses the "adjust state
  // during render" pattern (state-vs-prop comparison, like the API-key reset
  // in ServiceConfigEditor) — both branches are conditional and bounded.
  const [prevStreaming, setPrevStreaming] = useState(isStreaming);
  const [prevSession, setPrevSession] = useState(sessionId);
  const [freshlyCompletedIndex, setFreshlyCompletedIndex] = useState<
    number | null
  >(null);
  if (prevSession !== sessionId) {
    setPrevSession(sessionId);
    setPrevStreaming(false);
    setFreshlyCompletedIndex(null);
  } else if (prevStreaming !== isStreaming) {
    setPrevStreaming(isStreaming);
    if (!isStreaming && lastRenderedAssistantIndex >= 0) {
      setFreshlyCompletedIndex(lastRenderedAssistantIndex);
    }
  }

  return (
    <>
      {messageRows.map(({ msg, originalIndex, pairedUserMessage }) => {
        const i = originalIndex;
        if (msg.role === "user") {
          const sib =
            msg.id !== undefined ? siblingsByMessageId.get(msg.id) : undefined;
          return (
            <UserMessage
              key={`${msg.role}-${i}`}
              msg={msg}
              index={i}
              onPreviewAttachment={onPreviewAttachment}
              onCopy={onCopyAssistantMessage}
              onEdit={onEditMessage}
              editDisabled={isStreaming}
              siblingInfo={sib}
              onSwitchBranch={onSwitchBranch}
            />
          );
        }

        const isActiveAssistant =
          isStreaming && i === lastRenderedAssistantIndex;
        const msgDone = !isActiveAssistant;
        const showActions = msgDone && hasVisibleMarkdownContent(msg.content);
        const isLastAssistant = i === lastRenderedAssistantIndex;
        const showRegenerate =
          showActions &&
          !isStreaming &&
          isLastAssistant &&
          Boolean(pairedUserMessage) &&
          (!pairedUserMessage?.capability ||
            pairedUserMessage?.capability === "chat");
        const deletableTurnUserId =
          msgDone && pairedUserMessage?.id != null && onDeleteTurn
            ? pairedUserMessage.id
            : null;
        const showDelete = deletableTurnUserId != null;

        const costSummary = (() => {
          if (!msgDone) return null;
          const resultEv = msg.events?.find((e) => e.type === "result");
          if (!resultEv) return null;
          const meta = resultEv.metadata?.metadata as
            | Record<string, unknown>
            | undefined;
          const cs = meta?.cost_summary as
            | {
                total_cost_usd?: number;
                total_tokens?: number;
                total_calls?: number;
              }
            | undefined;
          if (!cs || !cs.total_calls) return null;
          return cs;
        })();

        return (
          <div key={`${msg.role}-${i}`} className="w-full">
            <InlineFileCardProvider
              attachments={msg.attachments ?? []}
              events={msg.events}
              onOpen={onPreviewAttachment}
            >
              <AssistantMessage
                msg={msg}
                isStreaming={isActiveAssistant}
                outlineStatus={outlineStatusByIndex.get(i)}
                sessionId={sessionId}
                language={language}
                onConfirmOutline={onConfirmOutline}
                onSubmitUserReply={onSubmitUserReply}
                researchRequestSnapshot={
                  pairedUserMessage?.requestSnapshot ?? null
                }
              />
            </InlineFileCardProvider>
            <GeneratedFileCards
              attachments={msg.attachments ?? []}
              events={msg.events}
              onOpen={onPreviewAttachment}
            />
            {(() => {
              // A turn that died (LLM/provider failure, interruption) ends
              // with a turn_terminal error event. Surface it as an error
              // card with an inline retry instead of leaving a bare trace.
              if (isActiveAssistant) return null;
              const terminalError = (msg.events ?? []).find(
                (e) =>
                  e.type === "error" &&
                  Boolean(
                    (e.metadata as { turn_terminal?: boolean } | undefined)
                      ?.turn_terminal,
                  ),
              );
              if (!terminalError) return null;
              return (
                <div className="mt-3 flex w-full max-w-[min(520px,90%)] items-center gap-2 rounded-xl border border-[var(--destructive)]/30 bg-[var(--destructive)]/5 px-3 py-2">
                  <AlertCircle className="h-4 w-4 shrink-0 text-[var(--destructive)]" />
                  <span className="min-w-0 flex-1 text-[12px] leading-[1.5] text-[var(--foreground)]">
                    {terminalError.content || t("The turn was interrupted.")}
                  </span>
                  {showRegenerate ? (
                    <button
                      type="button"
                      onClick={() => onRegenerateMessage()}
                      className="shrink-0 rounded-md px-2 py-1 text-[11.5px] font-medium text-[var(--destructive)] hover:bg-[var(--destructive)]/10"
                    >
                      {t("Retry")}
                    </button>
                  ) : null}
                </div>
              );
            })()}
            {(showActions || costSummary || showDelete) && (
              <div className="mt-3 flex items-center">
                {(showActions || showDelete) && (
                  <div className="flex items-center gap-1">
                    {showActions && (
                      <CopyActionButton
                        content={msg.content}
                        onCopy={onCopyAssistantMessage}
                      />
                    )}
                    {showActions && (
                      <PlayAudioButton
                        content={msg.content}
                        conversationKey={sessionId ?? undefined}
                        autoPlayFresh={
                          isLastAssistant && freshlyCompletedIndex === i
                        }
                      />
                    )}
                    {showActions && showRegenerate && (
                      <RoughActionButton
                        icon={RefreshCcw}
                        label={t("Regenerate")}
                        onClick={() => onRegenerateMessage()}
                      />
                    )}
                    {showDelete && (
                      <DeleteTurnButton
                        onDelete={() => onDeleteTurn?.(deletableTurnUserId)}
                      />
                    )}
                  </div>
                )}
                {costSummary && (
                  <div className="ml-auto">
                    <CostFooter
                      cost={costSummary.total_cost_usd ?? 0}
                      tokens={costSummary.total_tokens ?? 0}
                      calls={costSummary.total_calls ?? 0}
                    />
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
});

ChatMessageList.displayName = "ChatMessageList";
