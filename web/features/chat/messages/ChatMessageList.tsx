"use client";

import dynamic from "next/dynamic";
import { UsageFooter } from "./UsageFooter";
import { cumulativeMessageUsage, messageUsage } from "./usage-summary";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  BookMarked,
  BookOpen,
  Bot,
  Brain,
  Check,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Copy,
  AlertCircle,
  Database,
  Loader2,
  MessageSquare,
  Pencil,
  RefreshCcw,
  Square,
  UserRound,
  UsersRound,
  Volume2,
  X,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SelectedHistorySession } from "@/components/chat/HistorySessionPicker";
import type { SelectedQuestionEntry } from "@/components/chat/QuestionBankPicker";
import { ActivityFold, FoldCaret } from "@/components/activity";
import AssistantResponse from "@/components/common/AssistantResponse";
import {
  InlineFileCardProvider,
  mergeGeneratedFiles,
} from "@/components/common/InlineFileCard";
import Tooltip from "@/components/common/Tooltip";
import type {
  MessageAttachment,
  MessageRequestSnapshot,
} from "@/features/chat/ChatStateAdapter";
import { apiFetch, apiUrl } from "@/lib/api";
import { docIconFor } from "@/lib/doc-attachments";
import { useVoiceAutoplay } from "@/hooks/useVoiceAutoplay";
import { extractMathAnimatorResult } from "@/lib/math-animator-types";
import {
  extractQuizQuestions,
  extractQuizTurnId,
  extractStreamingQuizQuestions,
} from "@/lib/quiz-types";
import { extractVisualizeResult } from "@/lib/visualize-types";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { hasVisibleMarkdownContent } from "@/lib/markdown-display";
import type { SelectedBookReference } from "@/lib/book-references";
import { buildVisiblePath, type SiblingInfo } from "@/lib/message-branches";
import { turnAnchorKey } from "@/lib/chat-outline";
import { shouldSubmitOnEnter } from "@/lib/composer-keyboard";
import { useImeComposing } from "@/lib/use-ime-composing";
import type { SpaceMemoryFile } from "@/lib/space-items";
import {
  AskUserOptions,
  extractAskUserPayload,
  extractMessageSegments,
  leadingTraceEvents,
  type MessageSegment,
} from "@/components/chat/home/AskUserOptions";
import { MasteryQuestionCard } from "@/components/chat/home/MasteryQuestionCard";
import {
  collectMasteryGrades,
  collectMasterySkips,
  extractMasteryQuestion,
  type MasteryGradeResult,
  type MasteryQuestion,
} from "@/lib/mastery-question";
import { SetupCredentialCard } from "@/components/chat/home/SetupCredentialCard";
import { extractSetupCredential } from "@/lib/setup-signals";
import { PartnerDraftCard } from "@/components/chat/home/PartnerDraftCard";
import { extractPartnerDraft } from "@/lib/partner-draft";
import { CourseHandoffCards } from "@/components/chat/home/CourseHandoffCard";
import { MasteryHandoffCards } from "@/components/chat/home/MasteryHandoffCard";
import {
  extractCourseHandoffs,
  stripLeakedHandoffJson,
} from "@/lib/course-handoff";
import { extractMasteryHandoffs } from "@/lib/mastery-handoff";
import ContextReferenceTree, {
  type ContextTreeItem,
} from "@/components/chat/home/ContextReferenceTree";
import {
  AssistantActivity,
  NestedTraceFlow,
  TraceFlow,
} from "@/features/chat/trace/TracePresentation";
import { hasSettledFinalRound } from "@/features/chat/trace/selectors";
import type { MessageTraceMetadata } from "@/features/chat/trace/memory";
import { agentGlyph } from "@/components/agents/agent-icons";
import { useConsultationReference } from "@/hooks/useConsultationReference";
import { useConnectedAgentKinds } from "@/hooks/useConnectedAgentKinds";
import {
  authoritativeResearchReport,
  isConfirmedResearchFollowup,
  researchFollowupStatus,
} from "@/lib/deep-research-report";

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
  trace?: MessageTraceMetadata;
  attachments?: MessageAttachment[];
  requestSnapshot?: MessageRequestSnapshot;
  parentMessageId?: number | null;
}

interface NotebookReferenceGroup {
  notebookId: string;
  notebookName: string;
  count: number;
}

const MODE_BADGE_LABELS: Record<string, string> = {
  chat: "Chat",
  ask_questions: "Ask Questions",
  deep_solve: "Deep Solve",
  deep_question: "Quiz Generation",
  deep_research: "Deep Research",
  math_animator: "Math Animator",
  visualize: "Visualize",
  mastery_path: "Mastery Path",
  immersive_reading: "Immersive Reading",
};

// Returns the i18n key (and a sensible fallback) for the capability badge
// shown above the user's message. Callers must run `t(...)` on the result.
// Exported so the turn navigator's hover card labels a turn with exactly
// the same wording the bubble carries.
//
// A capability with no entry is title-cased rather than printed raw: an
// unlisted mode used to surface its internal id ("immersive_reading") in the
// conversation, which reads as a bug to everyone who sees it.
/**
 * What a run of working-out actually contains, for the memo below.
 *
 * Prose is identified by its length rather than its text because a streamed
 * segment only ever grows; a run of steps by how many events it holds.
 *
 * ``settled`` says a turn has moved on to writing its answer, and then only
 * the shape matters. The region a turn is working in stays open in the event
 * stream and keeps absorbing everything that arrives, so a finished run of
 * steps went on counting the answer's own deltas — 3300 events for a trace
 * drawing two rows — and reported itself as changed on every one of them.
 * Nothing below the answer can alter the working-out above it: a new round
 * would take the answer back into the process, which moves the shape.
 */
/**
 * The width of an ActivityRow's mark column: the 15px dot cell, the 10px gap
 * after it, and the 2px the stack insets itself by. Pulling a row left by
 * this lands its text on the same edge as the prose around it.
 */
const ROW_GUTTER = 27;

function processContentKey(
  segments: MessageSegment[],
  settled: boolean,
): string {
  return segments
    .map((seg) =>
      seg.kind === "ask_user"
        ? `q${seg.key}:${JSON.stringify(seg.data)}`
        : settled
          ? seg.key
          : seg.kind === "text"
            ? `t${seg.key}:${seg.text.length}`
            : seg.kind === "trace"
              ? `r${seg.key}:${seg.events.length}`
              : seg.key,
    )
    .join("|");
}

/**
 * Prose and the steps it introduced, in the order they were written.
 *
 * Spacing is owned here rather than left to each piece. Markdown carries a
 * bottom margin and the trace rows carried only a top one, so a row sat 24px
 * below the sentence that introduced it and flush against the one that
 * followed — reading as a heading for the next paragraph instead of as the
 * step between them. Both margins are stripped and one gap governs the whole
 * column, so the rhythm is even whichever way you read it.
 *
 * Alignment is owned here too, for the same reason. A trace row carries its
 * own mark column, so its text started {@link ROW_GUTTER}px right of the
 * prose above it and the column had four left edges inside 42px — the rule,
 * the prose, the dots, the row text. Read down it, every other line stepped
 * sideways. The rows are pulled back by exactly that gutter instead, which
 * leaves two edges: one content edge that prose and steps share, and the
 * dots hanging in the margin beside it, which is what a bullet gutter is.
 *
 * Memoized on what it holds rather than on the props it is handed.
 * ``messageSegments`` is rebuilt from scratch on every streamed delta, so the
 * working-out — which stops changing the moment a turn starts writing its
 * answer — arrived as a brand-new element tree on every frame of that answer.
 * React cannot skip a subtree whose elements it has never seen, so the whole
 * trace re-rendered for the answer's full length: profiled over one 35s turn,
 * 2905 renders costing 10.3s, none of which changed a pixel.
 *
 * ``events`` is deliberately left out of the comparison. It is read only to
 * verify reading-material locators, and anything that could verify one is a
 * tool call — which lands in a run of steps and moves the key on its own.
 */
const ProcessBody = memo(
  function ProcessBody({
    segments,
    events,
    language,
    isStreaming,
    readingMaterialId,
    readingMaterialRevision,
  }: {
    segments: MessageSegment[];
    events: StreamEvent[];
    /** The turn has moved on to its answer, so this run is finished. */
    settled: boolean;
    language?: string;
    isStreaming?: boolean;
    readingMaterialId?: string;
    readingMaterialRevision?: number;
  }) {
    return (
      <div
        className="flex flex-col gap-3"
        // The padding is the content edge — where prose starts and where a
        // row's text is pulled back to. Wide enough to hold the dots.
        style={{ paddingLeft: ROW_GUTTER }}
      >
        {segments.map((seg) =>
          seg.kind === "text" ? (
            <div key={seg.key} className="[&_.md-renderer>*:last-child]:mb-0">
              <AssistantResponse
                content={seg.text}
                language={language}
                isStreaming={isStreaming}
                readingMaterialId={readingMaterialId}
                readingMaterialRevision={readingMaterialRevision}
                events={events}
              />
            </div>
          ) : seg.kind === "trace" ? (
            <div
              key={seg.key}
              className="[&>div]:mb-0"
              style={{ marginLeft: -ROW_GUTTER }}
            >
              <TraceFlow events={seg.events} isStreaming={isStreaming} />
            </div>
          ) : seg.kind === "ask_user" && seg.data.resolved ? (
            <AskUserOptions
              key={seg.key}
              data={seg.data}
              onSubmit={() => false}
            />
          ) : null,
        )}
      </div>
    );
  },
  (a, b) =>
    a.language === b.language &&
    a.isStreaming === b.isStreaming &&
    a.settled === b.settled &&
    a.readingMaterialId === b.readingMaterialId &&
    a.readingMaterialRevision === b.readingMaterialRevision &&
    processContentKey(a.segments, a.settled) ===
      processContentKey(b.segments, b.settled),
);

/**
 * A run of working-out that folds itself away.
 *
 * Used for the runs that follow a card — the leading run rides in the
 * message's activity header instead, which is already a disclosure and
 * already pinned at the top, so the common turn shows one line of chrome
 * rather than two.
 */
function ProcessFold({
  segments,
  settled,
  children,
}: {
  segments: MessageSegment[];
  /** The turn has moved on: fold by default, and say what is inside. */
  settled: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const open = userOpen ?? !settled;
  const toolCalls = countProcessToolCalls(segments);

  return (
    <div className="mb-3">
      {/* Same shape as the activity header this fold echoes: the label first,
          the caret after it. The header has an orb holding the left column,
          so a leading caret here would make the two controls read as two
          different kinds of thing. */}
      <button
        type="button"
        onClick={() => setUserOpen(!open)}
        aria-expanded={open}
        className="group/act flex items-center gap-2 text-left text-[12px] font-medium text-[var(--muted-foreground)]/55 transition-colors hover:text-[var(--foreground)]"
      >
        {toolCalls > 0
          ? t("{{count}} tool calls", { count: toolCalls })
          : t("Working notes")}
        <FoldCaret open={open} />
      </button>
      <ActivityFold open={open}>
        <div className="pt-1">{children}</div>
      </ActivityFold>
    </div>
  );
}

/**
 * One row of the assistant message: a run of working-out, a card, or answer
 * prose. Cards and the answer stand on their own; a process run is what the
 * turn did before either of them and folds away once the turn has settled.
 */
type MessageBlock =
  | { kind: "process"; key: string; segments: MessageSegment[] }
  | { kind: "card"; key: string; segment: MessageSegment }
  | { kind: "answer"; key: string; segment: MessageSegment };

/**
 * Split a message into its blocks.
 *
 * A mastery question ends its turn, so the prose introducing it is teaching,
 * not commentary awaiting a later answer. Keep that text outside the fold as
 * well as the card. Earlier exploration and any intervening tool rows still
 * fold normally. Answered clarifications belong to the same process as the
 * work before and after them; only pending cards stand outside the fold.
 */
function buildMessageBlocks(
  segments: MessageSegment[],
  answerStart: number,
): MessageBlock[] {
  const teaching = new Set<number>();
  segments.forEach((segment, index) => {
    if (segment.kind !== "mastery_question") return;
    let before = index - 1;
    // Recording a grade or updating state can share the round with the quiz.
    // Those rows do not turn the preceding teaching into working notes.
    while (before >= 0 && segments[before].kind === "trace") before -= 1;
    while (before >= 0 && segments[before].kind === "text") {
      teaching.add(before);
      before -= 1;
    }
  });
  const blocks: MessageBlock[] = [];
  let run: MessageSegment[] = [];
  const flush = () => {
    if (!run.length) return;
    blocks.push({ kind: "process", key: `p-${run[0].key}`, segments: run });
    run = [];
  };
  segments.slice(0, answerStart).forEach((segment, index) => {
    if (
      (segment.kind === "ask_user" && !segment.data.resolved) ||
      segment.kind === "mastery_question"
    ) {
      flush();
      blocks.push({ kind: "card", key: segment.key, segment });
      return;
    }
    if (teaching.has(index)) {
      flush();
      blocks.push({ kind: "answer", key: segment.key, segment });
      return;
    }
    run.push(segment);
  });
  flush();
  segments.slice(answerStart).forEach((segment) => {
    blocks.push({ kind: "answer", key: segment.key, segment });
  });
  return blocks;
}

/**
 * How many steps a run of working-out took, for the line that names it.
 *
 * Steps only. Counting the paragraphs of commentary alongside them read as a
 * measure of how much was said rather than how much was done, which is the
 * thing a reader is deciding whether to open.
 */
function countProcessToolCalls(segments: MessageSegment[]): number {
  let toolCalls = 0;
  for (const segment of segments) {
    if (segment.kind !== "trace") continue;
    for (const event of segment.events) {
      if (event.type === "tool_call") toolCalls += 1;
    }
  }
  return toolCalls;
}

export function getModeBadgeLabel(capability?: string | null): string {
  if (!capability) return MODE_BADGE_LABELS.chat;
  const known = MODE_BADGE_LABELS[capability];
  if (known) return known;
  return capability
    .split("_")
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ");
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
export function GeneratedFileCards({
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
        const key = a.workspace_item_id || a.id || a.url || `gen-${i}`;
        const mime = a.mime_type || "";
        const mediaSrc = imageSrcForAttachment(a);
        const caption = a.caption?.trim() || "";

        // Generated media renders inline; other MIME types use a file card.
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
                <span className="min-w-0">
                  <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {a.title || humanizeFilename(filename)}
                  </span>
                  {caption ? (
                    <span className="block truncate text-[11px] text-[var(--muted-foreground)]">
                      {caption}
                    </span>
                  ) : null}
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
                <span className="min-w-0">
                  <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                    {a.title || humanizeFilename(filename)}
                  </span>
                  {caption ? (
                    <span className="block truncate text-[11px] text-[var(--muted-foreground)]">
                      {caption}
                    </span>
                  ) : null}
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
                {a.title || humanizeFilename(filename)}
              </span>
              <span className="block text-[11px] text-[var(--muted-foreground)]">
                {caption || spec.label}
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

export const AssistantMessage = memo(function AssistantMessage({
  msg,
  isStreaming,
  outlineStatus,
  sessionId,
  language,
  onConfirmOutline,
  onSubmitUserReply,
  onAnswerMasteryQuestion,
  onSkipMasteryQuestion,
  researchRequestSnapshot,
  onTraceToggle,
  masteryGrades,
  masterySkips,
}: {
  msg: {
    id?: number;
    content: string;
    capability?: string;
    events?: StreamEvent[];
    trace?: MessageTraceMetadata;
  };
  isStreaming?: boolean;
  /**
   * Every mastery verdict in the conversation, by question id. Collected once
   * for the whole list because a question answered in the composer is graded a
   * turn later than it was posed, and its card should still show the answer.
   */
  masteryGrades?: Map<string, MasteryGradeResult>;
  /** Every question the learner dropped, by id — collected the same way and
   *  for the same reason: the skip lands on a later turn than the card. */
  masterySkips?: Set<string>;
  outlineStatus?: "editing" | "researching" | "done" | "failed";
  sessionId?: string | null;
  language?: string;
  researchRequestSnapshot?: MessageRequestSnapshot | null;
  /** Notified when a persisted trace is opened or collapsed. Takes the id so
   *  the list can hand one callback to every row — see ``handleTraceToggle``. */
  onTraceToggle?: (messageId: number, open: boolean) => void;
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
  ) => void | boolean | Promise<void | boolean>;
  /**
   * Answer a mastery question card. Unlike ``onSubmitUserReply`` this does
   * NOT resume a paused turn — posing a mastery question ends its turn, so
   * the answer starts the next one, exactly as typing it would. That is what
   * keeps the learner free to answer, ask something else, or come back later.
   */
  onAnswerMasteryQuestion?: (answer: {
    questionId: string;
    text: string;
  }) => void | boolean | Promise<void | boolean>;
  /** Drop a question the learner does not want to answer. Same turn-starting
   *  shape as answering it, because the engine holds one open question per
   *  path: without this the tutor's next question is this same one again. */
  onSkipMasteryQuestion?: (
    questionId: string,
  ) => void | boolean | Promise<void | boolean>;
}) {
  const { t } = useTranslation();
  const events = useMemo(() => msg.events ?? [], [msg.events]);
  const readingMaterialId = researchRequestSnapshot?.readingMaterialId;
  const readingMaterialRevision =
    researchRequestSnapshot?.readingMaterialRevision;
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

  // Turn identity for the quiz card. Derived from the streamed events, not
  // just the final result event — during generation the result hasn't landed
  // yet, and a null turn id would let the QuizViewer fall back to
  // session-wide notebook state from a previous quiz (issue #677).
  const quizTurnId = useMemo(() => {
    if (msg.capability !== "deep_question") return null;
    return extractQuizTurnId(msg.events);
  }, [msg.capability, msg.events]);

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
    () => extractAskUserPayload(msg.events, { streaming: isStreaming }),
    [msg.events, isStreaming],
  );
  // A graded mastery question travels on the same pause channel as a
  // clarifying one: the study card that renders it shows the objective, the
  // attempt and the verdict, none of which the generic card has anywhere to
  // put.
  //
  // Only the last one is read here, for the surfaces that pin a single card
  // below the body. The default surface renders a card per segment instead —
  // a turn resumes on this same message after every answer, so working one
  // objective leaves a run of questions, and each card must show the question
  // it actually asked.
  const latestMasteryQuestion = useMemo(
    () => extractMasteryQuestion(msg.events),
    [msg.events],
  );
  // ``false`` — never a silent no-op — so a card with nowhere to send its
  // answer reopens instead of spinning forever. See ``submitUserReply``.
  const submitReply = useCallback(
    (reply: {
      text?: string;
      answers?: Array<{ questionId: string; text: string }>;
    }) => (onSubmitUserReply ? onSubmitUserReply(reply) : false),
    [onSubmitUserReply],
  );
  // The card is answered by sending the next message, so "already answered"
  // cannot come from a resolved pause any more — the turn that posed it is
  // long over. The verdict is the durable signal, and it survives a reload.
  const renderMasteryCard = useCallback(
    (question: MasteryQuestion) => {
      const grade = masteryGrades?.get(question.questionId) ?? null;
      return (
        <MasteryQuestionCard
          question={question}
          grade={grade}
          answered={Boolean(grade)}
          skipped={masterySkips?.has(question.questionId) ?? false}
          submittedAnswer={grade?.learnerAnswer ?? ""}
          onSubmit={({ text }) =>
            onAnswerMasteryQuestion
              ? onAnswerMasteryQuestion({
                  questionId: question.questionId,
                  text: String(text ?? ""),
                })
              : false
          }
          onSkip={onSkipMasteryQuestion}
        />
      );
    },
    [
      masteryGrades,
      masterySkips,
      onAnswerMasteryQuestion,
      onSkipMasteryQuestion,
    ],
  );
  // Set by ``request_credential`` when a configuration step needs a secret the
  // assistant must not handle itself.
  const setupCredential = useMemo(
    () => extractSetupCredential(msg.events),
    [msg.events],
  );

  const partnerDraft = useMemo(
    () => extractPartnerDraft(msg.events),
    [msg.events],
  );

  // Set by ``course_handoff`` when Course Study has decided what is worth doing
  // next. A turn may propose more than one, so this is a list.
  const courseHandoffs = useMemo(
    () => extractCourseHandoffs(msg.events),
    [msg.events],
  );

  // Set by the mastery navigation tools when the learner asked to be taken
  // back to something they are studying. Same shape of offer as above — a
  // destination, a reason, an editable opening line — for the surface that
  // actually teaches it.
  const masteryHandoffs = useMemo(
    () => extractMasteryHandoffs(msg.events),
    [msg.events],
  );

  // Some models write the hand-off out as literal JSON *and* call the tool, so
  // the card's own contents appear above it as raw arguments. Only stripped
  // once the turn is finished — mid-stream the text is still arriving and a
  // partial object would not match anyway — and only from a message that really
  // produced a card.
  const body = useMemo(
    () =>
      courseHandoffs.length && !isStreaming
        ? stripLeakedHandoffJson(msg.content)
        : msg.content,
    [courseHandoffs.length, isStreaming, msg.content],
  );

  // Interleaved segments for the default chat surface: the message is laid
  // out in the order it was written — what DeepTutor said it was about to do,
  // the work it then did, what it found, and so on down to the closing answer.
  // Only walked when this message will actually render through the default
  // branch (the research / quiz / animator / visualize branches have their own
  // layout and pin their cards elsewhere).
  const useInlineSegments =
    !outlinePreview &&
    !mathAnimatorResult &&
    !visualizeResult &&
    !(quizQuestions && quizQuestions.length > 0);
  const messageSegments = useMemo(
    () =>
      useInlineSegments
        ? extractMessageSegments(msg.events, msg.content, {
            streaming: isStreaming,
          })
        : [],
    [useInlineSegments, msg.events, msg.content, isStreaming],
  );
  // Either card kind: a clarifying ask_user, or a posed mastery question.
  const hasInlineCards =
    useInlineSegments &&
    messageSegments.some(
      (seg) => seg.kind === "ask_user" || seg.kind === "mastery_question",
    );
  // Lay the body out from the segments whenever there is more to place than
  // one run of prose. A message with nothing but text gets the plain body
  // branch below, which is the same thing with less machinery.
  const useSegmentLayout =
    useInlineSegments && messageSegments.some((seg) => seg.kind !== "text");
  // Every trace row now renders inline, where the work happened. The header
  // block keeps its status line and nothing else — leaving rows up there too
  // would show each step twice.
  const headerTraceEvents = useMemo(
    () =>
      useSegmentLayout ? leadingTraceEvents(events, messageSegments) : undefined,
    [useSegmentLayout, messageSegments, events],
  );

  // Where the working-out stops and the answer starts.
  //
  // Everything a turn writes is worth watching while it works, and almost
  // none of it is worth re-reading afterwards. So the two are separate
  // layers: the process stays open and streams live, then folds itself into
  // one line the moment the turn settles into its closing answer.
  //
  // The boundary is the trailing run of prose — the text after the last step —
  // and it is structural, not timed: whatever is being written right now is
  // always placed as the answer, from its first character.
  // Teaching before a mastery question is also answer prose; the block
  // builder preserves it separately because that card ends the turn.
  //
  // Waiting for the terminal round before promoting it is what an earlier cut
  // did, and it meant the closing answer streamed INSIDE the collapsible
  // process and jumped out of it once finished. That leaks a question the
  // reader should never have been asked to hold — "is this the answer yet?" —
  // and it is a question we cannot answer at that point anyway: a round only
  // reveals whether it called tools after its prose is complete.
  //
  // Placing it optimistically inverts which case pays. Commentary is demoted
  // into the process when its round turns out to have called a tool, and that
  // costs one 14px slide at the exact moment the tool row appears below it —
  // motion that reads as the two being grouped. The answer, which is the text
  // the reader actually came for, never moves at all.
  const answerStart = useMemo(() => {
    let idx = messageSegments.length;
    while (idx > 0 && messageSegments[idx - 1].kind === "text") idx -= 1;
    return idx;
  }, [messageSegments]);
  // A turn that has started writing its answer is no longer changing the
  // working-out above it, which is what lets that whole subtree stop
  // re-deriving itself on every delta. Structural, like the boundary: if a new
  // round starts, the answer goes back into the process and this goes false.
  const processSettled = answerStart < messageSegments.length;
  // Separately again: whether the working-out folds itself away. This is the
  // one thing that does need the terminal-round signal, since it is the claim
  // that there is no more work coming at all.
  const settledIntoAnswer = !isStreaming || hasSettledFinalRound(events);
  // Pending questions stay outside the disclosure so they remain answerable.
  // Once answered, a clarification joins the surrounding process so resumed
  // work continues under the original activity header.
  const messageBlocks = useMemo(
    () => buildMessageBlocks(messageSegments, answerStart),
    [messageSegments, answerStart],
  );
  // The leading run rides in the activity header, which is already pinned at
  // the top and already is a disclosure — giving it the process keeps the
  // message to ONE line of chrome instead of a status line plus a fold.
  // Only the segment layout hands its process to the header; a message with
  // nothing but prose renders through the plain body branch below, which would
  // otherwise draw the same opening sentence a second time.
  const headerProcess =
    useSegmentLayout && messageBlocks[0]?.kind === "process"
      ? messageBlocks[0]
      : null;
  const bodyBlocks = headerProcess ? messageBlocks.slice(1) : messageBlocks;

  const renderSegments = useCallback(
    (segments: MessageSegment[]) => (
      <ProcessBody
        segments={segments}
        events={events}
        settled={processSettled}
        language={language}
        isStreaming={isStreaming}
        readingMaterialId={readingMaterialId}
        readingMaterialRevision={readingMaterialRevision}
      />
    ),
    [
      language,
      isStreaming,
      readingMaterialId,
      readingMaterialRevision,
      events,
      processSettled,
    ],
  );
  const headerProcessSummary = useMemo(() => {
    if (!headerProcess) return undefined;
    const toolCalls = countProcessToolCalls(headerProcess.segments);
    return toolCalls > 0
      ? t("{{count}} tool calls", { count: toolCalls })
      : undefined;
  }, [headerProcess, t]);

  const researchInProgress =
    outlineStatus === "researching" ||
    outlineStatus === "done" ||
    outlineStatus === "failed";
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
        traceEvents={headerTraceEvents}
        isStreaming={isStreaming}
        content={msg.content}
        // ``events`` is a preview of a persisted turn — the events marking
        // where it began are not in it — so the header times the turn from
        // this span instead of from what survived the preview.
        traceBounds={msg.trace}
        // The settled preview drops ``thinking``, which for a round that
        // called no tools is the whole trace. Say that the server still holds
        // it, so the header stays openable and the click can fetch it.
        hasStoredTrace={Boolean(
          msg.trace?.turn_id &&
            (msg.trace?.truncated ||
              (msg.trace?.total ?? 0) > (msg.events?.length ?? 0)),
        )}
        className="mb-3"
        onTraceToggle={
          msg.id != null && msg.trace?.turn_id
            ? (open) => onTraceToggle?.(msg.id as number, open)
            : undefined
        }
        // The turn's working-out, folded behind this same header. One line of
        // chrome does both jobs: it says what is happening while the turn runs
        // and, once it settles, what it did on the way to the answer.
        processContent={
          headerProcess ? renderSegments(headerProcess.segments) : undefined
        }
        processSummary={headerProcessSummary}
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
              onSubmit={submitReply}
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
              language={language}
              isStreaming={isStreaming}
              readingMaterialId={readingMaterialId}
              readingMaterialRevision={readingMaterialRevision}
              events={events}
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
              language={language}
              isStreaming={isStreaming}
              readingMaterialId={readingMaterialId}
              readingMaterialRevision={readingMaterialRevision}
              events={events}
            />
          ) : null}
          <QuizViewer
            questions={quizQuestions}
            sessionId={sessionId}
            turnId={quizTurnId}
            language={language}
          />
        </>
      ) : useSegmentLayout ? (
        // Default chat surface. The working-out (prose interleaved with the
        // steps it introduced) is one layer, folded once the turn settles; the
        // closing answer is the other and always stands plain. Pending cards
        // stay outside the process until the user answers them.
        bodyBlocks.map((block) =>
          block.kind === "process" ? (
            <ProcessFold
              key={block.key}
              segments={block.segments}
              settled={settledIntoAnswer}
            >
              {renderSegments(block.segments)}
            </ProcessFold>
          ) : block.kind === "card" ? (
            block.segment.kind === "mastery_question" ? (
              <div key={block.key}>
                {renderMasteryCard(block.segment.question)}
              </div>
            ) : block.segment.kind === "ask_user" ? (
              <AskUserOptions
                key={block.key}
                data={block.segment.data}
                onSubmit={submitReply}
              />
            ) : null
          ) : block.segment.kind === "text" ? (
            <AssistantResponse
              key={block.key}
              content={block.segment.text}
              language={language}
              isStreaming={isStreaming}
              readingMaterialId={readingMaterialId}
              readingMaterialRevision={readingMaterialRevision}
              events={events}
            />
          ) : null,
        )
      ) : (
        <AssistantResponse
          content={body}
          language={language}
          isStreaming={isStreaming}
          readingMaterialId={readingMaterialId}
          readingMaterialRevision={readingMaterialRevision}
          events={events}
        />
      )}
      {/* Non-default branches (quiz, math animator, visualize) keep the
          card below the body. The default branch inlines it via
          ``messageSegments``; the research branch renders its own card
          above the outline editor — both skip this fallback. */}
      {!outlinePreview && !hasInlineCards && latestMasteryQuestion
        ? renderMasteryCard(latestMasteryQuestion)
        : null}
      {!outlinePreview &&
      !hasInlineCards &&
      !latestMasteryQuestion &&
      askUserPayload ? (
        <AskUserOptions data={askUserPayload} onSubmit={submitReply} />
      ) : null}
      {/* Credential hand-off sits below whichever body branch rendered: it
          supplements the answer ("here's where to paste the key") rather than
          replacing it, and applies to every branch. */}
      {setupCredential ? <SetupCredentialCard data={setupCredential} /> : null}
      {partnerDraft ? <PartnerDraftCard data={partnerDraft} /> : null}
      {/* Course Study's hand-offs sit last: they are what to do *after* reading
          the answer, so they belong below it rather than competing with it. */}
      <CourseHandoffCards handoffs={courseHandoffs} />
      <MasteryHandoffCards handoffs={masteryHandoffs} />
    </>
  );
});

AssistantMessage.displayName = "AssistantMessage";

// Claude-style icon-only message action: a quiet 15px glyph with the label
// in an instant tooltip, brightening on hover.
export function RoughActionButton({
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

/**
 * ``Promise<void>`` and not ``void | Promise<void>``: this button reports
 * success to the user, so it needs a handler that can tell it about failure.
 * A synchronously-void handler has no way to, which is how a swallowed
 * clipboard error came to be rendered as 已复制.
 */
type CopyHandler = (content: string) => Promise<void>;

export function CopyActionButton({
  content,
  onCopy,
}: {
  content: string;
  onCopy: CopyHandler;
}) {
  const { t } = useTranslation();
  const [outcome, setOutcome] = useState<"idle" | "copied" | "failed">("idle");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleClick = useCallback(() => {
    const settle = (next: "copied" | "failed") => {
      setOutcome(next);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setOutcome("idle"), 1600);
    };
    // `Promise.resolve().then(() => onCopy(...))` rather than
    // `Promise.resolve(onCopy(...))`: the latter runs the handler outside the
    // chain, so a *synchronous* throw — which is exactly what reading
    // `navigator.clipboard.writeText` on an insecure origin does — escapes it.
    void Promise.resolve()
      .then(() => onCopy(content))
      .then(
        () => settle("copied"),
        () => settle("failed"),
      );
  }, [content, onCopy]);

  const label =
    outcome === "copied"
      ? t("Copied")
      : outcome === "failed"
        ? t("Could not copy")
        : t("Copy");

  return (
    <Tooltip label={label} side="top">
      <button
        type="button"
        onClick={handleClick}
        aria-live="polite"
        aria-label={label}
        className={`inline-flex items-center justify-center rounded-md p-1 transition-colors ${
          outcome === "copied"
            ? "text-[var(--primary)]"
            : outcome === "failed"
              ? "text-[var(--destructive)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]/50 hover:text-[var(--foreground)]"
        }`}
      >
        {outcome === "copied" ? (
          <Check size={15} strokeWidth={2} />
        ) : outcome === "failed" ? (
          <X size={15} strokeWidth={2} />
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
export function PlayAudioButton({
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
      const resp = await apiFetch(apiUrl("/api/voice/tts"), {
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

export const UserMessage = memo(function UserMessage({
  msg,
  index,
  onPreviewAttachment,
  onCopy,
  onEdit,
  editDisabled,
  siblingInfo,
  onSwitchBranch,
  availableKbNames,
  showModeBadge,
  onOpenConsultation,
}: {
  msg: ChatMessageItem;
  index: number;
  onPreviewAttachment?: (attachment: MessageAttachment) => void;
  onCopy?: CopyHandler;
  onEdit?: (messageId: number, newContent: string) => void;
  editDisabled?: boolean;
  siblingInfo?: SiblingInfo;
  onSwitchBranch?: (parentMessageId: number | null, childId: number) => void;
  /** Names of KBs confirmed to exist. Omitted when the KB list is unavailable. */
  availableKbNames?: Set<string>;
  /** Label the bubble with its capability. A single-capability surface
   *  already names the mode in its own chrome. */
  showModeBadge?: boolean;
  onOpenConsultation?: () => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(msg.content);
  const { isComposingRef, onCompositionStart, onCompositionEnd } =
    useImeComposing();
  // Connected subagents ride in knowledge_bases (same selection path) but are
  // agents, not KBs — this maps a selected name to its backend kind so the
  // reference chip can badge it with the agent's brand icon.
  const agentKinds = useConnectedAgentKinds();
  const consultation = useConsultationReference(msg.requestSnapshot?.config);
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
    ...(consultation ? [{
      key: `${consultation.kind}-${consultation.id}`,
      icon: consultation.kind === "partner_group" ? UsersRound : UserRound,
      kind: t(consultation.kind === "partner_group" ? "Organize partner discussion" : "Ask partner"),
      label: consultation.name,
      onClick: onOpenConsultation,
    }] : []),
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
    ...(snap?.knowledgeBases ?? [])
      .filter(
        (name) =>
          !availableKbNames || availableKbNames.has(name) || agentKinds[name],
      )
      .map((name): ContextTreeItem => {
        const agentKind = agentKinds[name];
        if (agentKind) {
          return {
            key: `agent-${name}`,
            // Brand SVG marks share the lucide call signature (size/strokeWidth/
            // className); cast bridges the structural-variance gap.
            icon: (agentGlyph(agentKind) ?? Bot) as unknown as LucideIcon,
            kind: t("Ask subagent"),
            label: name,
            onClick: onOpenConsultation,
          };
        }
        return {
          key: `kb-${name}`,
          icon: Database,
          kind: t("Knowledge"),
          label: name,
        };
      }),
    ...(snap?.bookReferences ?? []).map((ref): ContextTreeItem => ({
      key: `book-${ref.book_id}`,
      icon: BookOpen,
      kind: t("Book"),
      label: `${ref.page_ids.length} ${t("chapters")}`,
    })),
    ...(snap?.readingReferences ?? []).map((ref): ContextTreeItem => ({
      key: `reading-${ref.material_id}-r${ref.revision}`,
      icon: BookMarked,
      kind: t("Reading"),
      label: `${ref.locators.length} ${t("reading sections")}`,
    })),
    ...(snap?.notebookReferences ?? []).map((ref): ContextTreeItem => ({
      key: `nb-${ref.notebook_id}`,
      icon: BookOpen,
      kind: t("Notebook"),
      label: `${ref.record_ids.length} ${t("records")}`,
    })),
    // Imported agent conversations are folded into the same history_references
    // payload but carry the `imported_` id prefix — split them back out so they
    // read as "My Agents" rather than "Chat History" (mirrors the composer).
    ...(snap?.historyReferences ?? [])
      .filter((sid) => !sid.startsWith("imported_"))
      .map((sid): ContextTreeItem => ({
        key: `hist-${sid}`,
        icon: MessageSquare,
        kind: t("Chat History"),
        label: "",
      })),
    ...(snap?.historyReferences ?? [])
      .filter((sid) => sid.startsWith("imported_"))
      .map((sid): ContextTreeItem => ({
        key: `agent-${sid}`,
        icon: Bot,
        kind: t("My Agents"),
        label: "",
      })),
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
    ...(snap?.memoryReferences ?? []).map((file): ContextTreeItem => ({
      key: `mem-${file}`,
      icon: Brain,
      kind: t("Memory"),
      label: file === "summary" ? t("Summary") : t("Profile"),
    })),
  ];

  return (
    <div key={`${msg.role}-${index}`} className="group flex justify-end">
      {/* ``data-turn-key`` is the scroll target the turn navigator jumps
          to; ``data-turn-bubble`` is what it flashes on arrival. Both keys
          come from ``turnAnchorKey`` so the rail and the transcript can
          never disagree about which bubble a tick means. */}
      <div
        data-turn-key={turnAnchorKey(msg, index)}
        className="flex max-w-[75%] flex-col items-end gap-1.5"
      >
        {showModeBadge && (
          <div className="flex justify-end pr-1">
            <span className="text-[10px] tracking-wide text-[var(--muted-foreground)]">
              {t(getModeBadgeLabel(msg.capability))}
            </span>
          </div>
        )}
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
                } else if (shouldSubmitOnEnter(e, isComposingRef.current)) {
                  e.preventDefault();
                  submitEdit();
                }
              }}
              onCompositionStart={onCompositionStart}
              onCompositionEnd={onCompositionEnd}
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
          <div
            data-turn-bubble="true"
            className="rounded-2xl bg-[var(--secondary)] px-4 py-2.5 text-[14px] leading-relaxed text-[var(--foreground)] shadow-sm"
          >
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
  onOpenConsultation,
  onDeleteTurn,
  selectedBranches,
  onEditMessage,
  onSwitchBranch,
  availableKbNames,
  onSubmitUserReply,
  onAnswerMasteryQuestion,
  onSkipMasteryQuestion,
  showModeBadge = true,
  onLoadMessageTrace,
  onReleaseMessageTrace,
}: {
  messages: ChatMessageItem[];
  isStreaming: boolean;
  sessionId?: string | null;
  language?: string;
  onCopyAssistantMessage: CopyHandler;
  onRegenerateMessage: () => void;
  onConfirmOutline?: (
    outline: Array<{ title: string; overview: string }>,
    topic: string,
    researchConfig?: Record<string, unknown> | null,
    requestSnapshot?: MessageRequestSnapshot | null,
  ) => void;
  onPreviewAttachment?: (attachment: MessageAttachment) => void;
  onOpenConsultation?: (events: StreamEvent[]) => void;
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
  ) => void | boolean | Promise<void | boolean>;
  /**
   * Answer a mastery question card by starting the next turn (see
   * ``AssistantMessage``). Separate from ``onSubmitUserReply`` because these
   * cards outlive their turn by design.
   */
  onAnswerMasteryQuestion?: (answer: {
    questionId: string;
    text: string;
  }) => void | boolean | Promise<void | boolean>;
  /** Drop a question instead of answering it; also starts a turn. */
  onSkipMasteryQuestion?: (
    questionId: string,
  ) => void | boolean | Promise<void | boolean>;
  /** Names of KBs confirmed to exist. Omitted when the KB list is unavailable. */
  availableKbNames?: Set<string>;
  /** Label each user bubble with its capability. Off on surfaces that run a
   *  single capability and already name it in their own chrome. */
  showModeBadge?: boolean;
  onLoadMessageTrace?: (messageId: number) => Promise<void>;
  onReleaseMessageTrace?: (messageId: number) => void;
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
  // One callback for every row rather than a closure per row per render.
  // ``AssistantMessage`` is memoized, and a fresh function defeats that
  // outright: every message in the conversation re-rendered on every streamed
  // delta of the turn at the bottom.
  const handleTraceToggle = useCallback(
    (messageId: number, open: boolean) => {
      if (open) {
        void onLoadMessageTrace?.(messageId);
      } else {
        onReleaseMessageTrace?.(messageId);
      }
    },
    [onLoadMessageTrace, onReleaseMessageTrace],
  );

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
      const nextResearchAssistantIdx = visibleMessages
        .slice(i + 1)
        .findIndex(
          (m) => m.role === "assistant" && m.capability === "deep_research",
        );
      if (nextResearchAssistantIdx === -1) continue;
      const absoluteFollowupIdx = i + 1 + nextResearchAssistantIdx;
      const followup = visibleMessages[absoluteFollowupIdx];
      if (!isConfirmedResearchFollowup(followup.events)) continue;
      const mergedEvents = [...(msg.events ?? []), ...(followup.events ?? [])];
      const mergedContent = authoritativeResearchReport(
        followup.events,
        followup.content || msg.content,
      );
      map.set(i, { mergedEvents, mergedContent });
      followupIndices.add(absoluteFollowupIdx);
    }
    return { mergedByParent: map, followupIndices };
  }, [visibleMessages]);

  // One pass for the whole conversation: a question posed in one turn can be
  // graded in a later one, and the card that asked it shows the verdict.
  const masteryGrades = useMemo(
    () => collectMasteryGrades(visibleMessages),
    [visibleMessages],
  );
  const masterySkips = useMemo(
    () => collectMasterySkips(visibleMessages),
    [visibleMessages],
  );

  const outlineStatusByIndex = useMemo(() => {
    const map = new Map<
      number,
      "editing" | "researching" | "done" | "failed"
    >();
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
      if (followup && isConfirmedResearchFollowup(followup.events)) {
        map.set(i, researchFollowupStatus(followup.events));
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

  const usageByRow = useMemo(() => {
    const totals = cumulativeMessageUsage(messageRows.map(row => row.msg));
    return new Map(messageRows.map((row, index) => [row.originalIndex, totals[index]]));
  }, [messageRows]);

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
      {messageRows.map(({ msg, originalIndex, pairedUserMessage }, rowIndex) => {
        const i = originalIndex;
        if (msg.role === "user") {
          const sib =
            msg.id !== undefined ? siblingsByMessageId.get(msg.id) : undefined;
          const reply = messageRows[rowIndex + 1]?.msg;
          const consultationEvents = reply?.role === "assistant"
            ? (reply.events ?? []).filter(event => event.metadata?.trace_kind === "subagent_event")
            : [];
          return (
            <div
              key={`${msg.role}-${i}`}
              className="w-full"
              data-chat-message-id={msg.id}
              data-chat-message-role={msg.role}
            >
              <UserMessage
                msg={msg}
                index={i}
                onPreviewAttachment={onPreviewAttachment}
                onCopy={onCopyAssistantMessage}
                onEdit={onEditMessage}
                editDisabled={isStreaming}
                siblingInfo={sib}
                onSwitchBranch={onSwitchBranch}
                availableKbNames={availableKbNames}
                showModeBadge={showModeBadge}
                onOpenConsultation={consultationEvents.length && onOpenConsultation
                  ? () => onOpenConsultation(consultationEvents)
                  : undefined}
              />
            </div>
          );
        }

        const isActiveAssistant =
          isStreaming && i === lastRenderedAssistantIndex;
        const msgDone = !isActiveAssistant;
        const showActions = msgDone && hasVisibleMarkdownContent(msg.content);
        const events = msg.events ?? [];
        const terminalError = [...events].reverse().find(
          (event) => event.type === "error" && Boolean(event.metadata?.turn_terminal),
        ) ?? (!hasVisibleMarkdownContent(msg.content)
          ? [...events].reverse().find((event) => event.type === "error")
          : undefined);
        const stopped = terminalError?.metadata?.status === "cancelled" ||
          events.some((event) => event.type === "done" && event.metadata?.status === "cancelled");
        const emptyResponse = !hasVisibleMarkdownContent(msg.content) &&
          !msg.attachments?.length &&
          !events.some((event) => ["result", "tool_call", "tool_result", "wait_for_input"].includes(event.type));
        const terminalErrorRetryable = Boolean(
          (terminalError?.metadata as { retryable?: boolean } | undefined)
            ?.retryable,
        );
        const isLastAssistant = i === lastRenderedAssistantIndex;
        const showRegenerate =
          !isStreaming &&
          isLastAssistant &&
          Boolean(pairedUserMessage) &&
          (!pairedUserMessage?.capability ||
            pairedUserMessage?.capability === "chat") &&
          (showActions || terminalErrorRetryable);
        const deletableTurnUserId =
          msgDone && pairedUserMessage?.id != null && onDeleteTurn
            ? pairedUserMessage.id
            : null;
        const showDelete = deletableTurnUserId != null;

        const costSummary = msgDone ? messageUsage(msg.events) : null;

        return (
          <div
            key={`${msg.role}-${i}`}
            className="w-full"
            data-chat-message-id={msg.id}
            data-chat-message-role={msg.role}
          >
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
                onAnswerMasteryQuestion={onAnswerMasteryQuestion}
                onSkipMasteryQuestion={onSkipMasteryQuestion}
                researchRequestSnapshot={
                  pairedUserMessage?.requestSnapshot ?? null
                }
                onTraceToggle={handleTraceToggle}
                masteryGrades={masteryGrades}
                masterySkips={masterySkips}
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
              if (stopped) return (
                <div role="status" className="mt-3 flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                  <Square className="h-3.5 w-3.5" aria-hidden="true" />
                  <span>{t("Stopped")}</span>
                </div>
              );
              if (!terminalError && !emptyResponse) return null;
              return (
                <div role="alert" className="mt-3 flex w-full max-w-[min(520px,90%)] items-center gap-2 rounded-xl border border-[var(--destructive)]/30 bg-[var(--destructive)]/5 px-3 py-2">
                  <AlertCircle className="h-4 w-4 shrink-0 text-[var(--destructive)]" />
                  <span className="min-w-0 flex-1 text-[12px] leading-[1.5] text-[var(--foreground)]">
                    {terminalError?.content || (terminalError
                      ? t("The turn was interrupted.")
                      : t("No response was generated. Please try again."))}
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
                    <UsageFooter turn={costSummary} session={usageByRow.get(i) ?? costSummary} />
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
